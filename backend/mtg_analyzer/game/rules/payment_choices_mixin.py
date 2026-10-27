"""Optional energy, life and effect-cost payments."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from ..costs import ActivationCost
from ..effects.core import TriggeredAbility
from .. import continuations
from .misc_helpers import (
    PAY_COST_THEN_MAX_X,
    PAY_X_OPTION_PREFIX,
    _cost_with_x,
    _substitute_x_specs,
    _substitute_x_modes,
)


class PaymentChoicesMixin:
    """Optional energy, life and effect-cost payments."""

    #: Prefix of a variable energy payment's option id (``pay_x:<n>``), mirroring `_request_pay_cost_then`'s ENG-48.
    PAY_ENERGY_X_PREFIX = "pay_x:"

    def _offer_cast_pip_life_payment(self, allowed: list[int]) -> None:
        pending = self.state.pending_cast_payment
        color = pending["colors"][len(pending["selected"])]
        player = self.state.player_by_id(pending["player_id"])
        self.open_choice({
            "kind": "cast_pip_life_payment", "player_id": player.id,
            "source_id": pending["instance_id"], "color": color,
            "prompt": f"Zusätzliche Lebenszahlung für {{{color}}} wählen",
            "options": [{"id": str(n), "label": "Kein Leben bezahlen" if n == 0 else
                         f"{2 * n} Leben bezahlen; {{{color}}}-Kosten um {n} reduzieren"}
                        for n in allowed],
        })

    @continuations.choice("cast_pip_life_payment", rule="601.2b")
    def _resume_cast_pip_life_payment(self, payload, answer) -> None:
        answer = "0" if answer is None else str(answer)
        if answer not in {option["id"] for option in payload["options"]}:
            raise ValueError("Ungültige Lebenszahlung")
        pending = self.state.pending_cast_payment
        pending["selected"][payload["color"]] = int(answer)

    def _request_pay_energy_then(
        self, player: Player, amount: int, effect_specs: list[dict], source: Optional[GameObject],
        variable: bool = False, targets: Optional[list[Any]] = None,
        trigger_event: Optional[GameEvent] = None, previous_targets: Optional[list[Any]] = None,
    ) -> None:
        """Open the interactive "you may pay {E}×N. If you do, `<effect>`."
        choice (RULE 122, Aether Chaser-shaped) — the resolve-time energy
        sibling of the shock-land pay-life choice. Assumes the caller
        (`PayEnergyThenEffect`) already checked the player can afford it.

        ``variable`` — "you may pay one or more {E}" (Rampaging Aetherhood): ``amount`` is the minimum, the offer is
        one ``pay_x:<n>`` option per affordable amount (largest first) and the paid n binds the branch's ``"x"``."""
        self.state.pending_energy_payment = {
            "player_id": player.id,
            "amount": int(amount),
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
            "variable": bool(variable),
            "targets": list(targets or []),
            "trigger_event": trigger_event,
            "previous_targets": list(previous_targets or []),
            "acting_player_id": self.context.acting_player_id or self.context.resolving_controller_id or player.id,
            "source_incarnation": (self.context.resolving_source_incarnation
                                   if self.context.resolving_source_incarnation is not None
                                   else getattr(source, "zone_incarnation", None)),
        }
        if variable:
            held = int(player.counters.get("energy", 0))
            options = [
                {"id": f"{self.PAY_ENERGY_X_PREFIX}{n}", "label": f"{'{E}' * n} bezahlen" if n <= 8 else f"{n} {{E}} bezahlen"}
                for n in range(held, int(amount) - 1, -1)
            ]
            options.append({"id": "decline", "label": "Nicht bezahlen"})
            self.open_choice({
                "kind": "pay_energy_then", "player_id": player.id,
                "source_id": source.instance_id if source is not None else None,
                "source_name": source.name if source is not None else None,
                "energy_cost": int(amount),
                "prompt": "{E} bezahlen? (beliebig viele)", "options": options,
            })
            return
        pips = "{E}" * int(amount)
        self.open_choice({
            "kind": "pay_energy_then",
            "player_id": player.id,
            "source_id": source.instance_id if source is not None else None,
            "source_name": source.name if source is not None else None,
            "energy_cost": int(amount),
            "prompt": f"{pips} bezahlen?",
            "options": [
                {"id": "pay", "label": f"{pips} bezahlen"},
                {"id": "decline", "label": "Nicht bezahlen"},
            ],
        })

    @continuations.choice("pay_energy_then", answer=continuations.ANSWER_STR, rule="122")
    def _resume_pay_energy_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_energy_then` choice. ``answer == "pay"``
        spends the energy and resolves the follow-up effects; anything else
        (``None``/``"decline"``) does neither. A variable payment answers ``pay_x:<n>``."""
        pending = self.state.pending_energy_payment
        self.state.pending_energy_payment = None
        if pending is None or answer is None:
            return
        player = self.state.player_by_id(pending["player_id"])
        specs = pending["effect_specs"]
        amount = pending["amount"]
        if pending.get("variable"):
            if not answer.startswith(self.PAY_ENERGY_X_PREFIX):
                return
            try:
                amount = int(answer[len(self.PAY_ENERGY_X_PREFIX):])
            except ValueError:
                return
            if amount < pending["amount"]:
                return
            specs = _substitute_x_specs(specs, amount)
        elif answer != "pay":
            return
        if player.counters.get("energy", 0) < amount:
            return  # energy changed since the offer — decline by default
        self.add_player_counters(player, -amount, "energy")
        # RULE 608.2: the branch continues the same resolving ability;
        # its pronouns retain this firing's object across the choice.
        outer_event = self.context.trigger_event
        outer_previous = self.context.previous_targets
        outer_acting = self.context.acting_player_id
        outer_incarnation = self.context.resolving_source_incarnation
        self.context.trigger_event = pending.get("trigger_event")
        self.context.previous_targets = pending.get("targets") or pending.get("previous_targets", [])
        self.context.acting_player_id = pending.get("acting_player_id")
        self.context.resolving_source_incarnation = pending.get("source_incarnation")
        try:
            self._apply_effect_specs(specs, pending["source"], pending.get("targets") or None)
        finally:
            self.context.trigger_event = outer_event
            self.context.previous_targets = outer_previous
            self.context.acting_player_id = outer_acting
            self.context.resolving_source_incarnation = outer_incarnation

    def _request_pay_cost_then(
        self,
        player: Player,
        cost: "ActivationCost",
        effect_specs: list[dict],
        source: Optional[GameObject],
        else_effect_specs: Optional[list[dict]] = None,
        prompt: Optional[str] = None,
        targets: Optional[list[Any]] = None,
        then_trigger_specs: Optional[list[dict]] = None,
        then_trigger_modes: Optional[dict[str, Any]] = None,
        then_trigger_event: Optional[GameEvent] = None,
        captured_previous: Optional[list[Any]] = None,
        x_color: Optional[str] = None,
        x_cap: Optional[int] = None,
    ) -> None:
        """Open the interactive "you may pay ``cost``. If you do, `<effect>`."
        choice (RULE 118.3-style optional payment mid-resolution).

        The general form of the already-shipped, energy-only
        `_request_pay_energy_then` (Aether Chaser) and the *optional* mirror
        of `_request_sacrifice_unless_pay` — same `_can_pay_player_cost`/
        `_pay_player_cost` machinery all three share, so an arbitrary
        `ActivationCost` (mana, life, discard, sacrifice) works without a
        fourth parallel payment path. Covers Mana Vault's upkeep untap and
        Wandering Archaic's per-opponent {2} tax.

        ``else_effect_specs`` is the "**If you don't**, `<effect>`." branch
        (Wandering Archaic: the opponent declining is what lets you copy
        their spell). A player who *can't* pay is never asked — the
        else-branch resolves straight away, the same "don't stall on a
        choice nobody can act on" shortcut ward and `counter_unless_pays`
        take.

        ``targets`` are handed to whichever branch resolves — a reflexive
        trigger's already-baked "that spell" (Wandering Archaic's copy),
        which the branch effects would otherwise never see, since they are
        built fresh at answer time rather than sitting on the stack item.

        ``then_trigger_specs`` is RULE 603.12's "**When you do**, `<targeted
        payoff>`." — instead of continuing the original resolution with
        its announced targets like ``effect_specs``, a paid cost enqueues
        these as their own `TriggeredAbility` on `pending_triggers`, so the
        ordinary placement path gathers targets and it goes on the stack.
        ``then_trigger_event`` is the *outer* trigger's event, carried so a
        payoff that names it ("that player") can read it back.

        ``captured_previous`` (MEC-52 — Back from the Brink) bakes in the
        RULE 608.2 referent (`GameContext.previous_targets`, the graveyard
        card whose mana cost this ``cost`` was priced off) so the paid
        branch's `copy_permanent` ``referent="previous"`` still resolves
        against it once the choice is *answered* — same re-seed idiom
        `_resume_villainous_choice` uses.
        """
        specs = [dict(d) for d in effect_specs]
        else_specs = [dict(d) for d in (else_effect_specs or [])]
        then_trigger = [dict(d) for d in (then_trigger_specs or [])]
        modal_trigger = dict(then_trigger_modes or {})
        # ENG-48 / RULE 107.3a: "you may pay {X}" — the payer announces X as
        # part of paying, so the offer is one option per affordable value.
        x_max = self._max_payable_x(player, cost, source, x_color) if cost.mana.has_variable else None
        if x_max is not None and x_cap is not None:
            x_max = min(x_max, max(x_cap, 0))  # "X is less than or equal to the amount of life you gained"
        if not self._can_pay_player_cost(player, cost, source):
            saved = self.context.previous_targets
            if captured_previous is not None:
                self.context.previous_targets = list(captured_previous)
            try:
                self._apply_effect_specs(
                    _substitute_x_specs(else_specs, None if x_max is None else 0), source, targets,
                )
            finally:
                self.context.previous_targets = saved
            return
        self.state.pending_pay_cost_then = {
            "player_id": player.id,
            "cost": cost,
            "effect_specs": specs,
            "else_effect_specs": else_specs,
            "source": source,
            "targets": list(targets or []),
            "then_trigger_specs": then_trigger,
            "then_trigger_modes": modal_trigger,
            "then_trigger_event": then_trigger_event,
            "captured_previous": list(captured_previous) if captured_previous else None,
            "x_max": x_max,
            "x_color": x_color,
            # RULE 109.5: the "if you do" effects belong to whoever the body was run as.
            "acting_player_id": self.context.acting_player_id or self.context.resolving_controller_id,
            # RULE 400.7: resumed branches still refer to the original source visit.
            "source_incarnation": (self.context.resolving_source_incarnation
                                   if self.context.resolving_source_incarnation is not None
                                   else getattr(source, "zone_incarnation", None)),
            "revealed_card": self.context.revealed_card,
        }
        cost_label = cost.label()
        # A free "you may …" (no cost to name, e.g. a Tempting offer) reads Ja/Nein, not " bezahlen".
        if not cost_label:
            pay_options = [{"id": "pay", "label": "Ja"}]
        elif x_max is None:
            pay_options = [{"id": "pay", "label": f"{cost_label} bezahlen"}]
        else:
            # Largest X first: it's almost always the reason to pay at all.
            pay_options = [
                {"id": f"{PAY_X_OPTION_PREFIX}{x}", "label": f"X = {x}: {cost_label} bezahlen", "x": x}
                for x in range(x_max, -1, -1)
            ]
        self.open_choice({
            "kind": "pay_cost_then",
            "player_id": player.id,
            "source_id": source.instance_id if source is not None else None,
            "source_name": source.name if source is not None else None,
            "cost_label": cost_label,
            "prompt": prompt or f"{cost_label} bezahlen?",
            "options": [*pay_options, {"id": "decline", "label": "Nein" if not cost_label else "Nicht bezahlen"}],
        })

    def _max_payable_x(
        self, player: Player, cost: ActivationCost, source: Optional[GameObject] = None,
        x_color: Optional[str] = None,
    ) -> int:
        """The largest X (up to `PAY_COST_THEN_MAX_X`) ``player`` can pay
        ``cost`` with — 0 when only X = 0 is affordable. Affordability is
        monotone in X, so the scan stops at the first miss."""
        best = 0
        for x in range(1, PAY_COST_THEN_MAX_X + 1):
            if not self._can_pay_player_cost(player, _cost_with_x(cost, x, x_color), source):
                break
            best = x
        return best

    @staticmethod
    def _pay_cost_then_x(answer: Optional[str], x_max: int) -> Optional[int]:
        """The X a `pay_cost_then` answer announces, or ``None`` for a
        malformed/out-of-range one (treated as declining). A bare ``"pay"``
        means the largest X offered."""
        if answer == "pay":
            return x_max
        if not answer or not answer.startswith(PAY_X_OPTION_PREFIX):
            return None
        try:
            x = int(answer[len(PAY_X_OPTION_PREFIX):])
        except ValueError:
            return None
        return x if 0 <= x <= x_max else None
    @continuations.choice("pay_cost_then", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_pay_cost_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_cost_then` choice. ``answer == "pay"``
        charges the cost and resolves the "if you do" effects; anything else
        resolves the "if you don't" branch (usually empty)."""
        pending = self.state.pending_pay_cost_then
        self.state.pending_pay_cost_then = None
        if pending is None:
            return
        player = self.state.player_by_id(pending["player_id"])
        cost = pending["cost"]
        x_max = pending.get("x_max")
        x: Optional[int] = None
        if x_max is not None:
            # ENG-48: the announced X prices the cost and is substituted into
            # whichever branch runs (RULE 107.3a) — the declined branch sees 0.
            x = self._pay_cost_then_x(answer, x_max)
            paying = x is not None
            if paying:
                cost = _cost_with_x(cost, x, pending.get("x_color"))
        else:
            paying = answer == "pay"
        if not paying or not self._can_pay_player_cost(player, cost, pending["source"]):
            # Re-checked: the board can have changed since the offer was made.
            self._apply_pay_cost_branch(
                pending, _substitute_x_specs(pending["else_effect_specs"], None if x_max is None else 0),
            )
        else:
            self._pay_player_cost(player, cost, pending["source"])
            if x is not None:
                pending = {
                    **pending,
                    "effect_specs": _substitute_x_specs(pending["effect_specs"], x),
                    "then_trigger_specs": _substitute_x_specs(pending["then_trigger_specs"], x),
                    "then_trigger_modes": _substitute_x_modes(pending["then_trigger_modes"], x),
                }
            if self.state.pending_choice is not None:
                # RULE 117.12 / 608.2c: "you may sacrifice a creature. If you do, …" — the *choice* of what to
                # sacrifice is part of paying, so the "if you do" half waits until it is answered. Parked as a
                # frame `resume_deferred_effects` runs once nothing is pending (the mass sweep advances then too).
                self.state.deferred_effects.append({"kind": self.DEFERRED_PAID_COST, "pending": pending})
                return
            self._finish_paid_cost_then(pending)
        # PAR-13: if this single-player choice is one leg of a mass
        # `_request_each_player_pay_or` sweep, move on to whoever's next —
        # a no-op for every ordinary (non-mass) `pay_cost_then` caller,
        # since that dict is only ever populated by the mass primitive.
        if self._pending_each_player_pay_or is not None:
            self._advance_each_player_pay_or()

    def _apply_pay_cost_branch(self, pending: dict[str, Any], specs: list[dict]) -> None:
        """Run one branch of a `pay_cost_then` ("if you do" / "if you don't") as the player it was run for."""
        targets = pending.get("targets") or None
        captured = pending.get("captured_previous")
        outer_acting = self.context.acting_player_id
        self.context.acting_player_id = pending.get("acting_player_id")
        outer_event = self.context.trigger_event
        self.context.trigger_event = pending.get("then_trigger_event") or outer_event
        outer_incarnation = self.context.resolving_source_incarnation
        self.context.resolving_source_incarnation = pending.get("source_incarnation")
        outer_revealed = self.context.revealed_card
        self.context.revealed_card = pending.get("revealed_card")
        try:
            if not captured:
                self._apply_effect_specs(specs, pending["source"], targets)
                return
            saved = list(self.context.previous_targets)
            self.context.previous_targets = list(captured)
            try:
                self._apply_effect_specs(specs, pending["source"], targets)
            finally:
                self.context.previous_targets = saved
        finally:
            self.context.acting_player_id = outer_acting
            self.context.trigger_event = outer_event
            self.context.revealed_card = outer_revealed
            self.context.resolving_source_incarnation = outer_incarnation

    def _finish_paid_cost_then(self, pending: dict[str, Any]) -> None:
        """The paid half of a `pay_cost_then`: the "if you do" effects, then the reflexive trigger."""
        self._apply_pay_cost_branch(pending, pending["effect_specs"])
        self._enqueue_pay_cost_then_trigger(pending)

    def _request_exile_source_then(
        self, player: Player, source: GameObject, then_trigger_specs: list[dict],
        prompt: Optional[str] = None, event: Optional[GameEvent] = None,
    ) -> None:
        """Offer ``You may exile this card. If you do, ...`` during a
        resolution.  This is intentionally separate from ``ActivationCost``:
        a dies trigger's source has already moved to its owner's graveyard.
        The follow-up is a reflexive trigger so its target is chosen only
        after the source was actually exiled (RULE 603.11)."""
        if source.zone != Zone.GRAVEYARD:
            return
        self._pending_exile_source_then = {
            "player_id": player.id,
            "source": source,
            "then_trigger_specs": [dict(d) for d in then_trigger_specs],
            # RULE 608.2h: the firing (dies) event rides along so the reflexive payoff reads the source's
            # last-known characteristics ("~'s power") from it.
            "event": event,
        }
        self.open_choice({
            "kind": "exile_source_then",
            "player_id": player.id,
            "prompt": prompt or f"{source.name} ins Exil schicken?",
            "options": [
                {"id": "exile", "label": "Ins Exil schicken"},
                {"id": "decline", "label": "Nicht ins Exil schicken"},
            ],
        })

    @continuations.choice("exile_source_then", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_exile_source_then(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        self.state.pending_choice = None
        pending = self._pending_exile_source_then
        self._pending_exile_source_then = None
        if pending is None or answer != "exile":
            return
        source = pending["source"]
        # Re-check the zone: another replacement or response may have moved it.
        if source.zone != Zone.GRAVEYARD:
            return
        self.exile(source)
        self.enqueue_reflexive_trigger(pending["then_trigger_specs"], source, pending.get("event"))
    def enqueue_reflexive_trigger(
        self,
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        event: Optional[GameEvent] = None,
        modes: Optional[dict[str, Any]] = None,
        controller_id: Optional[str] = None,
        condition: Optional[dict[str, Any]] = None,
        source_incarnation: Optional[int] = None,
    ) -> None:
        """RULE 603.12: "`<effect with its own condition>`. **When you
        do**, `<targeted payoff>`." fires the payoff as its *own* fresh
        triggered ability rather than resolving it off-stack — the whole
        point being that ``effect_specs``' own RULE 115 target (if any) has
        to go through the ordinary placement path (`put_triggers_on_stack`
        → `_place_triggers`) to be gathered at all; a bare `_apply_effect_
        specs` call resolves immediately and could never open that choice.
        Built fresh per the `TriggeredAbility` docstring's own sanctioned
        "bake per-firing data in at the call site" pattern and queued on
        `pending_triggers`, so it's picked up the next time triggers are
        placed (normally right after the caller's own resolution finishes).

        Two real callers: `_enqueue_pay_cost_then_trigger` (a paid optional
        cost's own "when you do" — RULE 603.12 proper) and PAR-30's
        `ExchangeControlThenCopyTokenEffect` (Arteeoh, Dread Scavenger — "if
        you do" gated on whether a *targeted effect* actually happened,
        not a cost payment).
        """
        if not effect_specs and not modes:
            return
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        controller_id = controller_id or getattr(source, "controller_id", None) or self.state.active_player.id
        if condition is not None:
            from ..static_conditions import condition_holds
            self.context.recompute()

            from ..effect_conditions import pin_source_reference

            condition = pin_source_reference(condition, source, source_incarnation)
            if not condition_holds(condition, self.state, source, controller_id):
                return  # RULE 603.4 / 603.12: no trigger and no target announcement.
            # Gate the complete body once at resolution, retaining its target
            # specs through the existing ConditionalEffect/seq composition.
            effect_specs = [{"type": "seq", "params": {"effects": effect_specs}, "condition": condition}]

        built = build_effects(
            [EffectSpec(type=d["type"], params=dict(d.get("params") or {}), condition=d.get("condition")) for d in effect_specs],
            source,
        )
        modal_options = None
        modal = dict(modes or {})
        if modal:
            modal_options = []
            for option in modal.get("options") or []:
                modal_options.append({
                    "effects": build_effects(
                        [EffectSpec(type=d["type"], params=dict(d.get("params") or {}), condition=d.get("condition")) for d in option], source,
                    ),
                    "description": "",
                })
            descriptions = list(modal.get("descriptions") or [])
            for index, option in enumerate(modal_options):
                option["description"] = descriptions[index] if index < len(descriptions) else f"Modus {index + 1}"
        ability = TriggeredAbility(
            trigger_event=getattr(event, "type", None) or EventType.SPELL_RESOLVED,
            effects=built,
            source=source,
            controller_id=controller_id,
            optional=False,  # the "may"/"if" was already decided; the payoff itself is not
            description=getattr(source, "name", "") or "reflexive ability",
            modes=modal_options,
            modes_or_both=bool(modal.get("or_both", False)),
            modes_choose=int(modal.get("choose", 1)),
            modes_at_least=bool(modal.get("at_least", False)),
            modes_repeatable=bool(modal.get("repeatable", False)),
        )
        # Carry the outer event so a payoff naming it ("that player") reads
        # it off its own `StackItem.trigger_event`.
        stamped_event = event if isinstance(event, GameEvent) else GameEvent(EventType.SPELL_RESOLVED)
        self.pending_triggers.append((ability, stamped_event))
    def _enqueue_pay_cost_then_trigger(self, pending: dict[str, Any]) -> None:
        """RULE 603.12: a paid "you may `<cost>`" whose card continues "When
        you do, `<targeted payoff>`" fires that payoff via
        `enqueue_reflexive_trigger`."""
        self.enqueue_reflexive_trigger(
            pending.get("then_trigger_specs") or [], pending.get("source"),
            pending.get("then_trigger_event"), pending.get("then_trigger_modes"),
        )
    def _request_pay_life_or_return_to_library(
        self, player: Player, objs: list[GameObject], amount: int = 4,
    ) -> None:
        """"For each of those cards, pay 4 life or put the card on top of
        your library." (Sylvan Library, MEC-40) — a genuine per-card
        mandatory either/or decision (RULE 601.2h-style, not "may"),
        offered one card at a time (`_open_pay_life_or_return_choice`
        re-opens for the next until ``objs`` is exhausted), the same
        "resolve one, re-open for the rest" shape `_request_choose_objects`
        uses for a multi-pick.
        """
        queue = [o.instance_id for o in objs if o is not None]
        if not queue:
            return
        self._open_pay_life_or_return_choice(player, queue, amount)
    def _open_pay_life_or_return_choice(
        self, player: Player, queue: list[int], amount: int,
    ) -> None:
        obj_id = queue[0]
        obj = self.state.find_object(obj_id)
        if obj is None or obj not in player.hand:
            # Left the zone some other way since being queued (rare) —
            # nothing left to ask about this one; move on to the rest.
            self._continue_pay_life_or_return(player, queue[1:], amount)
            return
        self.open_choice({
            "kind": "pay_life_or_return_to_library",
            "player_id": player.id,
            "instance_id": obj_id,
            "amount": amount,
            "remaining": queue[1:],
            "prompt": f"{amount} Leben zahlen oder {obj.name} auf die Bibliothek "
                      f"zurücklegen?",
            "options": [
                {"id": "pay", "label": f"{amount} Leben zahlen"},
                {"id": "return", "label": "Auf die Bibliothek zurücklegen"},
            ],
        })
    def _continue_pay_life_or_return(
        self, player: Player, remaining: list[int], amount: int,
    ) -> None:
        if remaining:
            self._open_pay_life_or_return_choice(player, remaining, amount)
    @continuations.choice(
        "pay_life_or_return_to_library",
        answer=continuations.ANSWER_STR,
        decline="return",
        rule="118.3",
    )
    def _resume_pay_life_or_return_to_library(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `pay_life_or_return_to_library` choice.
        ``answer == "pay"`` pays the life; anything else (including a
        missing/invalid answer — a mandatory choice) puts the card back."""
        player = self.state.player_by_id(choice["player_id"])
        amount = choice["amount"]
        if answer == "pay":
            self.lose_life(player, amount, cause="cost")
        else:
            obj = self.state.find_object(choice["instance_id"])
            if obj is not None and obj in player.hand:
                player.hand.remove(obj)
                obj.zone = Zone.LIBRARY
                player.library.append(obj)
        self._continue_pay_life_or_return(player, choice.get("remaining") or [], amount)
    def _request_library_position(self, owner: Player, obj: GameObject) -> None:
        """"The owner of … puts it on their choice of the top or bottom of their library." (Plan for All Outcomes) — the
        owner, not the ability's controller, chooses; the permanent stays where it is until the answer arrives.
        A "you may" is the trigger's own confirmation, not part of this choice (Arashin Sovereign)."""
        self.open_choice({
            "kind": "library_position",
            "player_id": owner.id,
            "instance_id": obj.instance_id,
            "prompt": f"{obj.name}: oben oder unten auf die Bibliothek legen?",
            "options": [
                {"id": "top", "label": "Oben auf die Bibliothek"},
                {"id": "bottom", "label": "Unter die Bibliothek"},
            ],
        })
    @continuations.choice("library_position", answer=continuations.ANSWER_STR, decline="top", rule="401.4")
    def _resume_library_position(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `library_position` choice (RULE 401.4: the owner decides top or bottom); a missing or invalid
        answer is the top, the safer default for the owner."""
        obj = self.state.find_object(choice["instance_id"])
        if obj is None:
            return
        position = "bottom" if answer == "bottom" else "top"
        if obj.zone == Zone.STACK:
            self.move_spell_off_stack(obj, f"library_{position}")  # Endless Detour's spell target
        elif obj.zone == Zone.LIBRARY:
            # A countered spell held on top meanwhile (Hinder): placed at the chosen end now (RULE 701.5g replaced).
            owner = self.state.player_by_id(obj.owner_id)
            if obj in owner.library:
                owner.library.remove(obj)
            if position == "bottom":
                owner.library.insert(0, obj)
            else:
                owner.library.append(obj)
        else:
            self.return_to_library(obj, position)
    def _request_each_player_pay_or(
        self,
        cost: "ActivationCost",
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        scope: str = "each_player",
        effect_targets: str = "decliner",
    ) -> None:
        """RULE 101.4's APNAP mass "unless" (PAR-13 — "Each player loses N
        life unless they `<pay cost>`.", Bellowing Mauler/Lim-Dûl's Hex/
        Tomb of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon
        rooms): every living player, starting with the active player and
        proceeding in turn order, is asked in turn whether to pay ``cost``;
        anyone who doesn't (or can't) gets ``effect_specs`` applied to
        *them* — not the ability's controller, which is why ``targets``
        (not the effects' own untargeted-controller default) carries each
        player through `_request_pay_cost_then`.

        ``scope`` (MEC-43, Acererak the Archlich — "for each opponent,
        `<effect>` unless that player `<pays>`.") is ``"each_player"``
        (default, unchanged) or ``"each_opponent"`` — excludes ``source``'s
        own controller from the sweep entirely. ``effect_targets`` is
        ``"decliner"`` (default, unchanged) or ``"controller"`` — Acererak's
        "**you** create a token" lands on the ability's own controller
        regardless of who declined, so no ``targets`` are threaded through
        and each inner spec resolves against its own untargeted-controller
        default instead.

        Built as a chain of ordinary single-player `_request_pay_cost_then`
        choices rather than a new chooser: each one either opens a real
        `pending_choice` (this method returns, and `resolve_pay_cost_then_
        choice` calls `_advance_each_player_pay_or` again once it's
        answered) or resolves synchronously because that player can't pay
        at all — the same "don't stall on a choice nobody can act on"
        shortcut every other pay-or-lose-it chooser takes, which is what
        lets this loop keep going without a choice for every player who
        has no way to pay.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        controller_id = getattr(source, "controller_id", None)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
            and (scope != "each_opponent" or self.state.players[(start + i) % n].id != controller_id)
            # "At the beginning of combat on each opponent's turn, **they** may pay {2}." (Jace, Multiverse Architect) —
            # only the active player is asked.
            and (scope != "active_player" or (start + i) % n == start)
        ]
        self._pending_each_player_pay_or = {
            "remaining_ids": order,
            "cost": cost,
            "effect_specs": [dict(d) for d in effect_specs],
            "source": source,
            "effect_targets": effect_targets,
        }
        self._advance_each_player_pay_or()
    def _advance_each_player_pay_or(self) -> None:
        """Ask the next still-pending player in a `_request_each_player_pay_or`
        sweep, or clear it once everyone has answered."""
        pending = self._pending_each_player_pay_or
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        effect_targets = pending.get("effect_targets", "decliner")
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost:
                continue
            self._request_pay_cost_then(
                player, pending["cost"], [], pending["source"],
                else_effect_specs=pending["effect_specs"],
                targets=[player] if effect_targets == "decliner" else None,
            )
            if self.state.pending_choice is not None:
                return  # a real choice opened — resumed via _resume_pay_cost_then
        self._pending_each_player_pay_or = None
    def _request_all_players_decline_or(
        self,
        cost: "ActivationCost",
        effect_specs: list[dict[str, Any]],
        source: Optional[GameObject],
        controller_id: str,
        paid_effect_specs: Optional[list[dict[str, Any]]] = None,
        opponents_only: bool = False,
    ) -> None:
        """RULE 118.3-adjacent multi-player tax: "Any player may pay
        `<cost>`. If no one does, `<effect>`." (Rhystic Circle, MEC-30).

        PAR-208 (RULE 608.2c): ``paid_effect_specs`` is the printed "**If a player does**, `<effect>`" payoff (Brain
        Gorgers, Argothian Wurm, Clackbridge Troll): it runs once, for ``controller_id``, as soon as the first player
        pays -- and the sweep ends there, exactly as for the "if no one does" form. ``opponents_only`` is "any
        **opponent** may" (Desecration Demon, Innocent Traveler): the controller is not asked.

        Every living player, starting with the active player and
        proceeding in turn order, is asked in turn whether to pay ``cost``.
        The *first* player to actually pay cancels the whole thing —
        ``effect_specs`` never resolves at all, since *someone* paid to
        stop it. Only once *every* player has declined (or can't pay —
        the same "don't stall on a choice nobody can act on" shortcut
        `_request_each_player_pay_or` takes) does ``effect_specs`` resolve,
        applied *once*, to ``controller_id`` (the ability's own controller
        — "you" in the printed text, not whoever happened to decline
        last).

        This is the aggregate-outcome mirror image of `request_each_player_
        pay_or` (PAR-13's "each player loses N life unless they pay" —
        that one applies its effect *per decliner*, and a payment simply
        skips that one player while the sweep continues regardless; this
        one applies its effect *once*, and a single payment cancels the
        *entire* sweep). The two can't share one advance loop for exactly
        that reason, but both are built the same way underneath: a chain
        of ordinary single-player pay/decline choices over the same
        `_can_pay_player_cost`/`_pay_player_cost` machinery.
        """
        start = self.state.active_player_index
        n = len(self.state.players)
        order = [
            self.state.players[(start + i) % n].id
            for i in range(n)
            if not self.state.players[(start + i) % n].has_lost
            and not (opponents_only and self.state.players[(start + i) % n].id == controller_id)
        ]
        self.state.pending_all_decline_or = {
            "remaining_ids": order,
            "cost": cost,
            "effect_specs": [dict(d) for d in effect_specs],
            "paid_effect_specs": [dict(d) for d in paid_effect_specs or []],
            "source": source,
            "controller_id": controller_id,
            "source_incarnation": (self.context.resolving_source_incarnation
                                   if self.context.resolving_source_incarnation is not None
                                   else getattr(source, "zone_incarnation", None)),
            "then_trigger_event": self.context.trigger_event,
            "revealed_card": self.context.revealed_card,
        }
        self._advance_all_decline_or()
    def _advance_all_decline_or(self) -> None:
        """Ask the next still-pending player in a `request_all_players_
        decline_or` sweep; once nobody's left (everyone declined or
        couldn't pay), resolve the "if no one does" effect and clear it."""
        pending = self.state.pending_all_decline_or
        if pending is None:
            return
        remaining: list[str] = pending["remaining_ids"]
        cost = pending["cost"]
        while remaining:
            player_id = remaining.pop(0)
            try:
                player = self.state.player_by_id(player_id)
            except (KeyError, ValueError):
                continue
            if player.has_lost or not self._can_pay_player_cost(player, cost):
                continue
            cost_label = cost.label()
            self.open_choice({
                "kind": "all_decline_or",
                "player_id": player.id,
                "prompt": f"{cost_label} bezahlen, um dies zu verhindern?",
                "options": [
                    {"id": "pay", "label": f"{cost_label} bezahlen"},
                    {"id": "decline", "label": "Nicht bezahlen"},
                ],
            })
            return  # a real choice opened — resumed via _resume_all_decline_or
        # Every remaining player declined or couldn't pay — the sweep is over.
        self.state.pending_all_decline_or = None
        try:
            controller = self.state.player_by_id(pending["controller_id"])
        except (KeyError, ValueError):
            return
        self._apply_effect_specs(pending["effect_specs"], pending["source"], targets=[controller])
    @continuations.choice("all_decline_or", answer=continuations.ANSWER_STR, rule="118.3")
    def _resume_all_decline_or(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `all_decline_or` choice (`request_all_players_
        decline_or`). ``answer == "pay"`` charges that player and cancels
        the whole sweep — nothing else happens, since someone paid to stop
        it. Anything else (decline, or a re-check finding they no longer
        can pay — the board can have changed since the offer was made)
        moves on to the next player."""
        pending = self.state.pending_all_decline_or
        if pending is None:
            return
        if answer == "pay":
            try:
                player = self.state.player_by_id(choice["player_id"])
            except (KeyError, ValueError):
                player = None
            if player is not None and self._can_pay_player_cost(player, pending["cost"]):
                self._pay_player_cost(player, pending["cost"])
                self.state.pending_all_decline_or = None
                if pending.get("paid_effect_specs"):
                    # RULE 608.2c: selecting the sacrifice/discard completes the cost before the payoff.
                    # Reuse the single-player paid-cost continuation, retaining the ability's controller.
                    paid = {
                        **pending, "effect_specs": pending["paid_effect_specs"],
                        "acting_player_id": pending["controller_id"],
                    }
                    if self.state.pending_choice is not None:
                        self.state.deferred_effects.append({"kind": self.DEFERRED_PAID_COST, "pending": paid})
                    else:
                        self._finish_paid_cost_then(paid)
                return
        self._advance_all_decline_or()
