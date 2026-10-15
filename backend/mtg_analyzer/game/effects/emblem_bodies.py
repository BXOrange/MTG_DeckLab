"""Event-bound control and delayed recursion, also usable outside emblems."""
from __future__ import annotations

from ...models.game.game_object import Zone
from ...models.game.game_state import DelayedTrigger
from ...models.game.events import GameEvent, EventType
from .core import GameEffect, _controller_of
from .exile_control import GainControlUntilEndOfTurnEffect
from .choices_actions import ReturnDyingSubjectToBattlefieldEffect


class CompleteTurnLifeLossEffect(GameEffect):
    """RULE 603.4: recheck the damaged player's loss, then supply the difference."""
    def __init__(self, threshold=0, source=None):
        super().__init__(source)
        self.threshold = threshold

    def apply(self, context, targets=None):
        event = context.trigger_event or {}
        player_id = event.get('target_id')
        if player_id is None:
            return
        lost = context.state.life_lost_this_turn.get(player_id, 0)
        if lost < self.threshold:
            context.lose_life(context.state.player_by_id(player_id), self.threshold - lost)


class GainControlOfCastTargetsEffect(GainControlUntilEndOfTurnEffect):
    """RULE 603.2 / 608.2h: refer to permanents targeted when the spell was cast."""
    def __init__(self,source=None):
        super().__init__(source=source,duration='permanent',untap=False,haste=False)
        self.target_spec=None

    def apply(self,context,targets=None):
        controller=_controller_of(self.source,context)
        if controller is None:
            return
        snapshots=(context.trigger_event or {}).get('target_permanent_incarnations') or {}
        for iid, incarnation in snapshots.items():
            target=context.state.find_object(int(iid))
            if (target is not None and target.zone==Zone.BATTLEFIELD
                    and target.zone_incarnation==incarnation):
                self._take(context,target,controller)
        context.recompute()


class _ReturnCapturedDyingSubjectEffect(ReturnDyingSubjectToBattlefieldEffect):
    def __init__(self,event,source=None):
        super().__init__(source=source)
        self.event=GameEvent(EventType.DIES,**dict(event.data))

    def apply(self,context,targets=None):
        outer=context.trigger_event
        context.trigger_event=self.event
        try:
            super().apply(context,targets)
        finally:
            context.trigger_event=outer


class DelayReturnDyingSubjectEffect(GameEffect):
    """RULE 603.7: remember one death and return that graveyard incarnation."""
    def apply(self,context,targets=None):
        event=context.trigger_event
        controller=_controller_of(self.source,context)
        if event is None or controller is None:
            return
        context.state.delayed_triggers.append(DelayedTrigger(
            controller_id=controller.id,step='end',scope='any',
            effects=[_ReturnCapturedDyingSubjectEffect(event,self.source)],
            description='Return dying permanent at next end step',
        ))
