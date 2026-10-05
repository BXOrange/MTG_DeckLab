from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sapling_nursery() -> list[AbilitySpec]:
    """Affinity for Forests (This spell costs {1} less to cast for each
    Forest you control.)
    Landfall — Whenever a land you control enters, create a 3/4 green
    Treefolk creature token with reach.
    {1}{G}, Exile this enchantment: Treefolk and Forests you control gain
    indestructible until end of turn.

    — PLAY-ALL Step 2 (Kodama). Affinity is a printed keyword recognized from
    the card's text, not authored here. The landfall trigger is the parser's
    own claim, reproduced verbatim. The activated ability is the parser's
    "{cost}, Exile this enchantment: <group> gain <keyword> until end of
    turn" `pump` over a battlefield selector (the Elves/hexproof form), with
    ``subtype_any`` for the two-word group "Treefolk and Forests" — Forests
    are lands, hence a land *subtype* match rather than a type one.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 3, "toughness": 4, "colors": ["G"],
                "subtypes": ["Treefolk"], "keywords": ["reach"], "token_name": "Treefolk",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "other": False, "type": "land"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "keywords": ["indestructible"],
                "selector": {
                    "zone": "battlefield", "of": "you",
                    "filter": {"subtype_any": ["treefolk", "forest"]},
                },
            })],
            cost={"text": "{1}{G}, Exile ~"},
        ),
    ]


register("Sapling Nursery", _sapling_nursery)
