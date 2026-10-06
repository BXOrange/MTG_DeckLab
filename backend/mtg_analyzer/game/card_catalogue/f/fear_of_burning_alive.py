from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 702.150 Delirium — four or more card types among cards in your graveyard.
_DELIRIUM_TYPES = 4


def _fear_of_burning_alive() -> list[AbilitySpec]:
    """When this creature enters, it deals 4 damage to each opponent.
    Delirium — Whenever a source you control deals noncombat damage to an opponent, if there are four or more card types among cards in your graveyard, this creature deals that amount of damage to target creature that player controls.

    — PLAY-ALL (Endless Punishment). The enters trigger is the parser's. The Delirium trigger is Chandra's Incinerator's noncombat-damage head
    (``requires_damage_to_opponent``) retargeted at ``creature_that_player_controls`` with the RULE 603.4 intervening-if as a trigger ``active_if`` — a `control_count`
    over the distinct card types in your graveyard.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 4, "selector": "each_opponent"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"target_kind": "creature_that_player_controls", "amount_from_trigger_event": "amount"})],
            trigger={
                "event": "DAMAGE", "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False}, "requires_damage_to_opponent": True,
                "active_if": {"kind": "control_count", "min": _DELIRIUM_TYPES,
                              "selector": {"zone": "graveyard", "of": "you", "distinct": "card_type"}},
            },
        ),
    ]


register("Fear of Burning Alive", _fear_of_burning_alive)
