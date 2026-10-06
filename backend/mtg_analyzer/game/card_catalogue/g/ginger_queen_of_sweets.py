from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _card() -> list[AbilitySpec]:
    return [
        AbilitySpec("triggered", [EffectSpec("become_monarch", {})],
                    trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}}),
        AbilitySpec("activated", [EffectSpec("gain_life", {"amount": 6})],
                    cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"}),
        AbilitySpec("triggered", [EffectSpec("create_token_copy_of_named", {"card_name": "Gingerbrute"})],
                    trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                             "active_if": {"kind": "is_monarch"}}),
    ]


register('Ginger, Queen of Sweets', _card)
