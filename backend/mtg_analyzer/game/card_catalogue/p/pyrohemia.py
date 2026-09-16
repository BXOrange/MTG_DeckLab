from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _pyrohemia() -> list[AbilitySpec]:
    """At the beginning of the end step, if no creatures are on the
    battlefield, sacrifice this enchantment.
    {R}: This enchantment deals 1 damage to each creature and each player.

    — Pyrohemia. New `EffectSpec.condition` key ``no_creatures_on_
    battlefield`` (global, unlike the existing controller-scoped
    ``controls_none_of_type``); the activated ability reuses
    `DealDamageEffect`'s already-shipped ``each_creature_and_player``
    selector (Volcanic Fallout-shaped) verbatim — this card's own body just
    hadn't been recognized by the parser yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {}, condition={"no_creatures_on_battlefield": True})],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "end"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_player"})],
            cost={"text": "{r}"},
        ),
    ]


register("Pyrohemia", _pyrohemia)
