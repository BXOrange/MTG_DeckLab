"""Counters on creatures a delayed trigger captured when it was created ("put two +1/+1 counters on it at the beginning
of the next end step" -- Foe-Razer Regent).

`CreateDelayedTriggerEffect` bakes the objects a resolution named into the delayed body's ``objects`` list (RULE
603.7c: the object is fixed when the delayed ability is created) and the zone stay it saw into ``incarnations``
(RULE 400.7: a creature that left and came back is a new object and is no longer named). `add_counters` has neither
attribute, so this is its captured-object sibling."""

from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import GameObject
from .core import GameContext, GameEffect


class AddCountersToCapturedEffect(GameEffect):
    """Put ``amount`` counters of ``kind`` on each captured object still on the battlefield as the same object
    (RULE 122.1)."""

    def __init__(self, amount: int = 1, kind: str = "+1/+1", source: Optional[GameObject] = None) -> None:
        super().__init__(source)
        self.amount = amount
        self.kind = kind
        #: Filled by `CreateDelayedTriggerEffect` at creation (see module docstring); empty until then.
        self.objects: list[GameObject] = []
        self.incarnations: Optional[dict[int, int]] = None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for obj in list(self.objects):
            if obj not in context.state.battlefield:
                continue
            if self.incarnations is not None and self.incarnations.get(obj.instance_id) != obj.zone_incarnation:
                continue
            context.add_counters(obj, self.amount, self.kind, source=self.source)
        context.recompute()


EFFECT_FACTORIES = {
    "add_counters_to_captured": lambda p: AddCountersToCapturedEffect(
        amount=int(p.get("amount", 1)), kind=str(p.get("kind", "+1/+1")),
    ),
}
