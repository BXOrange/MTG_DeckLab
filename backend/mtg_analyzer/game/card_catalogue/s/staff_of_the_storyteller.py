from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _staff_of_the_storyteller() -> list[AbilitySpec]:
    """When this artifact enters, create a 1/1 white Spirit creature token
    with flying.
    Whenever you create one or more creature tokens, put a story counter on
    this artifact.
    {W}, {T}, Remove a story counter from this artifact: Draw a card."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Spirit", "power": 1, "toughness": 1,
                "colors": ["W"], "subtypes": ["Spirit"], "keywords": ["flying"],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "story"})],
            trigger={
                "event": EventType.CREATE_TOKENS,
                "condition": {"subject": "group", "controller": "you", "type": "creature"},
                "limit": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("draw", {"count": 1})],
            cost={"mana": "{W}", "taps_self": True, "remove_counters": ["story", 1]},
        ),
    ]


register("Staff of the Storyteller", _staff_of_the_storyteller)
