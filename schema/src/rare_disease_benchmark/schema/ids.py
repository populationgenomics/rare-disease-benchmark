"""Identifiers, and which side of a release each one lives on."""

from __future__ import annotations

# Withheld: the case's own id, never written to the open side.
type CaseId = str

# Withheld: a label for one family member within one case record, such as 'proband'. It names no sequenced sample;
# the open side carries a ReleaseSampleId in its place.
type MemberId = str

# Open: a member's id in one case instance of one release. Reveals nothing about the case, and differs between two
# instances of the same case.
type ReleaseSampleId = str

# Withheld: the id of one case instance in one release. The harness keys a submission and its trace by it; the system
# under test never sees it.
type CaseInstanceId = str

# Withheld: the name of a background's catalogue entry. Only the build and the checks on a release use it; a system
# under test learns nothing about how an instance was built.
type BackgroundId = str
