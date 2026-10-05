from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "seven or more land cards are in your graveyard" — the printed threshold.
_LAND_CARDS_FOR_COPY = 7
_LAND_CARDS_IN_YOUR_GRAVEYARD = {"zone": "graveyard", "of": "you", "filter": {"card_type": "land"}}


def _scouring_swarm() -> list[AbilitySpec]:
    """Flying
    Whenever you sacrifice a land, create a tapped token that's a copy of this
    creature if seven or more land cards are in your graveyard. Otherwise,
    create a tapped 1/1 black Insect creature token with flying.

    — PLAY-ALL Step 2 (World Shaper). Flying is the keyword fold-in; the trigger
    head is the parser's `SACRIFICE` group (``filter card_type land``, you). The
    body is an `if_else` on a `control_count` over the structured land-cards-in-
    your-graveyard selector (``min 7``): `copy_permanent` of this creature
    (``target_kind None`` = the source, ``tapped``) or the tapped 1/1 black
    flying Insect. The land is already in the graveyard when the trigger
    resolves, so it counts.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {
                    "kind": "control_count", "selector": dict(_LAND_CARDS_IN_YOUR_GRAVEYARD),
                    "min": _LAND_CARDS_FOR_COPY,
                },
                "then": [{"type": "copy_permanent", "params": {"target_kind": None, "tapped": True}}],
                "else": [{"type": "create_token", "params": {
                    "count": 1, "power": 1, "toughness": 1, "colors": ["B"], "subtypes": ["Insect"],
                    "keywords": ["flying"], "token_name": "Insect", "tapped": True,
                }}],
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {
                    "subject": "group", "controller": "you", "other": False, "filter": {"card_type": "land"},
                },
            },
        ),
    ]


register("Scouring Swarm", _scouring_swarm)
