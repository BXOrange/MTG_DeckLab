
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _three_steps_ahead() -> list[AbilitySpec]:
    "Spree (Choose one or more additional costs.)\n+ {1}{U} — Counter target spell.\n+ {3} — Create a token that's a copy of target artifact or creature you control.\n+ {2} — Draw two cards, then discard a card."
    return [
        AbilitySpec("spell_effect", [], modes={
            "choose": 1, "at_least": True, "mode_costs": ["{1}{U}", "{3}", "{2}"],
            "options": [
                [EffectSpec("counter", {})],
                [EffectSpec("copy_permanent", {"target_kind": "artifact_or_creature_you_control"})],
                [EffectSpec("draw", {"count": 2}), EffectSpec("discard", {"count": 1})],
            ],
            "descriptions": ["Counter target spell.", "Copy target artifact or creature you control.", "Draw two cards, then discard a card."],
        }),
    ]


register('Three Steps Ahead', _three_steps_ahead)
