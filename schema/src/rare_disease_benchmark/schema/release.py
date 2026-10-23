"""Backgrounds, case instances, and the withheld side of a release.

A case instance is one case built into one background, as issued in one release: the family's synthetic genomes, one
per member, together with its pedigree and clinical presentation. The harness runs it, and keys the submission, under
its id. A release may hold several instances of the same case, each in a different background, which is how results
are checked for robustness to the background.
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


class CaseInstance(visibility.WithheldModel, frozen=True):
    """One case built into one background, as issued in one release.

    The case's proband is built into the background's child, and the proband's parents, where the case includes them,
    into the background's parents. The build names each sample by the member's id in the case, and the released files
    follow the case's family, so a case without parents yields the proband's files only.
    """

    id: ids.CaseInstanceId
    case: ids.CaseId
    background: ids.BackgroundId
    pipeline_version: str


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
            _check_fits(self.case(instance.case), self.background(instance.background), instance)
        return self


def _repeated[T](values: Iterable[T]) -> list[T]:
    return [value for value, count in collections.Counter(values).items() if count > 1]


def _check_fits(case: record.Case, background: Background, instance: CaseInstance) -> None:
    """Reject an instance whose case cannot be built into its background."""
    family = case.family
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
