"""Backgrounds, case instances, and the withheld side of a release.

A case instance is one case built into one background, as issued in one release: the family's synthetic genomes, one
per member, together with its pedigree and clinical presentation. Its id is the id of the item a system under test
receives. A release may hold several instances of the same case, each in a different background, which is how results
are checked for robustness to the background.

This module holds what connects an instance to its case, which is withheld. What a system under test receives is built
from it by `blinding.open_view`.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Iterable
from typing import Literal, Self

import pydantic

from rare_disease_benchmark.schema import ids, record, visibility

_VERSION = re.compile(r'\d+\.\d+\.\d+')


class Background(visibility.WithheldModel, frozen=True):
    """A catalogue entry: one prepared trio. Only the fields a case instance is checked against."""

    id: ids.BackgroundId
    child_sex: Literal['male', 'female']


class InstanceMember(visibility.WithheldModel, frozen=True):
    """One family member's id in the case record, and the id the release gives that member in this instance."""

    sample: ids.SampleId
    release_sample: ids.ReleaseSampleId


class CaseInstance(visibility.WithheldModel, frozen=True):
    """One case built into one background, as issued in one release.

    The case's proband is built into the background's child, and the proband's parents, where the case includes them,
    into the background's parents. The released files follow the case's family, so a case without parents yields the
    proband's files only.
    """

    id: ids.CaseInstanceId
    case: ids.CaseId
    background: ids.BackgroundId
    pipeline_version: str
    members: tuple[InstanceMember, ...]  # every member of the case's family, once

    def release_sample(self, sample: ids.SampleId) -> ids.ReleaseSampleId:
        for m in self.members:
            if m.sample == sample:
                return m.release_sample
        raise KeyError(f'{sample!r} is not a member of case instance {self.id!r}')

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        for field in ('sample', 'release_sample'):
            if repeated := _repeated(getattr(m, field) for m in self.members):
                raise ValueError(f'case instance {self.id!r} repeats {field} {repeated}')
        return self


class WithheldRelease(visibility.WithheldModel, frozen=True):
    """The withheld side of one release: its cases, the backgrounds they are built into, and the instances."""

    release: str  # the release version, e.g. 1.0.0
    cases: tuple[record.Case, ...]
    backgrounds: tuple[Background, ...]
    instances: tuple[CaseInstance, ...]

    def case(self, case_id: ids.CaseId) -> record.Case:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise KeyError(f'no case {case_id!r} in release {self.release}')

    def background(self, background_id: ids.BackgroundId) -> Background:
        for b in self.backgrounds:
            if b.id == background_id:
                return b
        raise KeyError(f'no background {background_id!r} in release {self.release}')

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        if not _VERSION.fullmatch(self.release):
            raise ValueError(f'release version {self.release!r} is not of the form MAJOR.MINOR.PATCH')
        for name, values in (
            ('case id', (c.id for c in self.cases)),
            ('background id', (b.id for b in self.backgrounds)),
            ('case instance id', (i.id for i in self.instances)),
            ('(case, background) pair', ((i.case, i.background) for i in self.instances)),
            ('release sample id', (m.release_sample for i in self.instances for m in i.members)),
        ):
            if repeated := _repeated(values):
                raise ValueError(f'release {self.release} repeats {name} {repeated}')
        case_ids = {c.id for c in self.cases}
        background_ids = {b.id for b in self.backgrounds}
        for instance in self.instances:
            if instance.case not in case_ids:
                raise ValueError(f'case instance {instance.id!r} names unknown case {instance.case!r}')
            if instance.background not in background_ids:
                raise ValueError(f'case instance {instance.id!r} names unknown background {instance.background!r}')
            case = self.case(instance.case)
            _check_fits(case, self.background(instance.background), instance)
            _check_opaque(case, instance)
        return self


def _repeated[T](values: Iterable[T]) -> list[T]:
    return [value for value, count in collections.Counter(values).items() if count > 1]


def _check_fits(case: record.Case, background: Background, instance: CaseInstance) -> None:
    """Reject an instance whose case cannot be built into its background."""
    family = case.open.family
    proband = family.proband_individual
    trio = {proband.id, proband.father, proband.mother} - {None}
    if beyond := sorted(m.id for m in family.members if m.id not in trio):
        raise ValueError(
            f'case instance {instance.id!r}: background {background.id!r} is a trio, '
            f'and case {case.id!r} has members beyond the proband and their parents: {beyond}'
        )
    if proband.sex != background.child_sex:
        raise ValueError(
            f'case instance {instance.id!r}: the proband of case {case.id!r} is {proband.sex}, '
            f'and the child of background {background.id!r} is {background.child_sex}'
        )
    mapped = {m.sample for m in instance.members}
    members = {m.id for m in family.members}
    if mapped != members:
        raise ValueError(
            f'case instance {instance.id!r} maps samples {sorted(mapped)}, '
            f'and case {case.id!r} has members {sorted(members)}'
        )


def _check_opaque(case: record.Case, instance: CaseInstance) -> None:
    """Reject open ids that would point a system under test at the case."""
    revealing = [s for s in (case.id, case.source.accession) if s is not None]
    member_ids = {m.id for m in case.open.family.members}
    for open_id in (instance.id, *(m.release_sample for m in instance.members)):
        if open_id in member_ids:
            raise ValueError(f'open id {open_id!r} of case instance {instance.id!r} is a member id of the case record')
        for s in revealing:
            if s.casefold() in open_id.casefold():
                raise ValueError(f'open id {open_id!r} of case instance {instance.id!r} contains {s!r}')
