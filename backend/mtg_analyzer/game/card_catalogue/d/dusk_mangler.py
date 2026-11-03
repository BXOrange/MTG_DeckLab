from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dusk_mangler():
    """As an additional cost to cast this spell, sacrifice a creature, discard a card, or pay 4 life.
    When this creature enters, each opponent sacrifices a creature of their choice, discards a card, and loses 4 life.
    """
    return [
        AbilitySpec("spell_effect", [], additional_cost={"alternatives": [
            {"sacrifice": "creature"}, {"discard": 1}, {"pay_life": 4},
        ]}),
        AbilitySpec("triggered", [
            EffectSpec("sacrifice", {"selector": "each_opponent", "what": "creature", "count": 1}),
            EffectSpec("discard", {"count": 1, "scope": "each_opponent"}),
            EffectSpec("lose_life", {"amount": 4, "selector": "each_opponent"}),
        ], trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
    ]


register("Dusk Mangler", _dusk_mangler)
