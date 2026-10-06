from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dimension_x_pizzasaur() -> list[AbilitySpec]:
    """When this creature enters, put two +1/+1 counters on target creature. When you do, destroy up to one target creature with mana value less than or equal to the number of counters among permanents you control.
    {2}, {T}, Sacrifice this creature: You gain 3 life and each opponent loses 3 life.

    — PLAY-ALL (Turtle Power!). The enters trigger puts the counters, then a RULE 603.12 `reflexive_trigger` (Auron's idiom) whose `destroy` of an optional target creature is gated at resolution by an
    ``amount_compare`` of its mana value against the new ``counters_on_permanents_you_control`` selector. The mana-value cap limits the reflexive trigger's legal targets. The sacrifice ability is the parser's claim.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {"count": 2, "kind": "+1/+1", "target_kind": "creature"}),
                EffectSpec("reflexive_trigger", {"then_trigger": [
                    {"type": "destroy", "params": {"target_kind": "creature", "optional": True,
                        "max_mana_value": "counters_on_permanents_you_control"}},
                ]}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_life", {"amount": 3}), EffectSpec("lose_life", {"amount": 3, "selector": "each_opponent"})],
            cost={"text": "{2}, {t}, sacrifice ~"},
        ),
    ]


register("Dimension X Pizzasaur", _dimension_x_pizzasaur)
