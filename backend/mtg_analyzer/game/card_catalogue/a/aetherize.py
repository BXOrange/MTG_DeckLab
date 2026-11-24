from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aetherize() -> list[AbilitySpec]:
    """Return all attacking creatures to their owner's hand.

    — Keen Engineering deck batch. `return_to_hand` over the ``all_creatures`` group narrowed by the
    shared object filter's ``attacking`` key — no target, every attacker whoever controls it.
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("return_to_hand", {
            "group": {"zone": "battlefield", "of": "any", "filter": {"card_type": "creature"}}, "filter": {"attacking": True},
        })]),
    ]


register("Aetherize", _aetherize)
