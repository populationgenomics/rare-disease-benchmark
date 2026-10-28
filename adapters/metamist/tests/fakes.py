"""An in-memory registry and storage standing in for Metamist and cloud storage. Every id here is invented."""

from __future__ import annotations

import itertools
from collections.abc import Collection

from rare_disease_benchmark.metamist import records

SOURCE = 'source-project'
TARGET = 'target-project'
FAMILY = 'trio_a'
CRAM_TEMPLATE = 'gs://source-bucket/cram/{sequencing_group}.cram'
MOTHER, FATHER, CHILD = 'mother_1', 'father_1', 'child_1'
TRIO = (MOTHER, FATHER, CHILD)
SEXES: dict[str, records.Sex] = {MOTHER: 'female', FATHER: 'male', CHILD: 'female'}


def cram_url(group: str) -> str:
    return CRAM_TEMPLATE.format(sequencing_group=group)


def genome(group: str, *, cram: str | None = None, crai: str | None = None) -> records.SequencingGroup:
    """A genome sequencing group whose one assay reads a CRAM, by default the source's own."""
    cram = cram_url(group) if cram is None else cram
    crai = f'{cram}.crai' if crai is None else crai
    return records.SequencingGroup(
        id=group,
        type=records.GENOME,
        technology='short-read',
        platform='illumina',
        assays=(
            records.Assay(
                id=1,
                type='sequencing',
                reads=(records.File(location=cram, secondary_files=(records.File(location=crai),)),),
            ),
        ),
    )


def participant(
    external_id: str, sex: records.Sex | None, *groups: records.SequencingGroup, pid: int = 1
) -> records.Participant:
    """A participant with one sample holding the given sequencing groups."""
    sample = records.Sample(id=f'SMX{pid}', external_id=external_id, type='blood', sequencing_groups=groups)
    return records.Participant(id=pid, external_id=external_id, sex=sex, samples=(sample,))


def trio_rows(family: str = 'source_family') -> tuple[records.PedigreeRow, ...]:
    return (
        records.PedigreeRow(family=family, individual=MOTHER, father=None, mother=None),
        records.PedigreeRow(family=family, individual=FATHER, father=None, mother=None),
        records.PedigreeRow(family=family, individual=CHILD, father=FATHER, mother=MOTHER),
    )


class FakeMetamist:
    """Implements `records.Registry` and `records.Writer`; writes land in the registry, as Metamist's would."""

    def __init__(self) -> None:
        self.projects: dict[str, list[records.Participant]] = {}
        self.rows: dict[str, list[records.PedigreeRow]] = {}
        self.calls: list[tuple[str, str]] = []
        self._ids = itertools.count(1000)

    def add(self, project: str, *participants: records.Participant) -> None:
        self.projects.setdefault(project, []).extend(participants)

    def add_rows(self, project: str, *rows: records.PedigreeRow) -> None:
        self.rows.setdefault(project, []).extend(rows)

    def with_trio_source(self, *, sexes: bool = True, pedigree: bool = True) -> FakeMetamist:
        for pid, member in enumerate(TRIO, start=1):
            self.add(SOURCE, participant(member, SEXES[member] if sexes else None, genome(f'SGX{pid}'), pid=pid))
        if pedigree:
            self.add_rows(SOURCE, *trio_rows())
        return self

    def participants(self, project: str, external_ids: Collection[str]) -> tuple[records.Participant, ...]:
        return tuple(p for p in self.projects.get(project, []) if p.external_id in external_ids)

    def pedigree(self, project: str, external_ids: Collection[str]) -> tuple[records.PedigreeRow, ...]:
        rows = self.rows.get(project, [])
        families = {row.family for row in rows if row.individual in external_ids}
        return tuple(row for row in rows if row.family in families)

    def family_pedigree(self, project: str, family: str) -> tuple[records.PedigreeRow, ...]:
        return tuple(row for row in self.rows.get(project, []) if row.family == family)

    def create_participants(self, project: str, participants: tuple[records.NewParticipant, ...]) -> None:
        self.calls.append(('create_participants', project))
        for new in participants:
            pid = next(self._ids)
            group = genome(f'SGT{pid}', cram=new.cram, crai=new.crai)
            self.add(project, participant(new.external_id, new.sex, group, pid=pid))

    def import_pedigree(self, project: str, family: str, members: tuple[records.Member, ...]) -> None:
        self.calls.append(('import_pedigree', project))
        known = {p.external_id for p in self.projects.get(project, [])}
        assert {m.id for m in members} <= known, 'the import creates no participants'
        ids = {m.id for m in members}
        kept = [row for row in self.rows.get(project, []) if row.individual not in ids]
        self.rows[project] = kept + [
            records.PedigreeRow(family=family, individual=m.id, father=m.father, mother=m.mother) for m in members
        ]


class FakeStorage:
    def __init__(self, *urls: str) -> None:
        self.urls = set(urls)

    def is_file(self, location: str) -> bool:
        return location in self.urls


def storage_with_source_crams(*groups: str) -> FakeStorage:
    return FakeStorage(*(url for group in groups for url in (cram_url(group), f'{cram_url(group)}.crai')))
