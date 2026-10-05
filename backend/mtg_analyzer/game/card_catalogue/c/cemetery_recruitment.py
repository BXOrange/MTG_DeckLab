from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _cemetery_recruitment() -> list[AbilitySpec]:
    """Return target creature card from your graveyard to your hand. If it's a Zombie card, draw a card.

    — PLAY-ALL Step 2 (Wretched Ranks). A `seq` of the targeted `return_from_graveyard` and an `if_else` on
    `is_subtype` of the returned card (`previous_target`, still the card in hand) drawing one.
    """
    return [AbilitySpec("spell_effect", [EffectSpec("seq", {"effects": [
        {"type": "return_from_graveyard", "params": {"target_kind": "graveyard_creature", "destination": "hand"}},
        {"type": "if_else", "params": {
            "condition": {"kind": "is_subtype", "of": "previous_target", "subtype": "zombie"},
            "then": [{"type": "draw", "params": {"count": 1}}], "else": [],
        }},
    ]})])]


register("Cemetery Recruitment", _cemetery_recruitment)
