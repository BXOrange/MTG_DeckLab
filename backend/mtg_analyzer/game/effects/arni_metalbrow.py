"""Arni Metalbrow's optional hand placement after the attack payment."""
from .core import GameEffect, _controller_of
from ..continuations import choice, ANSWER_STR
from ...models.game.game_object import Zone


@choice('arni_put_attacking', answer=ANSWER_STR, rule='508.4')
def _resume_arni(rules, frame, answer):
    if answer in (None, 'decline'):
        return
    offered = next((o for o in frame['options'] if o['id'] == answer), None)
    player = rules.state.player_by_id(frame['player_id'])
    obj = rules.state.find_object(offered.get('instance_id')) if offered else None
    if (obj is None or obj not in player.hand or obj.zone_incarnation != offered.get('incarnation')
            or not obj.is_creature or obj.mana_value >= frame['mana_value']):
        rules.open_choice(frame)
        raise ValueError('Choose a listed creature card or decline')
    player.remove_from_zone(obj, Zone.HAND)
    obj.controller_id = player.id
    rules._put_searched_card(player, obj, 'battlefield_attacking')


class ArniPutAttackingEffect(GameEffect):
    def apply(self, context, targets=None):
        event = context.trigger_event or {}
        instance_id = event.get('instance_id')
        visit = (event.get('subject_zone_incarnations') or {}).get('instance_id', event.get('zone_incarnation'))
        creature = context.state.find_object(instance_id)
        if creature is None or creature.zone_incarnation != visit:
            creature = context.state.zone_visit_sources.get((instance_id, visit))
        if creature is None:
            return
        # RULE 608.2h: measure that creature on resolution, using LKI when
        # it left; a later battlefield visit must not supply the mana value.
        mana_value = creature.mana_value
        player = _controller_of(self.source, context)
        candidates = [o for o in player.hand if o.is_creature and o.mana_value < mana_value]
        if not candidates:
            return
        context.engine.open_choice({'kind': 'arni_put_attacking', 'player_id': player.id,
            'source_id': self.source.instance_id, 'mana_value': mana_value,
            'optional': True, 'prompt': 'Kreaturenkarte getappt und angreifend ins Spiel bringen?',
            'options': [{'id': str(o.instance_id), 'instance_id': o.instance_id,
                         'incarnation': o.zone_incarnation, 'label': o.name} for o in candidates]
                       + [{'id': 'decline', 'label': 'Keine Karte ins Spiel bringen'}]})
