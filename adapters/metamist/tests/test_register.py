from __future__ import annotations

import collections
import json
import pathlib
from collections.abc import Callable

import metamist.graphql
import pytest

from rare_disease_benchmark.metamist import manifest, register

_FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'manifest'
_VERSION = '0.1.0'
_PROJECT = 'benchmark-project'
_DATASET = 'benchmark-dataset'
_SEQUENCING_GROUPS = {'SG0001': 'genome', 'SG0002': 'genome', 'SG0003': 'genome', 'SG0004': 'genome'}


def run_files(version: str = _VERSION, rewrite: Callable[[str], str] = lambda text: text) -> dict[str, str]:
    """The invented trio's manifest as a run of `version` would publish it: file name -> contents."""
    return {
        name: rewrite((_FIXTURE / name).read_text('utf-8').replace(f'/{_VERSION}/', f'/{version}/'))
        for name in ('samples.json', 'family.json')
    }


class FakeStorage:
    """A bucket holding a run's manifest and every file it names; each file's size is the length of its path."""

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.sizes: dict[str, int] = {}

    def publish(self, files: dict[str, str]) -> str:
        """Publishes a run's manifest and the files it names, and returns its directory."""
        run = manifest.parse(files['samples.json'], files['family.json'])
        for name, text in files.items():
            self.texts[f'{run.directory}/{name}'] = text
        self.sizes.update((p, len(p)) for p in run.paths())
        return run.directory

    def read_text(self, location: str) -> str:
        if location not in self.texts:
            raise FileNotFoundError(location)
        return self.texts[location]

    def size(self, location: str) -> int:
        if location not in self.sizes:
            raise FileNotFoundError(location)
        return self.sizes[location]


class FakeMetamist:
    """One project's sequencing groups and analyses, read and written in memory like Metamist does."""

    def __init__(self) -> None:
        self.analysis_types: tuple[str, ...] = ('cram', 'gvcf', 'joint-calling', 'qc')
        self.sequencing_groups = dict(_SEQUENCING_GROUPS)
        self.analyses: list[register.Analysis] = []
        self.writes = 0
        self.deactivation_fails = False

    def read(self, project: str) -> register.Project:
        assert project == _PROJECT
        return register.Project(
            name=project,
            dataset=_DATASET,
            analysis_types=self.analysis_types,
            sequencing_groups=self.sequencing_groups,
            analyses=tuple(self.analyses),
        )

    def create_analysis(self, project: str, analysis: register.NewAnalysis) -> None:
        assert project == _PROJECT
        self.writes += 1
        self.analyses.append(
            register.Analysis(
                id=len(self.analyses) + 1,
                type=analysis.type,
                status='COMPLETED',
                active=True,
                output=analysis.output,
                sequencing_groups=analysis.sequencing_groups,
                meta=analysis.meta,
            )
        )

    def deactivate_analysis(self, analysis: register.Analysis) -> None:
        if self.deactivation_fails:
            raise ConnectionError('Metamist went away')
        self.writes += 1
        self.set_active(analysis.id, active=False)

    def set_active(self, analysis_id: int, *, active: bool) -> None:
        index = next(i for i, a in enumerate(self.analyses) if a.id == analysis_id)
        self.analyses[index] = self.analyses[index].model_copy(update={'active': active})

    def add(self, **fields: object) -> None:
        """Adds an analysis registered by something else."""
        defaults = {'id': len(self.analyses) + 1, 'status': 'COMPLETED', 'active': True, 'meta': {}}
        self.analyses.append(register.Analysis.model_validate(defaults | fields))

    def active(self) -> list[register.Analysis]:
        return [a for a in self.analyses if a.active]

    def active_versions(self) -> set[str]:
        return {a.meta['pipeline_version'] for a in self.active()}


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def server() -> FakeMetamist:
    return FakeMetamist()


def register_run(
    storage: FakeStorage,
    server: FakeMetamist,
    files: dict[str, str] | None = None,
    pipeline_version: str = _VERSION,
    writer: register.Writer | None = None,
) -> register.Plan:
    directory = storage.publish(files or run_files())
    return register.register(
        directory, _PROJECT, pipeline_version, storage=storage, reader=server, writer=writer or server
    )


def run_of(files: dict[str, str]) -> manifest.Manifest:
    return manifest.parse(files['samples.json'], files['family.json'])


def test_registers_a_cram_and_a_gvcf_per_sample_and_the_family_joint_calling(
    storage: FakeStorage, server: FakeMetamist
) -> None:
    plan = register_run(storage, server)
    run = run_of(run_files())
    by_type = collections.defaultdict(list)
    for new in plan.create:
        by_type[new.type].append(new)
        assert new.meta['background'] == run.background
        assert new.meta['pipeline_version'] == run.version
        assert new.meta['published_dir'] == f'{run.directory}/'
        assert new.meta['dataset'] == _DATASET
        assert new.meta['size'] == storage.sizes[new.output]
        assert all(new.meta['sequencing_type'] == _SEQUENCING_GROUPS[sg] for sg in new.sequencing_groups)
        assert new.outputs()['basename'] == new.output

    for sample in run.samples:
        cram = [a for a in by_type['cram'] if a.sequencing_groups == (sample.id,)]
        gvcf = [a for a in by_type['gvcf'] if a.sequencing_groups == (sample.id,)]
        assert [(a.output, a.secondary_files) for a in cram] == [(sample.cram, {'index': sample.cram_index})]
        assert [(a.output, a.secondary_files) for a in gvcf] == [(sample.gvcf, {'index': sample.gvcf_index})]
        assert cram[0].meta['sequencing_group'] == gvcf[0].meta['sequencing_group'] == sample.id
    [joint] = by_type['joint-calling']
    assert set(joint.sequencing_groups) == {s.id for s in run.samples}
    assert joint.output == run.family.vcf
    assert set(joint.secondary_files.values()) == {run.family.vcf_index, run.family.pedigree}
    assert 'sequencing_group' not in joint.meta
    assert len(plan.create) == len(server.active()) == 2 * len(run.samples) + 1
    assert not plan.deactivate


def test_rerunning_creates_nothing(storage: FakeStorage, server: FakeMetamist) -> None:
    register_run(storage, server)
    writes = server.writes
    plan = register_run(storage, server)
    assert (plan.create, plan.deactivate) == ((), ())
    assert len(plan.registered) == len(server.analyses)
    assert server.writes == writes


def test_a_new_version_leaves_only_its_analyses_active(storage: FakeStorage, server: FakeMetamist) -> None:
    register_run(storage, server)
    register_run(storage, server, run_files('0.2.0'), '0.2.0')
    assert server.active_versions() == {'0.2.0'}
    assert len(server.active()) == len(server.analyses) // 2
    histories = [(a.type, a.sequencing_groups) for a in server.active()]
    assert len(histories) == len(set(histories))


def test_registering_an_older_version_again_changes_nothing(storage: FakeStorage, server: FakeMetamist) -> None:
    register_run(storage, server)
    register_run(storage, server, run_files('0.2.0'), '0.2.0')
    writes = server.writes
    register_run(storage, server)
    assert server.writes == writes
    assert server.active_versions() == {'0.2.0'}


def test_rerunning_completes_deactivations_that_failed(storage: FakeStorage, server: FakeMetamist) -> None:
    register_run(storage, server)
    server.deactivation_fails = True
    with pytest.raises(ConnectionError):
        register_run(storage, server, run_files('0.2.0'), '0.2.0')
    server.deactivation_fails = False
    assert server.active_versions() == {'0.1.0', '0.2.0'}

    register_run(storage, server)
    assert server.active_versions() == {'0.1.0', '0.2.0'}
    plan = register_run(storage, server, run_files('0.2.0'), '0.2.0')
    assert not plan.create
    assert server.active_versions() == {'0.2.0'}


def test_a_version_rolled_back_by_hand_stays_rolled_back(storage: FakeStorage, server: FakeMetamist) -> None:
    register_run(storage, server)
    register_run(storage, server, run_files('0.2.0'), '0.2.0')
    for analysis in list(server.analyses):
        server.set_active(analysis.id, active=analysis.meta['pipeline_version'] == '0.1.0')
    writes = server.writes
    register_run(storage, server, run_files('0.2.0'), '0.2.0')
    register_run(storage, server)
    assert server.writes == writes
    assert server.active_versions() == {'0.1.0'}


def test_other_backgrounds_and_other_registrations_are_left_alone(storage: FakeStorage, server: FakeMetamist) -> None:
    other_background = {'background': 'trio-b', 'sequencing_group': 'SG0001', 'pipeline_version': '0.1.0'}
    server.add(type='cram', output='gs://elsewhere/b/SG0001.cram', sequencing_groups=('SG0001',), meta=other_background)
    server.add(type='cram', output='gs://elsewhere/SG0001.cram', sequencing_groups=('SG0001',))
    server.add(type='joint-calling', output='gs://elsewhere/joint.vcf.gz', sequencing_groups=('SG0001', 'SG0004'))
    before = list(server.analyses)
    register_run(storage, server)
    register_run(storage, server, run_files('0.2.0'), '0.2.0')
    assert all(a in server.active() for a in before)


def test_dry_run_prints_the_requests_and_sends_none(
    storage: FakeStorage, server: FakeMetamist, capsys: pytest.CaptureFixture[str]
) -> None:
    register_run(storage, server)
    capsys.readouterr()
    writes = server.writes
    plan = register_run(storage, server, run_files('0.2.0'), '0.2.0', writer=register.DryRunWriter())
    assert server.writes == writes

    lines = capsys.readouterr().out.splitlines()
    puts = [
        json.loads(line.split(' ', 2)[2]) for line in lines if line.startswith(f'PUT /api/v1/analysis/{_PROJECT}/ ')
    ]
    patches = [line for line in lines if line.startswith('PATCH /api/v1/analysis/')]
    assert [(p['type'], p['outputs']['basename']) for p in puts] == [(a.type, a.output) for a in plan.create]
    assert all(p['status'] == 'completed' and p['sequencing_group_ids'] for p in puts)
    assert len(patches) == len(plan.deactivate) == len(plan.create)


def test_the_query_fits_the_client_schema() -> None:
    assert metamist.graphql.validate(metamist.graphql.gql(register._PROJECT_QUERY), use_local_schema=True)


def test_reads_the_primary_path_of_either_kind_of_registration() -> None:
    path = 'gs://bucket/x.cram'
    file = {'path': path, 'basename': 'x.cram', 'secondary_files': {}}
    response = {
        'enum': {'analysisType': ['cram']},
        'project': {
            'dataset': _DATASET,
            'sequencingGroups': [{'id': 'SG0001', 'type': 'genome'}],
            'analyses': [
                {
                    'id': i,
                    'type': 'cram',
                    'status': 'COMPLETED',
                    'active': True,
                    'output': output,
                    'outputs': file,
                    'meta': None,
                    'sequencingGroups': [{'id': 'SG0001'}],
                }
                for i, output in enumerate(('', path))
            ],
        },
    }
    project = register.project_from_response(_PROJECT, response)
    assert [a.output for a in project.analyses] == [path, path]


type Change = Callable[[FakeStorage, FakeMetamist], object]


def no_change(_storage: FakeStorage, _server: FakeMetamist) -> None:
    pass


REJECTED: dict[str, tuple[Change, dict[str, str], str, str]] = {
    'a sample that is not a sequencing group of the project': (
        lambda _s, server: server.sequencing_groups.pop('SG0003'),
        run_files(),
        _VERSION,
        'not active sequencing groups',
    ),
    'a missing file': (
        lambda storage, _m: storage.sizes.pop(next(p for p in storage.sizes if p.endswith('.log'))),
        run_files(),
        _VERSION,
        'do not exist',
    ),
    'a missing manifest': (lambda storage, _m: storage.texts.clear(), run_files(), _VERSION, 'samples.json'),
    'an analysis type the server lacks': (
        lambda _s, server: setattr(server, 'analysis_types', ('cram', 'gvcf')),
        run_files(),
        _VERSION,
        'no analysis type',
    ),
    'another pipeline version': (no_change, run_files(), '0.2.0', 'pipeline version 0.1.0'),
    'a family of mixed sequencing types': (
        lambda _s, server: server.sequencing_groups.update(SG0003='exome'),
        run_files(),
        _VERSION,
        'mixes sequencing types',
    ),
    'a file registered with other sequencing groups': (
        lambda _s, server: server.add(
            type='cram', output=run_of(run_files()).samples[0].cram, sequencing_groups=('SG0004',)
        ),
        run_files(),
        _VERSION,
        'differs from this run',
    ),
    'a file registered by something else': (
        lambda _s, server: server.add(
            type='cram', output=run_of(run_files()).samples[0].cram, sequencing_groups=('SG0001',)
        ),
        run_files(),
        _VERSION,
        r"differs from this run in \['background', 'pipeline_version'\]",
    ),
    'a file registered as failed': (
        lambda _s, server: server.add(
            type='cram',
            output=run_of(run_files()).samples[0].cram,
            sequencing_groups=('SG0001',),
            status='FAILED',
            meta={'background': 'trio-a', 'pipeline_version': _VERSION},
        ),
        run_files(),
        _VERSION,
        r"differs from this run in \['status'\]",
    ),
    'a file registered twice': (
        lambda _s, server: [
            server.add(type='gvcf', output=run_of(run_files()).samples[0].gvcf, sequencing_groups=('SG0001',))
            for _ in range(2)
        ],
        run_files(),
        _VERSION,
        'more than once',
    ),
    'files not on GCS': (
        no_change,
        run_files(rewrite=lambda text: text.replace('gs://example-bucket', '/data')),
        _VERSION,
        'files on GCS',
    ),
}


@pytest.mark.parametrize(('change', 'files', 'version', 'message'), REJECTED.values(), ids=REJECTED.keys())
def test_register_rejects(
    storage: FakeStorage,
    server: FakeMetamist,
    change: Change,
    files: dict[str, str],
    version: str,
    message: str,
) -> None:
    directory = storage.publish(files)
    change(storage, server)
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        register.register(directory, _PROJECT, version, storage=storage, reader=server, writer=server)
    assert server.writes == 0
