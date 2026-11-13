from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _grievous_wound() -> list[AbilitySpec]:
    """Enchant player
    Enchanted player can't gain life.
    Whenever enchanted player is dealt damage, they lose half their life, rounded up.
    """
    return [
        AbilitySpec("static", [EffectSpec("prevent_all_life_gain", {"scope": "enchanted"})]),
        AbilitySpec("triggered", [EffectSpec("lose_life", {
            "player": {"of": "damaged_player", "as": "controller"},
            "amount": {"kind": "resource", "resource": "life", "of": "damaged_player",
                       "divide": 2, "round_up": True},
        })], trigger={
            "event": EventType.DAMAGE,
            "condition": {"subject": "player", "scope": "enchanted", "recipient": True},
            "filter": {"is_player": True},
        }),
    ]


register("Grievous Wound", _grievous_wound)
