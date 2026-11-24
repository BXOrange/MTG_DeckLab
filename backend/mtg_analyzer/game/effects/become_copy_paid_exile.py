"""Become the copiable creature captured by this activation's exile payment."""
from types import SimpleNamespace

from .core import EffectRegistry, GameEffect
from ...models.cards.card import Card
from ...models.game.game_object import Zone


class BecomeCopyPaidExileEffect(GameEffect):
    def __init__(self, ability_line, source=None):
        super().__init__(source)
        self.ability_line = ability_line

    def apply(self, context, targets=None):
        source = self.source
        visit = context.resolving_source_incarnation
        if source is None or source.zone != Zone.BATTLEFIELD or (
                visit is not None and source.zone_incarnation != visit):
            return
        cards = (context.trigger_event or {}).get('cost_exiled_cards') or []
        if not cards:
            return
        # RULE 400.7j / 707.2: this payment's copiable values, not the source's latest payment.
        template = Card.from_dict(cards[0])
        context.become_copy(source, SimpleNamespace(card=template, _front_card=template),
                            add_ability_lines=[self.ability_line])


EffectRegistry.register('become_copy_paid_exile', lambda p: BecomeCopyPaidExileEffect(p['ability_line']))
