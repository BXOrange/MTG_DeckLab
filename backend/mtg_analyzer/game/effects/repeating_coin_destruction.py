"""A coin-flip process retaining its original two creature targets."""
from .core import GameEffect, _controller_of
from ..costs import parse_activation_cost
from ..targeting import TargetSpec
from ...models.game.game_object import Zone


class RepeatingCoinDestructionEffect(GameEffect):
    def __init__(self, visits=None, destroy_own=False, source=None):
        super().__init__(source)
        self.visits = visits
        self.destroy_own = destroy_own
        if visits is None:
            self.target_spec = TargetSpec(kind="creature_you_dont_control")
            self.extra_target_specs = (TargetSpec(kind="creature_you_control"),)

    def apply(self, context, targets=None):
        visits = self.visits
        if visits is None:
            # RULE 608.2c: repeating instructions does not announce new targets.
            visits = [
                {"id": obj.instance_id, "incarnation": obj.zone_incarnation} if obj else None
                for obj in (list(targets or []) + [None, None])[:2]
            ]
        if self.destroy_own:
            self._destroy(context, visits[1])
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        if context.engine.coin_flip(player):
            self._destroy(context, visits[0])
            return
        context.engine._request_pay_cost_then(
            player, parse_activation_cost("{3}"),
            [{"type": "coin_flip_destroy_or_pay_repeat", "params": {"visits": visits}}],
            self.source,
            else_effect_specs=[{
                "type": "coin_flip_destroy_or_pay_repeat",
                "params": {"visits": visits, "destroy_own": True},
            }],
        )

    @staticmethod
    def _destroy(context, visit):
        if visit is None:
            return
        obj = context.state.find_object(visit["id"])
        if obj is not None and obj.zone == Zone.BATTLEFIELD and obj.zone_incarnation == visit["incarnation"]:
            context.engine.destroy(obj)
