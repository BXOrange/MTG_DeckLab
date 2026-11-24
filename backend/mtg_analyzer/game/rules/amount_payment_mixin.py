"""Resolve variable payments and retain their totals across choices."""
from ...models.mana.mana_cost import ManaCost
from ...parser.oracle.catalogue.amount_payments import PAID_AMOUNT, PAID_BY_PLAYER
from ...parser.oracle.spec import MAX_EFFECT_MAGNITUDE
from .. import continuations
from ..costs import ActivationCost
from ..effects.composition import BindEffect, _build
from ..effects.core import _apply_effects_partitioned
from .misc_helpers import PAY_X_OPTION_PREFIX


class AmountPaymentMixin:
    """RULE 118.1 / 608.2d: collect payments during resolution."""

    DEFERRED_AMOUNT_PAYMENT = "amount_payment"
    AMOUNT_PAYMENT_MANA_ACTIONS = frozenset({"tap_for_mana", "activate_hand_mana"})

    def _request_amount_payment(self, source, targets, controller_id, resource, scope, repeat, specs):
        order = [p.id for p in self.state.living_players_apnap()]
        if scope == "you":
            order = [controller_id] if controller_id in order else []
        elif scope == "starting_with_you" and controller_id in order:
            start = order.index(controller_id)
            order = order[start:] + order[:start]
        pending = {
            "source": source, "targets": list(targets or ()), "controller_id": controller_id,
            "resource": resource, "repeat": repeat, "effects": specs, "order": order,
            "paid": dict.fromkeys(order, 0), "index": 0, "round_paid": 0,
            "trigger_event": self.context.trigger_event,
            "source_incarnation": self.context.resolving_source_incarnation,
        }
        self._advance_amount_payment(pending)

    def _max_amount_payment(self, player, resource, source):
        if resource == "life":
            return 0 if self._life_locked(player) else max(0, player.life)
        if resource == "energy":
            return player.counters.get("energy", 0)
        if resource == "discard":
            return len(player.hand)
        from ..game_engine import GameEngine
        from ..mana_potential import max_potential_total

        engine = GameEngine(self.state, rules=self)
        low = 0
        high = min(MAX_EFFECT_MAGNITUDE, player.mana_pool.total() + max_potential_total(engine, player))
        # Generic mana affordability is monotone. Avoid scanning and planning every option.
        while low < high:
            mid = (low + high + 1) // 2
            if self._can_pay_player_cost(player, self._amount_payment_cost("mana", mid), source):
                low = mid
            else:
                high = mid - 1
        return low

    @staticmethod
    def _amount_payment_cost(resource, amount):
        if resource == "mana":
            return ActivationCost(mana=ManaCost.parse(f"{{{amount}}}"))
        if resource == "life":
            return ActivationCost(pay_life=amount)
        return ActivationCost(pay_energy=amount)

    def _advance_amount_payment(self, pending):
        resource = pending["resource"]
        order = pending["order"]
        while True:
            if pending["index"] == len(order):
                if not pending["repeat"] or not pending["round_paid"]:
                    self._finish_amount_payment(pending)
                    return
                pending["index"] = pending["round_paid"] = 0
            pid = order[pending["index"]]
            pending["index"] += 1
            player = self.state.player_by_id(pid)
            if player.has_lost or player.is_dummy:
                continue
            limit = self._max_amount_payment(player, resource, pending["source"])
            limit = min(MAX_EFFECT_MAGNITUDE, limit)
            if not limit and (
                resource != "mana" or
                not self._amount_payment_mana_actions(player)
            ):
                continue
            unit = {"mana": "Mana", "life": "Leben", "energy": "{E}", "discard": "Karten"}[resource]
            prompt = f"Wie viel {unit} bezahlen?" if resource != "discard" else "Wie viele Karten abwerfen?"
            source = pending["source"]
            self.state.pending_amount_payment = pending
            self.open_choice({
                "kind": "amount_payment", "player_id": pid, "prompt": prompt,
                "source_id": getattr(source, "instance_id", None),
                "source_name": getattr(source, "name", None),
                "options": [
                    {"id": f"{PAY_X_OPTION_PREFIX}{n}", "label": str(n), "x": n}
                    for n in range(limit, 0, -1)
                ] + [{"id": "decline", "label": "0"}],
                "max_amount": limit, "resource": resource, "paid_amounts": dict(pending["paid"]),
            })
            return

    def _amount_payment_mana_actions(self, player):
        from ..game_engine import GameEngine

        return GameEngine(self.state, rules=self).mana_actions(player)

    def _begin_amount_payment_mana_action(self):
        """Suspend the prompt while the payer activates a RULE 608.2g mana ability."""
        pending = self.state.pending_amount_payment
        self.state.pending_choice = None
        self.state.pending_amount_payment = None
        pending["index"] -= 1
        self.state.deferred_effects.append({"kind": self.DEFERRED_AMOUNT_PAYMENT, "pending": pending})

    @continuations.choice("amount_payment", rule="608.2d")
    def _resume_amount_payment(self, choice, answer):
        pending = self.state.pending_amount_payment
        self.state.pending_amount_payment = None
        player = self.state.player_by_id(choice["player_id"])
        source, resource = pending["source"], pending["resource"]
        amount = self._pay_cost_then_x(answer, choice["max_amount"]) or 0
        if amount and not player.has_lost:
            if resource == "discard":
                amount = min(amount, len(player.hand))
                if amount:
                    # The generic object chooser commits the selected subset together.
                    # Park the round behind its replacement choices as well.
                    self.state.deferred_effects.append({"kind": self.DEFERRED_AMOUNT_PAYMENT, "pending": pending})
                    self._request_choose_objects(
                        player, list(player.hand), "discard", count=amount,
                        prompt="Wähle Karten zum Abwerfen", source=source,
                    )
            else:
                cost = self._amount_payment_cost(resource, amount)
                if (resource == "life" and self._life_locked(player)) or not self._can_pay_player_cost(player, cost, source):
                    amount = 0
                else:
                    self._pay_player_cost(player, cost, source)
                    if self.state.pending_choice is not None:
                        self.state.deferred_effects.append({"kind": self.DEFERRED_AMOUNT_PAYMENT, "pending": pending})
        else:
            amount = 0
        pending["paid"][player.id] += amount
        pending["round_paid"] += amount
        if not (amount and resource == "discard") and self.state.pending_choice is None:
            self._advance_amount_payment(pending)

    def _cancel_conceded_amount_payment(self, player_id, ending_game=False):
        choice = self.state.pending_choice or {}
        if choice.get("kind") != "amount_payment" or choice["player_id"] != player_id:
            return
        pending = self.state.pending_amount_payment
        self.state.pending_choice = None
        self.state.pending_amount_payment = None
        if not ending_game:
            self.state.deferred_effects.append({"kind": self.DEFERRED_AMOUNT_PAYMENT, "pending": pending})

    def _finish_amount_payment(self, pending):
        paid = pending["paid"]
        specs = BindEffect._substitute(pending["effects"], PAID_AMOUNT, sum(paid.values()))
        specs = BindEffect._substitute(specs, PAID_BY_PLAYER, paid)
        ctx = self.context
        saved = ctx.acting_player_id, ctx.trigger_event, ctx.resolving_source_incarnation
        ctx.acting_player_id = pending["controller_id"]
        ctx.trigger_event = pending["trigger_event"]
        ctx.resolving_source_incarnation = pending["source_incarnation"]
        try:
            source = pending["source"]
            _apply_effects_partitioned(_build(specs, source), ctx, pending["targets"], None, source)
        finally:
            ctx.acting_player_id, ctx.trigger_event, ctx.resolving_source_incarnation = saved
