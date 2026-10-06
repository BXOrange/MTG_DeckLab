from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tamiyo_upriser_crowned() -> list[AbilitySpec]:
    """Flying, double strike, haste
    When Tamiyo enters, you become the monarch.
    Whenever one or more creatures deal combat damage to you while you're the monarch, tap those creatures and put a stun
    counter on each of them.

    — PLAY-ALL (Multiverse Reforged). The keywords are the keyword catalogue's. **Simplification:** the batch trigger is one
    per-creature `DAMAGE` trigger (tap + stun counter on that creature), so a double strike pair of hits stuns twice and N
    simultaneous attackers put N triggers on the stack instead of one; the end state is the same (each creature is tapped
    and gets one counter per hit). "While you're the monarch" is the RULE 603.4 intervening-if ``trigger["active_if"]``.
    """
    body = [
        EffectSpec("tap", {}),
        EffectSpec("add_counters", {"kind": "stun", "amount": 1, "previous_subject": True}),
    ]
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_monarch", {})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {"event_key": "source_id", "effects": [
                {"type": b.type, "params": b.params} for b in body]})],
            trigger={
                "event": "DAMAGE",
                "filter": {"combat": True, "is_player": True},
                "condition": {"subject": "group", "recipient_is_you": True},
                "active_if": {"kind": "is_monarch"},
            },
        ),
    ]


register("Tamiyo, Upriser Crowned", _tamiyo_upriser_crowned)
