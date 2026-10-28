"""The interfaces of `records`, implemented against Metamist and cloud storage.

Reads go through Metamist's GraphQL API, writes through its REST API, both with the client's own configuration
(`SM_URL` or `SM_ENVIRONMENT` choose the deployment; the user's Google credentials authenticate).
"""

from __future__ import annotations

import json
import pathlib
import posixpath
import sys
import tempfile
from collections.abc import Collection, Mapping
from typing import Any, TextIO

import metamist.apis
import metamist.graphql
import metamist.models

from rare_disease_benchmark.metamist import records

# Metamist keys a record's external ids by the organisation that issued them; this is the key of the primary one.
PRIMARY_EXTERNAL_ID = ''

_SEX_CODES: dict[records.Sex, int] = {'male': 1, 'female': 2}

_PARTICIPANTS = """
query Participants($project: String!, $externalIds: [String!]!) {
  project(name: $project) {
    participants(externalId: {in_: $externalIds}) {
      id
      externalId
      reportedSex
      samples {
        id
        externalId
        type
        sequencingGroups {
          id
          type
          technology
          platform
          assays { id type meta }
        }
      }
    }
  }
}
"""

_FAMILIES_OF = """
query FamiliesOf($project: String!, $externalIds: [String!]!) {
  project(name: $project) {
    participants(externalId: {in_: $externalIds}) { families { id } }
  }
}
"""

_FAMILY = """
query Family($project: String!, $family: String!) {
  project(name: $project) {
    families(externalId: {eq: $family}) { id externalId }
  }
}
"""

_PEDIGREE = """
query Pedigree($project: String!, $familyIds: [Int!]!) {
  project(name: $project) { pedigree(internalFamilyIds: $familyIds) }
}
"""

QUERIES = (_PARTICIPANTS, _FAMILIES_OF, _FAMILY, _PEDIGREE)


class MetamistRegistry:
    def participants(self, project: str, external_ids: Collection[str]) -> tuple[records.Participant, ...]:
        data = _query(_PARTICIPANTS, project=project, externalIds=sorted(external_ids))
        # The filter matches any of a participant's external ids; the commands look them up by the primary one.
        return tuple(participant_record(p) for p in data['project']['participants'] if p['externalId'] in external_ids)

    def pedigree(self, project: str, external_ids: Collection[str]) -> tuple[records.PedigreeRow, ...]:
        data = _query(_FAMILIES_OF, project=project, externalIds=sorted(external_ids))
        family_ids = {f['id'] for p in data['project']['participants'] for f in p['families']}
        return self._pedigree(project, family_ids)

    def family_pedigree(self, project: str, family: str) -> tuple[records.PedigreeRow, ...]:
        families = _query(_FAMILY, project=project, family=family)['project']['families']
        ids = {f['id'] for f in families if f['externalId'] == family}
        if len(ids) > 1:
            raise records.RecordError(f'{project}: {len(ids)} families have the external id {family}')
        return self._pedigree(project, ids)

    def _pedigree(self, project: str, family_ids: Collection[int]) -> tuple[records.PedigreeRow, ...]:
        # Metamist returns every family of the project when given no ids.
        if not family_ids:
            return ()
        data = _query(_PEDIGREE, project=project, familyIds=sorted(family_ids))
        return tuple(pedigree_record(row) for row in data['project']['pedigree'])


class MetamistWriter:
    def create_participants(self, project: str, participants: tuple[records.NewParticipant, ...]) -> None:
        metamist.apis.ParticipantApi().upsert_participants(project, participant_upserts(participants))

    def import_pedigree(self, project: str, family: str, members: tuple[records.Member, ...]) -> None:
        with tempfile.TemporaryDirectory() as directory:
            # Metamist picks the delimiter by the file's extension.
            path = pathlib.Path(directory) / 'pedigree.ped'
            path.write_text(ped_text(family, members), encoding='utf-8')
            with path.open(encoding='utf-8') as ped:
                metamist.apis.FamilyApi().import_pedigree(
                    project, ped, has_header=False, create_missing_participants=False, perform_sex_check=True
                )


class DryRunWriter:
    """Prints the calls `MetamistWriter` would make, with what they would send."""

    def __init__(self, out: TextIO = sys.stdout) -> None:
        self._out = out

    def create_participants(self, project: str, participants: tuple[records.NewParticipant, ...]) -> None:
        payload = [upsert.to_dict() for upsert in participant_upserts(participants)]
        print(f'would call ParticipantApi.upsert_participants(project={project!r}) with', file=self._out)
        print(json.dumps(payload, indent=2), file=self._out)

    def import_pedigree(self, project: str, family: str, members: tuple[records.Member, ...]) -> None:
        print(
            f'would call FamilyApi.import_pedigree(project={project!r}, has_header=False, '
            'create_missing_participants=False, perform_sex_check=True) with this file',
            file=self._out,
        )
        print(ped_text(family, members), end='', file=self._out)


def participant_upserts(participants: tuple[records.NewParticipant, ...]) -> list[Any]:
    """A `ParticipantUpsert` per participant.

    The sample, sequencing group and assay are nested in it, so Metamist creates them in the same transaction.
    """
    return [
        metamist.models.ParticipantUpsert(
            external_ids={PRIMARY_EXTERNAL_ID: p.external_id},
            reported_sex=_SEX_CODES[p.sex],
            samples=[
                metamist.models.SampleUpsert(
                    external_ids={PRIMARY_EXTERNAL_ID: p.external_id},
                    type=p.sample_type,
                    sequencing_groups=[
                        metamist.models.SequencingGroupUpsert(
                            type=p.sequencing_type,
                            technology=p.technology,
                            platform=p.platform,
                            meta={},
                            assays=[metamist.models.AssayUpsert(type='sequencing', meta=_assay_meta(p))],
                        )
                    ],
                )
            ],
        )
        for p in participants
    ]


def _assay_meta(p: records.NewParticipant) -> dict[str, Any]:
    # The layout Metamist's own parsers give a CRAM.
    return {
        'reads_type': 'cram',
        'reads': _file(p.cram) | {'secondaryFiles': [_file(p.crai)]},
        'sequencing_type': p.sequencing_type,
        'sequencing_technology': p.technology,
        'sequencing_platform': p.platform,
    }


def _file(location: str) -> dict[str, Any]:
    return {'location': location, 'basename': posixpath.basename(location), 'class': 'File'}


def ped_text(family: str, members: tuple[records.Member, ...]) -> str:
    """Tab-separated PED rows: family, individual, father, mother, sex, and affected status, recorded as unknown (0)."""
    return ''.join(f'{family}\t{m.id}\t{m.father or 0}\t{m.mother or 0}\t{_SEX_CODES[m.sex]}\t0\n' for m in members)


def participant_record(data: Mapping[str, Any]) -> records.Participant:
    """A participant from the GraphQL query above."""
    return records.Participant(
        id=data['id'],
        external_id=data['externalId'],
        sex=_sex(data['reportedSex'], data['externalId']),
        samples=tuple(
            records.Sample(
                id=s['id'],
                external_id=s['externalId'],
                type=s['type'],
                sequencing_groups=tuple(
                    records.SequencingGroup(
                        id=g['id'],
                        type=g['type'],
                        technology=g['technology'],
                        platform=g['platform'],
                        assays=tuple(
                            records.Assay(id=a['id'], type=a['type'], reads=_reads(a['meta'], a['id']))
                            for a in g['assays']
                        ),
                    )
                    for g in s['sequencingGroups']
                ),
            )
            for s in data['samples']
        ),
    )


def pedigree_record(row: Mapping[str, Any]) -> records.PedigreeRow:
    """A row of Metamist's pedigree, with participants and families named by their external ids."""
    return records.PedigreeRow(
        family=row['family_id'],
        individual=row['individual_id'],
        father=row['paternal_id'],
        mother=row['maternal_id'],
    )


def _sex(reported: int | None, participant: str) -> records.Sex | None:
    # PED codes: 0 is unknown.
    if reported is None or reported == 0:
        return None
    if reported == 1:
        return 'male'
    if reported == 2:
        return 'female'
    raise records.RecordError(f'participant {participant} has the reported sex {reported}, expected 0, 1 or 2')


def _reads(meta: Mapping[str, Any], assay: int) -> tuple[records.File, ...]:
    reads = meta.get('reads')
    if reads is None:
        return ()
    # One file (a CRAM, BAM or single-ended FASTQ) is a mapping; a FASTQ pair is a list.
    return tuple(_read_file(f, assay) for f in (reads if isinstance(reads, list) else [reads]))


def _read_file(data: object, assay: int) -> records.File:
    if not isinstance(data, Mapping) or not isinstance(data.get('location'), str):
        raise records.RecordError(f'assay {assay} reads {data!r}, which is not a file with a location')
    return records.File(
        location=data['location'],
        secondary_files=tuple(_read_file(f, assay) for f in data.get('secondaryFiles') or ()),
    )


def _query(query: str, **variables: object) -> dict[str, Any]:
    return metamist.graphql.query(metamist.graphql.gql(query), variables)
