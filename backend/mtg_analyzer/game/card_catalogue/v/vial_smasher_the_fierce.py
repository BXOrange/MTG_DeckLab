from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vial_smasher_the_fierce() -> list[AbilitySpec]:
    """Whenever you cast your first spell each turn, choose an opponent at random. Vial Smasher deals damage equal to that spell's mana value to that player or a planeswalker that player controls.
    Partner (You can have two commanders if both have partner.)

    — PLAY-ALL (Endless Punishment). Partner is a keyword. The head is the parser's "first spell each turn" cast trigger; the body is `damage` with the ``random_opponent_or_planeswalker`` selector: the opponent is random
    (`RulesEngine.random_choice`), and when they control a planeswalker the controller picks the recipient
    (`RulesEngine._request_damage_recipient`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount_from_trigger_event": "mana_value", "selector": "random_opponent_or_planeswalker"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}, "is_nth_spell_cast_this_turn": 1},
        ),
    ]


register("Vial Smasher the Fierce", _vial_smasher_the_fierce)
