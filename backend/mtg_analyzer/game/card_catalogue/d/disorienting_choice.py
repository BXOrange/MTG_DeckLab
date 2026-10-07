from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _disorienting_choice() -> list[AbilitySpec]:
    """For each opponent, choose up to one target artifact or enchantment that player controls. For each permanent chosen this way, its controller may exile it. Then if one or more of the chosen permanents are still on the battlefield, you search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle.

    Targets are announced per opponent; exile and search choices occur at resolution.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("disorienting_choice", {})])]


register("Disorienting Choice", _disorienting_choice)
