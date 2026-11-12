"""Arcades Sabboth, including the token copy offered by Fate Reforged."""
from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arcades_sabboth():
    """Flying
At the beginning of your upkeep, sacrifice Arcades Sabboth unless you pay {G}{W}{U}.
Each untapped creature you control gets +0/+2 as long as it's not attacking.
{W}: Arcades Sabboth gets +0/+1 until end of turn."""
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("triggered", [EffectSpec("sacrifice_unless_pay", {"cost": "pay {G}{W}{U}"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"}),
        AbilitySpec("static", [EffectSpec("anthem", {"power": 0, "toughness": 2,
            "affects": {"zone": "battlefield", "of": "you", "filter": {
                "card_type": "creature", "tapped": False, "attacking": False,
            }}})]),
        AbilitySpec("activated", [EffectSpec("pump", {"power": 0, "toughness": 1})], cost={"text": "{W}"}),
    ]


register("Arcades Sabboth", _arcades_sabboth)
