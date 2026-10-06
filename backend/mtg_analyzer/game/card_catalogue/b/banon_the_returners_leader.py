from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _banon_the_returners_leader() -> list[AbilitySpec]:
    """Once during each of your turns, you may cast a creature spell from among cards in your graveyard that were put there from anywhere other than the battlefield this turn.
    Whenever you attack, you may pay {1} and discard a card. If you do, draw a card.

    — PLAY-ALL (Revival Trance). The permission is Lurrus's `graveyard_cast_permission` for creature spells with the new
    ``arrived_not_from_battlefield_this_turn`` (the turn's `PUT_INTO_GRAVEYARD` arrivals not from the battlefield). The attack
    trigger is a `pay_cost_then` over a mana-and-discard cost.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_cast_permission", {
                "spell_criteria": {"type": "Creature"}, "once_per_turn": True,
                "arrived_not_from_battlefield_this_turn": True, "active_if": {"kind": "your_turn"},
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}, discard a card", "effects": [{"type": "draw", "params": {"count": 1}}],
            })],
            trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}},
        ),
    ]


register("Banon, the Returners' Leader", _banon_the_returners_leader)
