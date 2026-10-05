from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _octomancer() -> list[AbilitySpec]:
    """At the beginning of each end step, create a token that's a copy of target creature token that entered the
    battlefield this turn.

    — Peace Offering deck batch. The end-step head is `STEP_BEGIN` with no ``phase_relation`` (every player's end
    step); the body is `copy_permanent` over a creature target restricted by the ``token`` and
    ``entered_this_turn`` filter keys. No such token → no target → the trigger is never put on the stack
    (RULE 603.3d).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "creature", "creature_filter": {"token": True, "entered_this_turn": True},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
        ),
    ]


register("Octomancer", _octomancer)
