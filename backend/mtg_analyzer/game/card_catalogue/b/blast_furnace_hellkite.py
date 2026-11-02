from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blast_furnace_hellkite() -> list[AbilitySpec]:
    """Artifact offering (You may cast this spell as though it had flash by sacrificing an artifact and paying the difference in mana costs between this and the sacrificed artifact. Mana cost includes color.)
    Flying, double strike
    Creatures attacking your opponents have double strike.

    Artifact offering, flying and double strike come from the RULE 702 keyword catalogue. The static is a layer-6
    `grant_keyword` over a structured battlefield selector whose filter uses the new
    ``attacking_reference_opponent`` key (`attack_scope.attacks_opponent_of`, RULE 506.2): any creature, whoever
    controls it, that is attacking one of this Hellkite controller's opponents (or their planeswalker or battle).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "keywords": ["double_strike"],
            "affects": {"zone": "battlefield", "of": "any",
                        "filter": {"card_type": "creature", "attacking_reference_opponent": True}},
        })]),
    ]


register("Blast-Furnace Hellkite", _blast_furnace_hellkite)
