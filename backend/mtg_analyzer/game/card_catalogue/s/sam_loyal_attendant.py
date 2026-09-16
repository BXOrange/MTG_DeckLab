from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sam_loyal_attendant() -> list[AbilitySpec]:
    """Partner with Frodo, Adventurous Hobbit.
    At the beginning of combat on your turn, create a Food token.
    Activated abilities of Foods you control cost {1} less to activate.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            # Bug report, 2026-09-04: `GameStep`'s real name for this step
            # (`game/phases.py`) is "begin_combat", not "combat" — the wrong
            # filter value meant this `STEP_BEGIN` event, whose `step` field
            # never carries a bare "combat", could never match, so the Food
            # token silently never got created at all.
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "scope": "activation", "subtype": "food"})],
        ),
    ]


register("Sam, Loyal Attendant", _sam_loyal_attendant)
