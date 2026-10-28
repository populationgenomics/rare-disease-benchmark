"""The build pipeline's manifest: what one run published, and where.

A run publishes everything under one directory, `<output_dir>/backgrounds/<background>/<version>/`, and writes two JSON
files there, each a list of records (see `build/README.md`, section "Outputs"). `samples.json` holds one record per
sample, named by the sample sheet's id, with its CRAM, its gVCF, their indexes and every other file its calling wrote.
`family.json` holds one record for the family, named by the background, with the joint VCF, its index, the PED file and
the other files of joint calling. Paths are where the files were published, as URIs (`gs://...` on Google Cloud).

The models below are the pipeline's side of the contract. They reject unknown keys, so that a field the pipeline adds
is a decision for this adapter rather than something it silently drops, and they check the layout, so that a manifest
whose paths point elsewhere than its own run fails before anything is registered.
"""

from __future__ import annotations

import collections
import posixpath
from collections.abc import Iterable
from typing import Self

import pydantic


class SampleOutputs(pydantic.BaseModel, frozen=True, extra='forbid'):
    """One record of `samples.json`: a sample's files."""

    id: str
    cram: str
    cram_index: str
    gvcf: str
    gvcf_index: str
    other: tuple[str, ...]  # metrics and logs

    def paths(self) -> tuple[str, ...]:
        return (self.cram, self.cram_index, self.gvcf, self.gvcf_index, *self.other)


class FamilyOutputs(pydantic.BaseModel, frozen=True, extra='forbid'):
    """The record of `family.json`: the family's files, named by the background."""

    id: str
    vcf: str
    vcf_index: str
    pedigree: str
    other: tuple[str, ...]  # metrics and logs

    def paths(self) -> tuple[str, ...]:
        return (self.vcf, self.vcf_index, self.pedigree, *self.other)


class Manifest(pydantic.BaseModel, frozen=True, extra='forbid'):
    """One run's manifest: its samples and its family."""

    samples: tuple[SampleOutputs, ...]
    family: FamilyOutputs

    @property
    def background(self) -> str:
        return self.family.id

    @property
    def directory(self) -> str:
        """The run's directory, `<output_dir>/backgrounds/<background>/<version>`, without a trailing slash."""
        return posixpath.dirname(posixpath.dirname(self.family.vcf))

    @property
    def version(self) -> str:
        """The pipeline version that wrote the run, as its directory names it."""
        return posixpath.basename(self.directory)

    def paths(self) -> tuple[str, ...]:
        return (*(p for s in self.samples for p in s.paths()), *self.family.paths())

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        if not self.samples:
            raise ValueError('the manifest lists no samples')
        if repeated := _repeated(s.id for s in self.samples):
            raise ValueError(f'the manifest repeats sample {repeated}')
        directory = self.directory
        parts = directory.rsplit('/', 3)
        if len(parts) != 4 or parts[1:3] != ['backgrounds', self.background]:
            raise ValueError(
                f'the family VCF {self.family.vcf!r} is not under backgrounds/{self.background}/<version>/family/'
            )
        expected = [(f'{directory}/samples/{s.id}/', s.paths()) for s in self.samples]
        expected.append((f'{directory}/family/', self.family.paths()))
        for prefix, paths in expected:
            for path in paths:
                if not path.startswith(prefix) or path == prefix:
                    raise ValueError(f'{path!r} is not a file under {prefix!r}')
        return self


_SAMPLES = pydantic.TypeAdapter(tuple[SampleOutputs, ...])
_FAMILIES = pydantic.TypeAdapter(tuple[FamilyOutputs, ...])


def parse(samples_json: str, family_json: str) -> Manifest:
    """Parses the contents of `samples.json` and `family.json`; raises `ValueError` if either is malformed."""
    families = _FAMILIES.validate_json(family_json)
    if len(families) != 1:
        raise ValueError(f'family.json must hold one record, and holds {len(families)}')
    return Manifest(samples=_SAMPLES.validate_json(samples_json), family=families[0])


def _repeated[T](values: Iterable[T]) -> list[T]:
    return [value for value, count in collections.Counter(values).items() if count > 1]
