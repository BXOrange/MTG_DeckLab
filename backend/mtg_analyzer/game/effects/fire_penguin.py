"""Fire Penguin's granted death ability returns the exact Aura, attached anew."""
from .core import GameEffect
from ..continuations import choice, ANSWER_STR
from ...models.game.game_object import Zone


@choice('fire_penguin_return', answer=ANSWER_STR, rule='303.4f')
def _resume_penguin(rules, frame, answer):
    aura=rules.state.find_object(frame['aura_id'])
    if aura is None or aura.zone!=Zone.GRAVEYARD or aura.zone_incarnation!=frame['aura_visit']:
        return
    offered=next((o for o in frame['options'] if str(o['id'])==str(answer)),None)
    host=rules.state.find_object(offered['instance_id']) if offered else None
    if (host is None or host.zone_incarnation!=offered['visit']
            or not rules._attachment_legal(aura,host,check_control=False)):
        rules.open_choice(frame)
        raise ValueError('Choose a creature the Aura can enchant')
    rules.return_from_graveyard(aura,'battlefield',attach_to=host)


class FirePenguinReturnEffect(GameEffect):
    capture_grantor=True

    def apply(self,context,targets=None):
        aura=context.state.find_object(self.grantor.instance_id) if self.grantor is not None else None
        # RULE 400.7 / 607: this death ability follows only the ensuing graveyard visit.
        if (aura is None or aura.zone!=Zone.GRAVEYARD
                or aura.zone_incarnation!=self.grantor_incarnation+1):
            return
        options=[{'id':str(o.instance_id),'instance_id':o.instance_id,'visit':o.zone_incarnation,'label':o.name}
                 for o in context.state.permanents()
                 if context.engine._attachment_legal(aura,o,check_control=False)]
        if not options:
            return
        context.engine.open_choice({'kind':'fire_penguin_return','player_id':aura.owner_id,
            'aura_id':aura.instance_id,'aura_visit':aura.zone_incarnation,
            'prompt':'Wähle die neue Kreatur für Curse of the Fire Penguin', 'options':options})
