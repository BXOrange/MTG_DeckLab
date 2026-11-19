"""RULE 702.62b: which exiled cards are "suspended", and the pools "permanent or suspended card" targets and mass effects
draw from (Shivan Sand-Mage, Timebender, Timecrafting, Dust of Moments).

A suspended card is an exiled card that has suspend and a time counter on it. Suspend may be printed or granted
(`GameObject.granted_suspend`); `rules.triggers_mixin._has_suspend` already reads both, so this module reuses it rather
than restating the test."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState

#: The counter kind Suspend places and removes (RULE 702.62a).
TIME_COUNTER = "time"


def is_suspended(obj: "GameObject") -> bool:
    """RULE 702.62b: an exiled card with suspend and at least one time counter."""
    from .rules.triggers_mixin import _has_suspend  # function-scoped: the rules package imports the effects layer
    from ..models.game.game_object import Zone

    return obj.zone == Zone.EXILE and _has_suspend(obj) and (obj.counters or {}).get(TIME_COUNTER, 0) > 0


def has_time_counter(obj: "GameObject") -> bool:
    return (obj.counters or {}).get(TIME_COUNTER, 0) > 0


def time_counter_pool(state: "GameState", *, permanents_need_counter: bool) -> list["GameObject"]:
    """Every battlefield permanent (only those with a time counter when ``permanents_need_counter``) plus every
    suspended card in any exile zone: "target permanent [with a time counter on it] or suspended card"."""
    pool: list[Any] = [o for o in state.permanents() if not permanents_need_counter or has_time_counter(o)]
    pool.extend(o for player in state.players for o in player.exile if is_suspended(o))
    return pool
