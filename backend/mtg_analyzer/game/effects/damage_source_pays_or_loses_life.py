"""'That source's controller loses N life unless they pay {M}' (Elesh Norn // The Argent Etchings).

Sibling of `damage_source_sacrifice_or_lose`: a DAMAGE trigger's payload carries the dealing source's controller
(``source_controller_id``); the penalty is an *unless*-cost owed by that controller (RULE 118.12), so it is the shared
optional-payment frame (`RulesEngine._request_pay_cost_then`) with the lose-life as the not-paid branch. Unlike
Archfiend of Spite the penalty is fixed, not "that much", so it does not read the event's amount."""
from __future__ import annotations

from typing import Any, Optional

from ..costs import parse_activation_cost
from .core import GameContext, GameEffect


class DamageSourcePaysOrLosesLifeEffect(GameEffect):
    """RULE 118.12: the damaging source's controller loses ``life`` life unless they pay ``cost`` (a mana string)."""

    def __init__(self, cost: str = "{1}", life: int = 1, source: Optional[Any] = None) -> None:
        super().__init__(source)
        self.cost = cost
        self.life = life

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        payer_id = (context.trigger_event or {}).get("source_controller_id")
        if payer_id is None:
            return
        payer = context.state.player_by_id(payer_id)
        if payer is None:
            return
        # The not-paid branch's untargeted "you" is the payer, not the trigger controller's (as for Archfiend of Spite).
        outer_acting = context.acting_player_id
        context.acting_player_id = payer.id
        try:
            context.engine._request_pay_cost_then(
                payer, parse_activation_cost(self.cost), [], self.source,
                else_effect_specs=[{"type": "lose_life", "params": {"amount": self.life}}],
                targets=[], prompt=f"Pay {self.cost} or lose {self.life} life?",
            )
        finally:
            context.acting_player_id = outer_acting


EFFECT_FACTORIES = {
    "damage_source_pays_or_loses_life": lambda p: DamageSourcePaysOrLosesLifeEffect(
        cost=str(p.get("cost", "{1}")), life=int(p.get("life", 1)),
    ),
}
