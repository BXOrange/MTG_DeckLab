from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _titan_of_industry() -> list[AbilitySpec]:
    return [AbilitySpec(
        "triggered", [], trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        modes={"choose": 2, "options": [
            [EffectSpec("destroy", {"target_kind": "artifact_or_enchantment"})],
            [EffectSpec("gain_life", {"amount": 5, "target_kind": "player"})],
            [EffectSpec("create_token", {"token_name": "Rhino", "power": 4, "toughness": 4, "colors": ["G"], "subtypes": ["Rhino", "Warrior"]})],
            [EffectSpec("add_counters", {"amount": 1, "kind": "shield", "target_kind": "creature_you_control"})],
        ]},
    )]


register("Titan of Industry", _titan_of_industry)
