from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _darksteel_reactor() -> list[AbilitySpec]:
    """Indestructible
    At the beginning of your upkeep, you may put a charge counter on this artifact.
    When this artifact has twenty or more charge counters on it, you win the game.

    — PLAY-ALL Step 2 (Counter Intelligence). Indestructible is the ordinary
    keyword fold-in; the upkeep counter is the parser's own claim. The win is
    Nine Lives' shape: counters only arrive one at a time through this card's
    own upkeep trigger, so a self-subject `COUNTER` trigger gated by
    `source_counters_at_least` is rules-equivalent to the RULE 603.8 state
    trigger (checked every time a counter lands, the only moment the count
    can newly cross twenty).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "charge"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("win_game", {})],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "charge"},
                "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 20, "kind": "charge"},
            },
        ),
    ]


register("Darksteel Reactor", _darksteel_reactor)
