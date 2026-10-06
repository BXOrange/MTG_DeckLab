from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "any number of land cards" — a hand never holds more than this many cards.
_ANY_NUMBER = 99


def _wrenn_and_seven() -> list[AbilitySpec]:
    """+1: Reveal the top four cards of your library. Put all land cards revealed this way into your hand and the rest into your graveyard.
    0: Put any number of land cards from your hand onto the battlefield tapped.
    −3: Create a green Treefolk creature token with reach and "This token's power and toughness are each equal to the number of lands you control."
    −8: Return all permanent cards from your graveyard to your hand. You get an emblem with "You have no maximum hand size."

    — PLAY-ALL (Death Toll). The +1, −3 and −8 bodies are what the parser claims for the same sentences (`inspect_top_choose`, `create_token` with the
    self-scaling P/T text, `return_from_graveyard` + `create_emblem`); the 0 is `put_from_hand_onto_battlefield` (Tooth and Nail's hand pick) for any
    number of land cards, tapped.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("inspect_top_choose", {
                "count": 4, "action": "library_to_hand", "max_picks": "all", "optional": False,
                "criteria": {"type": "land"}, "rest_destination": "graveyard",
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("put_from_hand_onto_battlefield", {"criteria": {"type": "land"}, "count": _ANY_NUMBER, "tapped": True})],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 0, "toughness": 0, "colors": ["G"], "subtypes": ["Treefolk"], "token_name": "Treefolk",
                "oracle_text": "~'s power and toughness are each equal to the number of lands you control.", "keywords": ["reach"],
            })],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("return_from_graveyard", {"target_kind": "graveyard_permanent", "destination": "hand", "players": "you"}),
                EffectSpec("create_emblem", {"ability": {
                    "ability_kind": "static",
                    "effects": [{"type": "no_max_hand_size", "params": {"affects": "you"}}],
                    "raw_text": "you have no maximum hand size.",
                }}),
            ],
            cost={"loyalty": -8},
        ),
    ]


register("Wrenn and Seven", _wrenn_and_seven)
