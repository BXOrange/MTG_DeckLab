from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

# ---------------------------------------------------------------------------
# MEC-51 (RULE 720): "You control target player during that player's next
# turn / next combat phase." `EffectSpec("control_player", {"scope":
# "turn"|"combat", "target_kind": "player"|"opponent"})` installs a
# `GameState.TurnControl`; `RulesEngine._advance_turn_controls` runs the
# `TURN_BEGIN` state machine and `services/game_session.py` routes the
# controlled seat's decisions, priority and turn-based actions to the
# controller for the window. The RULE 720.x carve-outs (the controlled
# player still concedes for themselves, the finer hidden-info edges) are a
# documented simplification — see `Done_Backend.md`.
# ---------------------------------------------------------------------------


def _mindslaver() -> list[AbilitySpec]:
    """{4}, {T}, Sacrifice Mindslaver: You control target player during
    that player's next turn."""
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("control_player", {"scope": "turn", "target_kind": "player"})],
            cost={"text": "{4}, {T}, Sacrifice ~"},
        ),
    ]


register("Mindslaver", _mindslaver)
