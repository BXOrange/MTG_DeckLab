"""Kaya's mixed-origin exile pool, fixed target and resolution-time card choice."""
from .core import EffectRegistry, GameEffect, _controller_of
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


def matching_exile_members(event, controller_id):
    if event.get('batch_of') != 'EXILE':
        return []
    return [member for member in event.get('members', [])
            if 'creature' in member.get('object_types', []) and (
                member.get('from_zone') == 'battlefield' and member.get('controller_id') == controller_id
                or member.get('from_zone') == 'graveyard' and member.get('owner_id') == controller_id
                and not member.get('is_token'))]


class ExileCreatureTokenCopyEffect(GameEffect):
    exile_pool_lookback = True

    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='token_you_control')

    def apply(self, context, targets=None):
        recipient = targets[0] if targets else None
        player = _controller_of(self.source, context)
        if recipient is None or player is None:
            return
        candidates = []
        for iid, visit in (context.trigger_event or {}).get('exile_pool_visits', []):
            obj = context.state.find_object(iid)
            if (obj is not None and obj.zone == Zone.EXILE and obj.zone_incarnation == visit
                    and not obj.is_token and not obj.face_down_in_exile and obj.card.is_creature):
                candidates.append(obj)
        context.engine._request_choose_objects(player, candidates, 'select_referent', count=1,
            optional=True, source=self.source, then_specs=[{'type': 'copy_for_duration', 'params': {
                'template': 'previous', 'duration': 'end_of_turn', 'add_keywords': ['Flying'],
                'recipient_visits': [[recipient.instance_id, recipient.zone_incarnation]],
            }}])


class ExileChosenGraveyardCardEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is not None:
            pool = [obj for owner in context.state.players for obj in owner.graveyard]
            context.engine._request_choose_objects(player, pool, 'exile', count=1,
                source=self.source, optional=False)


class ExileOwnAndOtherCreaturesEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature_you_control')
        self.extra_target_specs = [TargetSpec(kind='creature_that_player_controls',
                                            per_player='opponents', optional=True)]

    def apply(self, context, targets=None):
        with context.state.simultaneous():
            for obj in targets or []:
                context.exile(obj)


EffectRegistry.register('exile_creature_token_copy', lambda p: ExileCreatureTokenCopyEffect())
EffectRegistry.register('exile_chosen_graveyard_card', lambda p: ExileChosenGraveyardCardEffect())
EffectRegistry.register('exile_own_and_other_creatures', lambda p: ExileOwnAndOtherCreaturesEffect())
