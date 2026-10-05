from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _welcome_the_dead() -> list[AbilitySpec]:
    """Draw two cards, then discard a card and you lose 2 life. Create X tapped 2/2 black Zombie Druid creature
    tokens, where X is the number of cards that were put into your graveyard from your hand or library this turn.
    Flashback {5}{B}

    — PLAY-ALL Step 2 (Sultai Arisen). Flashback is a printed keyword. The body is a `seq` (the discard is an
    interactive choice, so the rest resumes after it) ending in a `bind` that measures the new
    ``cards_put_into_graveyard_from_hand_or_library_this_turn`` selector (the turn's PUT_INTO_GRAVEYARD arrivals whose
    origin zone was hand or library) *after* the discard, so the card just discarded counts.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "draw", "params": {"count": 2}},
                {"type": "discard", "params": {"count": 1}},
                {"type": "lose_life", "params": {"amount": 2}},
                {"type": "bind", "params": {
                    "name": "n",
                    "amount": {"kind": "count_selector",
                               "selector": "cards_put_into_graveyard_from_hand_or_library_this_turn"},
                    "effects": [{"type": "create_token", "params": {
                        "count": "$n", "power": 2, "toughness": 2, "colors": ["B"],
                        "subtypes": ["Zombie", "Druid"], "token_name": "Zombie Druid", "tapped": True,
                    }}],
                }},
            ]})],
        ),
    ]


register("Welcome the Dead", _welcome_the_dead)
