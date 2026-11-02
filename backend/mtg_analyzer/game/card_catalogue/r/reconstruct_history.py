
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _reconstruct_history() -> list[AbilitySpec]:
    'Return up to one target artifact card, up to one target enchantment card, up to one target instant card, up to one target sorcery card, and up to one target planeswalker card from your graveyard to your hand.\nExile Reconstruct History.'
    effects = [
        EffectSpec("return_from_graveyard", {"target_kind": "graveyard_" + kind, "destination": "hand", "optional": True})
        for kind in ("artifact", "enchantment", "instant", "sorcery", "planeswalker")
    ]
    effects.append(EffectSpec("exile", {"target_kind": None}))
    return [AbilitySpec("spell_effect", effects)]



register('Reconstruct History', _reconstruct_history)
