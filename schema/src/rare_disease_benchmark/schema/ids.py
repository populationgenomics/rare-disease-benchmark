"""Identifiers, and which side of a release each one lives on."""

from __future__ import annotations

# Withheld: the case's own id, never written to the open side.
type CaseId = str

# Open: a relational label for one family member within one case, such as 'proband', 'father' or 'sister_2'. It is
# also the sample's name in the released files and the PED, so it must reveal nothing about the case.
type MemberId = str

# Withheld: the id of one case instance in one release. The harness keys a submission and its trace by it; the system
# under test never sees it.
type CaseInstanceId = str

# Withheld: a sequenced sample as its source names it, such as NA19240 in 1000 Genomes. The build resolves it to that
# sample's prepared data. Withheld because a public sample's published genome could be subtracted from the files.
type SampleId = str
