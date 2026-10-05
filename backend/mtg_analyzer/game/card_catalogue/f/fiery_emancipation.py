from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _fiery_emancipation() -> list[AbilitySpec]:
    """If a source you control would deal damage to a permanent or player,
    it deals triple that damage to that permanent or player instead.

    — Fiery Emancipation. `double_damage` with ``multiplier=3`` +
    ``your_sources_only`` — the RULE 616.1 "triple" sibling of Furnace of
    Rath's unscoped "double" and Torbran's flat "+2"; stacking multiple
    multiplicative/additive damage replacements is exactly the ordering
    case `_furnace_of_rath`'s own docstring calls out.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})],
        )
    ]


register("Fiery Emancipation", _fiery_emancipation)
