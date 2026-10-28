"""Registers a build run's outputs in Metamist, as analyses of the run's sequencing groups.

    python -m rare_disease_benchmark.metamist.register <directory> --project <p> --pipeline-version <v> [--dry-run]

The manifest directory is the run's `<output_dir>/backgrounds/<background>/<version>/`, local or `gs://`. The sample
sheet named each sample by its sequencing group id, so the manifest's sample ids must be active sequencing groups of
the project. For each sample the command creates a `cram` and a `gvcf` analysis of its sequencing group, and for the
family a `joint-calling` analysis of all of them. Each is created as `completed`, after checking that every file the
manifest names exists, with the primary file and its companions in `outputs` (`{'basename': <path>,
'secondary_files': {<role>: {'basename': <path>}}}`) and these keys in `meta`:

- `sequencing_type` (the sequencing group's type), `stage` (the build process that wrote the file), `dataset` and,
  for a sample, `sequencing_group`, as CPG's pipelines record them; and `size`, the primary file's size in bytes;
- `background`, `pipeline_version` and `published_dir` (the run's directory), which trace the analysis to its run.

Metrics and logs stay unregistered: no consumer looks them up as analyses, and `published_dir` leads to them.

Rerunning is safe. An analysis is found by its type and its primary file's path, so a file already registered is not
registered again; one registered with other sequencing groups, another status or another run is a conflict, and fails.

Metamist never deactivates an analysis by itself: consumers choose among the active, completed ones, some the latest
per sequencing group and some all of them (seqr's CRAM sync lists every one). The analyses this command registers for
a target therefore form a history in which only the newest stays active: having created a run's analysis, it
deactivates the active ones it registered earlier for the same type, background and sequencing group. Registering an
older run again creates nothing and leaves the newer one active; a run whose deactivations failed midway completes
them when rerun; a run's analysis that is inactive (superseded, or retired by hand) is left as it is, and so is its
history. Analyses of other backgrounds, and analyses registered by anything else, are left alone.

Writes go through `Writer`; `--dry-run` swaps in one that prints each request instead of sending it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol, cast

import google.cloud.storage
import pydantic

import metamist.apis
import metamist.graphql
import metamist.models
from rare_disease_benchmark.metamist import manifest

CRAM = 'cram'
GVCF = 'gvcf'
JOINT_CALLING = 'joint-calling'
TYPES = (CRAM, GVCF, JOINT_CALLING)

# The build processes that write these files (build/main.nf), recorded as `stage` like a CPG pipeline's stage name.
_SAMPLE_STAGE = 'DRAGEN_GERMLINE'
_FAMILY_STAGE = 'DRAGEN_PEDIGREE'

_COMPLETED = 'COMPLETED'  # as GraphQL spells the status


class NewAnalysis(pydantic.BaseModel, frozen=True, extra='forbid'):
    """An analysis to create: a primary file and its companions, for some sequencing groups."""

    type: str
    sequencing_groups: tuple[str, ...]
    output: str
    secondary_files: dict[str, str]  # role -> path
    meta: dict[str, str | int]

    def outputs(self) -> dict[str, Any]:
        """The analysis's `outputs` field, as Metamist takes it."""
        return {
            'basename': self.output,
            'secondary_files': {role: {'basename': path} for role, path in self.secondary_files.items()},
        }


class Analysis(pydantic.BaseModel, frozen=True, extra='forbid'):
    """An analysis already in Metamist, as far as registering needs it."""

    id: int
    type: str
    status: str
    active: bool
    output: str | None  # the primary file's path
    sequencing_groups: tuple[str, ...]
    meta: dict[str, Any]


class Project(pydantic.BaseModel, frozen=True, extra='forbid'):
    """What registering reads from Metamist about a project."""

    name: str
    dataset: str
    analysis_types: tuple[str, ...]  # every type the server knows
    sequencing_groups: dict[str, str]  # active sequencing group id -> sequencing type
    analyses: tuple[Analysis, ...]  # of the types in TYPES, active or not


class Plan(pydantic.BaseModel, frozen=True, extra='forbid'):
    create: tuple[NewAnalysis, ...]
    deactivate: tuple[Analysis, ...]
    registered: tuple[Analysis, ...]  # already in Metamist, so not created again


class Storage(Protocol):
    def read_text(self, location: str) -> str:
        """The text of a file; raises `FileNotFoundError` if there is none."""
        ...

    def size(self, location: str) -> int:
        """A file's size in bytes; raises `FileNotFoundError` if there is none."""
        ...


class Reader(Protocol):
    def read(self, project: str) -> Project: ...


class Writer(Protocol):
    def create_analysis(self, project: str, analysis: NewAnalysis) -> None: ...

    def deactivate_analysis(self, analysis: Analysis) -> None: ...


def register(
    directory: str,
    project: str,
    pipeline_version: str,
    *,
    storage: Storage,
    reader: Reader,
    writer: Writer,
) -> Plan:
    """Registers the run whose manifest is in `directory`, and returns what it did."""
    directory = directory.rstrip('/')
    run = manifest.parse(storage.read_text(f'{directory}/samples.json'), storage.read_text(f'{directory}/family.json'))
    if run.version != pipeline_version:
        raise ValueError(f'the manifest is of pipeline version {run.version}, not {pipeline_version}')
    sizes = _sizes(run, storage)
    state = reader.read(project)
    plan = make_plan(analyses(run, state, sizes), state.analyses)

    for analysis in plan.registered:
        state = 'active' if analysis.active else 'inactive'
        print(f'already registered: analysis {analysis.id} ({state}), {analysis.type} {analysis.output}')
    for new in plan.create:
        writer.create_analysis(project, new)
    for old in plan.deactivate:
        writer.deactivate_analysis(old)
    return plan


def analyses(run: manifest.Manifest, state: Project, sizes: Mapping[str, int]) -> tuple[NewAnalysis, ...]:
    """The analyses that register `run` in the project `state` describes."""
    if missing := sorted(set(TYPES) - set(state.analysis_types)):
        raise ValueError(f'Metamist has no analysis type {missing}')
    ids = [s.id for s in run.samples]
    if unknown := [i for i in ids if i not in state.sequencing_groups]:
        raise ValueError(f'{unknown} are not active sequencing groups of project {state.name}')
    family_types = sorted({state.sequencing_groups[i] for i in ids})
    if len(family_types) != 1:
        raise ValueError(f'the family mixes sequencing types {family_types}')

    def meta(stage: str, sequencing_type: str, output: str) -> dict[str, str | int]:
        return {
            'sequencing_type': sequencing_type,
            'stage': stage,
            'dataset': state.dataset,
            'background': run.background,
            'pipeline_version': run.version,
            'published_dir': f'{run.directory}/',
            'size': sizes[output],
        }

    result: list[NewAnalysis] = []
    for sample in run.samples:
        sample_type = state.sequencing_groups[sample.id]
        for type_, output, index in ((CRAM, sample.cram, sample.cram_index), (GVCF, sample.gvcf, sample.gvcf_index)):
            result.append(
                NewAnalysis(
                    type=type_,
                    sequencing_groups=(sample.id,),
                    output=output,
                    secondary_files={'index': index},
                    meta=meta(_SAMPLE_STAGE, sample_type, output) | {'sequencing_group': sample.id},
                )
            )
    family = run.family
    result.append(
        NewAnalysis(
            type=JOINT_CALLING,
            sequencing_groups=tuple(ids),
            output=family.vcf,
            secondary_files={'index': family.vcf_index, 'pedigree': family.pedigree},
            meta=meta(_FAMILY_STAGE, family_types[0], family.vcf),
        )
    )
    return tuple(result)


def make_plan(wanted: Iterable[NewAnalysis], existing: Sequence[Analysis]) -> Plan:
    """What to create and what to deactivate so that `wanted` is registered and the newest of its history."""
    create: list[NewAnalysis] = []
    deactivate: list[Analysis] = []
    registered: list[Analysis] = []
    for new in wanted:
        same_file = [a for a in existing if a.type == new.type and a.output == new.output]
        if len(same_file) > 1:
            raise ValueError(f'{new.output} is registered as {new.type} more than once: {[a.id for a in same_file]}')
        if not same_file:
            create.append(new)
            superseded = existing
        else:
            current = same_file[0]
            _check_matches(current, new)
            registered.append(current)
            # Inactive, it was superseded by a newer run or retired by hand; either way its history is settled.
            superseded = [a for a in existing if a.id < current.id] if current.active else []
        deactivate.extend(a for a in superseded if a.active and a.output != new.output and _history(a) == _history(new))
    return Plan(create=tuple(create), deactivate=tuple(deactivate), registered=tuple(registered))


def _history(analysis: Analysis | NewAnalysis) -> tuple[str, Any, Any]:
    """The analyses that supersede one another: same type, same background, same sequencing group (or none)."""
    return analysis.type, analysis.meta.get('background'), analysis.meta.get('sequencing_group')


def _check_matches(current: Analysis, new: NewAnalysis) -> None:
    differences = [
        name
        for name, theirs, ours in (
            ('sequencing groups', sorted(current.sequencing_groups), sorted(new.sequencing_groups)),
            ('status', current.status, _COMPLETED),
            *((key, current.meta.get(key), new.meta[key]) for key in ('background', 'pipeline_version')),
        )
        if theirs != ours
    ]
    if differences:
        raise ValueError(
            f'{new.output} is registered as analysis {current.id}, which differs from this run in {differences}'
        )


def _sizes(run: manifest.Manifest, storage: Storage) -> dict[str, int]:
    """The size of every file the manifest names; raises if any is not on GCS or does not exist."""
    if local := [p for p in run.paths() if not p.startswith('gs://')]:
        raise ValueError(f'Metamist records files on GCS, and the manifest names others: {local}')
    sizes: dict[str, int] = {}
    missing: list[str] = []
    for path in run.paths():
        try:
            sizes[path] = storage.size(path)
        except FileNotFoundError:
            missing.append(path)
    if missing:
        raise FileNotFoundError(f'the manifest names files that do not exist: {missing}')
    return sizes


class CloudStorage:
    """Local files, and objects on GCS under the user's Google credentials."""

    def __init__(self) -> None:
        self._client: google.cloud.storage.Client | None = None

    def read_text(self, location: str) -> str:
        if location.startswith('gs://'):
            return self._blob(location).download_as_text()
        return pathlib.Path(location).read_text('utf-8')

    def size(self, location: str) -> int:
        if location.startswith('gs://'):
            size = self._blob(location).size
            if size is None:
                raise ValueError(f'GCS reports no size for {location}')
            return size
        return pathlib.Path(location).stat().st_size

    def _blob(self, location: str) -> google.cloud.storage.Blob:
        if self._client is None:
            self._client = google.cloud.storage.Client()
        bucket, _, name = location.removeprefix('gs://').partition('/')
        blob = self._client.bucket(bucket).get_blob(name)
        if blob is None:
            raise FileNotFoundError(location)
        return blob


_PROJECT_QUERY = """
query RegisterProject($project: String!, $types: [String!]!) {
  enum {
    analysisType
  }
  project(name: $project) {
    dataset
    sequencingGroups {
      id
      type
    }
    analyses(type: {in_: $types}, active: {in_: [true, false]}) {
      id
      type
      status
      active
      output
      outputs
      meta
      sequencingGroups {
        id
      }
    }
  }
}
"""


class GraphQLReader:
    """Reads a project from Metamist's GraphQL API; read-only."""

    def read(self, project: str) -> Project:
        response = metamist.graphql.query(
            metamist.graphql.gql(_PROJECT_QUERY), variables={'project': project, 'types': list(TYPES)}
        )
        return project_from_response(project, response)


def project_from_response(name: str, response: Mapping[str, Any]) -> Project:
    data = response['project']
    return Project(
        name=name,
        dataset=data['dataset'],
        analysis_types=tuple(response['enum']['analysisType']),
        sequencing_groups={sg['id']: sg['type'] for sg in data['sequencingGroups']},
        analyses=tuple(
            Analysis(
                id=a['id'],
                type=a['type'],
                status=a['status'],
                active=a['active'],
                output=_primary_path(a),
                sequencing_groups=tuple(sg['id'] for sg in a['sequencingGroups']),
                meta=a['meta'] or {},
            )
            for a in data['analyses']
        ),
    )


def _primary_path(analysis: Mapping[str, Any]) -> str | None:
    # Metamist reads an analysis registered with `outputs` back with an empty `output` and the primary file's full path
    # in `outputs.path`; one registered with the older `output` string has both.
    outputs = analysis['outputs']
    if isinstance(outputs, dict) and isinstance(path := outputs.get('path'), str):
        return path
    return analysis['output'] or None


class ApiWriter:
    """Creates and deactivates analyses through Metamist's REST API."""

    def __init__(self) -> None:
        self._api = metamist.apis.AnalysisApi()

    def create_analysis(self, project: str, analysis: NewAnalysis) -> None:
        analysis_id = self._api.create_analysis(project, _request(analysis))
        print(f'created analysis {analysis_id}: {analysis.type} {analysis.output}')

    def deactivate_analysis(self, analysis: Analysis) -> None:
        self._api.update_analysis(analysis.id, metamist.models.AnalysisUpdateModel(active=False))
        print(f'deactivated analysis {analysis.id}: {analysis.type} {analysis.output}')


class DryRunWriter:
    """Prints the requests `ApiWriter` would send, and sends nothing."""

    def create_analysis(self, project: str, analysis: NewAnalysis) -> None:
        print(f'PUT /api/v1/analysis/{project}/ {json.dumps(_request(analysis).to_dict(), sort_keys=True)}')

    def deactivate_analysis(self, analysis: Analysis) -> None:
        print(f'PATCH /api/v1/analysis/{analysis.id}/ {json.dumps({"active": False})}  # {analysis.output}')


def _request(analysis: NewAnalysis) -> metamist.models.Analysis:
    # The generated client's constructor goes through a `__new__` that pyright reads as returning a union.
    request = metamist.models.Analysis(
        type=analysis.type,
        status=metamist.models.AnalysisStatus('completed'),
        outputs=analysis.outputs(),
        sequencing_group_ids=list(analysis.sequencing_groups),
        meta=dict(analysis.meta),
    )
    return cast(metamist.models.Analysis, request)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog='python -m rare_disease_benchmark.metamist.register',
        description="Registers a build run's outputs in Metamist as analyses.",
    )
    parser.add_argument('directory', help="the run's manifest directory, local or gs://")
    parser.add_argument('--project', required=True, help='the Metamist project holding the sequencing groups')
    parser.add_argument('--pipeline-version', required=True, help='the pipeline version that wrote the run')
    parser.add_argument('--dry-run', action='store_true', help='print the requests instead of sending them')
    args = parser.parse_args(argv)
    register(
        args.directory,
        args.project,
        args.pipeline_version,
        storage=CloudStorage(),
        reader=GraphQLReader(),
        writer=DryRunWriter() if args.dry_run else ApiWriter(),
    )


if __name__ == '__main__':
    main()
