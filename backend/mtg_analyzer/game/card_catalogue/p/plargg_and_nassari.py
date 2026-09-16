from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Plargg and Nassari (each-player dig, opp denies, cast 2 free) —
# PAR-60
# ===========================================================================
# New `plargg_and_nassari` effect. Documented simplification: "an opponent
# chooses a nonland card exiled this way" is auto-resolved (highest-MV
# nonland denied); up to two of the remaining nonland cards get a this-turn
# free-cast window.


def _plargg_and_nassari() -> list[AbilitySpec]:
    """At the beginning of your upkeep, each player exiles cards from the top
    of their library until they exile a nonland card. An opponent chooses a
    nonland card exiled this way. You may cast up to two spells from among
    the other cards exiled this way without paying their mana costs."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("plargg_and_nassari", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                     "phase_relation": "you"},
        ),
    ]


register("Plargg and Nassari", _plargg_and_nassari)
