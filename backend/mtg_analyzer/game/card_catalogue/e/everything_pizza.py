from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _everything_pizza() -> list[AbilitySpec]:
    """When this artifact enters, search your library for a basic land card, reveal it, put it into your hand, then shuffle.
    {2}{W}{U}{B}{R}{G}, {T}, Sacrifice this artifact: Target player gains 3 life and draws a card. Each of your opponents discards a card. This artifact deals 3 damage to any target. Put three +1/+1 counters on up to one target creature.

    — PLAY-ALL (Turtle Power!). The search is the parser's claim. The ability is a sequence over one shared target list: `gain_life` and `draw` for the first (player) target, `discard` for each opponent, `damage` to any target and
    `add_counters` over up to one creature (``target_groups``-style separate requirements per clause).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("search", {"criteria": {"basic": True}, "destination": "hand"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("gain_life", {"amount": 3, "target_kind": "player"}),
                EffectSpec("draw", {"count": 1, "player": {"of": "previous_player", "as": "controller"}}),
                EffectSpec("discard", {"count": 1, "scope": "each_opponent"}),
                EffectSpec("damage", {"amount": 3, "target_kind": "any"}),
                EffectSpec("add_counters", {"count": 3, "kind": "+1/+1", "target_kind": "creature", "optional": True}),
            ],
            cost={"text": "{2}{W}{U}{B}{R}{G}, {T}, Sacrifice ~"},
        ),
    ]


register("Everything Pizza", _everything_pizza)
