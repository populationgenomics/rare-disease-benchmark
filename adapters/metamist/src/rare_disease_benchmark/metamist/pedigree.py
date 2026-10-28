"""Families: reading members from a PED file, and checking that a family is whole and consistent."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from rare_disease_benchmark.metamist import records

_PED_SEX: dict[str, records.Sex] = {'1': 'male', '2': 'female'}


def read_ped(text: str, ids: Collection[str], name: str) -> dict[str, records.Member]:
    """The members with these ids, from the text of a PED file named `name`.

    Columns are whitespace-separated and read by position: family, individual, father, mother, sex. The family column
    is ignored, and so is every row of someone else, which covers header lines and extra columns such as those of the
    public 1000 Genomes pedigrees.
    """
    found: dict[str, list[list[str]]] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#') or len(fields) < 2 or fields[1] not in ids:
            continue
        if len(fields) < 5:
            raise records.RecordError(f'{name}: the row of {fields[1]} has {len(fields)} columns, expected at least 5')
        found.setdefault(fields[1], []).append(fields)
    members = {}
    for member in ids:
        rows = found.get(member, [])
        if len(rows) != 1:
            raise records.RecordError(f'{name}: {len(rows)} rows for {member}, expected one')
        _, _, father, mother, sex = rows[0][:5]
        if sex not in _PED_SEX:
            raise records.RecordError(f'{name}: {member} has sex {sex!r}, expected 1 (male) or 2 (female)')
        members[member] = records.Member(
            id=member,
            sex=_PED_SEX[sex],
            father=None if father == '0' else father,
            mother=None if mother == '0' else mother,
        )
    return members


def check_family(members: Iterable[records.Member], name: str) -> None:
    """Raises unless each parent is another member, of the right sex, and no one is their own ancestor."""
    by_id: dict[str, records.Member] = {}
    for member in members:
        if member.id in by_id:
            raise records.RecordError(f'{name}: {member.id} appears twice')
        by_id[member.id] = member
    for member in by_id.values():
        for role, parent, sex in (('father', member.father, 'male'), ('mother', member.mother, 'female')):
            if parent is None:
                continue
            if parent not in by_id:
                raise records.RecordError(f'{name}: the {role} of {member.id}, {parent}, is not in the family')
            if by_id[parent].sex != sex:
                raise records.RecordError(f'{name}: {parent} is the {role} of {member.id} but {by_id[parent].sex}')
    _check_acyclic(by_id, name)


def _check_acyclic(by_id: dict[str, records.Member], name: str) -> None:
    placed: set[str] = set()
    remaining = dict(by_id)
    while remaining:
        ready = [
            member.id
            for member in remaining.values()
            if all(parent is None or parent in placed for parent in (member.father, member.mother))
        ]
        if not ready:
            raise records.RecordError(f'{name}: {", ".join(sorted(remaining))} descend from themselves')
        placed.update(ready)
        for member in ready:
            del remaining[member]
