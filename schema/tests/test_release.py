from __future__ import annotations

from typing import Any

import pydantic
import pytest
from edits import Change, changed

from rare_disease_benchmark.schema import item, release


def instance(data: dict[str, Any], index: int) -> dict[str, Any]:
    return data['instances'][index]


def as_singleton(data: dict[str, Any]) -> None:
    """Case 17 with the proband alone, as a laboratory that sequenced only her would record it."""
    case = data['cases'][0]
    case['open']['family']['members'] = case['open']['family']['members'][:1]
    case['open']['family']['members'][0].update(father=None, mother=None)
    case['answer']['placements'] = [
        p for p in case['answer']['placements'] if p['haplotype']['individual'] == 'proband'
    ]
    for i in data['instances']:
        i['members'] = i['members'][:1]


def test_a_case_may_have_several_instances_in_one_release(withheld: release.WithheldRelease) -> None:
    assert len({i.case for i in withheld.instances}) < len(withheld.instances)


def test_a_case_without_parents_builds_into_a_trio(release_data: dict[str, Any]) -> None:
    withheld = release.WithheldRelease.model_validate(changed(release_data, as_singleton))
    for run in item.items(withheld):
        assert len(run.input.family.members) == 1


def add_sibling(data: dict[str, Any]) -> None:
    data['cases'][0]['open']['family']['members'].append(
        {'id': 'sibling', 'father': 'father', 'mother': 'mother', 'sex': 'male', 'affected': False}
    )


REJECTED: dict[str, tuple[Change, str]] = {
    'proband and background child differ in sex': (
        lambda d: d['backgrounds'][0].update(child_sex='male'),
        'is female, and the child',
    ),
    'family beyond the trio': (add_sibling, 'beyond the proband'),
    'same case twice in one background': (
        lambda d: instance(d, 1).update(background=instance(d, 0)['background']),
        r'\(case, background\) pair',
    ),
    'release sample id shared between instances': (
        lambda d: instance(d, 1)['members'][0].update(release_sample=instance(d, 0)['members'][0]['release_sample']),
        'release sample id',
    ),
    'a member without a release sample id': (lambda d: instance(d, 0)['members'].pop(), 'maps members'),
    'release sample id equal to a record member id': (
        lambda d: instance(d, 0)['members'][0].update(release_sample='proband'),
        'member id of the case record',
    ),
    'release sample id containing the case id': (
        lambda d: instance(d, 0)['members'][0].update(release_sample='r1-case-17-p'),
        "contains 'case-17'",
    ),
    'release sample id containing the accession': (
        lambda d: (
            d['cases'][0]['source'].update(accession='ACC-981'),
            instance(d, 0)['members'][2].update(release_sample='r1-acc-981'),
        ),
        "contains 'ACC-981'",
    ),
    'unknown case': (lambda d: instance(d, 0).update(case='case-18'), 'unknown case'),
    'unknown background': (lambda d: instance(d, 0).update(background='bg-trio-z'), 'unknown background'),
    'version without three parts': (lambda d: d.update(release='1.0'), 'MAJOR.MINOR.PATCH'),
}


@pytest.mark.parametrize(('change', 'message'), REJECTED.values(), ids=REJECTED.keys())
def test_release_rejects(release_data: dict[str, Any], change: Change, message: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=message):
        release.WithheldRelease.model_validate(changed(release_data, change))
