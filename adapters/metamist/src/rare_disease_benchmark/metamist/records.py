"""What the commands read from a sample registry and write to it, and the interfaces they do it through.

The commands see Metamist only through `Registry` (reads), `Writer` (writes) and `Storage` (whether a file exists), so
tests replace all three, and `ingest --dry-run` replaces the writer with one that prints.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal, Protocol

import pydantic

type Sex = Literal['male', 'female']

# The sequencing group type of a whole genome, as Metamist names it.
GENOME = 'genome'


class RecordError(Exception):
    """The registry's records are missing, ambiguous or contradict what a command needs."""


class Model(pydantic.BaseModel, frozen=True, extra='forbid'):
    pass


class File(Model, frozen=True):
    """A file an assay reads, with its index files."""

    location: str
    secondary_files: tuple[File, ...] = ()


class Assay(Model, frozen=True):
    id: int
    type: str
    reads: tuple[File, ...]  # empty: the assay records no reads


class SequencingGroup(Model, frozen=True):
    id: str
    type: str
    technology: str
    platform: str
    assays: tuple[Assay, ...]


class Sample(Model, frozen=True):
    id: str
    external_id: str
    type: str
    sequencing_groups: tuple[SequencingGroup, ...]  # active ones only


class Participant(Model, frozen=True):
    id: int
    external_id: str  # the primary external id
    sex: Sex | None  # None: not recorded
    samples: tuple[Sample, ...]  # active ones only


class PedigreeRow(Model, frozen=True):
    """A participant's place in one family, by external ids."""

    family: str
    individual: str
    father: str | None  # None: no father recorded
    mother: str | None  # None: no mother recorded


class Member(Model, frozen=True):
    """One member of a family as the commands use it: sex and parents, by external ids."""

    id: str
    sex: Sex
    father: str | None  # None: a founder on the father's side
    mother: str | None  # None: a founder on the mother's side


class NewParticipant(Model, frozen=True):
    """A participant to create, with one sample holding one sequencing group with one assay that reads a CRAM."""

    external_id: str
    sex: Sex
    sample_type: str
    sequencing_type: str
    technology: str
    platform: str
    cram: str
    crai: str


class Registry(Protocol):
    def participants(self, project: str, external_ids: Collection[str]) -> tuple[Participant, ...]:
        """The participants that have any of these external ids, with their active samples and sequencing groups."""
        ...

    def pedigree(self, project: str, external_ids: Collection[str]) -> tuple[PedigreeRow, ...]:
        """Every row of every family that a participant with any of these external ids belongs to."""
        ...

    def family_pedigree(self, project: str, family: str) -> tuple[PedigreeRow, ...]:
        """The rows of the family with this external id; empty if there is no such family."""
        ...


class Writer(Protocol):
    def create_participants(self, project: str, participants: tuple[NewParticipant, ...]) -> None: ...

    def import_pedigree(self, project: str, family: str, members: tuple[Member, ...]) -> None:
        """Puts the members into the family, creating it if needed; the participants exist already."""
        ...


class Storage(Protocol):
    def is_file(self, location: str) -> bool: ...
