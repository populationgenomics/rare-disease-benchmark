from __future__ import annotations

from typing import Any

import pydantic
import pytest
from edits import Change, changed, placement

from rare_disease_benchmark.schema import record, release

# Off chr1/chr2, so that a change never collides with case 17's own placements.
X_SITE = 50_000_000  # chrX, outside both pseudoautosomal regions
Y_SITE = 20_000_000  # chrY, outside both pseudoautosomal regions
M_SITE = 3_000


def case_data(release_data: dict[str, Any]) -> dict[str, Any]:
    return release_data['cases'][0]


def members(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case['family']['members']


def placements(case: dict[str, Any]) -> list[dict[str, Any]]:
    return case['answer']['placements']


def as_son(case: dict[str, Any]) -> None:
    members(case)[0]['sex'] = 'male'


def test_placed_variants_outside_every_diagnosis_are_set_aside(withheld: release.WithheldRelease) -> None:
    answer = withheld.cases[0].answer
    causative = set(answer.causative_variants)
    assert answer.set_aside
    assert not causative & set(answer.set_aside)
    assert causative | set(answer.set_aside) == {p.variant for p in answer.placements}


# Rows from the situations the record has to express; each is added to case 17 and must validate.
ACCEPTED: dict[str, Change] = {
    'de novo on the maternal copy': lambda c: placements(c).append(placement('proband', 'maternal', 'chr3', 1_000)),
    'carried by the father and not passed on': lambda c: placements(c).append(
        placement('father', 'non_transmitted', 'chr3', 1_000)
    ),
    'mosaic father who transmitted': lambda c: placements(c).extend(
        [
            placement('father', 'transmitted', 'chr3', 1_000, vaf=0.1),
            placement('proband', 'paternal', 'chr3', 1_000),
        ]
    ),
    'daughter inherits her father X': lambda c: placements(c).extend(
        [
            placement('proband', 'paternal', 'chrX', X_SITE),
            placement('father', 'transmitted', 'chrX', X_SITE),
        ]
    ),
    'X-linked recessive in a son': lambda c: (
        as_son(c),
        placements(c).extend(
            [
                placement('proband', 'maternal', 'chrX', X_SITE),
                placement('mother', 'transmitted', 'chrX', X_SITE),
            ]
        ),
    ),
    'heteroplasmy': lambda c: placements(c).extend(
        [
            placement('proband', 'maternal', 'chrM', M_SITE, vaf=0.3),
            placement('mother', 'transmitted', 'chrM', M_SITE, vaf=0.8),
        ]
    ),
    'paternal isodisomy over a region': lambda c: placements(c).append(
        placement(
            'proband',
            'maternal',
            'chr15',
            23_000_000,
            ref='A',
            alt='<UPD>',
            end=28_000_000,
            origin={'individual': 'proband', 'name': 'paternal'},
        )
    ),
}


@pytest.mark.parametrize('change', ACCEPTED.values(), ids=ACCEPTED.keys())
def test_record_accepts(release_data: dict[str, Any], change: Change) -> None:
    record.Case.model_validate(changed(case_data(release_data), change))


REJECTED: dict[str, tuple[Change, str]] = {
    'placement on a non-member': (
        lambda c: placements(c).append(placement('sibling', 'paternal', 'chr3', 1_000)),
        'not a member',
    ),
    'paternal copy of a son X': (
        lambda c: (as_son(c), placements(c).append(placement('proband', 'paternal', 'chrX', X_SITE))),
        'does not exist',
    ),
    'father X transmitted to a son': (
        lambda c: (as_son(c), placements(c).append(placement('father', 'transmitted', 'chrX', X_SITE))),
        'does not exist',
    ),
    'chrY in a female': (
        lambda c: placements(c).append(placement('proband', 'paternal', 'chrY', Y_SITE)),
        'does not exist',
    ),
    'maternal chrY': (
        lambda c: (as_son(c), placements(c).append(placement('proband', 'maternal', 'chrY', Y_SITE))),
        'does not exist',
    ),
    'paternal chrM': (
        lambda c: placements(c).append(placement('proband', 'paternal', 'chrM', M_SITE)),
        'does not exist',
    ),
    'transmitted paternal chrM': (
        lambda c: placements(c).append(placement('father', 'transmitted', 'chrM', M_SITE)),
        'does not exist',
    ),
    'chrY coordinate in a pseudoautosomal region': (
        lambda c: (as_son(c), placements(c).append(placement('proband', 'paternal', 'chrY', 100_000))),
        'pseudoautosomal',
    ),
    'more than half on one of two copies': (
        lambda c: placements(c).append(placement('proband', 'paternal', 'chr3', 1_000, vaf=0.6)),
        'two placements',
    ),
    'transmitted names a non-parent': (
        lambda c: placements(c).append(placement('proband', 'transmitted', 'chr3', 1_000)),
        'not one',
    ),
    'paternal names an absent parent': (
        lambda c: placements(c).append(placement('father', 'paternal', 'chr3', 1_000)),
        'not in the family',
    ),
    'causative variant not placed in the proband': (
        lambda c: placements(c).pop(2),
        'not placed in the proband',
    ),
    'same variant twice on one haplotype': (
        lambda c: placements(c).append(placements(c)[0]),
        'placed twice',
    ),
    'origin without <UPD>': (
        lambda c: placements(c).append(
            placement('proband', 'paternal', 'chr3', 1_000, origin={'individual': 'proband', 'name': 'maternal'})
        ),
        'origin',
    ),
    'end on an explicit alternate': (
        lambda c: placements(c).append(placement('proband', 'paternal', 'chr3', 1_000, end=1_010)),
        'symbolic alleles only',
    ),
    'proband of unknown sex': (lambda c: members(c)[0].update(sex='unknown'), 'known sex'),
    'father of female sex': (lambda c: members(c)[1].update(sex='female'), 'male parent'),
    'member id that is not a relational label': (
        lambda c: members(c)[2].update(id='S-0093'),
        'not a relational label',
    ),
    # An accession that happens to look like a label; the record must not release it as a sample name.
    'member id containing the source accession': (
        lambda c: c['source'].update(accession='mother'),
        "contains 'mother'",
    ),
    'malformed HPO id': (
        lambda c: members(c)[0]['presentation'].update(hpo_present=['microcephaly']),
        'HPO id',
    ),
    'no cutoff recorded': (lambda c: c['answer'].pop('cutoff'), 'Field required'),
    'an unknown field': (lambda c: c['answer'].update(gene='ASPM'), 'Extra inputs'),
}


@pytest.mark.parametrize(('change', 'message'), REJECTED.values(), ids=REJECTED.keys())
def test_record_rejects(release_data: dict[str, Any], change: Change, message: str) -> None:
    with pytest.raises(pydantic.ValidationError, match=message):
        record.Case.model_validate(changed(case_data(release_data), change))
