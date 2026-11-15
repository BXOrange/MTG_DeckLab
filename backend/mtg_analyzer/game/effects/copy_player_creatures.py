"""Allocate token copies, prepare their choices, then admit the whole group."""
from .core import EffectRegistry, GameEffect, _controller_of
from .battlefield_batches import start_battlefield_batch
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
        frame = {'cards': cards, 'cursor': 0, 'objects': [], 'events': [],
                 'controller_id': controller.id, 'created_sink': context.created_objects}
        context.state.pending_token_batch = frame
        self._next(context, frame)

    def _next(self, context, frame):
        if frame['cursor'] == len(frame['cards']):
            frame['created_sink'].extend(frame['objects'])
            start_battlefield_batch(context.engine, frame['objects'], frame['controller_id'],
                source=self.source, token_creation_events=frame['events'])
            return
        card = frame['cards'][frame['cursor']]
        frame['cursor'] += 1
        context.engine.create_token(frame['controller_id'], card, defer_entry=True, on_created={
            'effect': self, 'frame': frame, 'trigger_event': context.trigger_event,
            'source_incarnation': context.resolving_source_incarnation,
        })

    def _finish_creation(self, context, made, payload):
        self._next(context, payload['frame'])


EffectRegistry.register('copy_player_creatures', lambda p: CopyPlayerCreaturesEffect(p['ability_line']))
