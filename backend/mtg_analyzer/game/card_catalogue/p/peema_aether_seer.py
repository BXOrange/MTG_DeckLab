from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _peema_aether_seer() -> list[AbilitySpec]:
    """When this creature enters, you get an amount of {E} (energy counters) equal to the greatest power among creatures you control.
    Pay {E}{E}{E}: Target creature blocks this turn if able.

    — PLAY-ALL (Living Energy). The ETB measures the ``greatest_power_among_creatures_you_control`` selector. The
    requirement is a new `must_block_if_able` combat restriction (RULE 509.1c: the creature blocks *some* attacker it can,
    enforced by `_enforce_block_requirements`) granted for the turn by `combat_restriction_this_turn`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {
                "amount": {"kind": "count_selector", "selector": "greatest_power_among_creatures_you_control"},
                "kind": "energy",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("combat_restriction_this_turn", {
                "restriction": {"kind": "must_block_if_able"}, "target_kind": "creature",
            })],
            cost={"text": "pay {e}{e}{e}"},
        ),
    ]


register("Peema Aether-Seer", _peema_aether_seer)
