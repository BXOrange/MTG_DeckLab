from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _guide_of_souls() -> list[AbilitySpec]:
    """Whenever another creature you control enters, you gain 1 life and get {E} (an energy counter).
    Whenever you attack, you may pay {E}{E}{E}. When you do, put two +1/+1 counters and a flying counter on target attacking creature. It becomes an Angel in addition to its other types.

    — PLAY-ALL (Hope to the last). The enters trigger is a group trigger over `gain_life` + `add_player_counters`. The
    attack trigger is Saheeli's `pay_cost_then` with a reflexive ``then_trigger`` (the target is chosen once the energy
    is paid): counters on an attacking creature, then the permanent Angel subtype as a rest-of-game `grant_until`
    `type_change` on that same creature (``previous_subject``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"amount": 1}), EffectSpec("add_player_counters", {"amount": 1, "kind": "energy"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {
                "subject": "group", "controller": "you", "other": True, "type": "creature",
            }},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {"cost": "pay {e}{e}{e}", "then_trigger": [
                {"type": "add_counters", "params": {
                    "amount": 2, "kind": "+1/+1", "target_kind": "creature", "creature_filter": {"attacking": True},
                }},
                {"type": "add_counters", "params": {"amount": 1, "kind": "flying", "previous_subject": True}},
                {"type": "grant_until", "params": {
                    "static": {"type": "type_change", "params": {"add_subtypes": ["Angel"]}},
                    "target_kind": None, "previous_subject": True,
                }},
            ]})],
            trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}},
        ),
    ]


register("Guide of Souls", _guide_of_souls)
