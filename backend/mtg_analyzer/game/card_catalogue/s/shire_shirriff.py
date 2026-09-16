from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shire_shirriff() -> list[AbilitySpec]:
    """Vigilance
    When this creature enters, you may sacrifice a token. When you do,
    exile target creature an opponent controls until this creature leaves
    the battlefield.

    Simplified: the "you may sacrifice a token" cost gate on the exile
    isn't modeled as an interactive optional choice — the exile always
    happens (still linked, still returned when Shire Shirriff leaves), a
    strictly *more* generous approximation than requiring a token
    sacrifice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Shire Shirriff", _shire_shirriff)
