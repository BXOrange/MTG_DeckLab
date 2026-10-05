from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _black_market_connections() -> list[AbilitySpec]:
    """At the beginning of your first main phase, choose one or more —
    • Sell Contraband — Create a Treasure token. You lose 1 life.
    • Buy Information — Draw a card. You lose 2 life.
    • Hire a Mercenary — Create a 3/2 colorless Shapeshifter creature
    token with changeling. You lose 3 life.

    — Black Market Connections. The modal shape (RULE 700.2's "choose one
    or more") reuses Farewell's own ``modes={"choose": 1, "at_least":
    True, "options": [...]}`` structure verbatim — the only difference is
    the wrapper: a `STEP_BEGIN` main-phase trigger (``filter: {"step":
    "main1"}``, ``phase_relation: "you"``, the same shape Trystan/Wall of
    Vipers-esque "at the beginning of your first main phase" grants
    already use) instead of a plain spell.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "at_least": True,
                "options": [
                    [
                        EffectSpec("create_token", {"count": 1, "token_name": "Treasure"}),
                        EffectSpec("lose_life", {"amount": 1}),
                    ],
                    [
                        EffectSpec("draw", {"count": 1}),
                        EffectSpec("lose_life", {"amount": 2}),
                    ],
                    [
                        EffectSpec("create_token", {
                            "count": 1, "power": 3, "toughness": 2, "colors": [],
                            "subtypes": ["Shapeshifter"], "keywords": ["changeling"],
                            "token_name": "Shapeshifter",
                        }),
                        EffectSpec("lose_life", {"amount": 3}),
                    ],
                ],
                "descriptions": [
                    "Sell Contraband: Erzeuge einen Schatz. Verliere 1 Leben.",
                    "Buy Information: Ziehe eine Karte. Verliere 2 Leben.",
                    "Hire a Mercenary: Erzeuge einen 3/2 farblosen Gestaltwandler "
                    "mit Wandelbar. Verliere 3 Leben.",
                ],
            },
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
        ),
    ]


register("Black Market Connections", _black_market_connections)
