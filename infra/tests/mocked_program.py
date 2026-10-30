"""The Pulumi program, run under mocks.

The run uses an invented stack config with no cloud access. The mocks synthesise the outputs the program reads off
the resources it creates, in the form GCP gives them.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import runpy
from typing import NamedTuple, override

import pulumi
from pulumi.runtime import mocks

_INFRA = pathlib.Path(__file__).resolve().parents[1]

# Invented values, in the shape of a real stack's config.
PROJECT = 'example-project'
LAUNCHER = 'group:pipeline-launchers@example.org'
STACK_CONFIG = {
    'gcp:project': PROJECT,
    'gcp:region': 'australia-southeast1',
    'rare-disease-benchmark:pipelineLaunchers': json.dumps([LAUNCHER]),
    'rare-disease-benchmark:dragenApiKey': 'mock-secret',
}

BINDING_TYPE = re.compile(r'^gcp:[^:]+:\w*(IAMMember|IamMember|IAMBinding|IamBinding|IAMPolicy|IamPolicy)$')
GRANT_TYPE_PREFIX = 'rare-disease-benchmark:grants:'

# The input that names what each binding type grants access to.
_TARGET_INPUT = {
    'gcp:projects/iAMMember:IAMMember': 'project',
    'gcp:storage/bucketIAMMember:BucketIAMMember': 'bucket',
    'gcp:artifactregistry/repositoryIamMember:RepositoryIamMember': 'repository',
    'gcp:secretmanager/secretIamMember:SecretIamMember': 'secretId',
    'gcp:serviceaccount/iAMMember:IAMMember': 'serviceAccountId',
}


class Binding(NamedTuple):
    urn: str
    type_: str
    capability: str | None  # the grants class it is a child of, or None
    member: str
    role: str
    target: str


class Program(NamedTuple):
    resources: dict[str, mocks.MockMonitor.ResourceRegistration]
    bindings: list[Binding]

    def of_type(self, type_: str) -> list[dict]:
        return [r.state for urn, r in self.resources.items() if urn_type_chain(urn)[-1] == type_]


class _Mocks(mocks.Mocks):
    @override
    def new_resource(self, args: mocks.MockResourceArgs) -> tuple[str, dict[str, object]]:
        outputs: dict[str, object] = {'name': args.inputs.get('name', args.name)}
        resource_id = f'{args.name}-id'
        if args.typ == 'gcp:serviceaccount/account:Account':
            email = f'{args.inputs["accountId"]}@{PROJECT}.iam.gserviceaccount.com'
            outputs |= {
                'email': email,
                'member': f'serviceAccount:{email}',
                'name': f'projects/{PROJECT}/serviceAccounts/{email}',
            }
        elif args.typ == 'gcp:secretmanager/secret:Secret':
            resource_id = f'projects/{PROJECT}/secrets/{args.inputs["secretId"]}'
        return resource_id, {**outputs, **args.inputs}

    @override
    def call(self, args: mocks.MockCallArgs) -> tuple[dict[str, object], list[tuple[str, str]]]:
        raise NotImplementedError(f'the program invoked {args.token}, which this mock does not answer')


def urn_type_chain(urn: str) -> list[str]:
    """The URN's type segment split on `$`: the immediate parent's type, then the resource's own."""
    return urn.split('::')[2].split('$')


def _bindings(resources: dict[str, mocks.MockMonitor.ResourceRegistration]) -> list[Binding]:
    bindings = []
    for urn, registration in resources.items():
        chain = urn_type_chain(urn)
        type_ = chain[-1]
        if not BINDING_TYPE.match(type_):
            continue
        if type_ not in _TARGET_INPUT:
            raise KeyError(f'{type_}: no target input known for this binding type ({urn})')
        parent = chain[-2] if len(chain) > 1 else ''
        state = registration.state
        bindings.append(
            Binding(
                urn=urn,
                type_=type_,
                capability=parent.removeprefix(GRANT_TYPE_PREFIX) if parent.startswith(GRANT_TYPE_PREFIX) else None,
                member=str(state['member']),
                role=str(state['role']),
                target=str(state[_TARGET_INPUT[type_]]),
            )
        )
    return bindings


def run() -> Program:
    """Run the program once. Pulumi's mock runtime is process-global, so a process runs it once (conftest.py)."""
    program_mocks = _Mocks()
    monitor = mocks.MockMonitor(program_mocks)

    @pulumi.runtime.test
    def program() -> None:
        runpy.run_path(str(_INFRA / '__main__.py'), run_name='rare_disease_infra_program')

    # The mock runtime drives the program on `asyncio.get_event_loop()`, which fails once an earlier `asyncio.run`
    # in the process has cleared the thread's loop; give it one of its own.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        pulumi.runtime.set_mocks(program_mocks, project='rare-disease-benchmark', stack='test', monitor=monitor)
        pulumi.runtime.set_all_config(STACK_CONFIG)
        program()
    finally:
        asyncio.set_event_loop(None)
        loop.close()
    return Program(monitor.resources, _bindings(monitor.resources))
