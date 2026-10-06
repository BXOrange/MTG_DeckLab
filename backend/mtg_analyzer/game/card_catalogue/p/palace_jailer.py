from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _palace_jailer() -> list[AbilitySpec]:
    """When this creature enters, you become the monarch.
    When this creature enters, exile target creature an opponent controls until an opponent becomes the monarch.

    — PLAY-ALL (Revival Trance). Two enters triggers: `become_monarch`, and an `exile` stamped ``until_opponent_monarch`` —
    the exiled card remembers its exiler and `RulesEngine.become_monarch` returns it (under its owner's control) the moment
    a *different* player takes the crown, even after the Jailer has left the battlefield.
    """
    return [
        AbilitySpec(
            "triggered", [EffectSpec("become_monarch", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "until_opponent_monarch": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Palace Jailer", _palace_jailer)
