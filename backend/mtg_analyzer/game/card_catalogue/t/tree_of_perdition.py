from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tree_of_perdition() -> list[AbilitySpec]:
    """Defender
    {T}: Exchange target opponent's life total with this creature's
    toughness.

    Defender folds in from the RULE 702 keyword catalogue. Authored: the
    activated ability — new bespoke `ExchangeLifeTotalWithToughnessEffect`
    ("exchange_life_total_with_toughness"): the opponent's life becomes ~'s
    former toughness (via life gain/loss, ruling 1) and ~'s base toughness
    is set to the opponent's former life by a permanent toughness-only
    layer-7b `pt_set` (ruling 2).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exchange_life_total_with_toughness", {})],
            cost={"text": "{T}"},
        ),
    ]


register("Tree of Perdition", _tree_of_perdition)
