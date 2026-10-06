from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _blitzball_stadium() -> list[AbilitySpec]:
    """When this artifact enters, support X. (Put a +1/+1 counter on each of up to X target creatures.)
    Go for the Goal! — {3}, {T}: Until end of turn, target creature gains "Whenever this creature deals combat damage to a player, draw
    a card for each kind of counter on it" and it can't be blocked this turn.

    — PLAY-ALL (Counter Blitz). Support X is the parser's claim (reproduced). The ability is a `grant_until` of a
    `grant_triggered_ability` (combat damage to a player; the body `bind`s the new ``counter_kinds`` amount — the number of distinct counter
    kinds on the creature — into a `draw`) plus `unblockable` on the same target (``previous_subject``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "count": 1, "kind": "+1/+1", "target_kind": "creature", "target_count_selector": "source_x_paid",
                "optional": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_until", {
                    "static": {"type": "grant_triggered_ability", "params": {
                        "trigger_event": "DAMAGE", "filter": {"combat": True, "is_player": True},
                        "grant_effects": [{"type": "bind", "params": {
                            "name": "kinds", "amount": {"kind": "counter_kinds", "of": "source"},
                            "effects": [{"type": "draw", "params": {"count": "$kinds"}}],
                        }}],
                    }},
                    "duration": "end_of_turn", "target_kind": "creature",
                }),
                EffectSpec("unblockable", {"previous_subject": True, "target_kind": None}),
            ],
            cost={"text": "{3}, {T}"},
        ),
    ]


register("Blitzball Stadium", _blitzball_stadium)
