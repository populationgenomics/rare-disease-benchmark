from __future__ import annotations

import io
import json
from typing import Any

import fakes
import metamist.graphql
import pytest

from rare_disease_benchmark.metamist import client, lookup, pedigree, records

NEW = records.NewParticipant(
    external_id=fakes.CHILD,
    sex='female',
    sample_type='blood',
    sequencing_type=records.GENOME,
    technology='short-read',
    platform='illumina',
    cram=fakes.cram_url('SGX3'),
    crai=f'{fakes.cram_url("SGX3")}.crai',
)
MEMBERS = (
    records.Member(id=fakes.MOTHER, sex='female', father=None, mother=None),
    records.Member(id=fakes.FATHER, sex='male', father=None, mother=None),
    records.Member(id=fakes.CHILD, sex='female', father=fakes.FATHER, mother=fakes.MOTHER),
)


def as_queried(upsert: dict[str, Any]) -> dict[str, Any]:
    """The participant as the GraphQL query would return it once Metamist has created it from the upsert."""
    return {
        'id': 1,
        'externalId': upsert['external_ids'][client.PRIMARY_EXTERNAL_ID],
        'reportedSex': upsert['reported_sex'],
        'samples': [
            {
                'id': 'SMX1',
                'externalId': sample['external_ids'][client.PRIMARY_EXTERNAL_ID],
                'type': sample['type'],
                'sequencingGroups': [
                    {
                        'id': 'SGT1',
                        'type': group['type'],
                        'technology': group['technology'],
                        'platform': group['platform'],
                        'assays': [{'id': 1, 'type': a['type'], 'meta': a['meta']} for a in group['assays']],
                    }
                    for group in sample['sequencing_groups']
                ],
            }
            for sample in upsert['samples']
        ],
    }


def test_what_ingest_writes_reads_back_as_the_same_participant_and_cram() -> None:
    [upsert] = client.participant_upserts((NEW,))
    participant = client.participant_record(as_queried(upsert.to_dict()))
    assert (participant.external_id, participant.sex) == (NEW.external_id, NEW.sex)
    sample, group = lookup.genome(participant, 'p')
    assert (sample.type, group.technology, group.platform) == (NEW.sample_type, NEW.technology, NEW.platform)
    assert lookup.cram(group, 'p') == (NEW.cram, NEW.crai)


def test_the_pedigree_import_reads_back_as_the_same_members() -> None:
    text = client.ped_text(fakes.FAMILY, MEMBERS)
    assert {line.split('\t')[0] for line in text.splitlines()} == {fakes.FAMILY}
    assert pedigree.read_ped(text, fakes.TRIO, 'import') == {m.id: m for m in MEMBERS}


def _participant(reported_sex: object = 2, reads: object = None) -> dict[str, Any]:
    meta = {} if reads is None else {'reads': reads}
    return {
        'id': 1,
        'externalId': 'x',
        'reportedSex': reported_sex,
        'samples': [
            {
                'id': 'S',
                'externalId': 'x',
                'type': 'blood',
                'sequencingGroups': [
                    {
                        'id': 'G',
                        'type': 'genome',
                        'technology': 'short-read',
                        'platform': 'illumina',
                        'assays': [{'id': 7, 'type': 'sequencing', 'meta': meta}],
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(('code', 'sex'), [(None, None), (0, None), (1, 'male'), (2, 'female')])
def test_reported_sex_is_read_as_ped_codes(code: int | None, sex: records.Sex | None) -> None:
    assert client.participant_record(_participant(reported_sex=code)).sex == sex


def test_an_unknown_reported_sex_is_refused() -> None:
    with pytest.raises(records.RecordError, match='reported sex 3'):
        client.participant_record(_participant(reported_sex=3))


def test_a_fastq_pair_is_two_files() -> None:
    pair = [{'location': 'gs://b/r1.fq.gz'}, {'location': 'gs://b/r2.fq.gz'}]
    participant = client.participant_record(_participant(reads=pair))
    reads = participant.samples[0].sequencing_groups[0].assays[0].reads
    assert [f.location for f in reads] == ['gs://b/r1.fq.gz', 'gs://b/r2.fq.gz']


@pytest.mark.parametrize('reads', ['gs://b/c.cram', {'basename': 'c.cram'}, [{'location': 1}]])
def test_reads_without_a_location_are_refused(reads: object) -> None:
    with pytest.raises(records.RecordError, match='assay 7 reads'):
        client.participant_record(_participant(reads=reads))


def test_pedigree_rows_name_participants_by_external_id() -> None:
    row = {'family_id': 'f', 'individual_id': 'c', 'paternal_id': 'a', 'maternal_id': None, 'sex': 2, 'affected': 0}
    assert client.pedigree_record(row) == records.PedigreeRow(family='f', individual='c', father='a', mother=None)


@pytest.mark.parametrize('query', client.QUERIES)
def test_the_queries_fit_the_clients_schema(query: str) -> None:
    metamist.graphql.validate(metamist.graphql.gql(query), use_local_schema=True)


def test_the_dry_run_prints_both_calls_with_what_they_would_send() -> None:
    out = io.StringIO()
    writer = client.DryRunWriter(out)
    writer.create_participants(fakes.TARGET, (NEW,))
    writer.import_pedigree(fakes.TARGET, fakes.FAMILY, MEMBERS)
    text = out.getvalue()
    upsert_call, rest = text.split('\n', 1)
    assert upsert_call == f"would call ParticipantApi.upsert_participants(project='{fakes.TARGET}') with"
    payload_text, pedigree_call = rest.split('would call FamilyApi.import_pedigree', 1)
    assert json.loads(payload_text) == [u.to_dict() for u in client.participant_upserts((NEW,))]
    assert pedigree_call.endswith(client.ped_text(fakes.FAMILY, MEMBERS))
