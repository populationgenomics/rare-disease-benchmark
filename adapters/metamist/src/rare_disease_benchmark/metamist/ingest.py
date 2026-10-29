"""Copies chosen participants, as one family, from a source project into a target project.

Each member becomes a participant in the target with the source's external id and the member's sex, holding one sample
with one genome sequencing group, whose one assay reads the source's CRAM and CRAI where they lie: no file is copied.
The target mints its own ids. The members then form the named family, with the pedigree's fathers and mothers.

Sex and parents come from the source project, or from a PED file when one is given; when both record them they must
agree. Records the target already holds are checked against what would be written and left alone, so a rerun writes
only what is missing, and a record that disagrees stops the run before anything is written.
"""

from __future__ import annotations

import string
from collections.abc import Mapping, Sequence

from rare_disease_benchmark.metamist import lookup, pedigree, records

TEMPLATE_FIELD = 'sequencing_group'


class Plan(records.Model, frozen=True):
    """The writes that bring the target up to date; nothing to do when both are empty."""

    target: str
    family: str
    create: tuple[records.NewParticipant, ...]
    pedigree: tuple[records.Member, ...]  # empty: the target holds the family already


def check_cram_template(template: str) -> str:
    """Raises ValueError unless the template names the source sequencing group, and nothing else, as a field."""
    fields = {field for _, field, _, _ in string.Formatter().parse(template) if field is not None}
    if fields != {TEMPLATE_FIELD}:
        raise ValueError(f'the CRAM template must have the one field {{{TEMPLATE_FIELD}}}, not {sorted(fields)}')
    return template


def plan(
    registry: records.Registry,
    storage: records.Storage,
    *,
    source: str,
    target: str,
    family: str,
    ids: Sequence[str],
    cram_template: str,
    ped: Mapping[str, records.Member] | None,
) -> Plan:
    """What to write to `target` so that it holds the members `ids` of `source` as the family `family`.

    `cram_template` gives the source CRAM's URL from its sequencing group's id; the CRAI is beside it, with `.crai`
    appended. `ped` is the members as a PED file records them, or None to take them from the source.
    """
    check_cram_template(cram_template)
    if not ids or len(set(ids)) != len(ids):
        raise records.RecordError(f'the members must be distinct and at least one, got {list(ids)}')
    found = {}
    sources = registry.participants(source, ids)
    for member in ids:
        participant = lookup.participant(sources, member, source)
        if participant is None:
            raise records.RecordError(f'{source}: no participant has the external id {member}')
        found[member] = participant
    members = _members(registry, source, found, ped)
    pedigree.check_family(members.values(), f'family {family}')

    wanted = {}
    for member, participant in found.items():
        sample, group = lookup.genome(participant, source)
        cram = cram_template.format(**{TEMPLATE_FIELD: group.id})
        crai = f'{cram}.crai'
        for url in (cram, crai):
            if not storage.is_file(url):
                raise records.RecordError(f'{source}: {url}, of {member}, does not exist')
        wanted[member] = records.NewParticipant(
            external_id=member,
            sex=members[member].sex,
            sample_type=sample.type,
            sequencing_type=group.type,
            technology=group.technology,
            platform=group.platform,
            cram=cram,
            crai=crai,
        )

    create = []
    existing = registry.participants(target, ids)
    for member, new in wanted.items():
        participant = lookup.participant(existing, member, target)
        if participant is None:
            create.append(new)
        else:
            _check_existing(participant, new, target)

    return Plan(
        target=target,
        family=family,
        create=tuple(create),
        pedigree=_pedigree_to_import(registry, target, family, [members[member] for member in ids]),
    )


def apply(plan: Plan, writer: records.Writer) -> None:
    # Participants first: the pedigree import links existing participants and creates none.
    if plan.create:
        writer.create_participants(plan.target, plan.create)
    if plan.pedigree:
        writer.import_pedigree(plan.target, plan.family, plan.pedigree)


def _members(
    registry: records.Registry,
    source: str,
    found: Mapping[str, records.Participant],
    ped: Mapping[str, records.Member] | None,
) -> dict[str, records.Member]:
    rows: dict[str, list[records.PedigreeRow]] = {}
    for row in registry.pedigree(source, list(found)):
        if row.individual in found:
            rows.setdefault(row.individual, []).append(row)
    members = {}
    for member, participant in found.items():
        recorded = rows.get(member, [])
        if len(recorded) > 1:
            families = ', '.join(sorted(row.family for row in recorded))
            raise records.RecordError(f'{source}: {member} is in {len(recorded)} families ({families}), expected one')
        row = recorded[0] if recorded else None
        if ped is None:
            if participant.sex is None:
                raise records.RecordError(f'{source}: {member} has no recorded sex; give a PED file')
            if row is None:
                raise records.RecordError(f'{source}: {member} is in no family; give a PED file')
            members[member] = records.Member(id=member, sex=participant.sex, father=row.father, mother=row.mother)
            continue
        if member not in ped:
            raise records.RecordError(f'the PED file has no row for {member}')
        from_ped = ped[member]
        if participant.sex is not None and participant.sex != from_ped.sex:
            raise records.RecordError(f'{source} records {member} as {participant.sex}, the PED file as {from_ped.sex}')
        if row is not None and (row.father, row.mother) != (from_ped.father, from_ped.mother):
            raise records.RecordError(
                f'{source} records the parents of {member} as {row.father} and {row.mother}, '
                f'the PED file as {from_ped.father} and {from_ped.mother}'
            )
        members[member] = from_ped
    return members


def _check_existing(participant: records.Participant, new: records.NewParticipant, target: str) -> None:
    where = f'{target}: participant {participant.external_id}'
    if participant.sex != new.sex:
        raise records.RecordError(f'{where} is recorded as {participant.sex}, but is {new.sex}')
    _, group = lookup.genome(participant, target)
    cram, crai = lookup.cram(group, target)
    if (cram, crai) != (new.cram, new.crai):
        raise records.RecordError(f'{where} reads {cram} and {crai}, not {new.cram} and {new.crai}')


def _pedigree_to_import(
    registry: records.Registry, target: str, family: str, members: Sequence[records.Member]
) -> tuple[records.Member, ...]:
    by_id = {member.id: member for member in members}
    rows = set(registry.pedigree(target, list(by_id))) | set(registry.family_pedigree(target, family))
    for row in rows:
        member = by_id.get(row.individual)
        if member is None:
            if row.family == family:
                raise records.RecordError(f'{target}: family {family} holds {row.individual}, who is not a member')
            continue
        if row.family != family:
            raise records.RecordError(f'{target}: {row.individual} is in the family {row.family}, not {family}')
        if (row.father, row.mother) != (member.father, member.mother):
            raise records.RecordError(
                f'{target}: family {family} records the parents of {member.id} as {row.father} and {row.mother}, '
                f'not {member.father} and {member.mother}'
            )
    if {row.individual for row in rows if row.family == family} == set(by_id):
        return ()
    # Metamist's import needs every parent named in the file, so the whole family goes in, not only what is missing.
    return tuple(members)
