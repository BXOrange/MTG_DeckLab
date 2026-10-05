from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _herald_of_eternal_dawn() -> list[AbilitySpec]:
    """Flash (You may cast this spell any time you could cast an instant.)
    Flying
    You can't lose the game and your opponents can't win the game.

    — PLAY-ALL (Calling All Angels). Flash and Flying are keywords. The two standing prohibitions (RULE 104.3b) are the new
    marker statics `cant_lose_game` / `opponents_cant_win`, read live by `RulesEngine._loss_prevented`/`_player_loses` and
    `player_wins` (`continuous.player_cant_lose` / `player_cant_win`). Conceding is exempt (RULE 104.3a).
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_lose_game", {})]),
        AbilitySpec("static", [EffectSpec("opponents_cant_win", {})]),
    ]


register("Herald of Eternal Dawn", _herald_of_eternal_dawn)
