"""Blitzball."""
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blitzball():
    """{T}: Add one mana of any color.
GOOOOAAAALLL! — {T}, Sacrifice this artifact: Draw two cards. Activate only if an opponent was dealt combat damage by a legendary creature this turn.
"""
    return [AbilitySpec("activated", [EffectSpec("draw", {"count": 2})], cost={
        "text": "{T}, Sacrifice ~", "activation_condition": {
            "kind": "opponent_damaged_by_legendary_creature_this_turn",
        },
    })]


register("Blitzball", _blitzball)
