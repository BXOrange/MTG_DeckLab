from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "if you control a creature with power 4 or greater".
_BIG_POWER = 4


def _furious_rise() -> list[AbilitySpec]:
    """At the beginning of your end step, if you control a creature with power 4 or greater, exile the top card of your library. You may play that card until you exile another card with this enchantment.

    — PLAY-ALL (Limit Break). An end-step trigger gated by a RULE 603.4 ``control_count`` (``min_power``) intervening-if over the new `exile_top_play_until_next_exile`: the exiled card (a land
    too) is playable on a *standing* permission (`GameState.temp_play_permission_standing`) that the next exile with this enchantment revokes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_play_until_next_exile", {})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "control_count", "selector": "creatures_you_control", "min_power": _BIG_POWER, "min": 1},
            },
        ),
    ]


register("Furious Rise", _furious_rise)
