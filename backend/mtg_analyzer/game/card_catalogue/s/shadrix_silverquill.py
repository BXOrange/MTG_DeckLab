from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Shadrix Silverquill (modal choose-two, each targets a player) —
# PAR-60
# ===========================================================================
# Reuse of the modal ``modes={"choose": 2, "options": [...]}`` triggered-
# ability shape (Titan of Industry). Mode 2 ("draws a card and loses 1
# life") is an ENG-37 B4 `seq` sharing one player target across `draw` +
# `lose_life`(``previous_subject``). New small
# `target_player_counter_each_creature` effect for mode 3.
# Documented simplification: "Each mode must target a different player" is
# dropped (the engine has no cross-mode target-distinctness constraint) —
# the modal choice + per-mode player target is preserved.


def _shadrix_silverquill() -> list[AbilitySpec]:
    """Flying, double strike (fold in).
    At the beginning of combat on your turn, you may choose two. Each mode
    must target a different player.
    • Target player creates a 2/1 white and black Inkling token with flying.
    • Target player draws a card and loses 1 life.
    • Target player puts a +1/+1 counter on each creature they control."""
    return [
        AbilitySpec(
            "triggered", [],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                     "phase_relation": "you"},
            modes={"choose": 2, "may": True, "options": [
                [EffectSpec("create_token", {
                    "token_name": "Inkling", "power": 2, "toughness": 1,
                    "colors": ["W", "B"], "subtypes": ["Inkling"], "keywords": ["flying"],
                    "target_kind": "player", "creators": "target",
                })],
                [EffectSpec("seq", {"effects": [
                    {"type": "draw", "params": {"count": 1, "target_kind": "player"}},
                    {"type": "lose_life", "params": {"amount": 1, "previous_subject": True}},
                ]})],
                [EffectSpec("target_player_counter_each_creature", {"amount": 1, "kind": "+1/+1"})],
            ]},
        ),
    ]


register("Shadrix Silverquill", _shadrix_silverquill)
