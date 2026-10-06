from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _spiked_corridor() -> list[AbilitySpec]:
    """When you unlock this door, create three 1/1 red Devil creature tokens with "When this token dies, it deals 1 damage to any target."
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — PLAY-ALL (Endless Punishment). **Simplification (as in Bottomless Pool // Locker Room):** Rooms have no door state in the engine, so casting the Room is its door
    unlocking — the ability is an enters trigger — and the cache holds only this front door's text. The Devils' own dies trigger is the token's quoted rules text, which the
    created-token path parses and binds (PARSER_VERSION 598).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 3, "power": 1, "toughness": 1, "colors": ["R"], "subtypes": ["Devil"], "token_name": "Devil",
                "oracle_text": "When this creature dies, it deals 1 damage to any target.",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Spiked Corridor // Torture Pit", _spiked_corridor)
register("Spiked Corridor", _spiked_corridor)
