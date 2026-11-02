from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register
from ...hexproof_from_quality import HEXPROOF_FROM_INSTANTS

#: "greater than your starting life total" means at least 1 more (life is an integer).
_ABOVE_STARTING = 1
#: "at least 10 greater than your starting life total".
_WELL_ABOVE_STARTING = 10


def _elenda_saint_of_dusk() -> list[AbilitySpec]:
    'Lifelink, hexproof from instants\nAs long as your life total is greater than your starting life total, Elenda gets +1/+1 and has menace. Elenda gets an additional +5/+5 as long as your life total is at least 10 greater than your starting life total.'
    above = {"kind": "life_over_starting_at_least", "amount": _ABOVE_STARTING}
    well_above = {"kind": "life_over_starting_at_least", "amount": _WELL_ABOVE_STARTING}
    return [
        # Lifelink is the printed keyword; "hexproof from instants" is a synthetic keyword that
        # `targeting._targetable_by` reads (RULE 702.11d).
        AbilitySpec("static", [EffectSpec("grant_keyword", {"affects": "self", "keywords": [HEXPROOF_FROM_INSTANTS]})]),
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "self", "power": 1, "toughness": 1, "active_if": dict(above)})]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "self", "keywords": ["menace"], "active_if": dict(above)})]),
        AbilitySpec("static", [EffectSpec("anthem", {
            "affects": "self", "power": 5, "toughness": 5, "active_if": dict(well_above)})]),
    ]


register('Elenda, Saint of Dusk', _elenda_saint_of_dusk)
