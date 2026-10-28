"""Puts the build pipeline's references into a stack's data bucket, and checks them.

    uv run --group infra python infra/references.py --stack <stack> fetch
    uv run --group infra python infra/references.py --stack <stack> verify

`fetch` copies GRCh38 from Broad's public bucket, which is a copy within GCS, and submits a Cloud Batch job that streams
Illumina's DRAGEN hash table into the bucket, unpacking it file by file so that no disk has to hold it. A file already
in the bucket is skipped: an object exists only once its upload completed, so an interrupted fetch is finished by
running it again. `verify` checks every hash table file against the MD5s Illumina ships with it, and the GRCh38 files
against Broad's.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import subprocess
import tempfile
from collections.abc import Mapping, Sequence

import stack_outputs

# Where the references sit in a data bucket; the pipeline's site config points at these paths.
DRAGEN_REFERENCE = 'references/dragen/hg38-alt_masked.cnv.graph.hla.methyl_cg.rna-12-r6.0-1'
CRAM_REFERENCE = 'references/grch38/Homo_sapiens_assembly38.fasta'

# Illumina's hg38 pangenome reference for DRAGEN 4.5 and 4.6 (hash table version 12). Its files sit at the top of the
# archive, with hash_table.md5sums among them.
HASH_TABLE_URL = (
    'https://webdata.illumina.com/downloads/software/dragen/resource-files/4.5/hash-tables/'
    'hg38-alt_masked.cnv.graph.hla.methyl_cg.rna-12-r6.0-1.tar.gz'
)

# The NYGC 1000 Genomes CRAMs were compressed against GRCh38_full_analysis_set_plus_decoy_hla.fa. Broad's copy has the
# same 3,366 sequences, with the same names, lengths and MD5s in the same order (its .dict against a CRAM header), and
# copies within GCS.
GRCH38_SOURCE = 'gs://gcp-public-data--broad-references/hg38/v0/Homo_sapiens_assembly38'
GRCH38_SUFFIXES = ('.fasta', '.fasta.fai', '.dict')

# The Google Cloud CLI image the fetch job runs in, pinned like every other image here.
_CLOUD_SDK_IMAGE = (
    'google/cloud-sdk:589.0.0-slim@sha256:ffd36b9b80bb08b2dea60b58ca2b60dfa3a40a3c00f3e5732d6d113f4e7ffa45'
)

_REQUIRED_OUTPUTS = ('project', 'region', 'dataBucket', 'network', 'subnetwork', 'serviceAccountEmail')

_FETCH_SCRIPT = r"""
set -euo pipefail
export DEST={dest}
curl -fsSL {url} | tar xzf - --to-command='
    f="${{TAR_FILENAME#./}}"
    if gcloud storage objects describe "$DEST/$f" >/dev/null 2>&1; then
        echo "skip $f"; cat >/dev/null
    else
        echo "upload $f"; gcloud storage cp --quiet - "$DEST/$f"; echo "done $f"
    fi'
echo "archive complete"
"""


def hash_table_job(outputs: Mapping[str, str]) -> dict:
    """The Cloud Batch job that streams the hash table into the stack's data bucket."""
    region = outputs['region']
    script = _FETCH_SCRIPT.format(dest=f'{outputs["dataBucket"]}/{DRAGEN_REFERENCE}', url=HASH_TABLE_URL)
    return {
        'taskGroups': [
            {
                'taskCount': 1,
                'taskSpec': {
                    'runnables': [
                        {
                            'container': {
                                'imageUri': _CLOUD_SDK_IMAGE,
                                'entrypoint': '/bin/bash',
                                'commands': ['-c', script],
                            }
                        }
                    ],
                    'computeResource': {'cpuMilli': 4000, 'memoryMib': 8192},
                    'maxRunDuration': '14400s',
                    'maxRetryCount': 0,
                },
            }
        ],
        'allocationPolicy': {
            # Not spot: a reclaimed VM would restart the stream from the beginning.
            'instances': [{'policy': {'machineType': 'e2-standard-4', 'provisioningModel': 'STANDARD'}}],
            'network': {'networkInterfaces': [{'network': outputs['network'], 'subnetwork': outputs['subnetwork']}]},
            'serviceAccount': {'email': outputs['serviceAccountEmail']},
            'location': {'allowedLocations': [f'regions/{region}']},
        },
        'logsPolicy': {'destination': 'CLOUD_LOGGING'},
    }


def _gcloud(*args: str) -> str:
    return subprocess.run(  # noqa: S603 (fixed arguments)
        ['gcloud', *args],  # noqa: S607 (gcloud is resolved from PATH)
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def hex_md5s(listing: Sequence[Mapping], prefix: str) -> dict[str, str | None]:
    """Object name below `prefix` to its MD5 in hex, from `gcloud storage ls --json`.

    A composite object maps to None: GCS stores it without an MD5.
    """
    md5s: dict[str, str | None] = {}
    for entry in listing:
        metadata = entry['metadata']
        md5 = metadata.get('md5Hash')
        md5s[metadata['name'].removeprefix(prefix)] = base64.b64decode(md5).hex() if md5 else None
    return md5s


def hash_table_problems(md5sums: str, md5s: Mapping[str, str | None]) -> list[str]:
    """What is wrong with the hash table in the bucket, given hash_table.md5sums and the objects' MD5s."""
    problems = []
    for line in md5sums.splitlines():
        expected, name = line.split(None, 1)
        if name not in md5s:
            problems.append(f'missing {name}')
        elif md5s[name] != expected:
            problems.append(f'checksum of {name} is {md5s[name]}, expected {expected}')
    return problems


def _fetch(outputs: Mapping[str, str], stack: str) -> None:
    grch38 = f'{outputs["dataBucket"]}/{CRAM_REFERENCE.rsplit("/", 1)[0]}/'
    _gcloud('storage', 'cp', '--no-clobber', *(GRCH38_SOURCE + suffix for suffix in GRCH38_SUFFIXES), grch38)
    print(f'GRCh38 is in {grch38}')
    with tempfile.NamedTemporaryFile('w', suffix='.json') as config:
        json.dump(hash_table_job(outputs), config)
        config.flush()
        name = f'references-{stack}-{dt.datetime.now(tz=dt.UTC):%Y%m%d-%H%M%S}'
        _gcloud(
            'batch', 'jobs', 'submit', name,
            f'--project={outputs["project"]}', f'--location={outputs["region"]}', f'--config={config.name}',
        )  # fmt: skip
    print(f'submitted Batch job {name}; when it has finished, run verify')


def _verify(outputs: Mapping[str, str]) -> list[str]:
    data = outputs['dataBucket']
    problems = []
    prefix = f'{DRAGEN_REFERENCE}/'
    listing = json.loads(_gcloud('storage', 'ls', '--json', '--recursive', f'{data}/{prefix}**'))
    md5s = hex_md5s(listing, prefix)
    if 'hash_table.md5sums' not in md5s:
        return [f'no {prefix}hash_table.md5sums in {data}; run fetch']
    problems += hash_table_problems(_gcloud('storage', 'cat', f'{data}/{prefix}hash_table.md5sums'), md5s)
    grch38_prefix = CRAM_REFERENCE.rsplit('/', 1)[0] + '/'
    copies = hex_md5s(json.loads(_gcloud('storage', 'ls', '--json', f'{data}/{grch38_prefix}*')), grch38_prefix)
    sources = hex_md5s(json.loads(_gcloud('storage', 'ls', '--json', f'{GRCH38_SOURCE}*')), 'hg38/v0/')
    for suffix in GRCH38_SUFFIXES:
        name = f'Homo_sapiens_assembly38{suffix}'
        if copies.get(name) is None or copies.get(name) != sources.get(name):
            problems.append(f"{grch38_prefix}{name} is missing or differs from Broad's")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stack', required=True, help='the Pulumi stack whose data bucket holds the references')
    parser.add_argument('command', choices=['fetch', 'verify'])
    args = parser.parse_args()
    outputs = stack_outputs.read(args.stack)
    stack_outputs.require(outputs, _REQUIRED_OUTPUTS, stack=args.stack)
    if args.command == 'fetch':
        _fetch(outputs, args.stack)
        return
    if problems := _verify(outputs):
        raise SystemExit('\n'.join(problems))
    print('references verified')


if __name__ == '__main__':
    main()
