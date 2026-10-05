from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _springleaf_parade() -> list[AbilitySpec]:
    """When this enchantment enters, create X 1/1 colorless Shapeshifter
    creature tokens with changeling. (They're every creature type.)
    Creature tokens you control have "{T}: Add one mana of any color."

    A deck-local singleton: the X-token sentinel and layer-6 mana grant
    already exist, so a catalogue entry is smaller and safer than widening
    the oracle token grammar for one card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "source_x_paid", "power": 1, "toughness": 1,
                "subtypes": ["Shapeshifter"], "keywords": ["changeling"],
                "token_name": "Shapeshifter",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "creatures_you_control", "tokens": True,
                "mana": [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}],
            })],
        ),
    ]


register("Springleaf Parade", _springleaf_parade)
