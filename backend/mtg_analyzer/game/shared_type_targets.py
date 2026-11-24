"""Cross-target "that share a creature type" relation for a multi-target requirement.

RULE 115.1a / 601.2c: the number of targets is fixed as the ability is put on the stack, and RULE 205.3m
defines creature types; a requirement such as Secret Tunnel's "two target creatures you control that
share a creature type" additionally relates the picks to *each other*, which a per-candidate filter
cannot express. It is enforced the same way as `TargetSpec.same_graveyard`: through
`targeting.target_group_within_budget` (activation-time validation, trigger rounds, resolution recheck).
"""
from __future__ import annotations

from typing import Any, Iterable

from .creature_types import CREATURE_SUBTYPES


def targets_share_creature_type(targets: Iterable[Any]) -> bool:
    """Whether every object in ``targets`` has at least one creature type in common.

    RULE 205.3m / 702.73a: read through `continuous.has_subtype`, the engine's one authority for subtypes, so
    a changeling or an "is every creature type" grant shares a type with anything (and a layer-4 type
    overwrite hides the printed types). Fewer than two objects trivially satisfy the relation (a
    partly-chosen group during the offer rounds)."""
    from .continuous import has_subtype  # function-scoped: continuous reaches back into effects

    objs = [getattr(t, "obj", t) for t in targets]
    objs = [o for o in objs if o is not None and hasattr(o, "card")]
    if len(objs) < 2:
        return True
    return any(all(has_subtype(o, subtype) for o in objs) for subtype in CREATURE_SUBTYPES)


def objects_share_creature_type(first: Any, second: Any) -> bool:
    """Whether two objects have a creature type in common (RULE 205.3m), by the same `continuous.has_subtype`
    authority as `targets_share_creature_type`: a changeling (RULE 702.73a) shares a type with any object that has one."""
    from .continuous import has_subtype  # function-scoped: continuous reaches back into effects

    return any(has_subtype(first, subtype) and has_subtype(second, subtype) for subtype in CREATURE_SUBTYPES)
