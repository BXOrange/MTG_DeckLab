
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _white_plume_adventurer() -> list[AbilitySpec]:
    "When this creature enters, you take the initiative.\nAt the beginning of each opponent's upkeep, untap a creature you control. If you've completed a dungeon, untap all creatures you control instead."
    return [
        AbilitySpec(
            'triggered',
            [EffectSpec('take_initiative', {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {'subject': 'self'}},
            raw_text='when ~ enters, you take the initiative.',
        ),
        AbilitySpec("triggered", [EffectSpec("if_else", {
            "condition": {"kind": "completed_dungeon"},
            "then": [{"type": "tap", "params": {"selector": "creatures_you_control", "untap": True}}],
            "else": [{"type": "choose_objects", "params": {"action": "untap", "what": "creature", "count": 1}}],
        })], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"}),
    ]


register('White Plume Adventurer', _white_plume_adventurer)
