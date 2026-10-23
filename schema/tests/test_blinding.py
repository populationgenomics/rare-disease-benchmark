from __future__ import annotations

import inspect
import typing
from collections.abc import Iterator

import pydantic
import pytest

from rare_disease_benchmark.schema import blinding, ids, item, record, release, variant, visibility

_MODULES = (ids, item, record, release, variant, visibility)


def reachable_models(root: type[pydantic.BaseModel]) -> set[type[pydantic.BaseModel]]:
    """Every model type that can occur inside an instance of `root`, root included."""
    seen: set[type[pydantic.BaseModel]] = set()
    stack: list[object] = [root]
    while stack:
        tp = stack.pop()
        if isinstance(tp, typing.TypeAliasType):
            stack.append(tp.__value__)
        elif isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
            if tp not in seen:
                seen.add(tp)
                stack.extend(field.annotation for field in tp.model_fields.values())
        else:
            stack.extend(typing.get_args(tp))
    return seen


def strings(value: object) -> Iterator[str]:
    """Every string value in a JSON-like structure; keys excluded, since they are field names."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def test_every_model_declares_its_side() -> None:
    models = {
        cls
        for module in _MODULES
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, pydantic.BaseModel) and cls.__module__ == module.__name__
    }
    sides = (visibility.OpenModel, visibility.WithheldModel)
    assert models - set(sides)
    for cls in models - set(sides):
        assert sum(issubclass(cls, side) for side in sides) == 1, cls


def test_nothing_withheld_is_reachable_from_an_item() -> None:
    assert all(issubclass(m, visibility.OpenModel) for m in reachable_models(item.Item))


def test_the_reachability_walk_finds_withheld_models() -> None:
    # Guards the test above against passing vacuously.
    assert record.CaseAnswer in reachable_models(record.Case)
    assert variant.Haplotype in reachable_models(record.Case)


def test_open_items_carry_no_record_ids_or_answer(withheld: release.WithheldRelease) -> None:
    case = withheld.cases[0]
    forbidden = {case.id, *(m.id for m in case.open.family.members)}
    for p in case.answer.placements:
        forbidden |= {str(p.variant.pos), f'{p.variant.chrom}:{p.variant.pos}'}
    for open_item in blinding.open_items(withheld):
        assert not forbidden & set(strings(open_item.model_dump(mode='json')))


def test_open_items_follow_the_release_order_and_ids(withheld: release.WithheldRelease) -> None:
    open_items = blinding.open_items(withheld)
    assert [i.id for i in open_items] == [i.id for i in withheld.instances]
    for open_item, instance in zip(open_items, withheld.instances, strict=True):
        released = {m.release_sample for m in instance.members}
        family = open_item.input.family
        assert {m.id for m in family.members} == released
        assert {p.individual for p in open_item.input.clinical_presentation} <= released
        assert family.proband == instance.release_sample(withheld.case(instance.case).open.family.proband)


def test_the_cutoff_crosses_to_the_manifest(withheld: release.WithheldRelease) -> None:
    for open_item in blinding.open_items(withheld):
        assert open_item.manifest.cutoff == withheld.cases[0].answer.cutoff


def test_open_view_rejects_an_instance_of_another_case(withheld: release.WithheldRelease) -> None:
    other = withheld.cases[0].model_copy(update={'id': 'case-18'})
    with pytest.raises(ValueError, match='not of'):
        blinding.open_view(other, withheld.instances[0], withheld.release)
