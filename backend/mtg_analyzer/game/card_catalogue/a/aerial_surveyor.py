from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _aerial_surveyor() -> list[AbilitySpec]:
    """Flying
    Whenever this Vehicle attacks, if defending player controls more lands than you, search your library for a basic Plains card, put it onto the battlefield tapped, then shuffle.
    Crew 2

    — PLAY-ALL (Shorikai Vehicles). Flying and Crew are keywords. The attack trigger is an `if_else` (RULE 603.4) on an `amount_compare`
    between the lands the *attacked player* controls (``of: attacked_player``, the ATTACKS event's defending player) and your own, around
    the parser's basic-Plains `search`.
    """
    lands = {"zone": "battlefield", "filter": {"card_type": "land"}}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "amount_compare", "op": "gt",
                              "left": {"kind": "count_selector", "of": "attacked_player", "selector": {**lands, "of": "you"}},
                              "right": {"kind": "count_selector", "selector": {**lands, "of": "you"}}},
                "then": [{"type": "search", "params": {"criteria": {"basic": True, "type": "plains"}, "destination": "battlefield_tapped"}}],
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Aerial Surveyor", _aerial_surveyor)
