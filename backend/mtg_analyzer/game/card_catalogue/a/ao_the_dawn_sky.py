from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Ao, the Dawn Sky (modal dies: budget dig / mass counters) — PAR-60
# ===========================================================================
# New `budget_dig_onto_battlefield` effect (greedy cheapest-first
# auto-selection under a total-MV budget). Mode 2 reuses `add_counters`
# with a mass selector.


def _ao_the_dawn_sky() -> list[AbilitySpec]:
    """Flying, vigilance (fold in).
    When Ao dies, choose one —
    • Look at the top seven cards of your library. Put any number of nonland
      permanent cards with total mana value 4 or less from among them onto
      the battlefield. Put the rest on the bottom of your library in a
      random order.
    • Put two +1/+1 counters on each permanent you control that's a creature
      or Vehicle.

    Documented simplification: mode 2's "or Vehicle" is dropped (each
    creature you control)."""
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.DIES, "condition": {"subject": "self"}},
            modes={"choose": 1, "options": [
                [EffectSpec("budget_dig_onto_battlefield", {"look": 7, "budget": 4})],
                [EffectSpec("add_counters", {
                    "amount": 2, "kind": "+1/+1", "selector": "creatures_you_control",
                })],
            ], "descriptions": ["graben", "marken"]},
        ),
    ]


register("Ao, the Dawn Sky", _ao_the_dawn_sky)
