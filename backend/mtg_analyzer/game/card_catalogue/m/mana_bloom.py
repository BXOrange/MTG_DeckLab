from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_bloom() -> list[AbilitySpec]:
    """This enchantment enters with X charge counters on it.
    Remove a charge counter from this enchantment: Add one mana of any color.
    Activate only once each turn.
    At the beginning of your upkeep, if this enchantment has no charge
    counters on it, return it to its owner's hand."""
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_mana", {"colors": ["ANY"]}),
                EffectSpec("once_per_turn_marker", {}),
            ],
            cost={"remove_counters": ["charge", 1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": None})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "you",
                "active_if": {"kind": "source_counters", "counter": "charge", "max": 0},
            },
        ),
    ]


register("Mana Bloom", _mana_bloom)
