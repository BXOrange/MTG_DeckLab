from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kogla_the_titan_ape() -> list[AbilitySpec]:
    """When Kogla enters, it fights up to one target creature you don't
    control.
    Whenever Kogla attacks, destroy target artifact or enchantment
    defending player controls.
    {1}{G}: Return target Human you control to its owner's hand. Kogla
    gains indestructible until end of turn.

    — MEC-43. The ETB fight was already parser-MODELED; the other two are
    hand-authored here so the whole card is AUTHORED. The attack trigger
    needed a new ``defending_player_id`` field on the `EventType.ATTACKS`
    event itself (the already-resolved RULE 508.1a defender, not
    previously threaded into the event) and a matching `targeting.py`
    kind reading it, the same trigger-event-scoped idiom `creature_or_
    planeswalker_that_player_controls` uses for a DAMAGE event's
    recipient. The activated ability's "target Human you control" reuses
    `TargetSpec.creature_filter` (now threaded through `ReturnToHandEffect`
    too) rather than a new fixed target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("fight", {
                "fighter_kind": None, "other_kind": "creature_you_dont_control",
                "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("destroy", {
                "target_kind": "artifact_or_enchantment_defending_player_controls",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_to_hand", {
                    "target_kind": "creature_you_control", "creature_filter": {"subtype": "human"},
                }),
                EffectSpec("pump", {"power": 0, "toughness": 0, "keywords": ["indestructible"]}),
            ],
            cost={"text": "{1}{G}"},
        ),
    ]


register("Kogla, the Titan Ape", _kogla_the_titan_ape)
