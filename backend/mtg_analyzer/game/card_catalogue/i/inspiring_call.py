from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _inspiring_call() -> list[AbilitySpec]:
    """Draw a card for each creature you control with a +1/+1 counter on it.
    Those creatures gain indestructible until end of turn.

    — PLAY-ALL Step 2 (Kodama). Neither clause parses, but both have a
    shipped shape: the draw is Freyalise's `draw` whose ``count`` is a
    `count_selector` operand over a ``{zone, of, filter}`` selector, and the
    indestructible grant is Make a Stand's `pump` over the same selector.
    The ``has_counter_kind: "+1/+1"`` filter is applied to *both*, so "those
    creatures" are exactly the ones counted — and the draw resolves first,
    before the grant could change anything about which creatures qualify.
    """
    with_counter = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "has_counter_kind": "+1/+1"}}
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": {"kind": "count_selector", "selector": dict(with_counter)}}),
                EffectSpec("pump", {"keywords": ["indestructible"], "selector": dict(with_counter)}),
            ],
        )
    ]


register("Inspiring Call", _inspiring_call)
