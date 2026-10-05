from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Quintorius, History Chaser (planeswalker: parser-claimed
# graveyard-exit token trigger + two loyalty abilities) — PAR-60
# ===========================================================================
# Engine: new `may_discard_then_draw_mill` effect (loot with a fixed
# payoff). The -4 reuses `pump` with a ``subtypes`` filter on a
# ``selector`` group (Valley Floodcaller idiom).


def _quintorius_history_chaser() -> list[AbilitySpec]:
    """Whenever one or more cards leave your graveyard, create a 3/2 red and
    white Spirit creature token.
    +1: You may discard a card. If you do, draw two cards, then mill a card.
    -4: Spirits you control gain double strike and vigilance until end of turn.

    The graveyard-exit trigger folds in from the parser (it fully claims
    that line); only the two loyalty abilities need authoring."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 2, "colors": ["R", "W"],
                "subtypes": ["Spirit"], "keywords": [], "token_name": "Spirit"})],
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("may_discard_then_draw_mill", {"draw": 2, "mill": 1})],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "keywords": ["double_strike", "vigilance"],
                "selector": "creatures_you_control", "subtypes": ["Spirit"]})],
            cost={"loyalty": -4},
        ),
    ]


register("Quintorius, History Chaser", _quintorius_history_chaser)
