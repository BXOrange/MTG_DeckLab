from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sorin_markov() -> list[AbilitySpec]:
    """[+2]: Sorin Markov deals 2 damage to any target and you gain 2 life.
    [-3]: Target opponent's life total becomes 10.
    [-7]: You control target opponent during that player's next turn.
    You draw a card during that turn's draw step. That player gains
    control of Sorin Markov and you lose control of Sorin Markov.

    — MEC-51 (RULE 720), the final loyalty ability shares the same
    `control_player` primitive as Mindslaver (`card_catalogue/m/
    mindslaver.py`); the "gains control of Sorin Markov"/draw-a-card riders
    are a documented simplification, folded into the plain turn-control
    grant rather than modeled as their own effects.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 2, "target_kind": "any"}),
             EffectSpec("gain_life", {"amount": 2})],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("set_life", {"amount": 10, "target_kind": "opponent"})],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("control_player", {"scope": "turn", "target_kind": "player"})],
            cost={"loyalty": -7},
        ),
    ]


register("Sorin Markov", _sorin_markov)
