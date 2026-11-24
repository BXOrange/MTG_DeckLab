"""Allocate token copies, prepare their choices, then admit the whole group."""
from .core import EffectRegistry, GameEffect, _controller_of
from .battlefield_batches import start_token_batch
from ..targeting import TargetSpec


class CopyPlayerCreaturesEffect(GameEffect):
    def __init__(self, ability_line, source=None):
        super().__init__(source)
        self.ability_line = ability_line
        self.target_spec = TargetSpec(kind='player')

    def apply(self, context, targets=None):
        target = targets[0] if targets else None
        controller = _controller_of(self.source, context)
        if target is None or controller is None:
            return
        # RULE 608.2c/707.2: fix the original group before creating any copy.
        cards = [obj.card.as_copy(
                    add_keywords=['Haste'], add_ability_lines=[self.ability_line])
                 for obj in context.state.permanents_controlled_by(target.id) if obj.is_creature]
        start_token_batch(context, [(controller.id, card, 1) for card in cards], self.source, controller.id)


EffectRegistry.register('copy_player_creatures', lambda p: CopyPlayerCreaturesEffect(p['ability_line']))
