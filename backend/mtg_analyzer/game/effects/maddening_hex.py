"""Maddening Hex's firing player and random, untargeted attachment."""
from .core import GameEffect, _controller_of
from ...models.game.game_object import Zone


def _source_visit(context, source):
    visit = context.resolving_source_incarnation
    return source.zone_incarnation if visit is None else visit


class MaddeningHexDamageEffect(GameEffect):
    def apply(self, context, targets=None):
        event = context.trigger_event or {}
        player = context.state.player_by_id(event.get('player_id') or event.get('controller_id'))
        if player is None or player.has_lost:
            return
        source = self.source
        visit = _source_visit(context, source)
        if source.zone_incarnation != visit:
            source = context.state.zone_visit_sources.get((source.instance_id, visit), source)
        # RULE 608.2h: damage belongs to the original source, even after it leaves.
        context.engine.deal_damage(player, int(context.die_result or 0), source=source)


class MaddeningHexAttachEffect(GameEffect):
    def apply(self, context, targets=None):
        source = self.source
        if (source.zone != Zone.BATTLEFIELD or source.phased_out
                or source.zone_incarnation != _source_visit(context, source)):
            return
        controller = _controller_of(source, context)
        event = context.trigger_event or {}
        caster = event.get('player_id') or event.get('controller_id')
        if controller is None:
            return
        opponents = [p for p in context.state.living_players()
                     if p.id not in (controller.id, caster)]
        if opponents:
            chosen = opponents[context.engine.random_int(len(opponents))]
            # RULE 701.3: this instruction attaches without targeting the player.
            context.engine.attach_to_target(source, chosen, check_control=False)
