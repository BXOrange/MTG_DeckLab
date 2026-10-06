from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hope_estheim() -> list[AbilitySpec]:
    """Lifelink
    At the beginning of your end step, each opponent mills X cards, where X is the amount of life you gained this turn.

    — PLAY-ALL (Hope to the last). Lifelink is the keyword. Ruin Crab's per-opponent `for_each` over `mill`, sized by the
    ``life_gained_this_turn`` count selector (read for the ability's controller, not the milled player).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("for_each", {"over": {"players": "each_opponent"}, "effects": [
                {"type": "mill", "params": {"target_kind": "player", "count_selector": "life_gained_this_turn"}},
            ]})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Hope Estheim", _hope_estheim)
