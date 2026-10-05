from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Quandrix charge-counter / {X}-matters singletons
# ===========================================================================
# Engine: `SPELL_CAST` event now carries ``has_x``; binder predicate
# ``spell_has_x`` reads it.


def _astral_cornucopia() -> list[AbilitySpec]:
    """This artifact enters with X charge counters on it.
    {T}: Choose a color. Add one mana of that color for each charge counter
    on this artifact."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {
                "colors": ["ANY"], "amount_selector": "charge_counters_on_source",
            })],
            cost={"text": "{T}"},
        ),
    ]


register("Astral Cornucopia", _astral_cornucopia)
