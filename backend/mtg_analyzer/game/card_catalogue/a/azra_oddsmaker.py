from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "you draw two cards" off the chosen creature's combat hit.
_CARDS_DRAWN = 2


def _azra_oddsmaker() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, you may discard a card. If you do, choose a creature. Whenever that
    creature deals combat damage to a player this turn, you draw two cards.

    Composition of shipped primitives: `pay_cost_then` (RULE 118.3 optional "discard a card" -> "if you do"), then an
    untargeted `choose_objects` ``select_only`` pick of any creature (RULE 608.2d -- a choice on resolution, not a
    target), then `create_turn_trigger` ``previous_subject`` (RULE 603.7a: a delayed trigger lasting the turn, whose
    subject is baked to the picked creature's ``instance_id``) over a combat-damage-to-a-player `DAMAGE` event.
    """
    chosen_creature_hits_a_player = {
        "event": EventType.DAMAGE, "condition": {"subject": "self"},
        "filter": {"combat": True, "is_player": True},
    }
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "discard a card",
                "effects": [{"type": "choose_objects", "params": {
                    "action": "select_only", "what": "creature", "count": 1,
                    "prompt": "Choose a creature",
                    "then": [{"type": "create_turn_trigger", "params": {
                        "trigger": chosen_creature_hits_a_player,
                        "effects": [{"type": "draw", "params": {"count": _CARDS_DRAWN}}],
                        "previous_subject": True,
                        "description": "whenever that creature deals combat damage to a player this turn, "
                                       "you draw two cards",
                    }}],
                }}],
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
    ]


register("Azra Oddsmaker", _azra_oddsmaker)
