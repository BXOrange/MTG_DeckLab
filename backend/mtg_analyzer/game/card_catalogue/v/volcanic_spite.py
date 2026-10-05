from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _volcanic_spite() -> list[AbilitySpec]:
    """Volcanic Spite deals 3 damage to target creature, planeswalker, or
    battle. You may put a card from your hand on the bottom of your
    library. If you do, draw a card.

    — Imodane deck batch. The target kind is the new `creature_
    planeswalker_or_battle`. The loot rider is the new `put_hand_card_on_
    bottom_then_draw` primitive (`RulesEngine.put_hand_card_on_bottom_
    then_draw`) — see its docstring for why the "may" is auto-taken
    rather than opening a real chooser.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature_planeswalker_or_battle"}),
                EffectSpec("put_hand_card_on_bottom_then_draw", {}),
            ],
        ),
    ]


register("Volcanic Spite", _volcanic_spite)
