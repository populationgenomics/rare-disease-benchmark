from __future__ import annotations

import base64

import references
import test_nextflow_site_config

OUTPUTS = test_nextflow_site_config.OUTPUTS


def test_the_fetch_job_runs_in_the_stack() -> None:
    job = references.hash_table_job(OUTPUTS)
    policy = job['allocationPolicy']
    assert policy['network']['networkInterfaces'] == [
        {'network': OUTPUTS['network'], 'subnetwork': OUTPUTS['subnetwork']}
    ]
    assert policy['serviceAccount'] == {'email': OUTPUTS['serviceAccountEmail']}
    assert policy['location'] == {'allowedLocations': [f'regions/{OUTPUTS["region"]}']}
    # A reclaimed spot VM would restart the 32 GB stream.
    assert [i['policy']['provisioningModel'] for i in policy['instances']] == ['STANDARD']


def test_the_fetch_job_streams_into_the_reference_path() -> None:
    script = references.hash_table_job(OUTPUTS)['taskGroups'][0]['taskSpec']['runnables'][0]['container']['commands'][1]
    assert f'export DEST={OUTPUTS["dataBucket"]}/{references.DRAGEN_REFERENCE}\n' in script
    assert references.HASH_TABLE_URL in script
    assert '${TAR_FILENAME#./}' in script


def _listing(prefix: str, md5s: dict[str, str | None]) -> list[dict]:
    return [
        {
            'metadata': {'name': prefix + name}
            | ({'md5Hash': base64.b64encode(bytes.fromhex(md5)).decode()} if md5 else {})
        }
        for name, md5 in md5s.items()
    ]


def test_hex_md5s_reads_gcloud_listings() -> None:
    listing = _listing('p/', {'a.bin': 'ee4d3c5df9927e095d2cc3bee8ec3a06', 'composite.bin': None})
    assert references.hex_md5s(listing, 'p/') == {'a.bin': 'ee4d3c5df9927e095d2cc3bee8ec3a06', 'composite.bin': None}


def test_hash_table_problems_names_each_missing_or_wrong_file() -> None:
    md5sums = 'aa\tok.bin\nbb\twrong.bin\ncc\tmissing.bin\ndd\tcomposite.bin\n'
    problems = references.hash_table_problems(md5sums, {'ok.bin': 'aa', 'wrong.bin': 'b0', 'composite.bin': None})
    assert problems == [
        'checksum of wrong.bin is b0, expected bb',
        'missing missing.bin',
        'checksum of composite.bin is None, expected dd',
    ]


def test_a_complete_hash_table_has_no_problems() -> None:
    assert references.hash_table_problems('aa\ta.bin\nbb\tsub/b.bin\n', {'a.bin': 'aa', 'sub/b.bin': 'bb'}) == []
