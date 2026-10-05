from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _broodcaller_scourge() -> list[AbilitySpec]:
    """Flying
    Whenever one or more Dragons you control deal combat damage to a player, you may put a permanent card with mana value less than or equal to that damage from your hand onto the battlefield.

    — PLAY-ALL Step 2 (Temur Roar). The batch head is the shape the parser composes for "one or more `<group>`
    deal combat damage to a player" (Malcolm's Pirates): the aggregate
    ``CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`` event with ``contributors``, whose captured copy carries
    ``matching_amount`` — the damage *this ability's Dragons* dealt (RULE 603.2, "that damage"). The pick is
    `put_from_hand_onto_battlefield` capped by that field (``max_mana_value_from_trigger``); "permanent card"
    is the six permanent types, the pick optional by construction.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": {"type": ["Land", "Creature", "Artifact", "Enchantment", "Planeswalker", "Battle"]},
                "count": 1, "max_mana_value_from_trigger": "matching_amount",
            })],
            trigger={
                "event": "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER",
                "condition": {"subject": "group", "controller": "you", "other": False,
                              "filter": {"subtype": "dragon"}},
                "contributors": {"min": 1},
            },
        ),
    ]


register("Broodcaller Scourge", _broodcaller_scourge)
