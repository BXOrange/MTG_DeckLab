from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _battle_for_bretagard() -> list[AbilitySpec]:
    """(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
    I — Create a 1/1 white Human Warrior creature token.
    II — Create a 1/1 green Elf Warrior creature token.
    III — Choose any number of artifact tokens and/or creature tokens you control with different names. For each of
    them, create a token that's a copy of it.

    I and II are the parser's own claims (copied verbatim); the Saga lore/sacrifice rules (RULE 715) come from the type.
    III is `choose_distinctly_named_tokens_to_copy`: one representative per token name is offered, the picks are copied
    with `copy_permanent` ``previous_each``.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Human", "Warrior"],
                "keywords": [], "token_name": "Human Warrior"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"], "subtypes": ["Elf", "Warrior"],
                "keywords": [], "token_name": "Elf Warrior"})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_distinctly_named_tokens_to_copy", {})],
            trigger={"event": EventType.SAGA_CHAPTER, "chapter": [3]},
        ),
    ]


register("Battle for Bretagard", _battle_for_bretagard)
