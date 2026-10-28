"""A Pulumi stack's outputs, for the helper tools that act on a deployment."""

from __future__ import annotations

import json
import pathlib
import subprocess
from collections.abc import Iterable, Mapping

_INFRA = pathlib.Path(__file__).resolve().parent


def read(stack: str) -> dict[str, str]:
    """The stack's outputs, as `pulumi stack output` reports them; PULUMI_BACKEND_URL selects the state bucket."""
    result = subprocess.run(  # noqa: S603 (fixed arguments; the stack name is a single argv entry)
        ['pulumi', 'stack', 'output', '--json', '--stack', stack],  # noqa: S607 (pulumi is resolved from PATH)
        cwd=_INFRA,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def require(outputs: Mapping[str, str], keys: Iterable[str], *, stack: str) -> None:
    if missing := [key for key in keys if not outputs.get(key)]:
        raise ValueError(f'stack {stack} lacks outputs {missing}; has `pulumi up` run?')
