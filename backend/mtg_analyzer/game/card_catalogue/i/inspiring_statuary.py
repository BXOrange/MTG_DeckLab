from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _inspiring_statuary() -> list[AbilitySpec]:
    """Nonartifact spells you cast have improvise. (Your artifacts can help cast those spells. Each artifact you tap after you're done activating mana abilities pays for {1}.)

    — PLAY-ALL (Limit Break). The new `grant_help_pay_to_spells` static (``spell_help_pay_grant``, `continuous.granted_help_pay_keyword`) gives the spells its controller casts the
    Improvise keyword, excluding artifact spells; `GameEngine._help_pay_keyword` consults it after a card's own printed Convoke/Delve/Improvise.
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_help_pay_to_spells", {"keyword": "improvise", "exclude_card_type": "artifact"})]),
    ]


register("Inspiring Statuary", _inspiring_statuary)
