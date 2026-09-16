from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _rionya_fire_dancer() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, create X tokens that are
    copies of another target creature you control, where X is one plus the
    number of instant and sorcery spells you've cast this turn. They gain
    haste. Exile them at the beginning of the next end step.

    Documented simplifications: X is modeled as *the number of spells you've
    cast this turn* (`spells_cast_this_turn`), missing the "+1" and the
    instant/sorcery narrowing."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": "other_creature_you_control",
                    "count_selector": "spells_cast_this_turn", "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "capture": "created_objects",
                    "effects": [{"type": "exile_specific", "params": {}}],
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
        ),
    ]


register("Rionya, Fire Dancer", _rionya_fire_dancer)
