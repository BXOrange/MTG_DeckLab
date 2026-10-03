from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _living_death() -> list[AbilitySpec]:
    """Each player exiles all creature cards from their graveyard, then sacrifices
    all creatures they control, then puts all cards they exiled this way onto
    the battlefield."""
    return [AbilitySpec("spell_effect", [EffectSpec("living_death", {})])]


register("Living Death", _living_death)
