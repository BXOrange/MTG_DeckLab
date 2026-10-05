from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _on_wings_of_gold() -> list[AbilitySpec]:
    """Whenever one or more cards leave your graveyard, create a 1/1 white Zombie creature token.
    Creatures you control that are Zombies and/or tokens get +1/+1 and have flying.

    — PLAY-ALL Step 2 (Eternal Might). The trigger is the parser's own claim. The static is an anthem and a
    keyword grant over one structured selector, the Zombie/token union being the `any_of` filter combinator (a
    token Zombie is one creature, so it gets the bonus once — two separate statics would double it).
    """
    group = {"zone": "battlefield", "of": "you", "filter": {
        "card_type": "creature", "any_of": [{"subtype": "zombie"}, {"token": True}],
    }}
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Zombie"],
                "keywords": [], "token_name": "Zombie",
            })],
            trigger={"event": EventType.CARDS_LEFT_GRAVEYARD, "graveyard_owner": "you"},
        ),
        AbilitySpec("static", [
            EffectSpec("anthem", {"affects": group, "power": 1, "toughness": 1}),
            EffectSpec("grant_keyword", {"affects": group, "keywords": ["flying"]}),
        ]),
    ]


register("On Wings of Gold", _on_wings_of_gold)
