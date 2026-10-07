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

    — PLAY-ALL (Raggadragga). The return tracks the dying card's graveyard
    incarnation and checks that it is a permanent card. It enters face down
    under its owner's control, then turns face up: face-up ETB abilities do
    not trigger, but turn-face-up abilities do (RULE 708.3 / 708.8).
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
                "face_down_kind": "manifest", "turn_face_up": True,
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
