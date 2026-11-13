"""Autumn-Tail targets an attached Aura, then chooses its untargeted new host."""
from .core import GameEffect, _controller_of
from ..targeting import TargetSpec
from ..continuations import choice, ANSWER_STR
from ...models.game.game_object import Zone


def _hosts(rules,aura):
    return [o for o in rules.state.permanents() if o.is_creature
            and o.instance_id!=aura.attached_to
            and rules._attachment_legal(aura,o,check_control=False)]


@choice('autumn_tail_attach', answer=ANSWER_STR, rule='701.3')
def _resume_autumn_tail(rules,frame,answer):
    aura=rules.state.find_object(frame['aura_id'])
    if aura is None or aura.zone!=Zone.BATTLEFIELD or aura.zone_incarnation!=frame['aura_visit']:
        return
    offered=next((o for o in frame['options'] if str(o['id'])==str(answer)),None)
    host=rules.state.find_object(offered['instance_id']) if offered else None
    if host is None or host.zone_incarnation!=offered['visit'] or host not in _hosts(rules,aura):
        rules.open_choice(frame)
        raise ValueError('Choose another creature the Aura can enchant')
    rules.attach_to_target(aura,host,check_control=False)


class AutumnTailAttachEffect(GameEffect):
    def __init__(self,source=None):
        super().__init__(source)
        self.target_spec=TargetSpec(kind='permanent',creature_filter={
            'subtype':'Aura','attached_to_creature':True})

    def apply(self,context,targets=None):
        aura=(targets or [None])[0]
        if aura is None:
            return
        player=_controller_of(self.source,context)
        hosts=_hosts(context.engine,aura)
        if player is None or not hosts:
            return
        context.engine.open_choice({'kind':'autumn_tail_attach','player_id':player.id,
            'aura_id':aura.instance_id,'aura_visit':aura.zone_incarnation,
            'prompt':'Wähle eine andere Kreatur für die Aura',
            'options':[{'id':str(o.instance_id),'instance_id':o.instance_id,'visit':o.zone_incarnation,'label':o.name}
                       for o in hosts]})
