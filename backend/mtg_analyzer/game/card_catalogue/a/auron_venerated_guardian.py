from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _auron_venerated_guardian() -> list[AbilitySpec]:
    """Vigilance
    Shooting Star — Whenever Auron attacks, put a +1/+1 counter on it. When you do, exile target creature defending player controls with
    power less than Auron's power until Auron leaves the battlefield.

    — PLAY-ALL (Counter Blitz). Vigilance is the keyword's. The attack trigger puts the counter, then a RULE 603.12 `reflexive_trigger` whose
    target (chosen when the reflexive trigger is put on the stack, so Auron's power already includes the counter) is a creature the defending
    player controls with ``power_vs_reference: less`` (reference = Auron). The exile is the linked-exile pair of Portable Hole:
    ``remember`` plus `return_linked_exile` when Auron leaves the battlefield (**simplification** shared with Portable Hole: the return is
    respondable).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 1, "kind": "+1/+1", "target_kind": None}),
                EffectSpec("reflexive_trigger", {"then_trigger": [
                    {"type": "exile", "params": {
                        "target_kind": "creature_defending_player_controls", "remember": True,
                        "creature_filter": {"power_vs_reference": "less"},
                    }},
                ]}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Auron, Venerated Guardian", _auron_venerated_guardian)
