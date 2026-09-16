from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stifle() -> list[AbilitySpec]:
    """Counter target activated or triggered ability. (Mana abilities
    can't be targeted.)

    — Stifle. The direct payoff of ENG-26's RULE 115/701.5b primitive
    (`counter_ability`/`CounterAbilityEffect`, `targeting.py`'s
    ``"ability"`` kind): a one-clause card that exercises it end to end.
    The parenthetical is reminder text (RULE 115.9c already excludes a
    mana ability from every targetable-ability kind — it never uses the
    stack at all — so nothing extra needs enforcing here).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("counter_ability", {})],
        )
    ]


register("Stifle", _stifle)
