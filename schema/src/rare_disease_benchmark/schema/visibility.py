"""The two sides of a release, as base classes.

Everything in a release is on the open side, which a system under test sees, or on the withheld side, which only the
harness and the grader read. Every model in this package derives from exactly one of the two bases below, so the side of
a new model is decided where it is defined. The tests walk the type graph of the case's open section, the only open
data, and fail if anything reachable from it is withheld, which turns a misplaced field into a failing test rather than
a leak.
"""

from __future__ import annotations

import pydantic


class OpenModel(pydantic.BaseModel, frozen=True, extra='forbid'):
    """A model a system under test may see."""


class WithheldModel(pydantic.BaseModel, frozen=True, extra='forbid'):
    """A model only the harness and the grader read."""
