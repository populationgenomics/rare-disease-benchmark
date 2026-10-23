from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from rare_disease_benchmark.schema import release

_FIXTURE = pathlib.Path(__file__).parent / 'fixtures' / 'withheld-release.json'


@pytest.fixture
def release_data() -> dict[str, Any]:
    """The invented case 17 in two backgrounds, as JSON."""
    return json.loads(_FIXTURE.read_text('utf-8'))


@pytest.fixture
def withheld(release_data: dict[str, Any]) -> release.WithheldRelease:
    return release.WithheldRelease.model_validate(release_data)
