from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shredder_shadow_master() -> list[AbilitySpec]:
    """Create nonlegendary attacking copies against the other opponents, sacrifice at combat end; halve a damaged player's life."""
    return [
        AbilitySpec("triggered", [
            EffectSpec("copy_permanent", {"target_kind": None, "other_opponents": True,
                "not_legendary": True, "tapped": True, "attacking": True}),
            EffectSpec("create_delayed_trigger", {"step": "end_combat", "scope": "any", "capture": "created_objects",
                "effects": [{"type": "sacrifice_specific", "params": {}}]}),
        ],
            trigger={"event": "ATTACKS", "condition": {"subject": "self"}, "filter": {"defender_kind": "player"}}),
        AbilitySpec("triggered", [EffectSpec("lose_life", {"player": {"of": "damaged_player", "as": "controller"},
            "amount": {"kind": "resource", "resource": "life", "of": "damaged_player", "divide": 2, "round_up": True}})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}}),
    ]


register('Shredder, Shadow Master', _shredder_shadow_master)
