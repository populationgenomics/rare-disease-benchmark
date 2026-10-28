"""Invariants of what the program deploys, checked on one mocked run (mocked_program.py)."""

from __future__ import annotations

import collections
import inspect

import mocked_program
import pulumi
import pytest

from rare_disease_infra import grants, members


def _grant_classes() -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(grants, inspect.isclass)
        if issubclass(member, pulumi.ComponentResource) and not name.startswith('_')
    }


def test_every_binding_is_a_capability(program: mocked_program.Program) -> None:
    assert program.bindings, 'the program registered no IAM binding; the mocks are not running it'
    loose = [b.urn for b in program.bindings if b.capability not in _grant_classes()]
    assert not loose, 'IAM bindings outside a grants capability:\n' + '\n'.join(loose)


def test_no_grant_is_made_twice(program: mocked_program.Program) -> None:
    # Member bindings are not authoritative: of two that grant the same thing, deleting either revokes it.
    made = collections.Counter((b.type_, b.target, b.role, b.member) for b in program.bindings)
    assert not [grant for grant, count in made.items() if count > 1]


def test_no_basic_role_is_granted(program: mocked_program.Program) -> None:
    basic = [b for b in program.bindings if b.role in {'roles/owner', 'roles/editor', 'roles/viewer'}]
    assert not basic


def test_only_the_task_account_reads_the_dragen_key(program: mocked_program.Program) -> None:
    readers = {b.member for b in program.bindings if b.type_.startswith('gcp:secretmanager/')}
    assert readers == {f'serviceAccount:pipeline-tasks@{mocked_program.PROJECT}.iam.gserviceaccount.com'}


def test_buckets_are_private(program: mocked_program.Program) -> None:
    buckets = program.of_type('gcp:storage/bucket:Bucket')
    assert buckets
    for bucket in buckets:
        assert bucket['uniformBucketLevelAccess'] is True, bucket['name']
        assert bucket['publicAccessPrevention'] == 'enforced', bucket['name']


def test_no_one_is_granted_on_all_users(program: mocked_program.Program) -> None:
    public = [b for b in program.bindings if b.member in {'allUsers', 'allAuthenticatedUsers'}]
    assert not public


def test_network_admits_nothing(program: mocked_program.Program) -> None:
    # With no firewall rules in a custom-mode network, GCP's implied rules deny all inbound traffic.
    assert not program.of_type('gcp:compute/firewall:Firewall')
    networks = program.of_type('gcp:compute/network:Network')
    assert [n['autoCreateSubnetworks'] for n in networks] == [False]


@pytest.mark.parametrize(
    ('launchers', 'message'),
    [
        ([], 'names no one'),
        (['user:someone@example.org'], 'must name groups'),
        (['group:a@example.org', 'group:a@example.org'], 'repeats'),
    ],
)
def test_launchers_are_distinct_groups(launchers: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        members.check_launchers(launchers)
