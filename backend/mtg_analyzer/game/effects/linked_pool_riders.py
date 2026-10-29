"""Single-card linked returns over the shared payment, selection and entry frames."""
from .core import GameEffect, _controller_of
from .battlefield_batches import start_exile_return_batch
from .choices_actions import PayCostThenEffect
from ...models.game.game_object import Zone


class LinkedPoolReturnOneEffect(GameEffect):
    def __init__(self, stage='pay', source_visit=None, visits=None, player_id=None, source=None, cost=None):
        super().__init__(source)
        self.stage, self.source_visit = stage, source_visit
        self.visits, self.player_id = list(visits or []), player_id
        self.cost = cost

    def apply(self, context, targets=None):
        if self.source is None:
            return
        if self.stage == 'pay':
            player = _controller_of(self.source, context)
            incarnation = context.resolving_source_incarnation
            key = (self.source.instance_id, self.source.zone_incarnation if incarnation is None else incarnation)
            PayCostThenEffect(cost=self.cost or '', effects=[{
                'type': 'linked_pool_return_one', 'params': {
                    'stage': 'choose', 'source_visit': list(key), 'player_id': player.id,
                }}], source=self.source).apply(context)
            return
        key = tuple(self.source_visit)
        visits = context.state.linked_exile_visits.get(key, [])
        if self.stage == 'choose':
            candidates = [obj for iid, incarnation in visits
                if (obj := context.state.find_object(iid)) is not None
                and obj.zone == Zone.EXILE and obj.zone_incarnation == incarnation and not obj.is_token]
            context.choose_objects(context.state.player_by_id(self.player_id), candidates,
                'select_only', count=1, source=self.source,
                then_specs=[{'type': 'linked_pool_return_one', 'params': {
                    'stage': 'return', 'source_visit': list(key), 'visits': list(visits),
                    'player_id': self.player_id}}])
            return
        # RULE 607.2a / 400.7: selection cannot pick a later exile visit.
        picked = {o.instance_id for o in context.previous_targets}
        chosen = [v for v in self.visits if v[0] in picked]
        context.state.linked_exile_visits[key] = [v for v in visits if v not in chosen]
        start_exile_return_batch(context.engine, chosen, controller_id=self.player_id, source=self.source)


class ReturnExileCounterPoolEffect(GameEffect):
    def __init__(self, counter, source=None):
        super().__init__(source)
        self.counter = counter

    def apply(self, context, targets=None):
        # This is a global counter-marked pool, not a RULE 607 source link.
        visits = [(obj.instance_id, obj.zone_incarnation)
                  for player in context.state.players for obj in player.exile
                  if obj.counters.get(self.counter, 0) > 0 and not obj.is_token]
        start_exile_return_batch(context.engine, visits, source=self.source)


EFFECT_FACTORIES = {
    'linked_pool_return_one': lambda p: LinkedPoolReturnOneEffect(
        p.get('stage', 'pay'), p.get('source_visit'), p.get('visits'), p.get('player_id'), cost=p.get('cost')),
    'return_exile_counter_pool': lambda p: ReturnExileCounterPoolEffect(str(p.get('counter', ''))),
}


class LinkedExileMoveEffect(GameEffect):
    """An untargeted linked-card operand, with serializable exact-visit choices."""
    def __init__(self, destination='hand', card_filter=None, all_cards=False,
                 under_your_control=False, tapped=False, visits=None, source=None):
        super().__init__(source)
        self.destination, self.card_filter = destination, card_filter
        self.all_cards, self.under_your_control, self.tapped = all_cards, under_your_control, tapped
        self.visits = visits

    def apply(self, context, targets=None):
        from ..linked_exile import linked_cards
        from ..combat import matches_object_filter
        player = _controller_of(self.source, context)
        if self.source is None or player is None:
            return
        if self.visits is None:
            pool = [obj for obj in linked_cards(context.state, self.source, context.resolving_source_incarnation)
                    if matches_object_filter(obj, self.card_filter, state=context.state, reference=self.source)]
            visits = [(obj.instance_id, obj.zone_incarnation) for obj in pool]
            if not self.all_cards:
                context.choose_objects(player, pool, 'select_referent', count=1, source=self.source,
                    then_specs=[{'type': 'linked_exile_move', 'params': {
                        'destination': self.destination, 'visits': visits,
                        'under_your_control': self.under_your_control, 'tapped': self.tapped}}])
                return
        else:
            picked = {obj.instance_id for obj in context.previous_targets}
            visits = [(iid, visit) for iid, visit in self.visits if iid in picked]
        # RULE 607.2a / 400.7: never act on a later visit after a pending choice.
        if self.destination == 'battlefield':
            start_exile_return_batch(context.engine, visits,
                controller_id=player.id if self.under_your_control else None,
                entry_options={'tapped': self.tapped}, source=self.source,
                source_incarnation=context.resolving_source_incarnation)
            return
        for iid, visit in visits:
            obj = context.state.find_object(iid)
            if obj is None or obj.zone != Zone.EXILE or obj.zone_incarnation != visit:
                continue
            if self.destination == 'hand':
                context.engine.return_to_hand(obj)
            elif self.destination == 'graveyard':
                context.put_into_graveyard(obj)


EFFECT_FACTORIES['linked_exile_move'] = lambda p: LinkedExileMoveEffect(
    destination=p.get('destination', 'hand'), card_filter=p.get('card_filter'),
    all_cards=bool(p.get('all_cards')), under_your_control=bool(p.get('under_your_control')),
    tapped=bool(p.get('tapped')), visits=p.get('visits'))
