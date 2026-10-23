"""The two sides of a release, as base classes.

Everything in a release is on the open side, which a system under test may see, or on the withheld side, which it may
not. Every model in this package derives from exactly one of the two bases below, so the side of a new model is decided
where it is defined. The tests walk the type graph of an item and fail if anything reachable from it is not an
`OpenModel`, which turns a misplaced field into a failing test rather than a leak.
"""

from __future__ import annotations

import pydantic


class OpenModel(pydantic.BaseModel, frozen=True, extra='forbid'):
    """A model that may appear on the open side of a release."""


class WithheldModel(pydantic.BaseModel, frozen=True, extra='forbid'):
    """A model that appears only on the withheld side of a release."""
