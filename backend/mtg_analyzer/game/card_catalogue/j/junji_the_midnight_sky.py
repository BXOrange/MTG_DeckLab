from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _junji_the_midnight_sky() -> list[AbilitySpec]:
    """Flying, menace
    When Junji dies, choose one —
    • Each opponent discards two cards and loses 2 life.
    • Put target non-Dragon creature card from a graveyard onto the battlefield under your control. You lose 2 life.

    — PLAY-ALL Step 2 (Sultai Arisen). Flying/menace are keyword fold-ins. A `modes` dies trigger (the Glissa
    Sunslayer shape): mode one is `discard` + `lose_life` over ``each_opponent``; mode two targets any graveyard's
    non-Dragon creature card (new ``non_dragon_creature`` graveyard filter) and costs its controller 2 life.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            modes={
                "choose": 1,
                "options": [
                    [
                        EffectSpec("discard", {"count": 2, "scope": "each_opponent"}),
                        EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}),
                    ],
                    [
                        EffectSpec("return_from_graveyard", {
                            "target_kind": "any_graveyard_non_dragon_creature", "destination": "battlefield",
                            "under_your_control": True,
                        }),
                        EffectSpec("lose_life", {"amount": 2}),
                    ],
                ],
                "descriptions": [
                    "Each opponent discards two cards and loses 2 life.",
                    "Put target non-Dragon creature card from a graveyard onto the battlefield under your control. "
                    "You lose 2 life.",
                ],
            },
        ),
    ]


register("Junji, the Midnight Sky", _junji_the_midnight_sky)
