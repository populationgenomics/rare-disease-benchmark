"""What a harness runs for one case instance.

The harness and the grader read the withheld side; the system under test reads only the open section an item carries,
together with the sequencing files. This assumes that every party running a harness also holds the release's withheld
side. A harness without it would need the instance id and the cutoff from somewhere other than the withheld side.
"""

from __future__ import annotations

import datetime as dt

from rare_disease_benchmark.schema import blinding, ids, record, release, visibility


class Item(visibility.WithheldModel, frozen=True):
    """One case instance as a harness runs it.

    Only `input`, with the sequencing files, reaches the system under test.
    """

    id: ids.CaseInstanceId  # the harness keys the submission and the trace by it
    cutoff: dt.date | None  # the harness rolls clinical-assertion resources and literature back to before it
    input: record.CaseOpen  # the case's open section, keyed by release sample ids


def items(withheld: release.WithheldRelease) -> tuple[Item, ...]:
    """Every case instance of a release as a harness runs it, in the release's order."""
    return tuple(
        Item(id=i.id, cutoff=withheld.case(i.case).answer.cutoff, input=blinding.open_view(withheld.case(i.case), i))
        for i in withheld.instances
    )
