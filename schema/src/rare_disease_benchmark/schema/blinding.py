"""The one place where withheld records become open ones.

Nothing else copies a field of a case to the open side, so this module is all that has to be reviewed for leaks
through the schema.
"""

from __future__ import annotations

from rare_disease_benchmark.schema import item, record, release


def open_view(case: record.Case, instance: release.CaseInstance, release_version: str) -> item.Item:
    """Build what a system under test receives for one case instance.

    The case's open section is copied with every sample id replaced by the instance's release sample id, and the
    cutoff is the one value taken from the answer. Nothing about the build (the background, the pipeline version)
    crosses.

    Raises:
        ValueError: If the instance is not an instance of this case.
    """
    if instance.case != case.id:
        raise ValueError(f'case instance {instance.id!r} is an instance of {instance.case!r}, not of {case.id!r}')
    rekey = instance.release_sample
    family = case.open.family
    return item.Item(
        manifest=item.Manifest(
            id=instance.id,
            release=release_version,
            cutoff=case.answer.cutoff,
        ),
        input=record.CaseOpen(
            family=record.Family(
                proband=rekey(family.proband),
                members=tuple(
                    record.Individual(
                        id=rekey(m.id),
                        father=None if m.father is None else rekey(m.father),
                        mother=None if m.mother is None else rekey(m.mother),
                        sex=m.sex,
                        affected=m.affected,
                    )
                    for m in family.members
                ),
            ),
            clinical_presentation=tuple(
                p.model_copy(update={'individual': rekey(p.individual)}) for p in case.open.clinical_presentation
            ),
        ),
    )


def open_items(withheld: release.WithheldRelease) -> tuple[item.Item, ...]:
    """The open view of every case instance in a release, in the release's order."""
    return tuple(open_view(withheld.case(i.case), i, withheld.release) for i in withheld.instances)
