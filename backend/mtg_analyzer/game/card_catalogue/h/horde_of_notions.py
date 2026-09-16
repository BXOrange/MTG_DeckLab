from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _horde_of_notions() -> list[AbilitySpec]:
    return [
        AbilitySpec("keyword", [], keyword={"name": "vigilance"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("keyword", [], keyword={"name": "haste"}),
        AbilitySpec(
            "activated", [EffectSpec("cast_target_elemental_from_graveyard_free", {})],
            cost={"mana": "{W}{U}{B}{R}{G}"},
        ),
    ]


register("Horde of Notions", _horde_of_notions)
