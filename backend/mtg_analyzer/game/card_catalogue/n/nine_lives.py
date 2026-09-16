from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nine_lives() -> list[AbilitySpec]:
    """Hexproof
    If a source would deal damage to you, prevent that damage and put an
    incarnation counter on this enchantment.
    When there are nine or more incarnation counters on this enchantment,
    exile it.
    When this enchantment leaves the battlefield, you lose the game.

    — Hexproof is the ordinary keyword fold-in. The prevent clause is a
    plain shield with the already-shipped `add_self_counter` rider. RULE
    603.8's "when there are N or more counters" state trigger — the one
    piece the ticket had marked as needing a genuine new subsystem — turned
    out not to: since incarnation counters only ever arrive one at a time
    via this card's own rider, an ordinary `EventType.COUNTER` self-subject
    trigger (Flourishing Defenses' own precedent) gated by the new
    `source_counters_at_least` trigger-condition key (MEC-30, the mirror of
    the already-shipped `source_counters_below`) is exactly rules-equivalent
    to a real state trigger for this card — checked fresh every time a
    counter lands, which is the only time the count could newly cross 9.
    The "leaves the battlefield" clause is the four-times-precedented
    `EventType.LEAVES_BATTLEFIELD`/``condition={"subject": "self"}`` shape.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "controller", "amount": "all",
                "rider": {"kind": "add_self_counter", "counter": "incarnation"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": None})],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "incarnation"},
                "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 9, "kind": "incarnation"},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_game", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Nine Lives", _nine_lives)
