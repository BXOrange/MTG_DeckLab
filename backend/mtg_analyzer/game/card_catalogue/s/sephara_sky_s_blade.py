from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: The printed alternative cost: tap this many untapped flying creatures.
_FLYERS_TO_TAP = 4


def _sephara_sky_s_blade() -> list[AbilitySpec]:
    """You may pay {W} and tap four untapped creatures you control with flying rather than pay this spell's mana cost.
    Flying, lifelink
    Other creatures you control with flying have indestructible.

    — PLAY-ALL (Calling All Angels). Flying/lifelink are keywords and the indestructible grant is the parser's. The
    alternative cost (RULE 118.9) is `alt_cost` pairing ``mana`` with ``tap_others`` over the ``flying_creature`` word
    (`continuous.matches_permanent_word`).
    """
    return [
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "other_creatures_you_control", "object_filter": {"keyword": "flying"},
            "keywords": ["indestructible"],
        })]),
        AbilitySpec("spell_effect", [], alt_cost={"mana": "{W}", "tap_others": [_FLYERS_TO_TAP, "flying_creature"]}),
    ]


register("Sephara, Sky's Blade", _sephara_sky_s_blade)
