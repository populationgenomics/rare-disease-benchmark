from __future__ import annotations

import copy
import json
import pathlib
from collections.abc import Callable
from typing import Any

import pydantic
import pytest

from rare_disease_benchmark.metamist import manifest

_FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'manifest'

type Data = dict[str, list[dict[str, Any]]]
type Change = Callable[[Data], object]


def fixture_data() -> Data:
    """The manifest of an invented trio's run, as its two JSON files hold it."""
    return {name: json.loads((_FIXTURE / f'{name}.json').read_text('utf-8')) for name in ('samples', 'family')}


def parse(data: Data) -> manifest.Manifest:
    return manifest.parse(json.dumps(data['samples']), json.dumps(data['family']))


def changed(data: Data, change: Change) -> Data:
    data = copy.deepcopy(data)
    change(data)
    return data


def sample(data: Data, index: int) -> dict[str, Any]:
    return data['samples'][index]


def family(data: Data) -> dict[str, Any]:
    return data['family'][0]


def test_the_run_directory_holds_every_file_and_names_background_and_version() -> None:
    run = parse(fixture_data())
    assert run.directory.endswith(f'/backgrounds/{run.background}/{run.version}')
    assert all(p.startswith(f'{run.directory}/') for p in run.paths())
    assert len(set(run.paths())) == len(run.paths())


def test_paths_name_every_file_of_every_record() -> None:
    data = fixture_data()
    named: set[str] = set()
    for record in (*data['samples'], *data['family']):
        for key, value in record.items():
            if key != 'id':
                named.update(value if isinstance(value, list) else [value])
    assert set(parse(data).paths()) == named


REJECTED: dict[str, tuple[Change, str]] = {
    'no samples': (lambda d: d.update(samples=[]), 'lists no samples'),
    'a sample twice': (lambda d: d['samples'].append(sample(d, 0)), 'repeats sample'),
    'an unknown key': (lambda d: sample(d, 0).update(bam='x.bam'), 'Extra inputs are not permitted'),
    'a missing key': (lambda d: family(d).pop('pedigree'), 'Field required'),
    'two family records': (lambda d: d['family'].append(family(d)), 'one record'),
    "a sample's file in another sample's folder": (
        lambda d: sample(d, 0).update(cram=sample(d, 1)['cram']),
        'is not a file under',
    ),
    'a family file among the samples': (
        lambda d: family(d).update(vcf_index=sample(d, 0)['gvcf_index'].replace('SG0001/', '')),
        'is not a file under',
    ),
    'a folder as a file': (
        lambda d: sample(d, 0)['other'].append(sample(d, 0)['cram'].rsplit('/', 1)[0] + '/'),
        'is not a file under',
    ),
    "a background other than the folder's": (lambda d: family(d).update(id='trio-b'), 'backgrounds/trio-b/'),
    "some of a sample's whole-genome files": (lambda d: sample(d, 0).pop('cnv_counts'), 'not all of'),
    "some of the family's whole-genome files": (lambda d: family(d).pop('sv_vcf'), 'not all of'),
    'slice samples in a whole-genome run': (lambda d: [as_slice(r) for r in d['samples']], 'mixes'),
    'UPD calls in a slice': (lambda d: [family(d).pop(k) for k in ('cnv_vcf', 'sv_vcf')], "must be a whole genome's"),
}

_WHOLE_GENOME_KEYS = ('sv_vcf', 'cnv_vcf', 'cnv_counts', 'upd_vcf')


def as_slice(record: dict[str, Any]) -> None:
    for key in _WHOLE_GENOME_KEYS:
        record.pop(key, None)


def test_a_slice_names_no_whole_genome_files() -> None:
    data = fixture_data()
    for record in (*data['samples'], *data['family']):
        as_slice(record)
    run = parse(data)
    assert not run.family.whole_genome
    assert not any(s.whole_genome for s in run.samples)
    assert not any(p.endswith(('.sv.vcf.gz', '.cnv.vcf.gz', '.tn.tsv.gz', '.upd.vcf.gz')) for p in run.paths())


@pytest.mark.parametrize(('change', 'message'), REJECTED.values(), ids=REJECTED.keys())
def test_manifest_rejects(change: Change, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse(changed(fixture_data(), change))


def test_family_json_must_be_a_list() -> None:
    with pytest.raises(pydantic.ValidationError, match='valid'):
        manifest.parse(json.dumps(fixture_data()['samples']), json.dumps(family(fixture_data())))


def test_manifest_rejects_text_that_is_not_json() -> None:
    with pytest.raises(pydantic.ValidationError, match='Invalid JSON'):
        manifest.parse('[{', json.dumps(fixture_data()['family']))
