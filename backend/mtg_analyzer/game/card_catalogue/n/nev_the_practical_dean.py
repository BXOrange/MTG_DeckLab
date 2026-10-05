from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nev_the_practical_dean() -> list[AbilitySpec]:
    """Creatures you control with counters on them have trample.
    Whenever you cast your first spell with {X} in its mana cost each turn,
    put X +1/+1 counters on Nev.

    Documented simplifications: "with counters" is narrowed to "with +1/+1
    counters"; the counter payoff uses the firing spell's mana value as X
    (exact for an {X}-only cost)."""
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "creatures_you_control", "keywords": ["trample"],
                "has_counter_kind": "+1/+1",
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "kind": "+1/+1", "amount_from_trigger_event": "mana_value",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "first_x_spell": True,
            },
        ),
    ]


register("Nev, the Practical Dean", _nev_the_practical_dean)
