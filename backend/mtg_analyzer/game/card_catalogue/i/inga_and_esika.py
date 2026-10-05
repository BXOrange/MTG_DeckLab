from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

_ANY_COLOR = [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}]


def _inga_and_esika() -> list[AbilitySpec]:
    """Creatures you control have vigilance and "{T}: Add one mana of any color.
    Spend this mana only to cast a creature spell."
    Whenever you cast a creature spell, if three or more mana from creatures
    was spent to cast it, draw a card.

    — PLAY-ALL Step 2 (SpongeBob). The first sentence is two statics on
    ``creatures_you_control``: `grant_keyword` vigilance and `grant_mana_ability`
    (the five-color option list) with the RULE 605.3a ``mana_restriction``
    ``creature_spell`` ("spend only to cast a creature spell"). The draw is a
    ``SPELL_CAST`` trigger on creature spells with the new
    ``spell_creature_mana_spent_at_least`` predicate (`binding.core`), read off
    the event's ``creature_mana_spent`` — the diff of the creature-sourced bucket
    of the mana pool (`ManaPool.pool_by_source["creature"]`) across the payment,
    the Treasure-spent tally's sibling (`GameObject.mana_spent_to_cast_creature`).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "creatures_you_control", "keywords": ["vigilance"]})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "mana": [dict(option) for option in _ANY_COLOR], "affects": "creatures_you_control",
                "mana_restriction": {"kind": "creature_spell", "allow_ability": False},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"card_type": "creature"}, "spell_creature_mana_spent_at_least": 3,
            },
        ),
    ]


register("Inga and Esika", _inga_and_esika)
