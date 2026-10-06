from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hero_s_heirloom() -> list[AbilitySpec]:
    """Equipped creature gets +2/+1.
    As long as equipped creature is legendary, it has trample and haste.
    Equip {2}

    — PLAY-ALL (Limit Break). Champion's Helm's shape: the parser's anthem plus `grant_keyword` gated on the host being legendary. Equip is the keyword's.
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {"power": 2, "toughness": 1, "affects": "attached_permanent"})]),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "attached_permanent", "keywords": ["trample", "haste"],
                "active_if": {"kind": "is_legendary", "of": "attached"},
            })],
        ),
    ]


register("Hero's Heirloom", _hero_s_heirloom)
