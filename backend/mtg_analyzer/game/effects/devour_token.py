"""Create a token with devour N (RULE 702.82).

"Create a 1/1 red and green Dragon creature token with flying and devour 2." (Dragon Broodmother.) Devour is
"as this enters, you may sacrifice any number of creatures; it enters with N +1/+1 counters for each". The
creatures go *before* the token exists (so none of them can be the token and none sees it), then the token is
made carrying the counters — the sacrifice choice runs first and this effect re-enters with the picked count.
"""
from __future__ import annotations

from typing import Any, Optional

from .core import EffectRegistry, GameContext, GameEffect, _controller_of


class DevourTokenEffect(GameEffect):
    """RULE 702.82a: ``token`` is a ``create_token`` param dict; ``devour`` is N of "devour N".

    ``sacrificed`` is ``None`` on the first pass (ask which creatures to sacrifice), and the literal ``"x"``
    sentinel in the follow-up spec the chooser applies, which the engine binds to how many creatures were picked.
    """

    def __init__(self, token: dict[str, Any], devour: int, sacrificed: Any = None, source=None) -> None:
        super().__init__(source)
        self.token = dict(token)
        self.devour = int(devour)
        self.sacrificed = sacrificed

    def _spec(self, sacrificed: Any) -> dict[str, Any]:
        return {"type": "devour_token", "params": {"token": self.token, "devour": self.devour, "sacrificed": sacrificed}}

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.sacrificed is not None:
            self._create(context, int(self.sacrificed))
            return
        player = _controller_of(self.source, context)
        pool = [o for o in context.state.permanents_controlled_by(player.id)
                if o.is_creature and not o.cant_be_sacrificed_this_turn]
        if not pool:
            self._create(context, 0)
            return
        # RULE 702.82a: "any number" — an optional pick, declining (or picking nothing) still makes the token.
        context.engine._request_choose_objects(
            player, pool, "sacrifice", count=len(pool), optional=True, source=self.source,
            prompt="Wähle Kreaturen für Devour",
            then_that_many={"effects": [self._spec("x")]},
            else_specs=[self._spec(0)],
        )

    def _create(self, context: GameContext, sacrificed: int) -> None:
        params = dict(self.token)
        if sacrificed > 0:
            params["extra_counters"] = {"kind": "+1/+1", "count": self.devour * sacrificed}  # RULE 702.82a
        effect = EffectRegistry.create("create_token", params)
        effect.source = self.source
        effect.apply(context, None)


EffectRegistry.register(
    "devour_token",
    lambda p: DevourTokenEffect(dict(p.get("token") or {}), int(p.get("devour", 1)), p.get("sacrificed")),
)
