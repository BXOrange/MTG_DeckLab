from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _targ_wrangler() -> list[AbilitySpec]:
    """Menace (This creature can't be blocked except by two or more creatures.)
    At the beginning of your end step, if this creature attacked this turn, sacrifice a nonland permanent.

    RULE 603.4: the intervening "if" (``source_attacked_this_turn``) is
    checked both when the step begins and on resolution. Menace folds in
    from the keyword catalogue. The sacrifice is the controller's own
    choice among nonland permanents (RULE 701.21).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "controller", "what": "nonland", "count": 1},
                        condition={"kind": "source_attacked_this_turn"})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you",
                "active_if": {"kind": "source_attacked_this_turn"},
            },
        ),
    ]


register("Targ Wrangler", _targ_wrangler)
