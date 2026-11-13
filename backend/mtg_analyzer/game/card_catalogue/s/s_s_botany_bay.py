from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _s_s_botany_bay() -> list[AbilitySpec]:
    """{T}: Each opponent exiles a card from their graveyard. You may exile a card from your graveyard.
    Station
    8+ | Flying
    Whenever S.S. Botany Bay deals combat damage to a player, return each creature card you own exiled with it to the battlefield.
    """
    return [
        AbilitySpec("activated", [
            EffectSpec("for_each", {"over": {"players": "each_opponent", "simultaneous": True}, "effects": [
                {"type": "exile_hand_card", "params": {"zone": "graveyard", "target_kind": "player",
                                                        "track_exiled_with": True}},
            ]}),
            EffectSpec("exile_hand_card", {"zone": "graveyard", "optional": True,
                                          "track_exiled_with": True}),
        ], cost={"text": "{T}"}),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "keywords": ["flying"], "affects": "self", "min_level": 8, "level_counter": "charge",
        })]),
        AbilitySpec("static", [EffectSpec("type_change", {
            "add_types": ["creature"], "affects": "self", "min_level": 8,
            "level_counter": "charge", "power": 3, "toughness": 5,
        })]),
        AbilitySpec("triggered", [EffectSpec("return_all_exiled_with", {
            "card_types": ["creature"], "own_only": True,
        })], trigger={"event": EventType.DAMAGE,
                      "condition": {"subject": "self"},
                      "filter": {"combat": True, "is_player": True}}),
    ]


register("S.S. Botany Bay", _s_s_botany_bay)
