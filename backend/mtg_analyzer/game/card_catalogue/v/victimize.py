from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _victimize() -> list[AbilitySpec]:
    """Choose two target creature cards in your graveyard. Sacrifice a creature.
    If you do, return the chosen cards to the battlefield tapped."""
    return [AbilitySpec("spell_effect", [EffectSpec("sacrifice_to_return_targets", {})])]


register("Victimize", _victimize)
