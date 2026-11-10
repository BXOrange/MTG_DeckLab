from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _k_vort_class_raider() -> list[AbilitySpec]:
    """During your turn, this Spacecraft and creatures you control have hexproof.
    Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. Station only as a sorcery. It's an artifact creature at 4+.)
    4+ | Flying, menace, haste

    RULE 702.184 / 721: the station keyword and the 4+ level rows are the
    parser-claimed specs. The turn-scoped hexproof is two layer-6 grants
    gated by the ``your_turn`` condition (RULE 604.2), one for itself and
    one for the creatures its controller controls.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "keywords": ["flying", "menace", "haste"], "affects": "self",
                "min_level": 4, "level_counter": "charge",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "add_types": ["creature"], "affects": "self",
                "min_level": 4, "level_counter": "charge", "power": 5, "toughness": 3,
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "self", "keywords": ["hexproof"], "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["hexproof"],
                "active_if": {"kind": "your_turn"},
            })],
        ),
    ]


register("K'Vort-Class Raider", _k_vort_class_raider)
