from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _betor_ancestor_s_voice() -> list[AbilitySpec]:
    """Flying, lifelink
    At the beginning of your end step, put a number of +1/+1 counters on up to one other target creature you control equal to the amount of life you gained this turn. Return up to one target creature card with mana value less than or equal to the amount of life you lost this turn from your graveyard to the battlefield.

    One trigger announces both optional targets and resolves in printed order.
    """
    end_step = {"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": {"kind": "count_selector", "selector": "life_gained_this_turn"}, "kind": "+1/+1",
                "target_kind": "other_creature_you_control", "optional": True,
            }), EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield", "optional": True,
                "max_mana_value": "life_lost_this_turn",
            })],
            trigger=dict(end_step),
        ),
    ]


register("Betor, Ancestor's Voice", _betor_ancestor_s_voice)
