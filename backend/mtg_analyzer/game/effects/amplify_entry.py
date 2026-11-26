"""Amplify reveals happen as the creature enters (RULE 702.38a)."""
from __future__ import annotations

from .core import EffectRegistry, GameEffect, _controller_of
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone


class AmplifyEntryEffect(GameEffect):
    """RULE 702.38a Amplify N: "As this object enters, reveal any number of cards from your hand that share a creature
    type with it. This permanent enters with N +1/+1 counters on it for each card revealed this way." The first pass
    asks for the whole set, the second (``visits`` bound by the chooser) reveals it and stamps the counters the entry
    collects (`GameObject.entry_bonus_counters`). RULE 702.38b: each instance works separately, so the keyword's own
    ``instances`` multiply the counters per revealed card."""

    is_enter_effect = True

    def __init__(self, amount: int, visits=None, source=None):
        super().__init__(source)
        self.amount = max(0, int(amount))
        self.visits = visits

    def apply(self, context, targets=None):
        from ..continuous import derived_subtype_words

        source = self.source
        if source is None:
            return
        player = _controller_of(source, context)
        shared = derived_subtype_words(source)
        # The entering object itself never counts (RULE 702.38a: "you can't reveal this card").
        pool = [card for card in player.hand if card is not source and card.card.is_creature
                and shared & derived_subtype_words(card)]
        if self.visits is None:
            if not pool:
                return
            context.engine._request_choose_objects(
                player, pool, "select_referent", count=len(pool), optional=True, source=source,
                prompt="Wähle Karten aus deiner Hand, die du für Amplify aufdeckst",
                then_specs=[{"type": "amplify_entry", "params": {
                    "amount": self.amount, "visits": {"kind": "chosen_object_visits"},
                }}],
            )
            return
        eligible = {card.instance_id: card for card in pool}
        revealed = [card for iid, visit in self.visits
                    if (card := eligible.get(iid)) is not None and card.zone == Zone.HAND
                    and card.zone_incarnation == visit]
        for card in revealed:
            context.state.fire_event(GameEvent(
                EventType.REVEAL, player_id=player.id, object=card.name, instance_id=card.instance_id,
                from_zone=Zone.HAND.value,
            ))
        if revealed:
            counters = source.entry_bonus_counters
            counters["+1/+1"] = counters.get("+1/+1", 0) + self.amount * len(revealed)


EffectRegistry.register("amplify_entry", lambda p: AmplifyEntryEffect(p.get("amount", 1), p.get("visits")))
