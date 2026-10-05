from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scavenger_grounds() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {2}, {T}, Sacrifice a Desert: Exile all graveyards.

    — Tramplesaurus Rex deck batch. The mana ability is read off the printed text. The second is an
    activated `exile_all_graveyards`; its cost sacrifices *a Desert* (this land included, being a
    Desert itself) next to the tap, so it needs the sacrifice-cost subtype form.
    """
    return [
        AbilitySpec(
            "activated", [EffectSpec("exile_all_graveyards", {})],
            cost={"text": "{2}, {t}, sacrifice a desert"},
            raw_text="{2}, {t}, sacrifice a desert: exile all graveyards.",
        ),
    ]


register("Scavenger Grounds", _scavenger_grounds)
