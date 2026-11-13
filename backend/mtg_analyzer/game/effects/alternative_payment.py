"""Resolve-time choice of one payable cost, with a shared optional payoff."""
from __future__ import annotations

from .core import GameEffect, EffectRegistry, _controller_of
from ..costs import parse_activation_cost
from ..continuations import choice


class AlternativePaymentEffect(GameEffect):
    def __init__(self, alternatives, effects, source=None):
        super().__init__(source)
        self.alternatives = list(alternatives)
        self.inner_specs = list(effects)

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        costs = {str(i): item for i, item in enumerate(self.alternatives)
                 if context.engine._can_pay_player_cost(player, parse_activation_cost(item["cost"]), self.source)}
        if not costs:
            return
        context.engine.open_choice({
            "kind": "alternative_payment", "player_id": player.id, "source": self.source,
            "costs": costs, "effects": self.inner_specs,
            "source_incarnation": context.resolving_source_incarnation,
            "prompt": "Kosten bezahlen?",
            "options": [{"id": key, "label": item["label"]} for key, item in costs.items()]
                       + [{"id": "decline", "label": "Nicht bezahlen"}],
        })


@choice("alternative_payment", rule="118.3")
def _resume_alternative_payment(rules, payload, answer):
    item = payload["costs"].get(str(answer))
    if item is None:
        if answer is not None and answer != "decline":
            rules.open_choice(payload)
        return
    player = rules.state.player_by_id(payload["player_id"])
    cost = parse_activation_cost(item["cost"])
    # Reuse the payment continuation: a sacrifice/discard choice must finish
    # before the payoff, including after cloning the pending game state.
    outer_incarnation = rules.context.resolving_source_incarnation
    rules.context.resolving_source_incarnation = payload.get("source_incarnation")
    try:
        rules._request_pay_cost_then(player, cost, payload["effects"], payload["source"])
    finally:
        rules.context.resolving_source_incarnation = outer_incarnation
    if rules.state.pending_pay_cost_then is not None:
        rules.state.pending_choice = None
        rules._resume_pay_cost_then({}, "pay")


EffectRegistry.register("alternative_payment", lambda p: AlternativePaymentEffect(p.get("alternatives", []), p.get("effects", [])))
