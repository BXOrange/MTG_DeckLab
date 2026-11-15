"""Choose one land from each opponent's exact exiled library-top pool."""
from .core import GameEffect, EffectRegistry, _controller_of, _apply_effects_partitioned
from ...models.game.game_object import Zone


class _ChooseExiledLandEffect(GameEffect):
    def __init__(self, owner_id, controller_id, visits, source=None):
        super().__init__(source)
        self.owner_id = owner_id
        self.controller_id = controller_id
        self.visits = list(visits)

    def apply(self, context, targets=None):
        player = context.state.player_by_id(self.controller_id)
        if player is None or player.has_lost:
            return
        pool = []
        for instance_id, visit in self.visits:
            obj = context.state.find_object(instance_id)
            if (obj is not None and obj.zone == Zone.EXILE and obj.zone_incarnation == visit
                    and obj.owner_id == self.owner_id and obj.card.is_land):
                pool.append(obj)
        context.engine._request_choose_objects(
            player, pool, 'grant_temp_play_standing', count=1, optional=False,
            source=self.source, prompt='Wähle eine exilierte Landkarte dieses Gegners',
        )


class ExileOpponentsChooseLandsEffect(GameEffect):
    def __init__(self, count=0, source=None):
        super().__init__(source)
        self.count = count

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        count = self._measured(self.count, context, targets)
        selections = []
        # RULE 608.2c: finish every opponent's exile instruction before
        # choosing from any pool. One resolution-time X applies to them all.
        with context.state.simultaneous():
            for opponent in context.state.living_players():
                if opponent.id == controller.id:
                    continue
                cards = list(reversed(opponent.library[-count:])) if count > 0 else []
                visits = []
                for obj in cards:
                    context.engine.exile(obj)
                    if obj.zone == Zone.EXILE:
                        visits.append((obj.instance_id, obj.zone_incarnation))
                selections.append(_ChooseExiledLandEffect(
                    opponent.id, controller.id, visits, self.source,
                ))
        # The normal deferred-effect pipeline preserves the other pools
        # while a choose_objects decision is pending, including clone/undo.
        _apply_effects_partitioned(selections, context, None, None, source=self.source)


EffectRegistry.register('exile_opponents_choose_lands', lambda p: ExileOpponentsChooseLandsEffect(
    count=p.get('count', 0),
))
