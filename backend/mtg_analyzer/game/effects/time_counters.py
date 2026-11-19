"""Remove or put time counters on permanents and suspended cards (RULE 122.1, 702.62a-b).

"Remove two time counters from target permanent or suspended card." / "Put two time counters on target permanent with a
time counter on it or suspended card." (Shivan Sand-Mage, Timebender, Timecrafting) and the untargeted "from each
permanent and each suspended card" mass form (Dust of Moments)."""

from __future__ import annotations

from typing import Any, Optional, Union

from ..suspended_cards import TIME_COUNTER, has_time_counter, is_suspended, time_counter_pool
from ..targeting import TargetSpec
from .core import GameContext, GameEffect

#: The parser's literal for the announced {X} (RULE 107.3), read off the source at resolution.
COUNT_X = "x"


class TimeCountersEffect(GameEffect):
    """``mode`` is ``"remove"`` or ``"add"``; ``count`` an int or ``"x"``; ``target_kind`` one of the two
    permanent-or-suspended-card kinds, or ``mass=True`` for "each permanent and each suspended card" (the add form
    reaching only permanents that already carry a time counter, RULE 122.1)."""

    def __init__(
        self, mode: str = "remove", count: Union[int, str] = 1, target_kind: Optional[str] = None, mass: bool = False,
        source: Optional[Any] = None,
    ) -> None:
        super().__init__(source)
        self.mode = "add" if mode == "add" else "remove"
        self.count = count
        self.mass = bool(mass)
        self.target_spec = None if self.mass or target_kind is None else TargetSpec(kind=target_kind)

    def _amount(self) -> int:
        if self.count == COUNT_X:
            return max(0, int(getattr(self.source, "x_paid", 0) or 0))
        return max(0, int(self.count))

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        amount = self._amount()
        if amount <= 0:
            return
        if self.mass:
            objects = time_counter_pool(context.state, permanents_need_counter=self.mode == "add")
        else:
            # RULE 608.2b: a target that is no longer a permanent or suspended card is illegal and does nothing.
            objects = [o for o in (targets or [])[:1] if o in context.state.permanents() or is_suspended(o)]
        for obj in objects:
            self._change(context, obj, amount)

    def _change(self, context: GameContext, obj: Any, amount: int) -> None:
        if self.mode == "add":
            context.add_counters(obj, amount, TIME_COUNTER)
            return
        # One counter at a time on a suspended card, so removing the last one fires Suspend's own last-counter
        # trigger (RULE 702.62a, `RulesEngine.remove_suspend_time_counter`); a permanent just loses the counters.
        if is_suspended(obj):
            for _ in range(min(amount, obj.counters.get(TIME_COUNTER, 0))):
                context.engine.remove_suspend_time_counter(obj)
        elif has_time_counter(obj):
            context.add_counters(obj, -min(amount, obj.counters[TIME_COUNTER]), TIME_COUNTER)
