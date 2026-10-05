from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _archaeomancers_map() -> list[AbilitySpec]:
    """When this artifact enters, search your library for up to two basic
    Plains cards, reveal them, put them into your hand, then shuffle.
    Whenever a land an opponent controls enters, if that player controls more
    lands than you, you may put a land card from your hand onto the
    battlefield.

    Documented simplification: the intervening-if is "any opponent controls
    more lands than you" rather than "the player whose land entered" — a
    difference only in a 3+ player game where a *different* opponent is
    ahead."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {
                "criteria": {"basic": True, "type": "plains"}, "count": 2,
                "destination": "hand",
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("put_from_hand_onto_battlefield", {
                "criteria": {"type": "land"}, "count": 1, "optional": True,
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "type": "land", "controller": "not_you",
                              "other": True},
                "active_if": {"kind": "opponent_controls_more_lands"},
            },
        ),
    ]


register("Archaeomancer's Map", _archaeomancers_map)
