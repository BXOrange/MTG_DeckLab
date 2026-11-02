"""Per-opponent "greatest power" destruction (Highcliff Felidar, Commander Cube singleton batch).

"For each opponent, choose a creature with the greatest power among creatures that player controls. Destroy those
creatures." The choice is made per opponent, from that opponent's own creatures, so one creature per opponent is
destroyed and the set can be as large as the number of opponents.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import continuous
from .core import EffectRegistry, GameContext, GameEffect, _controller_of


class DestroyGreatestPowerPerOpponentEffect(GameEffect):
    """RULE 701.8: destroy one creature with the greatest power from each opponent's creatures.

    Power is read after a RULE 613 recompute, since the layer engine owns derived power. Ties for the greatest power
    are auto-picked (the first on the battlefield): the controller's own choice among tied creatures is not routed
    through the `pending_choice` chooser. That is the same documented simplification `SacrificeEffect`'s
    ``greatest_power`` makes, and a board with one creature at the top power is exact.
    """

    def __init__(self, source: Optional[Any] = None) -> None:
        super().__init__(source)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        # RULE 613: derived power is only current after a layer recompute (see CLAUDE.md's derived-state invariant).
        continuous.recompute(context.state)
        for opponent in context.state.living_players():
            if opponent.id == controller.id:
                continue
            creatures = [o for o in context.state.battlefield if o.is_creature and o.controller_id == opponent.id]
            if not creatures:
                continue
            top = max(int(o.power or 0) for o in creatures)
            leaders = [o for o in creatures if int(o.power or 0) == top]
            context.destroy(leaders[0], can_be_regenerated=True)


EffectRegistry.register(
    "destroy_greatest_power_per_opponent",  # Highcliff Felidar
    lambda p: DestroyGreatestPowerPerOpponentEffect(),
)
