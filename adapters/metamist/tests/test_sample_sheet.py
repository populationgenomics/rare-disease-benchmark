from __future__ import annotations

import csv
import io
import pathlib
from collections.abc import Callable

import fakes
import pytest

from rare_disease_benchmark.metamist import records, sample_sheet

GROUPS = {fakes.MOTHER: 'SGT1', fakes.FATHER: 'SGT2', fakes.CHILD: 'SGT3'}
_MAIN_NF = pathlib.Path(__file__).parents[3] / 'build' / 'main.nf'


def family_in_target(**groups: records.SequencingGroup) -> fakes.FakeMetamist:
    metamist = fakes.FakeMetamist()
    for pid, member in enumerate(fakes.TRIO, start=1):
        group = groups.get(member, fakes.genome(GROUPS[member]))
        metamist.add(fakes.TARGET, fakes.participant(member, fakes.SEXES[member], group, pid=pid))
    metamist.add_rows(fakes.TARGET, *fakes.trio_rows(fakes.FAMILY))
    return metamist


def test_the_header_is_the_one_the_pipeline_reads() -> None:
    assert f'CSV with header {",".join(sample_sheet.HEADER)}.' in ' '.join(_MAIN_NF.read_text('utf-8').split())


def test_each_member_is_a_row_named_by_its_sequencing_group_with_parents_by_theirs() -> None:
    text = sample_sheet.to_csv(sample_sheet.rows(family_in_target(), fakes.TARGET, fakes.FAMILY))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [row['sample'] for row in rows] == sorted(GROUPS.values())
    by_sample = {row['sample']: row for row in rows}
    for member, group in GROUPS.items():
        row = by_sample[group]
        assert row['sex'] == fakes.SEXES[member]
        assert (row['cram'], row['crai']) == (fakes.cram_url(group), f'{fakes.cram_url(group)}.crai')
    child = by_sample[GROUPS[fakes.CHILD]]
    assert (child['father'], child['mother']) == (GROUPS[fakes.FATHER], GROUPS[fakes.MOTHER])
    founder = by_sample[GROUPS[fakes.MOTHER]]
    assert (founder['father'], founder['mother']) == ('', '')


def _replace_participant(member: str, sex: records.Sex | None) -> Callable[[fakes.FakeMetamist], None]:
    def change(metamist: fakes.FakeMetamist) -> None:
        [old] = metamist.participants(fakes.TARGET, [member])
        metamist.projects[fakes.TARGET].remove(old)
        metamist.add(fakes.TARGET, old.model_copy(update={'sex': sex}))

    return change


def _drop_participant(metamist: fakes.FakeMetamist) -> None:
    [child] = metamist.participants(fakes.TARGET, [fakes.CHILD])
    metamist.projects[fakes.TARGET].remove(child)


def _child_names_a_stranger(metamist: fakes.FakeMetamist) -> None:
    rows = metamist.rows[fakes.TARGET]
    [child] = [row for row in rows if row.individual == fakes.CHILD]
    rows[rows.index(child)] = child.model_copy(update={'father': 'stranger_1'})


def _assays(*assays: records.Assay) -> records.SequencingGroup:
    return fakes.genome(GROUPS[fakes.CHILD]).model_copy(update={'assays': assays})


_CRAM = records.File(location='gs://b/c.cram', secondary_files=(records.File(location='gs://b/c.cram.crai'),))


def _changed(change: Callable[[fakes.FakeMetamist], None]) -> Callable[[], fakes.FakeMetamist]:
    def build() -> fakes.FakeMetamist:
        metamist = family_in_target()
        change(metamist)
        return metamist

    return build


def _child(group: records.SequencingGroup) -> Callable[[], fakes.FakeMetamist]:
    return lambda: family_in_target(**{fakes.CHILD: group})


REFUSED: dict[str, tuple[Callable[[], fakes.FakeMetamist], str]] = {
    'a member without a known sex': (_changed(_replace_participant(fakes.CHILD, None)), 'has no recorded sex'),
    'a pedigree naming a non-participant': (_changed(_drop_participant), 'who is not a participant'),
    'a parent outside the family': (
        _changed(_child_names_a_stranger),
        f'the father of {fakes.CHILD}, stranger_1, is not in the family',
    ),
    'no CRAI': (_child(fakes.genome(GROUPS[fakes.CHILD], crai='gs://b/c.bai')), '0 CRAI files'),
    'a BAM': (_child(fakes.genome(GROUPS[fakes.CHILD], cram='gs://b/c.bam')), 'not a CRAM'),
    'no reads': (_child(_assays(records.Assay(id=1, type='sequencing', reads=()))), '0 files'),
    'two assays': (
        _child(
            _assays(
                records.Assay(id=1, type='sequencing', reads=(_CRAM,)),
                records.Assay(id=2, type='sequencing', reads=(_CRAM,)),
            )
        ),
        '2 assays',
    ),
    'no genome': (_child(fakes.genome(GROUPS[fakes.CHILD]).model_copy(update={'type': 'exome'})), '0 active genome'),
}


@pytest.mark.parametrize('case', REFUSED)
def test_missing_or_ambiguous_records_are_refused(case: str) -> None:
    build, message = REFUSED[case]
    with pytest.raises(records.RecordError, match=message):
        sample_sheet.rows(build(), fakes.TARGET, fakes.FAMILY)


def test_an_unknown_family_is_refused() -> None:
    with pytest.raises(records.RecordError, match='no family other'):
        sample_sheet.rows(family_in_target(), fakes.TARGET, 'other')
