from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chromatic_orrery() -> list[AbilitySpec]:
    """You may spend mana as though it were mana of any color.
    {T}: Add {C}{C}{C}{C}{C}.
    {5}, {T}: Draw a card for each color among permanents you control.

    — PLAY-ALL Step 2 (SpongeBob). The {T}: Add {C}{C}{C}{C}{C} mana ability
    is read off the oracle text. The first line is the new
    `spend_mana_as_any_color` static (a `mana_wildcard` layer,
    `continuous.standing_mana_wildcard`), the standing sibling of the per-card
    `mana_wildcard_permission` that casting already passes to
    `ManaPool.can_pay`/`pay` as ``wildcard`` (RULE 605.1a). The draw is a
    `draw` whose ``count`` is a `count_selector` operand over the existing
    ``colors_among_permanents_you_control`` selector.
    """
    return [
        AbilitySpec("static", [EffectSpec("spend_mana_as_any_color", {})]),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": {
                "kind": "count_selector", "selector": "colors_among_permanents_you_control",
            }})],
            cost={"text": "{5}, {T}"},
        ),
    ]


register("Chromatic Orrery", _chromatic_orrery)
