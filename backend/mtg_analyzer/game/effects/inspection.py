"""Bounded inspection pools and their serializable step continuations (PAR-213)."""
from __future__ import annotations

from copy import deepcopy

from ...models.cards import card_query
from ...models.game.game_object import Zone
from ..continuations import choice, ANSWER_STR
from ..targeting import TargetSpec
from .core import GameEffect


def _objects(rules, visits):
    # RULE 400.7: a card which left and returned is no longer in this pool.
    return [obj for iid, incarnation in visits
            if (obj := rules.state.find_object(iid)) is not None and obj.zone_incarnation == incarnation]


def _visits(objects):
    return [[obj.instance_id, obj.zone_incarnation] for obj in objects]


class InspectCardsEffect(GameEffect):
    """An inspected set, followed by independently parsed selection/action steps."""
    def __init__(self, params, source=None):
        super().__init__(source)
        self.params = deepcopy(params)
        self.target_spec = TargetSpec(kind=params['target_kind']) if params.get('target_kind') else None

    def apply(self, context, targets=None):
        player = context.state.player_by_id(context.acting_player_id or context.resolving_controller_id
                                             or getattr(self.source, 'controller_id', None))
        if player is None:
            return
        if self.params['scope'] == 'target':
            owners = list(targets or [])[:1]
        elif self.params['scope'] == 'each_player':
            owners = context.state.living_players()
        else:
            owners = [player]
        objects = []
        for owner in owners:
            pool = owner.hand if self.params['zone'] == 'hand' else list(reversed(owner.library))[:self.params['count']]
            objects.extend(pool)
        visits = _visits(objects)
        frame = {'source_id': getattr(self.source, 'instance_id', None), 'controller': player.id,
                 'source_incarnation': (context.resolving_source_incarnation if context.resolving_source_incarnation is not None else getattr(self.source, 'zone_incarnation', None)),
                 'previous_selector': {'zone_visits': visits}, 'rest': visits, 'chosen': [],
                 'steps': deepcopy(self.params.get('steps', [])), 'position': 0,
                 'reveal': self.params.get('reveal', False), 'picked': [], 'owners': [p.id for p in owners]}
        context.previous_selector = frame['previous_selector']
        if len(objects) == 1 and self.params['zone'] == 'library' and self.params.get('reveal'):
            context.revealed_card = objects[0]
        # RULE 701.20: looking/revealing changes no zone or library order.
        # Acknowledgement also makes a stand-alone look observable to its player.
        if objects:
            _offer(context.engine, frame, objects, 'ack', player.id)
        else:
            _run(context.engine, frame)


def _offer(rules, frame, objects, mode, chooser, optional=False):
    options = [{'id': str(obj.instance_id), 'instance_id': obj.instance_id,
                'card_id': obj.card.id, 'label': obj.name} for obj in objects]
    if mode == 'ack':
        options.append({'id': 'done', 'label': 'Weiter'})
    elif optional:
        options.append({'id': 'decline', 'label': 'Auswahl abschließen'})
    shown = frame.get('public_visits', frame['previous_selector']['zone_visits'])
    public = frame['reveal'] or bool(frame.get('public_visits'))
    rules.open_choice({'kind': 'inspection', 'player_id': chooser, 'prompt': 'Karten ansehen' if mode == 'ack' else 'Wähle eine Karte',
                       'options': options, 'mode': mode, 'inspection': frame,
                       'hand_visibility': 'public' if public else 'private',
                       'visible_hand_visits': {str(i): v for i, v in shown}})


def _move(rules, frame, objects, destination):
    player = rules.state.player_by_id(frame['controller'])
    source = rules.state.find_object(frame['source_id'])
    if destination in ('battlefield', 'battlefield_tapped'):
        from .battlefield_batches import start_battlefield_batch
        start_battlefield_batch(rules, objects, player.id, tapped=destination.endswith('tapped'))
        return
    if destination == 'bottom_random':
        import random
        random.shuffle(objects)
    # Ordered piles are selected top/bottom first; insert order preserves that order.
    for obj in objects:
        owner = rules.state.player_by_id(obj.owner_id)
        if destination == 'discard':
            rules.discard_specific(obj, cause=source)
        elif destination == 'exile':
            rules.exile(obj)
        elif destination == 'graveyard':
            rules._remove_from_current_zone(owner, obj)
            rules._move_to_graveyard(obj)
        elif destination == 'hand':
            rules._remove_from_current_zone(owner, obj)
            owner.add_to_zone(obj, Zone.HAND)
        elif destination in ('top', 'bottom', 'bottom_random'):
            rules._remove_from_current_zone(owner, obj)
            obj.zone = Zone.LIBRARY
            if destination == 'top':
                owner.library.append(obj)
            else:
                owner.library.insert(0, obj)


def _run(rules, frame):
    # RULE 400.7 / 113.7a: the suspended ability retains its controller and
    # source visit even if its source leaves or changes control meanwhile.
    context = rules.context
    outer = context.resolving_controller_id, context.resolving_source_incarnation
    context.resolving_controller_id = frame['controller']
    context.resolving_source_incarnation = frame['source_incarnation']
    try:
        _run_steps(rules, frame)
    finally:
        context.resolving_controller_id, context.resolving_source_incarnation = outer


def _run_steps(rules, frame):
    from .core import _apply_effects_partitioned
    from .composition import _build

    while frame['position'] < len(frame['steps']):
        step = frame['steps'][frame['position']]
        op = step['op']
        if step.get('condition') and (bool(frame.get('last_chosen')) != (step['condition'] == 'chosen')):
            frame['position'] += 1
            continue
        if op == 'choose':
            pool = [o for o in _objects(rules, frame['rest']) if card_query.matches(o.card, step['criteria'])
                    and o.instance_id not in frame['picked']]
            count = len(pool) + len(frame['picked']) if step['count'] == 'all' else step['count']
            if step.get('random'):
                import random
                frame['picked'] = [o.instance_id for o in random.sample(pool, min(count, len(pool)))]
            elif step.get('all'):
                frame['picked'] = [o.instance_id for o in pool]
            elif pool and len(frame['picked']) < count:
                chooser = frame['controller']
                if step.get('chooser') == 'opponent':
                    opponents = [p for p in rules.state.living_players() if p.id != chooser]
                    if len(opponents) > 1 and not frame.get('chooser'):
                        rules.open_choice({'kind': 'inspection', 'player_id': chooser, 'mode': 'opponent',
                                           'prompt': 'Wähle einen Gegner', 'inspection': frame,
                                           'options': [{'id': p.id, 'label': p.name} for p in opponents]})
                        return
                    chooser = frame.get('chooser') or opponents[0].id if opponents else chooser
                _offer(rules, frame, pool, 'choose', chooser, step.get('optional', False))
                return
            picked = set(frame['picked'])
            frame['chosen'] = [v for v in frame['rest'] if v[0] in picked]
            frame['rest'] = [v for v in frame['rest'] if v[0] not in picked]
            frame['last_chosen'] = bool(frame['chosen'])
            frame['picked'] = []
            frame.pop('chooser', None)
        elif op == 'reveal':
            objects = _objects(rules, frame[step['pool']])
            frame['public_visits'] = _visits(objects)
            frame['position'] += 1
            if objects:
                _offer(rules, frame, objects, 'ack', frame['controller'])
                return
            continue
        elif op == 'move':
            visits = frame['previous_selector']['zone_visits'] if step['pool'] == 'all' else frame[step['pool']]
            objects = _objects(rules, visits)
            if step['destination'] in ('top', 'bottom') and len(objects) > 1:
                frame['ordering'] = []
                frame['order_visits'] = _visits(objects)
                _offer(rules, frame, objects, 'order', frame['controller'])
                return
            frame['position'] += 1
            source = rules.state.find_object(frame['source_id'])
            _apply_effects_partitioned(
                [InspectMoveEffect(deepcopy(frame), _visits(objects), step['destination']),
                 InspectContinuationEffect(deepcopy(frame))], rules.context,
                source=source, targets=None, target_groups=None,
                previous_selector=frame['previous_selector'])
            return
        elif op == 'shuffle':
            for pid in frame['owners'] if step['owners'] else [frame['controller']]:
                rules.shuffle_library(rules.state.player_by_id(pid))
        elif op in ('payoff', 'effects'):
            specs = step['effects']
            if op == 'payoff':
                count = sum(card_query.matches(o.card, step['criteria']) for o in _objects(rules, frame['previous_selector']['zone_visits']))
                specs = specs * count
            frame['position'] += 1
            # Reuse the normal suspended-effect stack, including nested payoff choices.
            remaining = InspectContinuationEffect(deepcopy(frame))
            source = rules.state.find_object(frame['source_id'])
            _apply_effects_partitioned(_build(specs, source) + [remaining], rules.context, source=source, targets=None, target_groups=None,
                                      previous_selector=frame['previous_selector'],
                                      revealed_card=next(iter(_objects(rules, frame['previous_selector']['zone_visits'])), None) if len(frame['previous_selector']['zone_visits']) == 1 else None)
            return
        frame['position'] += 1


class InspectMoveEffect(GameEffect):
    def __init__(self, frame, visits, destination):
        super().__init__()
        self.frame, self.visits, self.destination = frame, visits, destination

    def apply(self, context, targets=None):
        _move(context.engine, self.frame, _objects(context.engine, self.visits), self.destination)


class InspectContinuationEffect(GameEffect):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame

    def apply(self, context, targets=None):
        _run(context.engine, deepcopy(self.frame))


@choice('inspection', answer=ANSWER_STR, rule='701.20')
def _resume_inspection(rules, choice, answer):
    if answer not in {o['id'] for o in choice['options']} and not (answer is None and any(o['id'] == 'decline' for o in choice['options'])):
        rules.open_choice(choice)
        raise ValueError('Choose an offered inspection option')
    frame = choice['inspection']
    mode = choice['mode']
    if mode == 'opponent':
        frame['chooser'] = answer
    elif mode == 'choose':
        if answer is None or answer == 'decline':
            # Finish the selection without changing its optional minimum.
            frame['steps'][frame['position']]['count'] = len(frame['picked'])
        else:
            frame['picked'].append(int(answer))
    elif mode == 'order':
        frame['ordering'].append(int(answer))
        objects = [o for o in _objects(rules, frame['order_visits']) if o.instance_id not in frame['ordering']]
        if len(objects) > 1:
            _offer(rules, frame, objects, 'order', frame['controller'])
            return
        frame['ordering'].extend(o.instance_id for o in objects)
        ordered = {o.instance_id: o for o in _objects(rules, frame['order_visits'])}
        step = frame['steps'][frame['position']]
        picked = [ordered[i] for i in frame['ordering'] if i in ordered]
        # Last element of a library list is its top.
        _move(rules, frame, list(reversed(picked)) if step['destination'] == 'top' else picked, step['destination'])
        frame['position'] += 1
    _run(rules, frame)
