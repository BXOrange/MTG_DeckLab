"""Blitzwing's life-loss echo and random combat ability."""
from .core import GameEffect
from ..targeting import TargetSpec


def _same_visit(context, source):
    return (source is not None and source in context.state.permanents()
            and (context.resolving_source_incarnation is None
                 or source.zone_incarnation == context.resolving_source_incarnation))


class BlitzwingLifeEchoEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="opponent")

    def apply(self, context, targets=None):
        opponent = targets[0] if targets else None
        if opponent is None:
            return
        # Read at resolution; gaining life never subtracts from life lost this turn.
        before = context.state.life_lost_this_turn.get(opponent.id, 0)
        context.engine.lose_life(opponent, before)
        lost = context.state.life_lost_this_turn.get(opponent.id, 0) - before
        if lost == 0 and _same_visit(context, self.source):
            context.engine.transform_permanent(self.source)


class BlitzwingRandomAbilityEffect(GameEffect):
    def apply(self, context, targets=None):
        chosen = context.engine.random_choice(("flying", "indestructible"))
        if _same_visit(context, self.source):
            self.source.temp_keywords.add(chosen)
            context.recompute()


class BlitzwingConvertEffect(GameEffect):
    def apply(self, context, targets=None):
        if _same_visit(context, self.source):
            context.engine.transform_permanent(self.source)
