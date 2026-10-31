"""Haunt links and effects that refer to the haunted permanent."""
from .core import GameEffect
from ..control import gain_control
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


def is_haunted(state, target):
    """RULE 702.55b / 400.7: a link names a particular battlefield object."""
    return target.zone == Zone.BATTLEFIELD and any(
        obj.zone == Zone.EXILE
        and obj.haunting_instance_id == target.instance_id
        and obj.haunting_incarnation == target.zone_incarnation
        for player in state.players for obj in player.exile
    )


class HauntedCreatureEffect(GameEffect):
    """Target a haunted creature; damage its owner or take control while haunted."""

    def __init__(self, mode='damage_owner', amount=0, source=None):
        super().__init__(source)
        self.mode = mode
        self.amount = amount
        self.target_spec = TargetSpec(kind='haunted_creature')

    def apply(self, context, targets=None):
        target = (targets or [None])[0]
        if target is None or not target.is_creature or not is_haunted(context.state, target):
            return
        if self.mode == 'damage_owner':
            # RULE 115.1: the creature is the target; its owner is not targeted.
            owner = context.state.player_by_id(target.owner_id)
            if owner is not None:
                context.deal_damage(owner, self.amount, self.source)
        elif self.mode == 'control' and self.source is not None:
            # RULE 611.2b: the window is consumed forever when haunting ends.
            target.control_change_while_source = {
                'revert_to': (target.control_change_while_source or {}).get('revert_to', target.controller_id),
                'player_id': self.source.controller_id,
                'source_id': target.instance_id,
                'incarnation': target.zone_incarnation,
                'needs_control': False,
                'needs_haunted': True,
            }
            if target.controller_id != self.source.controller_id:
                gain_control(context.state, target, self.source.controller_id,
                             duration="while_source", window=target.control_change_while_source)
                target.summoning_sick = True
