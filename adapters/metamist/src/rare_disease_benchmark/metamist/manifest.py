"""The build pipeline's manifest: what one run published, and where.

A run publishes everything under one directory, `<output_dir>/backgrounds/<background>/<version>/`, and writes two JSON
files there, each a list of records (see `build/README.md`, section "Outputs"). `samples.json` holds one record per
sample, named by the sample sheet's id, with its CRAM, its gVCF, their indexes, DRAGEN's settings for the run and every
other file its calling wrote. `family.json` holds one record for the family, named by the background, with the joint
VCF, its index, the PED file, DRAGEN's settings and the other files of joint calling. A whole genome's records also name
the structural variant and copy number calls (and, for a trio, the UPD calls); a slice's do not. Paths are where the
files were published, as URIs (`gs://...` on Google Cloud).

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
    dragen_replay: str
    # A whole genome's; a slice has none of them.
    sv_vcf: str | None = None
    cnv_vcf: str | None = None
    cnv_counts: str | None = None
    other: tuple[str, ...]  # metrics, logs and the other callers' files

    @property
    def whole_genome(self) -> bool:
        return self.sv_vcf is not None

    def paths(self) -> tuple[str, ...]:
        whole_genome = (p for p in (self.sv_vcf, self.cnv_vcf, self.cnv_counts) if p is not None)
        return (self.cram, self.cram_index, self.gvcf, self.gvcf_index, self.dragen_replay, *whole_genome, *self.other)

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        _together(self, ('sv_vcf', 'cnv_vcf', 'cnv_counts'))
        return self


class FamilyOutputs(pydantic.BaseModel, frozen=True, extra='forbid'):
    """The record of `family.json`: the family's files, named by the background."""

    id: str
    vcf: str
    vcf_index: str
    pedigree: str
    dragen_replay: str
    # A whole genome's; a slice has none of them, and only a trio has UPD calls.
    cnv_vcf: str | None = None
    sv_vcf: str | None = None
    upd_vcf: str | None = None
    other: tuple[str, ...]  # metrics, logs and the other joint steps' files

    @property
    def whole_genome(self) -> bool:
        return self.sv_vcf is not None

    def paths(self) -> tuple[str, ...]:
        whole_genome = (p for p in (self.cnv_vcf, self.sv_vcf, self.upd_vcf) if p is not None)
        return (self.vcf, self.vcf_index, self.pedigree, self.dragen_replay, *whole_genome, *self.other)

    @pydantic.model_validator(mode='after')
    def _check(self) -> Self:
        _together(self, ('cnv_vcf', 'sv_vcf'))
        if self.upd_vcf is not None and not self.whole_genome:
            raise ValueError("a family record with UPD calls must be a whole genome's")
        return self


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
        if any(s.whole_genome != self.family.whole_genome for s in self.samples):
            raise ValueError('the manifest mixes whole-genome and slice records')
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


def _together(record: SampleOutputs | FamilyOutputs, fields: tuple[str, ...]) -> None:
    """Raises unless the record has all of the fields or none."""
    present = [f for f in fields if getattr(record, f) is not None]
    if present and len(present) != len(fields):
        raise ValueError(f'{type(record).__name__} {record.id!r} has {present} but not all of {list(fields)}')
