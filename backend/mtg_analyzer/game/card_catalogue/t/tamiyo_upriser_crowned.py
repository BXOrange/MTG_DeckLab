from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tamiyo_upriser_crowned() -> list[AbilitySpec]:
    """Flying, double strike, haste
    When Tamiyo enters, you become the monarch.
    Whenever one or more creatures deal combat damage to you while you're the monarch, tap those creatures and put a stun
    counter on each of them.

    The RULE 603.2c damage batch produces one trigger. The captured damage
    sources are tapped and each receives a stun counter at resolution.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("for_each", {"over": {"batch_members": True}, "effects": [
                {"type": "tap", "params": {"target_kind": "previous_target"}},
                {"type": "add_counters", "params": {"kind": "stun", "count": 1, "previous_subject": True}},
            ]})],
            trigger={
                "event": "EVENT_BATCH",
                "batch": {"of": "DAMAGE", "min": 1},
                "filter": {"combat": True, "is_player": True},
                "condition": {"subject": "group", "recipient_is_you": True, "filter": {"card_type": "creature"}},
                "active_if": {"kind": "is_monarch"},
            },
        ),
    ]


register("Tamiyo, Upriser Crowned", _tamiyo_upriser_crowned)
