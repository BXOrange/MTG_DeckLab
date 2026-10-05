from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _resourceful_defense() -> list[AbilitySpec]:
    """Whenever a permanent you control leaves the battlefield, if it had
    counters on it, put those counters on target permanent you control.
    {4}{W}: Move any number of counters from target permanent you control onto
    a second target permanent you control.

    — PLAY-ALL Step 2 (Counter Intelligence). The trigger head is the parser's
    own (group ``controller: you`` + ``event_counter_gate {min: 1}`` — the
    intervening "if it had counters", read off the event's RULE 603.10a
    snapshot); the body is the existing `transfer_event_counters` (PAR-120:
    every kind from the departed object's snapshot onto the chosen permanent). The ability is
    `move_counters` (Nexus Mentality's ``move_all_kinds``). **Documented
    simplification:** "any number of counters" moves *all* of them, every kind —
    there is no per-counter chooser (the same all-or-one tier as Forgotten
    Ancient's all-onto-one).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("transfer_event_counters", {"target_kind": "permanent_you_control"})],
            trigger={
                "event": EventType.LEAVES_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "permanent"},
                "event_counter_gate": {"min": 1},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("move_counters", {
                "source_target_kind": "permanent_you_control",
                "dest_target_kind": "permanent_you_control",
                "move_all_kinds": True,
            })],
            cost={"mana": "{4}{W}"},
        ),
    ]


register("Resourceful Defense", _resourceful_defense)
