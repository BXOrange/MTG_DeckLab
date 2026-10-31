"""Prepare entry choices, then put a group of permanents onto the field together."""
from __future__ import annotations

from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from .core import GameEffect, _controller_of, ChooseColorReplacement, _apply_effects_partitioned


def start_battlefield_batch(rules, objects, controller_id, *, tapped=False):
    frame = {'cards': [{'id': o.instance_id, 'from_zone': o.zone.value,
                        'controller_id': controller_id or o.owner_id,
                        'tapped': tapped} for o in objects],
             'cursor': 0, 'stage': 'reset'}
    advance_battlefield_batch(rules, frame)


def start_exile_return_batch(rules, visits, controller_id=None, *, entry_options=None,
                            after_effects=None, source=None, source_incarnation=None, source_return_visit=None):
    return start_zone_return_batch(rules, visits, 'exile', controller_id,
        entry_options=entry_options, after_effects=after_effects, source=source,
        source_incarnation=source_incarnation, source_return_visit=source_return_visit)


def start_zone_return_batch(rules, visits, zone, controller_id=None, *, entry_options=None,
                            after_effects=None, source=None, source_incarnation=None, source_return_visit=None):
    """RULE 603.7c/614.12: prepare exact zone visits, then admit them together.

    Entry choices and the successful-return continuation are state-owned so
    cloning/undo never depend on a Python callback from the original engine.
    """
    if zone not in {'exile', 'graveyard'}:
        raise ValueError('Unsupported return zone')
    options = dict(entry_options or {})
    cards = []
    for instance_id, incarnation in visits:
        obj = rules.state.find_object(instance_id)
        if (obj is not None and not obj.is_token and obj.zone.value == zone
                and obj.zone_incarnation == incarnation):
            cards.append({'id': instance_id, 'expected_incarnation': incarnation,
                          'from_zone': zone, 'controller_id': controller_id or obj.owner_id,
                          **options})
    frame = {'cards': cards, 'cursor': 0, 'stage': 'reset',
             'returned_visits': [], 'after_effects': list(after_effects or []),
             'source_id': getattr(source, 'instance_id', None),
             'source_return_visit': source_return_visit,
             'source_incarnation': (source_incarnation if source_incarnation is not None
                 else rules.context.resolving_source_incarnation
                 if rules.context.resolving_source_incarnation is not None
                 else getattr(source, 'zone_incarnation', None)),
             'effect_controller_id': _controller_of(source, rules.context).id}
    advance_battlefield_batch(rules, frame)
    return frame


def cancel_conceded_return_entry(rules, player_id, ending_game=False):
    """RULE 800.4a/b/g: cancel owned resolutions, skip departed entrants,
    and give a surviving resolution's required choice to its controller.
    """
    choice = rules.state.pending_choice
    frame = choice.get('battlefield_batch') if choice else None
    if frame is None or (choice.get('player_id') != player_id and
                         frame.get('effect_controller_id') != player_id and not ending_game):
        return
    controller = frame.get('effect_controller_id')
    if ending_game or controller == player_id:
        rules.state.pending_choice = None
        rules.state.deferred_effects = [tail for tail in rules.state.deferred_effects
            if not ending_game and getattr(tail.get('source'), 'controller_id', None) != player_id]
        return
    obj, record = _current(rules, frame)
    if record['controller_id'] != player_id and (obj is None or obj.owner_id != player_id):
        # The object still enters under a living player's control; the
        # resolving ability's controller makes the departed chooser's pick.
        choice['player_id'] = controller
        return
    rules.state.pending_choice = None
    old_cursor = frame['cursor']
    keep = []
    kept_before = 0
    for index, card in enumerate(frame['cards']):
        current = rules.state.find_object(card['id'])
        if card['controller_id'] == player_id or (current is not None and current.owner_id == player_id):
            continue
        keep.append(card)
        kept_before += index < old_cursor
    frame['cards'], frame['cursor'], frame['stage'] = keep, kept_before, 'reset'
    advance_battlefield_batch(rules, frame)


def _prune_departed_entry_choices(rules):
    choice = rules.state.pending_choice
    if choice is None:
        return
    options = []
    for option in choice.get('options', []):
        instance_id = option.get('instance_id')
        if instance_id is None and str(option.get('id', '')).isdigit():
            instance_id = int(option['id'])
        candidate = rules.state.find_object(instance_id) if instance_id is not None else None
        if candidate is not None and rules.state.player_by_id(candidate.owner_id).has_lost:
            continue
        options.append(option)
    choice['options'] = options


def _valid_record(obj, record, state=None):
    if state is not None and record.get('attach_to'):
        host_id, host_incarnation = record['attach_to']
        host = state.find_object(host_id)
        if host is None or host.zone.value != 'battlefield' or host.zone_incarnation != host_incarnation:
            return False
    return (obj is not None and not record.get('entry_failed')
            and (state is None or (not state.player_by_id(obj.owner_id).has_lost
                                  and not state.player_by_id(record['controller_id']).has_lost))
            and (record.get('expected_incarnation') is None
            or (obj.zone.value == record['from_zone']
                and obj.zone_incarnation == record['expected_incarnation'] and not obj.is_token)))


def _current(rules, frame):
    record = frame['cards'][frame['cursor']]
    return rules.state.find_object(record['id']), record


def restore_batch_runtime(rules, choice):
    """Rebuild the current entry chooser from identities after a state restore.

    Ordinary entry handlers still apply their existing semantics. The batch
    never depends on a Python closure surviving a session rewind.
    """
    frame = choice['battlefield_batch']
    obj, record = _current(rules, frame)
    if not _valid_record(obj, record, rules.state):
        return False
    kind = choice['kind']
    if kind == 'enter_as_copy':
        rules._pending_enter_as_copy_obj = obj
        rules._pending_enter_as_copy_effect = obj.enter_as_copy_effects[0]
        rules._pending_enter_as_copy_continuation = lambda: None
        frame['stage'] = 'protector'
    elif frame['stage'] == 'choose':
        # The batch re-offers the remaining queue itself: the entry choice only drops the answered effect.
        rules.state.pending_enter_choice = {'obj': obj, 'incarnation': obj.zone_incarnation, 'batch': True}
    elif kind == 'choose_protector':
        rules._pending_protector_obj = obj
        rules._pending_protector_continuation = lambda: None
        frame['stage'] = 'choose'
    elif kind == 'read_ahead':
        rules._pending_read_ahead_obj = obj
        rules._pending_read_ahead_continuation = lambda: None
        frame['stage'] = 'read_answered'
    return True


def resume_battlefield_batch(rules, choice):
    frame = choice['battlefield_batch']
    if rules.state.pending_choice:
        rules.state.pending_choice.setdefault('battlefield_batch', frame)
        return
    if frame['stage'] == 'read_answered':
        frame['cards'][frame['cursor']]['lore'] = rules._pending_read_ahead_count
        rules._pending_read_ahead_count = None
        frame['stage'] = 'tap'
    if frame['stage'] == 'tap_wait':
        frame['stage'] = 'ready'
    advance_battlefield_batch(rules, frame)


def advance_battlefield_batch(rules, frame):
    while frame['cursor'] < len(frame['cards']):
        obj, record = _current(rules, frame)
        if not _valid_record(obj, record, rules.state):
            frame['cursor'] += 1
            frame['stage'] = 'reset'
            continue
        stage = frame['stage']
        if stage == 'reset':
            obj.reset_as_new_object()
            obj.controller_id = record['controller_id']
            if record.get('transformed'):
                if obj.card.back_face() is None:
                    # RULE 712.14a: a single-faced physical card cannot
                    # enter transformed, even if its previous copy could.
                    record['entry_failed'] = True
                    frame['cursor'] += 1
                    frame['stage'] = 'reset'
                    continue
                rules.transform_permanent(obj)
            if record.get('face_down_kind'):
                rules.turn_face_down(obj, record['face_down_kind'])
            if record.get('attach_to'):
                host_id, host_incarnation = record['attach_to']
                host = rules.state.find_object(host_id)
                if host is None or host.zone.value != 'battlefield' or host.zone_incarnation != host_incarnation:
                    frame['cursor'] += 1
                    frame['stage'] = 'reset'
                    continue
                obj.attached_to = host_id
            frame['stage'] = 'copy'
        elif stage == 'copy':
            if obj.enter_as_copy_effects:
                rules._offer_enter_as_copy(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'protector'
        elif stage == 'protector':
            rules._offer_protector_choice(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'choose'
        elif stage == 'choose':
            rules._offer_enter_choices(obj, lambda: None)
            if not rules.state.pending_choice:
                if obj.entry_abandoned:
                    # RULE 614.12: the entry was replaced (Mox Diamond declined) -- the object never
                    # enters, so no ENTERS_BATTLEFIELD; it goes to its owner's graveyard from where it is.
                    obj.entry_abandoned = False
                    record['entry_failed'] = True
                    if obj.zone.value != 'graveyard':
                        owner = rules.state.player_by_id(obj.owner_id)
                        rules._remove_from_current_zone(owner, obj)
                        owner.add_to_zone(obj, Zone.GRAVEYARD)
                    frame['cursor'] += 1
                    frame['stage'] = 'reset'
                    continue
                frame['stage'] = 'read'
        elif stage == 'read':
            rules._offer_read_ahead(obj, lambda: None)
            if not rules.state.pending_choice:
                frame['stage'] = 'tap'
        elif stage == 'tap':
            if record.get('tapped') or record.get('attacking') or (record.get('tapped_if_types') and
                                       any(t in obj.type_words for t in record['tapped_if_types'])):
                obj.tapped = True
            else:
                rules.enter_land_tapped(obj)
            frame['stage'] = 'tap_wait' if rules.state.pending_choice else 'ready'
        elif stage == 'ready':
            frame['cursor'] += 1
            frame['stage'] = 'reset'
        if rules.state.pending_choice:
            _prune_departed_entry_choices(rules)
            rules.state.pending_choice['battlefield_batch'] = frame
            return
    _commit_battlefield_batch(rules, frame)


def _commit_battlefield_batch(rules, frame):
    from .. import continuous
    state = rules.state
    entrants = [(state.find_object(r['id']), r) for r in frame['cards']]
    entrants = [(obj, r) for obj, r in entrants if _valid_record(obj, r, state)]
    # RULE 614.12: prepare all entry replacements before any entrant is a
    # battlefield source for the other entrants' replacement effects.
    for obj, record in entrants:
        amounts = dict(record.get('entry_counters') or {})
        if 'kind' in amounts:
            amounts = {str(amounts['kind']): amounts.get('count', 1)}
        for counter in record.get('typed_entry_counters') or []:
            if all(t in obj.type_words for t in counter.get('types', [])):
                kind = counter.get('kind', '+1/+1')
                amounts[kind] = amounts.get(kind, 0) + int(counter.get('count', 1))
        obj.entry_bonus_counters.update({str(k): max(0, int(v)) for k, v in amounts.items()})
        rules._apply_entry_counters(obj)
        obj.summoning_sick = True
    outer_events = getattr(state, '_deferred_entry_events', None)
    buffered = outer_events if outer_events is not None else []
    state._deferred_entry_events = buffered
    try:
        with state.simultaneous():
            for obj, record in entrants:
                rules._remove_from_current_zone(state.player_by_id(obj.owner_id), obj)
                state.add_to_battlefield(obj, saga_lore_override=record.get('lore'))
                frame.setdefault('returned_visits', []).append((obj.instance_id, obj.zone_incarnation))
                if (frame.get('source_return_visit') is not None
                        and frame['source_return_visit'] == (obj.instance_id, record['expected_incarnation'])):
                    frame['returned_source_visit'] = (obj.instance_id, obj.zone_incarnation)
                if record['from_zone'] == 'graveyard':
                    rules.context.created_objects.append(obj)
                if record.get('attacking'):
                    rules.put_onto_battlefield_attacking(obj)
                state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
                    from_zone=record['from_zone'], controller_id=obj.controller_id,
                    object=obj.name, instance_id=obj.instance_id, object_types=sorted(obj.type_words)))
            continuous.recompute(state)
            state._deferred_entry_events = outer_events
            if outer_events is None:
                for event in buffered:
                    if event.type == EventType.ENTERS_BATTLEFIELD:
                        obj = state.find_object(event.get('instance_id'))
                        event.data['object_types'] = sorted(obj.type_words)
                    state.fire_event(event)
    finally:
        state._deferred_entry_events = outer_events
    if frame.get('after_effects'):
        returned = [obj for iid, inc in frame['returned_visits']
                    if (obj := state.find_object(iid)) is not None
                    and obj.zone.value == 'battlefield' and obj.zone_incarnation == inc]
        context = rules.context
        outer_controller = context.resolving_controller_id
        outer_source_incarnation = context.resolving_source_incarnation
        source = state.find_object(frame.get('source_id'))
        # RULE 400.7j: only this operation's exact successful source return
        # lets its continuation find the new object. Other source captures
        # keep their original visit, including across entry choices/clone.
        context.resolving_source_incarnation = (source.zone_incarnation
            if source is not None and source in returned
            and frame.get("returned_source_visit") == (source.instance_id, source.zone_incarnation)
            else frame.get('source_incarnation'))
        context.resolving_controller_id = frame.get('effect_controller_id')
        try:
            _apply_effects_partitioned(frame['after_effects'], context, returned, None,
                source=state.find_object(frame.get('source_id')), previous_targets=returned)
        finally:
            context.resolving_controller_id = outer_controller
            context.resolving_source_incarnation = outer_source_incarnation


class BattlefieldBatchEffect(GameEffect):
    """Internal runtime step: immutable identities of revealed/selected cards."""
    def __init__(self, ids, controller_id, source=None):
        super().__init__(source)
        self.ids, self.controller_id = list(ids), controller_id

    def apply(self, context, targets=None):
        objects = [o for iid in self.ids if (o := context.state.find_object(iid)) is not None]
        start_battlefield_batch(context.engine, objects, self.controller_id)
