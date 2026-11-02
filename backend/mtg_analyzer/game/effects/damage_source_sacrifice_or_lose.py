"""'That source's controller loses that much life unless they sacrifice that many permanents' (Archfiend of Spite).

A DAMAGE trigger's payload carries the amount and the dealing source's controller; the penalty is an
*unless*-cost owed by that controller (RULE 118.12), so it is the shared optional-payment frame
(`RulesEngine._request_pay_cost_then`) with the lose-life as the not-paid branch.
"""
from __future__ import annotations

from typing import Any, Optional

from ..costs import ActivationCost
from .core import GameContext, GameEffect

#: The word `RulesEngine.sacrifice` / `_matches_sacrifice_type` takes for "any permanent of your choice".
_ANY_PERMANENT = "permanent"


class DamageSourceSacrificeOrLoseLifeEffect(GameEffect):
    """RULE 118.12: the damaging source's controller loses N life unless they sacrifice N permanents of their choice."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        amount = event.get("amount")
        payer_id = event.get("source_controller_id")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0 or payer_id is None:
            return
        payer = context.state.player_by_id(payer_id)
        if payer is None:
            return
        cost = ActivationCost()
        cost.sacrifice_count = (amount, _ANY_PERMANENT)
        # The not-paid branch's untargeted "you" is the payer, not the Archfiend's controller (as for Gix).
        outer_acting = context.acting_player_id
        context.acting_player_id = payer.id
        try:
            context.engine._request_pay_cost_then(
                payer, cost, [], self.source,
                else_effect_specs=[{"type": "lose_life", "params": {"amount": amount}}],
                targets=[], prompt=f"Sacrifice {amount} permanent(s) instead of losing {amount} life?",
            )
        finally:
            context.acting_player_id = outer_acting


EFFECT_FACTORIES = {
    "damage_source_sacrifice_or_lose_life": lambda p: DamageSourceSacrificeOrLoseLifeEffect(),
}
