"""Prepare entry choices, then put a group of permanents onto the field together."""
from __future__ import annotations

from ...models.game.events import EventType, GameEvent
from .core import GameEffect, _controller_of, ChooseColorReplacement, _apply_effects_partitioned


def start_battlefield_batch(rules, objects, controller_id, *, tapped=False):
    frame = {'cards': [{'id': o.instance_id, 'from_zone': o.zone.value,
                        'controller_id': controller_id or o.owner_id,
                        'tapped': tapped} for o in objects],
             'cursor': 0, 'stage': 'reset'}
    advance_battlefield_batch(rules, frame)


def start_exile_return_batch(rules, visits, controller_id=None, *, entry_options=None,
                            after_effects=None, source=None):
    """RULE 603.7c/614.12: prepare exact exile visits, then admit them together.

    Entry choices and the successful-return continuation are state-owned so
    cloning/undo never depend on a Python callback from the original engine.
    """
    options = dict(entry_options or {})
    cards = []
    for instance_id, incarnation in visits:
        obj = rules.state.find_object(instance_id)
        if (obj is not None and not obj.is_token and obj.zone.value == 'exile'
                and obj.zone_incarnation == incarnation):
            cards.append({'id': instance_id, 'expected_incarnation': incarnation,
                          'from_zone': 'exile', 'controller_id': controller_id or obj.owner_id,
                          **options})
    frame = {'cards': cards, 'cursor': 0, 'stage': 'reset',
             'returned_visits': [], 'after_effects': list(after_effects or []),
             'source_id': getattr(source, 'instance_id', None),
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
    return (obj is not None
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
        effect = obj.enter_choice_effects[0]
        remaining = obj.enter_choice_effects[1:]
        if isinstance(effect, ChooseColorReplacement) and effect.count > 1:
            remaining = [ChooseColorReplacement(count=effect.count - 1), *remaining]
        rules._pending_enter_choice_obj = obj
        rules._pending_enter_choice_effect = effect
        rules._pending_enter_choice_continuation = lambda: setattr(obj, 'enter_choice_effects', remaining)
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
        context.resolving_controller_id = frame.get('effect_controller_id')
        try:
            _apply_effects_partitioned(frame['after_effects'], context, returned, None,
                source=state.find_object(frame.get('source_id')), previous_targets=returned)
        finally:
            context.resolving_controller_id = outer_controller


class BattlefieldBatchEffect(GameEffect):
    """Internal runtime step: immutable identities of revealed/selected cards."""
    def __init__(self, ids, controller_id, source=None):
        super().__init__(source)
        self.ids, self.controller_id = list(ids), controller_id

    def apply(self, context, targets=None):
        objects = [o for iid in self.ids if (o := context.state.find_object(iid)) is not None]
        start_battlefield_batch(context.engine, objects, self.controller_id)
