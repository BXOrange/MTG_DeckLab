from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _oracle_of_mul_daya() -> list[AbilitySpec]:
    """You may play an additional land on each of your turns.
    Play with the top card of your library revealed.
    You may play lands from the top of your library.

    — Oracle of Mul Daya. Only the reveal/play-lands-from-top lines are
    modeled here (`top_library_permission`, `game/top_library.py`); the
    "additional land drop" line is a separate, still-unmodeled player-level
    permission (`docs/implementation-state/BACKLOG.md`'s processing-list tail — "you may
    play an additional land on each of your turns") — deliberately left
    off rather than guessed at, not silently dropped by oversight.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {"look": True, "play_lands": True})],
        )
    ]


register("Oracle of Mul Daya", _oracle_of_mul_daya)
