"""Identifiers, and which side of a release each one lives on."""

from __future__ import annotations

# Withheld: the case's own id, never written to the open side.
type CaseId = str

# Withheld: a member's id within the case record. The open side carries ReleaseSampleId instead.
type SampleId = str

# Open: a member's id in one case instance of one release. Reveals nothing about the case, and differs between two
# instances of the same case.
type ReleaseSampleId = str

# Open: the id of one case instance in one release, which is also the id of the item a system under test receives.
type CaseInstanceId = str

# Open: the name of a background's catalogue entry.
type BackgroundId = str
