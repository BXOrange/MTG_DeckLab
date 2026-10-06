from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dream_eater() -> list[AbilitySpec]:
    """Flash
    Flying
    When this creature enters, surveil 4. When you do, you may return target nonland permanent an opponent controls to its owner's hand. (To surveil 4, look at the top four cards of your library, then put any number of them into your graveyard and the rest on top of your library in any order.)

    — PLAY-ALL (Miracle Worker). Flash and Flying are keywords. `surveil` then Faebloom Trick's RULE 603.12 `reflexive_trigger` carrying
    the optional bounce, whose target is chosen only once the surveil is done.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("surveil", {"count": 4}),
                EffectSpec("reflexive_trigger", {"then_trigger": [
                    {"type": "return_to_hand", "params": {"target_kind": "nonland_permanent_you_dont_control", "optional": True}},
                ]}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Dream Eater", _dream_eater)
