from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _barrin_tolarian_archmage() -> list[AbilitySpec]:
    """When Barrin enters, return up to one other target creature or planeswalker to its owner's hand.
    At the beginning of your end step, if a permanent was put into your hand from the battlefield this turn, draw a
    card.

    The ETB is the parser's own ``return_to_hand``. The end-step trigger is an intervening-if (RULE 603.4) over the
    turn's event log (``event_this_turn``): a `LEAVES_BATTLEFIELD` whose ``to_zone`` is hand -- fired by
    `RulesEngine.return_to_hand` -- and whose *owner* is the ability's controller, because a permanent always goes to
    its owner's hand (RULE 400.3), so "your hand" is an owner test, not a controller one.
    """
    put_into_your_hand = {
        "event": EventType.LEAVES_BATTLEFIELD, "to_zone": "hand",
        "condition": {"subject": "group", "owner": "you"},
    }
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_hand", {"target_kind": "creature_or_planeswalker", "optional": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "event_this_turn", "min": 1, "trigger": put_into_your_hand},
            },
        ),
    ]


register("Barrin, Tolarian Archmage", _barrin_tolarian_archmage)
