
from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _peel_from_reality() -> list[AbilitySpec]:
    "Return target creature you control and target creature you don't control to their owners' hands."
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("return_to_hand", {"target_kind": "creature_you_control"}),
            EffectSpec("return_to_hand", {"target_kind": "creature_you_dont_control"}),
        ]),
    ]


register('Peel from Reality', _peel_from_reality)
