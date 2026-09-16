from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deflecting_swat() -> list[AbilitySpec]:
    """If you control a commander, you may cast this spell without paying
    its mana cost.
    You may choose new targets for target spell or ability.

    **Documented simplifications**: the commander-tax-free alternative
    cast (RULE 601.2f's `free_cast_condition` — confirmed unreachable from
    a real game session regardless, see BACKLOG.md) is dropped, fully
    castable at its printed {2}{R}. "Spell or ability" is now the real
    printed scope (ENG-26, `spell_or_ability=True` — was **spell**-only
    before the RULE 115 targetable-ability-on-the-stack primitive shipped).
    ``optional=True`` is the printed "you may" (unlike Misdirection's
    mandatory "Change the target").
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("change_target", {"optional": True, "spell_or_ability": True})],
        )
    ]


register("Deflecting Swat", _deflecting_swat)
