"""Checks on the IAM members a stack's config names."""

from __future__ import annotations

from collections.abc import Sequence


def check_launchers(members: Sequence[str]) -> None:
    """Reject a launcher that is not a Google group.

    The stack config is committed to a public repository, so it names groups, whose membership is managed elsewhere,
    and never an individual's address.
    """
    if not members:
        raise ValueError('pipelineLaunchers names no one, so nobody could launch a run')
    for member in members:
        if not member.startswith('group:'):
            raise ValueError(f'pipelineLaunchers must name groups (group:<address>), got {member!r}')
    if len(set(members)) != len(members):
        raise ValueError(f'pipelineLaunchers repeats a member: {sorted(members)}')
