from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _yarus_roar_of_the_old_gods() -> list[AbilitySpec]:
    """Other creatures you control have haste.
    Whenever one or more face-down creatures you control deal combat damage to
    a player, draw a card.
    Whenever a face-down creature you control dies, return it to the
    battlefield face down under its owner's control if it's a permanent card,
    then turn it face up.

    — PLAY-ALL Step 2 (Raggadragga). The haste lord and the draw trigger are the
    parser's own claims, reproduced. The dies trigger uses the parser's head for
    "whenever a face-down creature you control dies" (group ``controller: you``,
    ``filter {face_down, creature}``, read off the look-back snapshot) with
    `return_self_to_battlefield` on the dying object. **Documented simplification:**
    the creature returns *face up* directly, rather than face down and then turned
    face up — so its own enters-the-battlefield abilities fire here, where the
    printed sequence (a face-down permanent has no abilities when it enters, and
    "turned face up" is not "enters") would not trigger them.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"affects": "other_creatures_you_control", "keywords": ["haste"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"face_down": True, "card_type": "creature"},
                },
                "contributors": {"min": 1},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_self_to_battlefield", {
                "tapped": False, "target_kind": "trigger_subject", "trigger_event_key": "__group_subject__",
            })],
            trigger={
                "event": EventType.DIES,
                "condition": {
                    "subject": "group", "controller": "you", "other": False,
                    "filter": {"face_down": True, "card_type": "creature"},
                },
            },
        ),
    ]


register("Yarus, Roar of the Old Gods", _yarus_roar_of_the_old_gods)
