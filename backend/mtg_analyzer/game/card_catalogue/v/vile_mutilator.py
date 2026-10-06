from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vile_mutilator() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, sacrifice a creature or enchantment.
    Flying, trample
    When this creature enters, each opponent sacrifices a nontoken enchantment of their choice, then sacrifices a nontoken creature of their choice.

    — PLAY-ALL (Death Toll). Flying/trample are keywords; the additional cost is the parser's (``sacrifice: creature_or_enchantment``). The
    ETB is two `sacrifice` edicts over ``each_opponent`` in printed order — each opponent picks their own nontoken permanent (RULE 701.17).
    """
    return [
        AbilitySpec("spell_effect", [], additional_cost={"sacrifice": "creature_or_enchantment"}),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("sacrifice", {"what": "nontoken_enchantment", "selector": "each_opponent"}),
                EffectSpec("sacrifice", {"what": "nontoken_creature", "selector": "each_opponent"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Vile Mutilator", _vile_mutilator)
