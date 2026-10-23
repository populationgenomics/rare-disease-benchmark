from __future__ import annotations

import inspect
import typing
from collections.abc import Iterator

import pydantic

from rare_disease_benchmark.schema import ids, item, record, release, variant, visibility

_MODULES = (ids, item, record, release, variant, visibility)


# Id types that name something withheld.
_WITHHELD_IDS = (ids.CaseId, ids.SampleId, ids.CaseInstanceId)


def reachable_types(root: type[pydantic.BaseModel]) -> set[object]:
    """Every model type and type alias that can occur inside an instance of `root`, root included."""
    seen: set[object] = set()
    stack: list[object] = [root]
    while stack:
        tp = stack.pop()
        if isinstance(tp, typing.TypeAliasType):
            if tp not in seen:
                seen.add(tp)
                stack.append(tp.__value__)
        elif isinstance(tp, type) and issubclass(tp, pydantic.BaseModel):
            if tp not in seen:
                seen.add(tp)
                stack.extend(field.annotation for field in tp.model_fields.values())
        else:
            stack.extend(typing.get_args(tp))
    return seen


def reachable_models(root: type[pydantic.BaseModel]) -> set[type[pydantic.BaseModel]]:
    return {tp for tp in reachable_types(root) if isinstance(tp, type) and issubclass(tp, pydantic.BaseModel)}


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


def test_nothing_withheld_is_reachable_from_the_family() -> None:
    assert all(issubclass(m, visibility.OpenModel) for m in reachable_models(record.Family))


def test_no_withheld_id_type_is_reachable_from_the_family() -> None:
    assert not set(_WITHHELD_IDS) & reachable_types(record.Family)


def test_the_reachability_walk_finds_withheld_types() -> None:
    # Guards the two tests above against passing vacuously.
    assert record.CaseAnswer in reachable_models(record.Case)
    assert variant.Haplotype in reachable_models(record.Case)
    assert set(_WITHHELD_IDS) <= reachable_types(item.Item) | reachable_types(release.WithheldRelease)


def test_inputs_carry_nothing_withheld(withheld: release.WithheldRelease) -> None:
    case = withheld.cases[0]
    forbidden = {
        case.id,
        *(i.id for i in withheld.instances),
        *(s.sample for i in withheld.instances for s in i.samples),
    }
    for p in case.answer.placements:
        forbidden |= {str(p.variant.pos), f'{p.variant.chrom}:{p.variant.pos}'}
    forbidden |= {gene for d in case.answer.diagnoses for gene in d.genes}
    if case.answer.cutoff is not None:
        forbidden.add(case.answer.cutoff.isoformat())
    for run in item.items(withheld):
        assert not forbidden & set(strings(run.input.model_dump(mode='json')))


def test_items_follow_the_release_order(withheld: release.WithheldRelease) -> None:
    runs = item.items(withheld)
    assert [r.id for r in runs] == [i.id for i in withheld.instances]
    for run, instance in zip(runs, withheld.instances, strict=True):
        case = withheld.case(instance.case)
        assert run.input == case.family
        assert run.cutoff == case.answer.cutoff
