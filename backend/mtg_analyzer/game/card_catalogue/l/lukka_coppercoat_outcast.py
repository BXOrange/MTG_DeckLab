from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lukka_coppercoat_outcast() -> list[AbilitySpec]:
    """+1: Exile the top three cards of your library. Creature cards
    exiled this way gain "You may cast this card from exile as long as
    you control a Lukka planeswalker."
    −2: Exile target creature you control, then reveal cards from the top
    of your library until you reveal a creature card with greater mana
    value. Put that card onto the battlefield and the rest on the bottom
    of your library in a random order.
    −7: Each creature you control deals damage equal to its power to
    each opponent.

    — MEC-12 (cEDH M-K). ENG-37 B6 split the +1 into a `seq` of
    `exile_top_of_library` (count 3, positional) and the new
    `grant_conditional_cast_from_exile`, which reads the just-exiled batch
    off `GameContext.created_objects` and registers a genuinely standing
    (never turn-swept) `GameState.exile_cast_condition` per creature card,
    gated on the ``planeswalkers_you_control_of_type_`` count selector via
    the already-general `control_count` static condition. The −2 is an ENG-37
    B5 `bind`: it measures the target creature's mana value + 1 (the dig's
    floor, RULE 608.2 "measured between the two halves"), then the body
    `exile`s the target and runs `dig_until` over the substituted
    `$floor` — the retired `exile_then_reveal_greater_mana_value` fusion.
    The −7 is `each_creature_you_control_damages_each_opponent`, a double
    mass effect no existing `DealDamageEffect` selector already composes.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("seq", {"effects": [
                {"type": "exile_top_of_library", "params": {"count": 3}},
                {"type": "grant_conditional_cast_from_exile", "params": {
                    "condition": {
                        "kind": "control_count",
                        "selector": "planeswalkers_you_control_of_type_lukka",
                        "min": 1,
                    },
                }},
            ]})],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "floor",
                "amount": {"kind": "characteristic", "characteristic": "mana_value",
                           "of": "target", "plus": 1},
                "effects": [
                    {"type": "exile", "params": {"target_kind": "creature_you_control"}},
                    {"type": "dig_until", "params": {
                        "criteria": {"type": "Creature", "min_mana_value": "$floor"},
                        "hit_destination": "battlefield",
                        "rest_destination": "library_bottom_random",
                    }},
                ],
            })],
            cost={"loyalty": -2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("each_creature_you_control_damages_each_opponent", {})],
            cost={"loyalty": -7},
        ),
    ]


register("Lukka, Coppercoat Outcast", _lukka_coppercoat_outcast)
