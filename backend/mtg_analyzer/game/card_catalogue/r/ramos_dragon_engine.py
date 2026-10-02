from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ramos_dragon_engine() -> list[AbilitySpec]:
    """Flying
    Whenever you cast a spell, put a +1/+1 counter on Ramos for each of that
    spell's colors.
    Remove five +1/+1 counters from Ramos: Add {W}{W}{U}{U}{B}{B}{R}{R}{G}{G}.
    Activate only once each turn.

    — PLAY-ALL Step 2 (SpongeBob). Flying and the counter-removal mana ability
    are read off the card's text. The trigger is an `add_counters` whose
    ``amount`` is the ``trigger_event`` operand over the SPELL_CAST event's
    ``colors`` — `effect_amounts` now counts a collection field's members, so
    "for each of that spell's colors" is the number of colors on the spell
    (a colorless spell adds none, a gold one several).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": {"kind": "trigger_event", "field": "colors"}, "kind": "+1/+1",
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
        ),
    ]


register("Ramos, Dragon Engine", _ramos_dragon_engine)
