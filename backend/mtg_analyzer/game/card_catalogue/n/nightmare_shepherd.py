from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nightmare_shepherd() -> list[AbilitySpec]:
    """Flying
    Whenever another nontoken creature you control dies, you may exile it. If you do, create a token that's a copy of that creature, except it's 1/1 and it's a Nightmare in addition to its other types.

    — PLAY-ALL (Miracle Worker). Flying is the keyword's. An optional group DIES trigger: `exile` of the dying card (``trigger_subject``),
    then the parser's `copy_permanent` over the trigger event's object with a 1/1 override and the Nightmare subtype.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": "trigger_subject"}),
                EffectSpec("copy_permanent", {
                    "target_kind": None, "referent": "trigger_event", "set_power": 1, "set_toughness": 1,
                    "add_subtypes": ["Nightmare"],
                }),
            ],
            trigger={"event": EventType.DIES, "condition": {
                "subject": "group", "controller": "you", "other": True,
                "filter": {"nontoken": True, "card_type": "creature"},
            }},
            optional=True,
        ),
    ]


register("Nightmare Shepherd", _nightmare_shepherd)
