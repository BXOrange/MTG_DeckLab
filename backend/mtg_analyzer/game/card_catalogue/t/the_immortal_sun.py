from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_immortal_sun() -> list[AbilitySpec]:
    """Players can't activate planeswalkers' loyalty abilities.
    At the beginning of your draw step, draw an additional card.
    Spells you cast cost {1} less to cast.
    Creatures you control get +1/+1.
    """
    return [
        AbilitySpec("static", [EffectSpec("activation_prohibition", {
            "affects": "all_permanents", "card_type": "planeswalker", "loyalty_only": True,
        })]),
        AbilitySpec("triggered", [EffectSpec("draw", {"count": 1})], trigger={
            "event": EventType.STEP_BEGIN, "filter": {"step": "draw"}, "phase_relation": "you",
        }),
        AbilitySpec("static", [EffectSpec("cost_reduction", {"generic": 1, "increase": False})]),
        AbilitySpec("static", [EffectSpec("anthem", {
            "power": 1, "toughness": 1, "affects": "creatures_you_control",
        })]),
    ]


register("The Immortal Sun", _the_immortal_sun)
