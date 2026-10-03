from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _eumidian_hatchery() -> list[AbilitySpec]:
    """{T}, Pay 1 life: Add {B}. Put a hatchling counter on this land.
    When this land is put into a graveyard from the battlefield, for each
    hatchling counter on it, create a 1/1 black Insect creature token with
    flying.

    — PLAY-ALL Step 2 (World Shaper). The mana ability (with its life payment)
    and its hatchling counter are read off the land's own mana-ability text
    and resolve together without using the stack (RULE 605.3b). The dies
    clause is the parser's own head (`DIES`, subject self) with `create_token`
    whose count is the `trigger_event_counter` operand — the counters the land had
    as it left, off the RULE 603.10a snapshot.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": {"kind": "trigger_event_counter", "counter": "hatchling"},
                "power": 1, "toughness": 1, "colors": ["B"], "subtypes": ["Insect"],
                "keywords": ["flying"], "token_name": "Insect",
            })],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Eumidian Hatchery", _eumidian_hatchery)
