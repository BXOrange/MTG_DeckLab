"""RULE 707.2 / 611.2: copies over the shared continuous-effect clock."""
from types import SimpleNamespace
from .core import GameEffect, EffectRegistry, _controller_of
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class DurationCopyEffect(GameEffect):
    def __init__(self, recipient='source', template='target', duration='end_of_turn', condition=None,
                 target_kind='creature', creature_filter=None, optional=False, recipient_visits=None,
                 source_visit=None, source=None):
        super().__init__(source)
        self.recipient, self.template = recipient, template
        self.duration, self.condition = duration, condition
        self.optional, self.recipient_visits, self.source_visit = optional, recipient_visits, source_visit
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter) if template == 'target' else None

    def apply(self, context, targets=None):
        from .. import durations
        from ..copy_mechanics import become_copy
        source = self.source
        if self.recipient_visits is not None:
            recipients = [obj for iid, visit in self.recipient_visits
                if (obj := context.state.find_object(iid)) is not None
                and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == visit]
        elif self.recipient == 'source':
            visit = context.resolving_source_incarnation
            recipients = [source] if source and source.zone == Zone.BATTLEFIELD and (
                visit is None or source.zone_incarnation == visit) else []
        elif self.recipient == 'attached':
            # Attachment triggers identify the original host, not whichever
            # host the Equipment moved to while its trigger waited.
            event = context.trigger_event or {}
            iid = event.get('attached_to', event.get('target_id'))
            obj = context.state.find_object(iid) if iid is not None else None
            recipients = [obj] if obj is not None and obj.zone == Zone.BATTLEFIELD and (
                event.get('target_incarnation') is None or obj.zone_incarnation == event['target_incarnation']) else []
        else:
            recipients = [o for o in context.previous_targets if getattr(o, 'zone', None) == Zone.BATTLEFIELD]
        if not recipients:
            return
        if self.template == 'linked':
            from ..linked_exile import linked_cards
            templates = [o for o in linked_cards(context.state, source, context.resolving_source_incarnation)
                         if o.card.is_creature]
        elif self.template == 'previous':
            templates = list(context.previous_targets)
        else:
            templates = list(targets or [])
        if not templates:
            return
        if self.optional or len(templates) > 1:
            condition = self.condition
            if condition and condition.get('kind') == 'source_attached_to_affected':
                condition = {**condition, 'attachment_generation': condition.get('attachment_generation',
                    (context.trigger_event or {}).get('attachment_generation', getattr(source, 'attachment_generation', None)))}
            player = _controller_of(source, context)
            if player is None:
                return
            context.engine._request_choose_objects(player, templates, 'select_referent', count=1,
                optional=self.optional, source=source, then_specs=[{'type': 'copy_for_duration', 'params': {
                    'template': 'previous', 'duration': self.duration, 'condition': condition,
                    'recipient_visits': [[o.instance_id, o.zone_incarnation] for o in recipients],
                    'source_visit': context.resolving_source_incarnation if context.resolving_source_incarnation is not None
                                    else getattr(source, 'zone_incarnation', None),
                }}])
            return
        for obj in recipients:
            condition_subject = (templates[0] if self.recipient == 'source' and self.condition
                                 and self.condition.get('of') == 'affected' else obj)
            clock = durations.stamp(SimpleNamespace(), context, source, self.duration, self.condition, condition_subject)
            if self.source_visit is not None and 'source_incarnation' in clock.duration_data:
                clock.duration_data['source_incarnation'] = self.source_visit
            if durations.is_expired(clock, context.state, 'recompute'):
                continue
            become_copy(obj, templates[0], duration=self.duration)
            obj._duration_copy_layers[-1].update(duration=clock.duration, duration_data=clock.duration_data,
                source_id=getattr(source, 'instance_id', None), object_ids=clock.object_ids)
        context.recompute()


EffectRegistry.register('copy_for_duration', lambda p: DurationCopyEffect(**{
    k: p[k] for k in ('recipient', 'template', 'duration', 'condition', 'target_kind', 'creature_filter',
                     'optional', 'recipient_visits', 'source_visit') if k in p}))
