from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shabraz_the_skyshark() -> list[AbilitySpec]:
    """Flying
    Partner with Hope Estheim
    Whenever you draw a card, put a +1/+1 counter on this creature and you gain 1 life.
    {W/U}: Target Human gains flying until end of turn.

    — PLAY-ALL (Hope to the last). Keywords are the catalogue's; the draw trigger is the parser's. The activation is a
    `pump` (no stat change) granting flying to a creature target narrowed to the Human subtype.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"}), EffectSpec("gain_life", {"amount": 1})],
            trigger={"event": EventType.DRAW, "condition": {"subject": "you"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["flying"],
                "target_kind": "creature", "creature_filter": {"subtype": "Human"},
            })],
            cost={"text": "{w/u}"},
        ),
    ]


register("Shabraz, the Skyshark", _shabraz_the_skyshark)
