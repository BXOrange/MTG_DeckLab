from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec
from ...card_registry.core import register

#: "your first, second, or third turns of the game" — the last own turn on which it can't be cast.
_LAST_FORBIDDEN_TURN = 3


def _serra_avenger() -> list[AbilitySpec]:
    """You can't cast Serra Avenger during your first, second, or third turns of the game.
    Flying, vigilance

    — PLAY-ALL (Calling All Angels). Flying/vigilance are keywords. The restriction is the spell's ``cast_condition`` with
    the new `own_turn_after` key (`condition_query`): forbidden only while it is the caster's own turn and
    `Player.turns_taken` is at most three.
    """
    return [AbilitySpec("spell_effect", [], cast_condition={"own_turn_after": _LAST_FORBIDDEN_TURN})]


register("Serra Avenger", _serra_avenger)
