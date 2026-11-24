from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_of_amity() -> list[AbilitySpec]:
    """Flying
    When this creature enters, exile the top eight cards of your library. You
    may cast an Aura spell from among them without paying its mana cost. Then
    put the rest on the bottom of your library in a random order.
    Whenever this creature attacks, it gets +X/+X until end of turn, where X
    is the number of Auras you control.

    PAR-292 M23: the ETB is the parser's own exile-top-N + resolution-local free cast of an Aura spell with the rest
    to the bottom (`cast_window_exiled_pool` with ``rest_to_bottom``; RULE 608.2g, 401.4), no longer the old
    draw-eight simplification. The attack pump ("+X/+X where X is the number of Auras you control") is modeled via
    a per-count anthem pump on ``self``."""
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {
                    "face_down": False, "player_selector": "controller", "count": 8, "position": "top"}),
                EffectSpec("cast_window_exiled_pool", {
                    "only_spells": True, "resolution_local": True, "rest_to_bottom": True,
                    "card_filter": {"subtype": "aura"}, "free": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {
                "power": 1, "toughness": 1,
                "amount_from_count_selector": "auras_you_control",
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Herald of Amity", _herald_of_amity)
