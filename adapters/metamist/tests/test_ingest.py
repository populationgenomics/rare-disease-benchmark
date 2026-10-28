from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from rare_disease_benchmark.metamist import ingest, records, sample_sheet

from . import fakes

SOURCE_GROUPS = {fakes.MOTHER: 'SGX1', fakes.FATHER: 'SGX2', fakes.CHILD: 'SGX3'}


def plan(
    metamist: fakes.FakeMetamist,
    *,
    storage: fakes.FakeStorage | None = None,
    ids: Sequence[str] = fakes.TRIO,
    ped: dict[str, records.Member] | None = None,
    cram_template: str = fakes.CRAM_TEMPLATE,
) -> ingest.Plan:
    return ingest.plan(
        metamist,
        fakes.storage_with_source_crams(*SOURCE_GROUPS.values()) if storage is None else storage,
        source=fakes.SOURCE,
        target=fakes.TARGET,
        family=fakes.FAMILY,
        ids=ids,
        cram_template=cram_template,
        ped=ped,
    )


def ped_trio(**changes: records.Member) -> dict[str, records.Member]:
    members = {
        fakes.MOTHER: records.Member(id=fakes.MOTHER, sex='female', father=None, mother=None),
        fakes.FATHER: records.Member(id=fakes.FATHER, sex='male', father=None, mother=None),
        fakes.CHILD: records.Member(id=fakes.CHILD, sex='female', father=fakes.FATHER, mother=fakes.MOTHER),
    }
    return members | changes


def test_a_new_family_points_at_the_source_crams_and_keeps_its_pedigree() -> None:
    result = plan(fakes.FakeMetamist().with_trio_source())
    assert [p.external_id for p in result.create] == list(fakes.TRIO)
    for new in result.create:
        cram = fakes.cram_url(SOURCE_GROUPS[new.external_id])
        assert (new.cram, new.crai) == (cram, f'{cram}.crai')
        assert new.sex == fakes.SEXES[new.external_id]
        assert new.sequencing_type == records.GENOME
    parents = {m.id: (m.father, m.mother) for m in result.pedigree}
    assert parents == {r.individual: (r.father, r.mother) for r in fakes.trio_rows()}


def test_a_rerun_writes_nothing() -> None:
    metamist = fakes.FakeMetamist().with_trio_source()
    ingest.apply(plan(metamist), metamist)
    assert metamist.calls == [('create_participants', fakes.TARGET), ('import_pedigree', fakes.TARGET)]
    again = plan(metamist)
    assert (again.create, again.pedigree) == ((), ())
    assert len(metamist.projects[fakes.TARGET]) == len(fakes.TRIO)


def test_a_rerun_after_an_interrupted_run_imports_only_the_pedigree() -> None:
    metamist = fakes.FakeMetamist().with_trio_source()
    first = plan(metamist)
    metamist.create_participants(fakes.TARGET, first.create)
    again = plan(metamist)
    assert again.create == ()
    assert {m.id for m in again.pedigree} == set(fakes.TRIO)


def test_the_sample_sheet_of_an_ingested_family_names_the_targets_sequencing_groups() -> None:
    metamist = fakes.FakeMetamist().with_trio_source()
    ingest.apply(plan(metamist), metamist)
    sheet = {row.sample: row for row in sample_sheet.rows(metamist, fakes.TARGET, fakes.FAMILY)}
    groups = {p.external_id: p.samples[0].sequencing_groups[0].id for p in metamist.projects[fakes.TARGET]}
    assert set(sheet) == set(groups.values())
    child = sheet[groups[fakes.CHILD]]
    assert (child.father, child.mother) == (groups[fakes.FATHER], groups[fakes.MOTHER])
    assert child.cram == fakes.cram_url(SOURCE_GROUPS[fakes.CHILD])


def test_a_ped_file_supplies_what_the_source_lacks() -> None:
    result = plan(fakes.FakeMetamist().with_trio_source(sexes=False, pedigree=False), ped=ped_trio())
    assert set(result.pedigree) == set(ped_trio().values())
    assert {p.external_id: p.sex for p in result.create} == fakes.SEXES


@pytest.mark.parametrize(
    ('sexes', 'pedigree', 'message'),
    [(False, True, 'no recorded sex; give a PED file'), (True, False, 'in no family; give a PED file')],
)
def test_without_a_ped_file_the_source_must_record_sex_and_pedigree(sexes: bool, pedigree: bool, message: str) -> None:
    with pytest.raises(records.RecordError, match=message):
        plan(fakes.FakeMetamist().with_trio_source(sexes=sexes, pedigree=pedigree))


@pytest.mark.parametrize(
    'ped',
    [
        ped_trio(**{fakes.CHILD: records.Member(id=fakes.CHILD, sex='male', father=fakes.FATHER, mother=fakes.MOTHER)}),
        ped_trio(**{fakes.CHILD: records.Member(id=fakes.CHILD, sex='female', father=None, mother=fakes.MOTHER)}),
    ],
    ids=['sex', 'parents'],
)
def test_a_ped_file_that_contradicts_the_source_is_refused(ped: dict[str, records.Member]) -> None:
    with pytest.raises(records.RecordError, match='the PED file as'):
        plan(fakes.FakeMetamist().with_trio_source(), ped=ped)


def _second_genome_in_another_sample(metamist: fakes.FakeMetamist) -> None:
    [child] = metamist.participants(fakes.SOURCE, [fakes.CHILD])
    extra = records.Sample(id='SMX9', external_id='other', type='blood', sequencing_groups=(fakes.genome('SGX9'),))
    metamist.projects[fakes.SOURCE].remove(child)
    metamist.add(fakes.SOURCE, child.model_copy(update={'samples': (*child.samples, extra)}))


def _child_missing(metamist: fakes.FakeMetamist) -> None:
    [child] = metamist.participants(fakes.SOURCE, [fakes.CHILD])
    metamist.projects[fakes.SOURCE].remove(child)


def _no_genome(metamist: fakes.FakeMetamist) -> None:
    _child_missing(metamist)
    exome = fakes.genome('SGX9').model_copy(update={'type': 'exome'})
    metamist.add(fakes.SOURCE, fakes.participant(fakes.CHILD, 'female', exome, pid=3))


def _target_holds(*participants: records.Participant) -> Callable[[fakes.FakeMetamist], None]:
    return lambda metamist: metamist.add(fakes.TARGET, *participants)


def _target_rows(*rows: records.PedigreeRow) -> Callable[[fakes.FakeMetamist], None]:
    return lambda metamist: metamist.add_rows(fakes.TARGET, *rows)


REFUSED: dict[str, tuple[Callable[[fakes.FakeMetamist], None], str]] = {
    'member missing from the source': (
        _child_missing,
        f'no participant has the external id {fakes.CHILD}',
    ),
    'two source participants with one id': (
        lambda m: m.add(fakes.SOURCE, fakes.participant(fakes.CHILD, 'female', fakes.genome('SGX9'), pid=9)),
        f'2 participants have the external id {fakes.CHILD}',
    ),
    'two genomes in two samples': (_second_genome_in_another_sample, '2 active genome sequencing groups'),
    'no genome': (_no_genome, '0 active genome sequencing groups'),
    'a member in two source families': (
        lambda m: m.add_rows(
            fakes.SOURCE, records.PedigreeRow(family='other', individual=fakes.CHILD, father=None, mother=None)
        ),
        'in 2 families',
    ),
    'a target participant of another sex': (
        _target_holds(fakes.participant(fakes.CHILD, 'male', fakes.genome('SGT1', cram=fakes.cram_url('SGX3')))),
        'is recorded as male, but is female',
    ),
    'a target participant reading another CRAM': (
        _target_holds(fakes.participant(fakes.CHILD, 'female', fakes.genome('SGT1'))),
        'reads gs://source-bucket/cram/SGT1.cram',
    ),
    'a target participant with two genomes': (
        _target_holds(fakes.participant(fakes.CHILD, 'female', fakes.genome('SGT1'), fakes.genome('SGT2'))),
        '2 active genome sequencing groups',
    ),
    'a member already in another target family': (
        _target_rows(records.PedigreeRow(family='other', individual=fakes.CHILD, father=None, mother=None)),
        f'{fakes.CHILD} is in the family other',
    ),
    'the target family holding someone else': (
        _target_rows(records.PedigreeRow(family=fakes.FAMILY, individual='stranger_1', father=None, mother=None)),
        'holds stranger_1, who is not a member',
    ),
    'the target family recording other parents': (
        _target_rows(records.PedigreeRow(family=fakes.FAMILY, individual=fakes.CHILD, father=None, mother=None)),
        f'records the parents of {fakes.CHILD} as None and None',
    ),
}


@pytest.mark.parametrize('case', REFUSED)
def test_ambiguous_or_contradicting_records_are_refused(case: str) -> None:
    change, message = REFUSED[case]
    metamist = fakes.FakeMetamist().with_trio_source()
    change(metamist)
    with pytest.raises(records.RecordError, match=message):
        plan(metamist)


@pytest.mark.parametrize('missing', ['SGX3.cram', 'SGX3.cram.crai'])
def test_a_missing_cram_or_crai_is_refused(missing: str) -> None:
    storage = fakes.storage_with_source_crams(*SOURCE_GROUPS.values())
    storage.urls.remove(f'gs://source-bucket/cram/{missing}')
    with pytest.raises(records.RecordError, match=f'{missing}, of {fakes.CHILD}, does not exist'):
        plan(fakes.FakeMetamist().with_trio_source(), storage=storage)


def test_a_parent_left_out_of_the_members_is_refused() -> None:
    with pytest.raises(records.RecordError, match=f'the father of {fakes.CHILD}, {fakes.FATHER}, is not in the family'):
        plan(fakes.FakeMetamist().with_trio_source(), ids=(fakes.MOTHER, fakes.CHILD))


@pytest.mark.parametrize('ids', [(), (fakes.CHILD, fakes.CHILD)])
def test_members_must_be_distinct_and_present(ids: tuple[str, ...]) -> None:
    with pytest.raises(records.RecordError, match='distinct and at least one'):
        plan(fakes.FakeMetamist().with_trio_source(), ids=ids)


@pytest.mark.parametrize(
    'template', ['gs://bucket/cram.cram', 'gs://bucket/{sample}.cram', 'gs://b/{sequencing_group}/{sample}.cram']
)
def test_a_cram_template_must_name_only_the_sequencing_group(template: str) -> None:
    with pytest.raises(ValueError, match='one field'):
        ingest.check_cram_template(template)
