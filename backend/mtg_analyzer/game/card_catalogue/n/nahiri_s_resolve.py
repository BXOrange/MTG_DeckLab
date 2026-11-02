
from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nahiri_s_resolve() -> list[AbilitySpec]:
    "Creatures you control get +1/+0 and have haste.\nAt the beginning of your end step, exile any number of nontoken artifacts and/or creatures you control. Return those cards to the battlefield under their owner's control at the beginning of your next upkeep."
    return [
        AbilitySpec(
            'static',
            [EffectSpec('anthem', {"power": 1, "toughness": 0, "affects": 'creatures_you_control'}), EffectSpec('grant_keyword', {"affects": 'creatures_you_control', "keywords": ['haste']})],
            raw_text='creatures you control get +1/+0 and have haste.',
        ),
        AbilitySpec("triggered", [EffectSpec("choose_objects", {
            "action": "select_only", "what": "permanent", "count": "all", "optional": True,
            "permanent_filter": {"nontoken": True, "card_type_any": ["artifact", "creature"]},
            "then": [{"type": "blink", "params": {
                "subject": "previous_targets", "return_step": "upkeep", "return_scope": "controller",
            }}],
        })], trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"}),
    ]


register("Nahiri's Resolve", _nahiri_s_resolve)
