"""What a system under test receives for one case instance. Everything here is on the open side."""

from __future__ import annotations

import datetime as dt

from rare_disease_benchmark.schema import ids, record, visibility


class Manifest(visibility.OpenModel, frozen=True):
    """The open record of one case instance; it travels with the files and says nothing about how they were built."""

    id: ids.CaseInstanceId
    release: str  # the release version; a result is always quoted against it
    cutoff: dt.date | None  # the harness rolls clinical-assertion resources and literature back to before it


class Item(visibility.OpenModel, frozen=True):
    """One case instance as a system under test receives it, apart from the sequencing files themselves."""

    manifest: Manifest
    input: record.CaseOpen  # the case's open section, keyed by release sample ids

    @property
    def id(self) -> ids.CaseInstanceId:
        return self.manifest.id
