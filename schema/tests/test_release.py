from __future__ import annotations

from typing import Any

import pydantic
import pytest
from edits import Change, changed

from rare_disease_benchmark.schema import release


def instance(data: dict[str, Any], index: int) -> dict[str, Any]:
    return data['instances'][index]


def as_singleton(data: dict[str, Any]) -> None:
    """Case 17 with the proband alone, as a laboratory that sequenced only her would record it."""
    case = data['cases'][0]
    case['family']['members'] = case['family']['members'][:1]
    case['family']['members'][0].update(father=None, mother=None)
    case['answer']['placements'] = [p for p in case['answer']['placements'] if p['haplotype']['member'] == 'proband']
    for i in data['instances']:
        i['samples'] = i['samples'][:1]


def test_a_case_may_have_several_instances_in_one_release(withheld: release.WithheldRelease) -> None:
    assert len({i.case for i in withheld.instances}) < len(withheld.instances)


def test_a_case_without_parents_maps_only_the_proband(release_data: dict[str, Any]) -> None:
    withheld = release.WithheldRelease.model_validate(changed(release_data, as_singleton))
    assert all(len(s.samples) == 1 for s in withheld.instances)


REJECTED: dict[str, tuple[Change, str]] = {
    'a member without a sample': (lambda d: instance(d, 0)['samples'].pop(), 'maps members'),
    'a sample for someone not in the family': (
        lambda d: instance(d, 0)['samples'].append({'member': 'sibling', 'sample': 'NA19241'}),
        'maps members',
    ),
    'one sample for two members': (
        lambda d: instance(d, 0)['samples'][2].update(sample=instance(d, 0)['samples'][1]['sample']),
        'repeats sample',
    ),
    'same case twice into the same samples': (
        lambda d: instance(d, 1).update(samples=instance(d, 0)['samples']),
        'same samples',
    ),
    'unknown case': (lambda d: instance(d, 0).update(case='case-18'), 'unknown case'),
    'version without three parts': (lambda d: d.update(release='1.0'), 'MAJOR.MINOR.PATCH'),
}


@pytest.mark.parametrize(('change', 'message'), REJECTED.values(), ids=REJECTED.keys())
def test_release_rejects(release_data: dict[str, Any], change: Change, message: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=message):
        release.WithheldRelease.model_validate(changed(release_data, change))
