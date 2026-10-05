from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _wave_of_rats() -> list[AbilitySpec]:
    """Trample
    When this creature dies, if it dealt combat damage to a player this turn,
    return it to the battlefield under its owner's control.
    Blitz {4}{B} (If you cast this spell for its blitz cost, it gains haste and
    "When this creature dies, draw a card." Sacrifice it at the beginning of the
    next end step.)

    — Riveteer Rampage deck batch. RULE 603.4 intervening-if, so the gate sits
    both on the trigger (`active_if`, not put on the stack otherwise) and on the
    effect (rechecked on resolution) — the `Deathbringer Regent` shape. The
    predicate is `dealt_combat_damage_to_player_this_turn`, read off the
    event-derived `GameState.combat_damage_to_players_this_turn` by the creature's
    stable instance id, which is why it still answers after the creature died.
    Trample and Blitz are keywords, not clauses (RULE 702.19 / 702.152).
    """
    gate = {"kind": "dealt_combat_damage_to_player_this_turn"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "return_from_graveyard",
                {"trigger_subject_key": "instance_id"},
                condition=gate,
            )],
            trigger={
                "event": EventType.DIES,
                "condition": {"subject": "self"},
                "active_if": gate,
            },
        ),
    ]


register("Wave of Rats", _wave_of_rats)
