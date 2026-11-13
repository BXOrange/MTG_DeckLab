
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rocket_launcher() -> list[AbilitySpec]:
    "{2}: This artifact deals 1 damage to any target. Destroy this artifact at the beginning of the next end step. Activate only if you've controlled this artifact continuously since the beginning of your most recent turn."
    return [
        AbilitySpec("activated", [
            EffectSpec("damage", {"amount": 1, "target_kind": "any"}),
            EffectSpec("create_delayed_trigger", {"step": "end", "scope": "any", "capture": "self",
                "effects": [{"type": "destroy_specific", "params": {}}], "description": "Destroy Rocket Launcher"}),
            EffectSpec("activation_condition_marker", {"condition": {"kind": "source_controlled_since_turn_begin"}}),
        ], cost={"mana": "{2}"}),
    ]


register('Rocket Launcher', _rocket_launcher)
