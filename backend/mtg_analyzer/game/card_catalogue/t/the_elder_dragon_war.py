from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_elder_dragon_war() -> list[AbilitySpec]:
    """Read ahead (Choose a chapter and start with that many lore counters. Add one after your draw step.
    Skipped chapters don't trigger. Sacrifice after III.)
    I — This Saga deals 2 damage to each creature and each opponent.
    II — Discard any number of cards, then draw that many cards.
    III — Create a 4/4 red Dragon creature token with flying.

    — Reign of Dragons deck batch. Read ahead is the keyword (RULE 702.155) and III the parser's own
    claim. I is two mass `damage` effects (every creature, then each opponent). II is the chooser
    (`choose_objects`, discard any number from the hand) whose ``then_that_many`` body draws that many.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "selector": "each_creature"}),
             EffectSpec("damage", {"amount": 2, "selector": "each_opponent"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "discard", "pool_zones": ["hand"], "count": "all", "optional": True,
                "then_that_many": {"effects": [{"type": "draw", "params": {"count": "x"}}]},
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["R"], "subtypes": ["Dragon"],
                "keywords": ["flying"], "token_name": "Dragon",
            })],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("The Elder Dragon War", _the_elder_dragon_war)
