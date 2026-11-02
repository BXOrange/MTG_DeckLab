"""Counters for "for each other <subtype> that entered the battlefield under your control this turn" (Geralf, the
Fleshwright, Commander Cube singleton batch).

The count is read from the turn's logged ENTERS_BATTLEFIELD events, through the same trigger-shaped matcher the
ENG-47 "this turn" conditions use (`static_conditions._events_this_turn_matching`). That keeps one definition of
"entered under your control" for both the trigger and the count.
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.events import EventType
from .core import EffectRegistry, GameContext, GameEffect, _controller_of


class CountersPerOtherEnteredThisTurnEffect(GameEffect):
    """RULE 122.1 / 603.2: put a +1/+1 counter on the entering object once for each *other* object of ``subtype``
    that entered the battlefield under this ability's controller's control this turn. The entering object is itself
    one logged event, so it is subtracted; a count of zero places no counter (RULE 122.1 places nothing for zero).
    """

    def __init__(self, subtype: str, source: Optional[Any] = None) -> None:
        super().__init__(source)
        self.subtype = str(subtype).lower()

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..static_conditions import _events_this_turn_matching  # function-scoped: static_conditions imports effects

        controller = _controller_of(self.source, context)
        event = context.trigger_event
        if controller is None or event is None:
            return
        entering = context.state.find_object(event.get("instance_id"))
        if entering is None:
            return
        trigger = {"event": EventType.ENTERS_BATTLEFIELD,
                   "condition": {"subject": "group", "controller": "you", "filter": {"subtype": self.subtype}}}
        entered = _events_this_turn_matching(context.state, trigger, self.source, controller.id)
        # "other": the entering object's own ENTERS event is in the log, so it does not count toward "other".
        others = max(entered - 1, 0)
        if others:
            context.add_counters(entering, others, "+1/+1", source=self.source)


EffectRegistry.register(
    "counters_per_other_entered_this_turn",  # Geralf, the Fleshwright
    lambda p: CountersPerOtherEnteredThisTurnEffect(subtype=p.get("subtype", "zombie")),
)
