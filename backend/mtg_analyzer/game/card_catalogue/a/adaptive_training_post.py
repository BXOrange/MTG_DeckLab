from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _adaptive_training_post() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, if this artifact has
    fewer than three charge counters on it, put a charge counter on it.
    Remove three charge counters from this artifact: When you next cast an
    instant or sorcery spell this turn, copy it and you may choose new
    targets for the copy.

    — Adaptive Training Post. The counter trigger carries its "fewer than
    three" as a RULE 603.4 intervening-if (``trigger["active_if"]``,
    `source_counters` with a ``max`` of two). The activated ability's cost is
    Umezawa's Jitte's ``remove_counters`` cost; its effect is Thunderclap
    Drake's one-shot `create_turn_trigger`, copying the next instant or
    sorcery cast this turn (the copy keeps the original's targets, as
    `CopySpellEffect` documents).
    """
    instant_or_sorcery = {"card_type_any": ["instant", "sorcery"]}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"amount": 1, "kind": "charge", "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
                "spell_filter": dict(instant_or_sorcery),
                "active_if": {"kind": "source_counters", "counter": "charge", "max": 2},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_turn_trigger", {
                "trigger": {
                    "event": "SPELL_CAST", "condition": {"subject": "you"},
                    "spell_filter": dict(instant_or_sorcery),
                },
                "effects": [{"type": "copy_spell", "params": {"spell_from_trigger_event": "instance_id"}}],
                "once": True,
                "description": "when you next cast an instant or sorcery spell this turn, copy it",
            })],
            cost={"remove_counters": ("charge", 3)},
        ),
    ]


register("Adaptive Training Post", _adaptive_training_post)
