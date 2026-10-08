from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aminatou_veil_piercer() -> list[AbilitySpec]:
    """At the beginning of your upkeep, surveil 2. (Look at the top two cards of your library, then put any number of them into your graveyard and the rest on top of your library in any order.)
    Each enchantment card in your hand has miracle. Its miracle cost is equal to its mana cost reduced by {4}. (You may cast a card for its miracle cost when you draw it if it's the first card you drew this turn.)

    Enchantments use the shared first-draw reveal and resolving Miracle trigger.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 2})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_miracle", {"card_type": "enchantment", "reduce_generic": 4})],
        ),
    ]


register("Aminatou, Veil Piercer", _aminatou_veil_piercer)
