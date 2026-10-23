"""The one place where case data becomes open.

Nothing else copies a field of a case to the open side, so this module is all that has to be reviewed for leaks
through the schema.
"""

from __future__ import annotations

from rare_disease_benchmark.schema import record, release


def open_view(case: record.Case, instance: release.CaseInstance) -> record.CaseOpen:
    """Build what a system under test receives for one case instance, apart from the sequencing files.

    This is the case's open section with every sample id replaced by the instance's release sample id. Nothing from
    the answer, the bookkeeping or the build crosses, and neither do the instance id or the cutoff, which only the
    harness reads.

    Raises:
        ValueError: If the instance is not an instance of this case.
    """
    if instance.case != case.id:
        raise ValueError(f'case instance {instance.id!r} is an instance of {instance.case!r}, not of {case.id!r}')
    rekey = instance.release_sample
    family = case.open.family
    return record.CaseOpen(
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
    )
