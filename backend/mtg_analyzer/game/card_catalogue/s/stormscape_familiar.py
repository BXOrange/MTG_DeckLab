from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _stormscape_familiar() -> list[AbilitySpec]:
    """Flying
    White spells and black spells you cast cost {1} less to cast.

    — PLAY-ALL Step 2 (yshtola). "White spells and black spells" is two
    independent discounts, not one: `cost_reduction`'s ``spell_color`` is a
    single colour (plain AND with the other filters), so each colour gets
    its own static. A spell that is both white and black gets both — which
    is what the printed text means too, the two reductions being separate
    effects (RULE 601.2f applies every one that matches). Flying is not
    authored: it reaches the object through the card's printed keywords.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_color": "W"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "spell_color": "B"})],
        ),
    ]


register("Stormscape Familiar", _stormscape_familiar)
