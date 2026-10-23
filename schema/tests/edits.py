"""Edits to the fixture's JSON, for tests that need a variant of case 17."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

# A change applied in place to a deep copy of the fixture's JSON.
type Change = Callable[[dict[str, Any]], object]


def changed(data: dict[str, Any], change: Change) -> dict[str, Any]:
    result = copy.deepcopy(data)
    change(result)
    return result


def placement(member: str, name: str, chrom: str, pos: int, **extra: object) -> dict[str, Any]:
    variant: dict[str, Any] = {'chrom': chrom, 'pos': pos, 'ref': 'A', 'alt': 'G'}
    vaf = extra.pop('vaf', None)
    variant.update(extra)
    row: dict[str, Any] = {'haplotype': {'member': member, 'name': name}, 'variant': variant}
    if vaf is not None:
        row['vaf'] = vaf
    return row
