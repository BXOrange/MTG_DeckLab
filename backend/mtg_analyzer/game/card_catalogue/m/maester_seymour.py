from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _maester_seymour() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, put a number of +1/+1 counters equal to Maester Seymour's power on another target creature you control.
    {3}{G}{G}: Monstrosity X, where X is the number of counters among creatures you control. (If this creature isn't monstrous, put X +1/+1 counters on it and it becomes monstrous.)

    — PLAY-ALL (Counter Blitz). Both abilities `bind` a measurement into the body: the source's derived power into `add_counters`' ``count`` (target
    ``other_creature_you_control``), and the new ``counters_on_creatures_you_control`` count selector (every kind) into `monstrosity`'s ``amount``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("bind", {
                "name": "p", "amount": {"kind": "characteristic", "characteristic": "power", "of": "source"},
                "effects": [{"type": "add_counters", "params": {
                    "count": "$p", "kind": "+1/+1", "target_kind": "other_creature_you_control",
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("bind", {
                "name": "x", "amount": {"kind": "count_selector", "selector": "counters_on_creatures_you_control"},
                "effects": [{"type": "monstrosity", "params": {"amount": "$x"}}],
            })],
            cost={"mana": "{3}{G}{G}"},
        ),
    ]


register("Maester Seymour", _maester_seymour)
