from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _champion_s_helm() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2.
    As long as equipped creature is legendary, it has hexproof. (It can't be the target of spells or abilities your opponents control.)
    Equip {1}

    — PLAY-ALL (Limit Break). The anthem is the parser's claim. The conditional keyword is `grant_keyword` over the attached permanent
    gated by an ``active_if`` ``is_legendary`` read of the host (``of: attached``, RULE 613.6). Equip is the keyword catalogue's.
    """
    return [
        AbilitySpec("static", [EffectSpec("anthem", {"power": 2, "toughness": 2, "affects": "attached_permanent"})]),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "attached_permanent", "keywords": ["hexproof"],
                "active_if": {"kind": "is_legendary", "of": "attached"},
            })],
        ),
    ]


register("Champion's Helm", _champion_s_helm)
