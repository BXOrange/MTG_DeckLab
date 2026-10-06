from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: Chaos — "if Vincent's power is 7 or greater".
_CHAOS_POWER = 7


def _vincent_vengeful_atoner() -> list[AbilitySpec]:
    """Menace
    Whenever one or more creatures you control deal combat damage to a player, put a +1/+1 counter on Vincent.
    Chaos — Whenever Vincent deals combat damage to an opponent, it deals that much damage to each other opponent if Vincent's power is 7 or greater.

    — PLAY-ALL (Limit Break). Menace is the keyword; the counter trigger is the parser's claim (batch `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`). Chaos is Parapet
    Thrasher's `damage` with the ``each_other_opponent`` selector and ``amount_from_trigger_event`` ("amount"), behind an ``if_else`` on Vincent's power.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "+1/+1"})],
            trigger={
                "event": EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER,
                "condition": {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}},
                "contributors": {"min": 1},
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "power", "of": "source", "min": _CHAOS_POWER},
                "then": [{"type": "damage", "params": {
                    "selector": "each_other_opponent", "amount_from_trigger_event": "amount",
                }}],
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self"}, "filter": {"combat": True, "is_player": True}},
        ),
    ]


register("Vincent, Vengeful Atoner", _vincent_vengeful_atoner)
