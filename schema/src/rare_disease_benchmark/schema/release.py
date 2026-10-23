"""Case instances and the withheld side of a release.

A case instance is one case built into the sequencing data of real samples, as issued in one release: a synthetic
genome for each family member, together with the pedigree and clinical presentation. The harness runs it, and keys the
submission, under its id. A release may hold several instances of the same case, each built into different samples,
which is how results are checked for robustness to the background.

Which samples a case can be built into (their relationships and sexes against the case's family, and the family
structures a pipeline version handles) is checked by the build against its own data, not here.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Iterable
from typing import Self

import pydantic

from rare_disease_benchmark.schema import ids, record, visibility

_VERSION = re.compile(r'\d+\.\d+\.\d+')


class MemberSample(visibility.WithheldModel, frozen=True):
    """One family member of the case, and the sample whose data was edited for them."""

    member: ids.MemberId
    sample: ids.SampleId


class CaseInstance(visibility.WithheldModel, frozen=True):
    """One case built into the sequencing data of real samples, as issued in one release.

    The pipeline version pins the prepared data the build used for each sample: the calls, the phasing and the added
    variants. The build names each sample in the released files by the member's id in the case.
    """

    id: ids.CaseInstanceId
    case: ids.CaseId
    pipeline_version: str
    samples: tuple[MemberSample, ...]  # every member of the case's family, once

    def sample(self, member_id: ids.MemberId) -> ids.SampleId:
        for s in self.samples:
            if s.member == member_id:
                return s.sample
        raise KeyError(f'{member_id!r} is not a member of case instance {self.id!r}')

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        for field in ('member', 'sample'):
            if repeated := _repeated(getattr(s, field) for s in self.samples):
                raise ValueError(f'case instance {self.id!r} repeats {field} {repeated}')
        return self


class WithheldRelease(visibility.WithheldModel, frozen=True):
    """The withheld side of one release: its cases, and the instances built from them."""

    release: str  # the release version, e.g. 1.0.0
    cases: tuple[record.Case, ...]
    instances: tuple[CaseInstance, ...]

    def case(self, case_id: ids.CaseId) -> record.Case:
        for c in self.cases:
            if c.id == case_id:
                return c
        raise KeyError(f'no case {case_id!r} in release {self.release}')

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        if not _VERSION.fullmatch(self.release):
            raise ValueError(f'release version {self.release!r} is not of the form MAJOR.MINOR.PATCH')
        for name, values in (
            ('case id', (c.id for c in self.cases)),
            ('case instance id', (i.id for i in self.instances)),
            (
                'case built into the same samples',
                ((i.case, frozenset(s.sample for s in i.samples)) for i in self.instances),
            ),
        ):
            if repeated := _repeated(values):
                raise ValueError(f'release {self.release} repeats {name} {repeated}')
        case_ids = {c.id for c in self.cases}
        for instance in self.instances:
            if instance.case not in case_ids:
                raise ValueError(f'case instance {instance.id!r} names unknown case {instance.case!r}')
            members = {m.id for m in self.case(instance.case).family.members}
            mapped = {s.member for s in instance.samples}
            if mapped != members:
                raise ValueError(
                    f'case instance {instance.id!r} maps members {sorted(mapped)}, '
                    f'and case {instance.case!r} has members {sorted(members)}'
                )
        return self


def _repeated[T](values: Iterable[T]) -> list[T]:
    return [value for value, count in collections.Counter(values).items() if count > 1]
