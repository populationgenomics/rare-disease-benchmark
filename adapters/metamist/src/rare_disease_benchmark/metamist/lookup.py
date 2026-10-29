"""Picking the one record a command needs out of what the registry holds, and refusing when there is not exactly one."""

from __future__ import annotations

from collections.abc import Iterable

from rare_disease_benchmark.metamist import records


def participant(
    participants: Iterable[records.Participant], external_id: str, project: str
) -> records.Participant | None:
    """The participant with this primary external id; None if there is none."""
    matches = [p for p in participants if p.external_id == external_id]
    if len(matches) > 1:
        raise records.RecordError(f'{project}: {len(matches)} participants have the external id {external_id}')
    return matches[0] if matches else None


def genome(participant: records.Participant, project: str) -> tuple[records.Sample, records.SequencingGroup]:
    """The participant's one active genome sequencing group, and the sample it belongs to.

    Samples without a genome sequencing group do not count, so a participant may have other samples, but two genomes
    are ambiguous whether they sit in one sample or in two.
    """
    found = [
        (sample, group)
        for sample in participant.samples
        for group in sample.sequencing_groups
        if group.type == records.GENOME
    ]
    if len(found) != 1:
        listed = ', '.join(f'{group.id} in sample {sample.id}' for sample, group in found)
        raise records.RecordError(
            f'{project}: participant {participant.external_id} has {len(found)} active genome sequencing groups, '
            f'expected one{f" ({listed})" if listed else ""}'
        )
    return found[0]


def cram(group: records.SequencingGroup, project: str) -> tuple[str, str]:
    """The CRAM and CRAI that the sequencing group's one assay reads."""
    where = f'{project}: sequencing group {group.id}'
    if len(group.assays) != 1:
        raise records.RecordError(f'{where} has {len(group.assays)} assays, expected one')
    reads = group.assays[0].reads
    if len(reads) != 1:
        raise records.RecordError(f'{where}: its assay reads {len(reads)} files, expected one CRAM')
    if not reads[0].location.endswith('.cram'):
        raise records.RecordError(f'{where}: its assay reads {reads[0].location}, which is not a CRAM')
    indexes = [f.location for f in reads[0].secondary_files if f.location.endswith('.crai')]
    if len(indexes) != 1:
        raise records.RecordError(f'{where}: its CRAM has {len(indexes)} CRAI files, expected one')
    return reads[0].location, indexes[0]
