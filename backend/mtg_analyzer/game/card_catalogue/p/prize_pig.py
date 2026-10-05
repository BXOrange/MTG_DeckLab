from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _prize_pig() -> list[AbilitySpec]:
    """Whenever you gain life, put that many ribbon counters on this
    creature. Then if there are three or more ribbon counters on this
    creature, remove those counters and untap it.
    {T}: Add one mana of any color.

    Simplified: narrowed to the counter accumulation — the "at 3+, remove
    and untap" follow-up isn't modeled (no "then if this permanent's own
    counter count reaches N, do X" primitive exists yet). The counters
    still visibly accumulate, so the card isn't a no-op, just missing its
    payoff.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "ribbon", "amount_from_trigger_event": "amount"})],
            trigger={"event": EventType.LIFE_GAINED, "condition": {"subject": "you"}},
        ),
    ]


register("Prize Pig", _prize_pig)
