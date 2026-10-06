from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ancient_cellarspawn() -> list[AbilitySpec]:
    """Each spell you cast that's a Demon, Horror, or Nightmare costs {1} less to cast.
    Whenever you cast a spell, if the amount of mana spent to cast it was less than its mana value, target opponent loses life equal to the difference.

    — PLAY-ALL (Miracle Worker). The discount is the parser's subtype `cost_reduction` over a subtype list. The trigger measures the cast
    event's ``mana_value`` against its ``mana_spent``: `lose_life` for their `abs_diff`, gated on spent < value.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "generic": 1, "increase": False, "spell_subtype": ["demon", "horror", "nightmare"],
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "amount": {
                    "kind": "abs_diff",
                    "left": {"kind": "trigger_event", "field": "mana_value"},
                    "right": {"kind": "trigger_event", "field": "mana_spent"},
                },
                "target_kind": "opponent",
            }, condition={
                "kind": "amount_compare", "op": "lt",
                "left": {"kind": "trigger_event", "field": "mana_spent"},
                "right": {"kind": "trigger_event", "field": "mana_value"},
            })],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
        ),
    ]


register("Ancient Cellarspawn", _ancient_cellarspawn)
