from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _coiling_rebirth() -> list[AbilitySpec]:
    """Gift a card
    Return target creature card from your graveyard to the battlefield. Then
    if the gift was promised and that creature isn't legendary, create a token
    that's a copy of that creature, except it's 1/1.

    Gift is folded in by the keyword catalogue; the copy reads the returned
    target and checks its current legendary status (RULE 608.2h).
    """
    return [AbilitySpec("spell_effect", [
        EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature"}),
        EffectSpec("if_else", {
            "condition": {"kind": "all", "conditions": [
                {"kind": "flag", "flag": "gift_promised"},
                {"kind": "not", "condition": {"kind": "is_legendary", "of": "previous_target"}},
                {"kind": "source_on_battlefield", "of": "previous_target"},
            ]},
            "then": [{"type": "copy_permanent", "params": {
                "target_kind": None, "referent": "previous", "set_power": 1, "set_toughness": 1,
            }}],
        }),
    ])]


register("Coiling Rebirth", _coiling_rebirth)
