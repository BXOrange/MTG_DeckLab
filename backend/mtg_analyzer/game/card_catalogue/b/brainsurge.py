from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [AbilitySpec("spell_effect", [
        EffectSpec("draw", {"count": 4}),
        EffectSpec("choose_objects", {"pool_zone": "hand", "what": "card", "count": 2,
                                    "action": "hand_to_library_top", "prompt": "Lege zwei Handkarten auf die Bibliothek"}),
    ])]


register('Brainsurge', _card)
