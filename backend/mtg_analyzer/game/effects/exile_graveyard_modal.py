"""Exile a card from a graveyard, then a reflexive "choose one" whose modes are scaled by that card's mana value.

"Exile another card from a graveyard. When you do, choose one -- Remove X counters from target permanent, where X is
the mana value of the exiled card. / Target creature an opponent controls gets -X/-X until end of turn, where X is the
mana value of the exiled card." (Cemetery Desecrator.) The exile is a `choose_objects` pick (mandatory when any
card qualifies); the "when you do" is a RULE 603.12 reflexive trigger that is built *after* the exile, so X is already
known and can be baked into the modes as a literal -- a `pending_choice` never has to carry a closure.
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import GameObject, Zone
from ..targeting import TargetSpec
from .core import EffectRegistry, GameEffect

#: `choose_objects` action that exiles the pick (RULE 701.13a).
_EXILE_ACTION = "exile"
#: Both modes of the reflexive ability; the choice is made when it is put on the stack (RULE 603.3c / 700.2b).
_MODE_COUNT = 1
_REMOVE_COUNTERS_LABEL = "{x} Marker von bleibender Karte entfernen"
_SHRINK_LABEL = "Kreatur eines Gegners erhält -{x}/-{x}"


class RemoveExactCountersEffect(GameEffect):
    """RULE 122.1 / 701: remove exactly ``amount`` counters from the target permanent (as many as it has if fewer),
    one at a time, choosing the kind whenever the permanent carries several (`_continue_remove_counters`).

    Unlike `RemoveCountersEffect(max_count=)` ("up to N"), the amount is not optional: "remove X counters" means X."""

    def __init__(self, amount: int = 0, target_kind: str = "permanent", source: Optional[GameObject] = None):
        super().__init__(source)
        self.amount = max(0, int(amount))
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context, targets=None):
        target = (targets[0] if targets else None) or self.target
        if target is None or self.amount <= 0:
            return
        context.engine._continue_remove_counters(target, self.amount)


class ExileGraveyardCardThenModalEffect(GameEffect):
    """Exile another card from a graveyard, then queue the reflexive modal ability scaled by its mana value."""

    def apply(self, context, targets=None):
        candidates = [
            obj
            for player in context.state.players
            for obj in player.graveyard
            if obj is not self.source and obj.zone == Zone.GRAVEYARD  # "another card" (RULE 109.5)
        ]
        if not candidates:
            return  # nothing to exile: the instruction is impossible, so "when you do" never happens (RULE 603.12)
        context.choose_objects(
            self._chooser(context), candidates, _EXILE_ACTION, count=1, source=self.source,
            then_specs=[{"type": "graveyard_exile_modal_payoff", "params": {}}],
        )

    def _chooser(self, context):
        from .core import _controller_of

        return _controller_of(self.source, context)


class GraveyardExileModalPayoffEffect(GameEffect):
    """The "when you do" half: runs right after the exile, with the exiled card as the previous target."""

    def apply(self, context, targets=None):
        exiled = next((o for o in context.previous_targets if o is not None), None)
        if exiled is None:
            return
        x = int(getattr(exiled, "mana_value", 0) or 0)  # RULE 202.3 (an exiled card keeps its printed mana value)
        modes: dict[str, Any] = {
            "choose": _MODE_COUNT,
            "options": [
                [{"type": "remove_exact_counters", "params": {"amount": x, "target_kind": "permanent"}}],
                [{"type": "pump", "params": {
                    "power": -x, "toughness": -x, "target_kind": "creature_you_dont_control"}}],
            ],
            "descriptions": [_REMOVE_COUNTERS_LABEL.format(x=x), _SHRINK_LABEL.format(x=x)],
        }
        context.engine.enqueue_reflexive_trigger([], self.source, context.trigger_event, modes)


EffectRegistry.register("remove_exact_counters", lambda p: RemoveExactCountersEffect(p.get("amount", 0), p.get("target_kind", "permanent")))
EffectRegistry.register("exile_graveyard_card_then_modal", lambda p: ExileGraveyardCardThenModalEffect())
EffectRegistry.register("graveyard_exile_modal_payoff", lambda p: GraveyardExileModalPayoffEffect())
