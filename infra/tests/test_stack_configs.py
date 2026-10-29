"""Every committed stack config against the program's rules on config.

The stack configs are public, so a secret in one must be encrypted, and launchers must be groups.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from rare_disease_infra import members

_INFRA = pathlib.Path(__file__).resolve().parents[1]
_STACKS = sorted(path for path in _INFRA.glob('Pulumi.*.yaml'))
_SECRETS = ('rare-disease-benchmark:dragenApiKey',)


def _config(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize('path', _STACKS, ids=lambda path: path.name)
def test_secrets_are_kms_encrypted(path: pathlib.Path) -> None:
    stack = _config(path)
    assert stack['secretsprovider'].startswith('gcpkms://')
    for key in _SECRETS:
        if key in stack['config']:
            assert set(stack['config'][key]) == {'secure'}, f'{key} is not encrypted'


@pytest.mark.parametrize('path', _STACKS, ids=lambda path: path.name)
def test_launchers_are_groups(path: pathlib.Path) -> None:
    members.check_launchers(_config(path)['config']['rare-disease-benchmark:pipelineLaunchers'])
