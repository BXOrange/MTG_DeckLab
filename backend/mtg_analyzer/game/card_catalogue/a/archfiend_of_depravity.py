from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "chooses up to two creatures they control, then sacrifices the rest".
_KEPT_CREATURES = 2


def _archfiend_of_depravity() -> list[AbilitySpec]:
    """Flying
    At the beginning of each opponent's end step, that player chooses up to two creatures they control, then sacrifices the rest.

    — PLAY-ALL (Revival Trance). Flying is a keyword. Planetary Annihilation's ``all_but_N`` edict (the player picks the
    survivors) aimed at the turn's active player — new ``selector="active_player"`` on `sacrifice` — on an opponent's end step.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {
                "selector": "active_player", "what": "creature", "count": f"all_but_{_KEPT_CREATURES}",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "not_you"},
        ),
    ]


register("Archfiend of Depravity", _archfiend_of_depravity)
