from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _flesh_duplicate() -> list[AbilitySpec]:
    """You may have this creature enter as a copy of any creature on the
    battlefield, except it has vanishing 3 if that creature doesn't have
    vanishing.

    — MEC-12 (cEDH staples 2). ``add_keywords_if_target_lacks`` is checked
    against the *target*'s own printed keywords in `resolve_enter_as_copy_
    choice` before the copy runs, so a creature that already has Vanishing
    (of any N) isn't granted a second, conflicting instance.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature",
                "add_keywords_if_target_lacks": ["Vanishing 3"],
            })],
        ),
    ]


register("Flesh Duplicate", _flesh_duplicate)
