from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _undead_butler() -> list[AbilitySpec]:
    """When this creature enters, mill three cards.
    When this creature dies, you may exile it. When you do, return target creature card from your graveyard to your hand.

    — PLAY-ALL Step 2 (Wretched Ranks). The mill is the parser's own claim. The dies trigger is Greenwarden of
    Murasa's `may_exile_source_then` (the exile is the optional cost, the return the reflexive "when you do"),
    narrowed to creature cards.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("mill", {"count": 3})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("may_exile_source_then", {"then_trigger": [
                {"type": "return_from_graveyard", "params": {
                    "target_kind": "graveyard_creature", "destination": "hand",
                }},
            ]})],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
        ),
    ]


register("Undead Butler", _undead_butler)
