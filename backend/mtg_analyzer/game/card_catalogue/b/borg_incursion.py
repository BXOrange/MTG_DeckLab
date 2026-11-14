from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _borg_incursion() -> list[AbilitySpec]:
    """Create two 1/1 colorless Borg artifact creature tokens, then artifact creatures you control gain protection from the color of your choice until end of turn. (They can't be blocked, targeted, dealt damage, enchanted, or equipped by anything of that color.)"""
    return [AbilitySpec("spell_effect", [
        EffectSpec("create_token", {"count": 2, "power": 1, "toughness": 1,
            "is_artifact": True, "colors": [], "subtypes": ["Borg"], "token_name": "Borg"}),
        EffectSpec("grant_protection", {"selector": {"zone": "battlefield", "of": "you",
            "filter": {"card_type_all": ["artifact", "creature"]}}}),
    ])]


register("Borg Incursion", _borg_incursion)
