from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.catalogue.player_event_head import THIS_DOOR
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _misty_salon() -> list[AbilitySpec]:
    """When you unlock this door, create an X/X blue Spirit creature token with flying, where X is the number of unlocked doors among Rooms you control.
    (You may cast either half. That door unlocks on the battlefield. As a sorcery, you may pay the mana cost of a locked door to unlock it.)

    — MEC-111, the right door of Smoky Lounge // Misty Salon. `create_token` with a ``pt_amount`` over the structured count selector
    ``unlocked_doors`` summed across your Rooms (`continuous._count_structured`); the door that triggered this is already unlocked
    when the trigger resolves, so it counts.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "power": 0, "toughness": 0, "colors": ["U"], "subtypes": ["Spirit"], "keywords": ["flying"], "token_name": "Spirit",
                "pt_amount": {"kind": "count_selector", "selector": {
                    "zone": "battlefield", "of": "you", "filter": {"subtype": "room"},
                    "aggregate": "sum", "value": "unlocked_doors",
                }},
            })],
            trigger={"event": EventType.DOOR_UNLOCKED, "condition": {"subject": "self"}, "filter": {"door": THIS_DOOR}},
        ),
    ]


register("Misty Salon", _misty_salon)
