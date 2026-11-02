"""Mill N, optionally take one card of a type from among them, otherwise do something else.

"Mill three cards. You may put a land card from among the cards milled this way into your hand. If you don't,
put a +1/+1 counter on this creature." (Blanchwood Prowler.) `compound_permanents.MillRecoverPermanentEffect`
covers the "permanent card, no else-branch" shape (Cache Grab); this is its typed-with-fallback sibling.
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import Zone
from .compound_permanents import _RecoverMilledPermanentEffect
from .core import EffectRegistry, GameEffect, _apply_effects_partitioned, _controller_of

#: `choose_objects` action that moves a graveyard card to its owner's hand (the "from among the milled cards" pick).
_RETURN_TO_HAND_ACTION = "return_from_graveyard_to_hand"


class _OfferMilledCardEffect(_RecoverMilledPermanentEffect):
    """The "you may put ... into your hand. If you don't, ..." half, run after the mill has resolved."""

    def __init__(self, history_start, card_type, else_effects, source=None):
        super().__init__(history_start, source, "hand")
        self.card_type = str(card_type).lower()
        self.else_effects = list(else_effects)

    def apply(self, context, targets=None):
        candidates = [
            obj for obj in self._milled(context)
            if obj is not None and obj.zone == Zone.GRAVEYARD and self.card_type in obj.type_words
        ]
        # RULE 608.2d: with nothing to take, "you don't" is true by default -- the else-branch runs
        # (`choose_objects` does the same for an empty pool, and for a declined optional pick).
        context.choose_objects(
            _controller_of(self.source, context), candidates, _RETURN_TO_HAND_ACTION, optional=True,
            source=self.source, else_specs=self.else_effects,
        )


class MillRecoverCardElseEffect(GameEffect):
    """Mill ``count`` cards, then offer one ``card_type`` card from that exact mill batch for the hand; if none
    is taken, run ``else_effects`` (serialized effect specs) instead."""

    def __init__(self, count: int = 3, card_type: str = "land",
                 else_effects: Optional[list[dict[str, Any]]] = None, source=None):
        super().__init__(source)
        self.count, self.card_type = count, card_type
        self.else_effects = list(else_effects or [])

    def apply(self, context, targets=None):
        from .core import MillEffect

        _apply_effects_partitioned([
            MillEffect(count=self.count, source=self.source),
            _OfferMilledCardEffect(len(context.state.event_log), self.card_type, self.else_effects, self.source),
        ], context, None, None, source=self.source)


EffectRegistry.register(
    "mill_recover_card_else",
    lambda p: MillRecoverCardElseEffect(p.get("count", 3), p.get("card_type", "land"), p.get("else_effects")),
)
