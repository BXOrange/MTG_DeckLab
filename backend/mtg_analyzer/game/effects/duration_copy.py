"""RULE 707.2 / 611.2: copies over the shared continuous-effect clock."""
from types import SimpleNamespace
from .core import GameEffect, EffectRegistry, _controller_of
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class DurationCopyEffect(GameEffect):
    def __init__(self, recipient='source', template='target', duration='end_of_turn', condition=None,
                 target_kind='creature', creature_filter=None, optional=False, recipient_visits=None,
                 source_visit=None, keep_own_abilities=False, add_keywords=None,
                 add_ability_lines=None, source=None):
        super().__init__(source)
        self.recipient, self.template = recipient, template
        self.duration, self.condition = duration, condition
        self.optional, self.recipient_visits, self.source_visit = optional, recipient_visits, source_visit
        # RULE 707.9a: the copy's "except …" clause — "it has this ability", granted keywords and quoted abilities.
        self.keep_own_abilities = bool(keep_own_abilities)
        self.add_keywords, self.add_ability_lines = list(add_keywords or []), list(add_ability_lines or [])
        self.target_spec = TargetSpec(kind=target_kind, creature_filter=creature_filter) if template == 'target' else None

    def apply(self, context, targets=None):
        from .. import durations
        from ..copy_mechanics import (become_copy, keep_as_copiable, resolving_ability, restore_own_abilities,
                                  this_ability_only)
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
                    'keep_own_abilities': self.keep_own_abilities, 'add_keywords': self.add_keywords,
                    'add_ability_lines': self.add_ability_lines,
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
            if templates[0] is obj:
                continue  # "another target permanent": a permanent never becomes a copy of itself
            ability_key = getattr(context.resolving_stack_item, 'ability_key', None)
            own = (this_ability_only(obj, resolving_ability(context.resolving_stack_item), ability_key)
                   if self.keep_own_abilities else None)
            added_lines = list(self.add_ability_lines)
            if own is not None:
                # RULE 707.9a: "it has this ability" joins the copy's copiable values (so a Clone of it has it too).
                kept_lines, own = keep_as_copiable(obj, own)
                added_lines.extend(line for line in kept_lines if line not in added_lines)
            become_copy(obj, templates[0], duration=self.duration, add_keywords=self.add_keywords or None,
                        add_ability_lines=added_lines or None)
            if own is not None:
                restore_own_abilities(obj, own)  # whatever cannot be re-bound from its printed line
            obj._duration_copy_layers[-1].update(duration=clock.duration, duration_data=clock.duration_data,
                source_id=getattr(source, 'instance_id', None), object_ids=clock.object_ids)
        context.recompute()


EffectRegistry.register('copy_for_duration', lambda p: DurationCopyEffect(**{
    k: p[k] for k in ('recipient', 'template', 'duration', 'condition', 'target_kind', 'creature_filter',
                     'optional', 'recipient_visits', 'source_visit', 'keep_own_abilities', 'add_keywords',
                     'add_ability_lines') if k in p}))
