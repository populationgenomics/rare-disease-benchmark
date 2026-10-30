"""One mocked run of the Pulumi program per test session."""

from __future__ import annotations

import mocked_program
import pytest


@pytest.fixture(scope='session')
def program() -> mocked_program.Program:
    return mocked_program.run()
