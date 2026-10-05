from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _betor_ancestor_s_voice() -> list[AbilitySpec]:
    """Flying, lifelink
    At the beginning of your end step, put a number of +1/+1 counters on up to one other target creature you control equal to the amount of life you gained this turn. Return up to one target creature card with mana value less than or equal to the amount of life you lost this turn from your graveyard to the battlefield.

    — PLAY-ALL (Abzan Armor). Flying and lifelink are keywords. One ability with two independent targets is two triggers
    on the same end step (only one targeting effect fits an ability): the counters use ``life_gained_this_turn`` as the amount,
    the return caps its target by the new ``life_lost_this_turn`` mana-value bound (`targeting`'s ``max_mana_value``
    sentinel). Both amounts are fixed by the end step, so splitting them changes nothing.
    """
    end_step = {"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": {"kind": "count_selector", "selector": "life_gained_this_turn"}, "kind": "+1/+1",
                "target_kind": "other_creature_you_control", "optional": True,
            })],
            trigger=dict(end_step),
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {
                "target_kind": "graveyard_creature", "destination": "battlefield", "optional": True,
                "max_mana_value": "life_lost_this_turn",
            })],
            trigger=dict(end_step),
        ),
    ]


register("Betor, Ancestor's Voice", _betor_ancestor_s_voice)
