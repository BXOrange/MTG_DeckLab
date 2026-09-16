from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_drain() -> list[AbilitySpec]:
    """Counter target spell. At the beginning of your next main phase, add
    an amount of {C} equal to that spell's mana value.

    — Mana Drain. Now fully modeled (batch 22 built the delayed-trigger
    primitive): `counter` the target spell, then `create_delayed_trigger`
    arms an "at the beginning of your next main phase" ability (``step``
    ``"main"`` matches whichever of main1/main2 begins first, ``scope``
    ``"controller"``). The countered spell is gone by the time the delayed
    ability fires, so its mana value is captured *now* via
    ``capture="target_mana_value"`` and substituted into the delayed
    `add_mana`'s ``"x"`` amount (RULE 603.7's "that spell's mana value").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("counter", {}),
                EffectSpec("create_delayed_trigger", {
                    "step": "main",
                    "scope": "controller",
                    "capture": "target_mana_value",
                    "effects": [
                        {"type": "add_mana", "params": {"color": "C", "amount": "x"}},
                    ],
                    "description": "Mana Drain: {C} in Höhe der Manakosten des annullierten Zauberspruchs hinzufügen",
                }),
            ],
        )
    ]


register("Mana Drain", _mana_drain)
