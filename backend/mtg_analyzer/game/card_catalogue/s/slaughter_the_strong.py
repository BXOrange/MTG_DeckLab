from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "total power 4 or less".
_KEPT_POWER = 4


def _slaughter_the_strong() -> list[AbilitySpec]:
    """Each player chooses any number of creatures they control with total power 4 or less, then sacrifices all other creatures they control.

    — PLAY-ALL (Abzan Armor). `slaughter_the_strong`: each player in turn order picks creatures to keep within the power
    budget (`total_power_budget` on the general chooser), then every unchosen creature is sacrificed together.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("slaughter_the_strong", {"budget": _KEPT_POWER})])]


register("Slaughter the Strong", _slaughter_the_strong)
