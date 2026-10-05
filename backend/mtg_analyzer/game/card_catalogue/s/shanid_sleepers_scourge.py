from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shanid_sleepers_scourge() -> list[AbilitySpec]:
    """Menace
    Other legendary creatures you control have menace.
    Whenever you play a legendary land or cast a legendary spell, you draw a
    card and you lose 1 life.

    — PLAY-ALL Step 2 (SpongeBob). Menace is a printed keyword; the menace
    grant is the parser's own claim, reproduced. "Play a legendary land or
    cast a legendary spell" is two events, so two triggers (the Cemetery
    Gatekeeper "one spec per event" shape): the cast half is the parser's
    shape (``SPELL_CAST`` + ``spell_filter {legendary: True}``); the land half
    watches ``LAND_PLAYED`` — which carries the land's instance id but not its
    supertype — so each of its two effects is gated by the effect-level
    condition ``is_legendary`` read off the trigger's subject (the land that
    was played).
    """
    legendary_land = {"kind": "is_legendary", "of": "trigger_subject"}
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "other_creatures_you_control", "object_filter": {"legendary": True},
                "keywords": ["menace"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1}), EffectSpec("lose_life", {"amount": 1})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": {"legendary": True},
            },
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}, condition=dict(legendary_land)),
                EffectSpec("lose_life", {"amount": 1}, condition=dict(legendary_land)),
            ],
            trigger={"event": EventType.LAND_PLAYED, "condition": {"subject": "you"}},
        ),
    ]


register("Shanid, Sleepers' Scourge", _shanid_sleepers_scourge)
