from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _havengul_lich():
    """{1}: You may cast target creature card in a graveyard this turn. When you cast it this turn, this creature gains all activated abilities of that card until end of turn."""
    return [AbilitySpec("activated", [EffectSpec("graveyard_cast_borrow_activated", {})], cost={"mana": "{1}"})]


register("Havengul Lich", _havengul_lich)
