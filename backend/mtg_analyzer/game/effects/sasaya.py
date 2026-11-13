"""Sasaya's same-name land multiplier with independently chosen mana types."""
from .core import GameEffect


class SasayaManaEffect(GameEffect):
    def apply(self,context,targets=None):
        event=context.trigger_event or {}
        player=context.state.player_by_id(event.get('player_id'))
        if player is None:
            return
        land=context.state.find_object(event.get('instance_id'))
        name=land.name if land is not None else event.get('object')
        others=[o for o in context.state.permanents_controlled_by(player.id)
                if o.is_land and o.instance_id!=event.get('instance_id') and o.name==name]
        colors=[c for c,n in (event.get('produced') or {}).items() if n>0]
        if not others or not colors:
            return
        if len(colors)==1:
            context.engine.add_mana_any_color(player,colors,amount=len(others))
            return
        # RULE 605.1b / 106.3: each extra mana may be a different produced type.
        # State-owned iterations keep every outstanding choice through clone/undo.
        context.engine.defer_iteration([], [player]*len(others), source=self.source,
            specs=[{'type':'add_mana','params':{'colors':['ANY'],'any_color_choices':colors,'recipient':'event_controller'}}])
        while not context.state.pending_choice and context.state.deferred_effects:
            if not context.engine.resume_deferred_effects():
                break
