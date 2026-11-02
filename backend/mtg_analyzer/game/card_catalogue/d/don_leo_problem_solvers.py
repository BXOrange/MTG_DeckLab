from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _don_leo_problem_solvers() -> list[AbilitySpec]:
    "Vigilance\nAt the beginning of your end step, exile up to one target artifact you control and up to one target creature you control. Then return them to the battlefield under their owners' control."
    return [
        AbilitySpec(
            'triggered',
            [
                # RULE 601.2c: two independent "up to one" targets announced together, then flickered as one batch.
                EffectSpec('choose_targets', {"kinds": ["artifact_you_control", "creature_you_control"], "optional": True}),
                EffectSpec('blink', {"subject": "previous_targets"}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="at the beginning of your end step, exile up to one target artifact you control and up to one target creature you control. then return them to the battlefield under their owners' control.",
        ),
    ]


register('Don & Leo, Problem Solvers', _don_leo_problem_solvers)
