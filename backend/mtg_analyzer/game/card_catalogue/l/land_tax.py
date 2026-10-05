from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Lorehold "land catch-up" + "a card left your graveyard this turn"
# ===========================================================================
# Engine: `static_conditions` kinds `opponent_controls_more_lands` and
# `card_left_graveyard_this_turn` (the latter backed by the new
# `GameState.cards_left_graveyard_this_turn` per-turn set).


def _land_tax() -> list[AbilitySpec]:
    """At the beginning of your upkeep, if an opponent controls more lands
    than you, you may search your library for up to three basic land cards,
    reveal them, put them into your hand, then shuffle."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"basic": True}, "count": 3, "destination": "hand",
                "optional": True,
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
        ),
    ]


register("Land Tax", _land_tax)
