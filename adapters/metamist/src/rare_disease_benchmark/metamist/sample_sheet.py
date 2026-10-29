"""Writes the build pipeline's sample sheet for one family in a project.

One row per member of the family: the member's genome sequencing group id as the sample, the member's sex, the
sequencing group ids of the father and mother (empty for a founder), and the CRAM and CRAI that the sequencing group's
assay reads. The header is the one `build/main.nf` reads.
"""

from __future__ import annotations

import csv
import io

from rare_disease_benchmark.metamist import lookup, pedigree, records

HEADER = ('sample', 'sex', 'father', 'mother', 'cram', 'crai')


class Row(records.Model, frozen=True):
    sample: str
    sex: records.Sex
    father: str  # empty: a founder
    mother: str  # empty: a founder
    cram: str
    crai: str


def rows(registry: records.Registry, project: str, family: str) -> tuple[Row, ...]:
    """The family's rows, sorted by sample."""
    pedigree_rows = registry.family_pedigree(project, family)
    if not pedigree_rows:
        raise records.RecordError(f'{project}: no family {family}')
    ids = [row.individual for row in pedigree_rows]
    participants = registry.participants(project, ids)
    members = []
    groups = {}
    for row in pedigree_rows:
        participant = lookup.participant(participants, row.individual, project)
        if participant is None:
            raise records.RecordError(f'{project}: family {family} names {row.individual}, who is not a participant')
        if participant.sex is None:
            raise records.RecordError(f'{project}: {row.individual} has no recorded sex')
        members.append(records.Member(id=row.individual, sex=participant.sex, father=row.father, mother=row.mother))
        _, groups[row.individual] = lookup.genome(participant, project)
    pedigree.check_family(members, f'{project}: family {family}')

    def sample(member: str | None) -> str:
        return '' if member is None else groups[member].id

    sheet = []
    for member in members:
        cram, crai = lookup.cram(groups[member.id], project)
        sheet.append(
            Row(
                sample=sample(member.id),
                sex=member.sex,
                father=sample(member.father),
                mother=sample(member.mother),
                cram=cram,
                crai=crai,
            )
        )
    return tuple(sorted(sheet, key=lambda row: row.sample))


def to_csv(sheet: tuple[Row, ...]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(HEADER)
    writer.writerows([getattr(row, column) for column in HEADER] for row in sheet)
    return out.getvalue()
