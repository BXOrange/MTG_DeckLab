from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _motivated_pony() -> list[AbilitySpec]:
    """Trample, haste
    Whenever this creature attacks, attacking creatures get +1/+1 until
    end of turn. If a Food entered under your control this turn, untap
    those creatures and they get an additional +2/+2 until end of turn.

    Simplified: narrowed to the unconditional first half (attacking
    creatures get +1/+1) — the "if a Food entered this turn" bonus/untap
    branch isn't modeled (no "permanent of type X entered this turn"
    tracker exists, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "selector": "attacking_creatures"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Motivated Pony", _motivated_pony)
