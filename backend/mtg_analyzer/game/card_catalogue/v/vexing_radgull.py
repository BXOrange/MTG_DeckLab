from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vexing_radgull() -> list[AbilitySpec]:
    """Flying
    Whenever this creature deals combat damage to a player, that player
    gets two rad counters if they don't have any rad counters. Otherwise,
    proliferate.

    — Vexing Radgull. Flying picked up unconditionally (RULE 702 keyword
    fold-in). An ordinary DAMAGE trigger over an `if_else` on the damaged
    player's rad counters (checked as the ability resolves, RULE 608.2):
    2 rad counters if they have none, otherwise a real RULE 701.30
    proliferate (`ProliferateEffect`, which also proliferates player-level
    counters).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("if_else", {
                "condition": {"kind": "source_counters", "of": "damaged_player", "counter": "rad", "max": 0},
                "then": [{"type": "add_player_counters", "params": {
                    "amount": 2, "kind": "rad", "player": {"of": "damaged_player"},
                }}],
                "else": [{"type": "proliferate", "params": {}}],
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Vexing Radgull", _vexing_radgull)
