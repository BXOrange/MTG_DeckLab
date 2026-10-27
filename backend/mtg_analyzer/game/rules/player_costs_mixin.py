"""Validate and pay player costs during resolution."""
from __future__ import annotations

from typing import Any, Optional
from ...models.game.game_object import GameObject
from ...models.game.player import Player
from ..costs import DISCARD_HAND, REMOVE_COUNTERS_ANY_KIND, ActivationCost
from .. import continuations
from .misc_helpers import (
    _names_other_word,
    _matches_permanent_type,
)


class PlayerCostsMixin:
    """Validate and pay player costs during resolution."""
    def _can_pay_player_cost(
        self, player: Player, cost: ActivationCost, source: Optional[GameObject] = None
    ) -> bool:
        """Whether ``player`` can pay ``cost`` out of their own resources.

        The same per-component affordability checks
        `GameEngine._can_pay_activation_cost` uses for an activated
        ability's cost, minus the tap/untap-source and remove-counters
        components — those are tied to a specific permanent's own state,
        which doesn't apply to any of the "pay this or else" costs a *rule
        or resolving effect* asks a player for: ward (RULE 702.21), and
        cumulative upkeep-shaped "sacrifice ~ unless you pay `<cost>`"
        (`sacrifice_unless_pay`). Those are always paid from the player's
        own resources (mana, life, hand, permanents they control), never
        "this permanent".
        """
        if cost.mana.symbols and not player.mana_pool.can_pay(
            cost.mana, life_available=player.life
        ):
            from ..game_engine import GameEngine
            from ..mana_potential import find_tap_plan

            # RULE 117.12b: a resolving payment permits mana abilities without priority.
            # Reuse these rules/listeners and preserve the live turn cursor.
            if find_tap_plan(GameEngine(self.state, rules=self), player, cost.mana) is None:
                return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.discard and cost.discard != DISCARD_HAND and len(self._discard_pool(player, cost, source)) < cost.discard:
            return False
        if cost.sacrifice and not any(
            _matches_permanent_type(obj, cost.sacrifice)
            and not (obj is source and _names_other_word(cost.sacrifice))
            for obj in self.state.permanents_controlled_by(player.id)
        ):
            return False
        if cost.sacrifice_count and isinstance(cost.sacrifice_count[0], int):
            # "sacrifice two Blood tokens" (Strefan) — enough matching, sacrificable permanents to pay it all.
            needed, word = cost.sacrifice_count
            if sum(
                1 for obj in self.state.permanents_controlled_by(player.id)
                if _matches_permanent_type(obj, word) and not obj.cant_be_sacrificed_this_turn
            ) < needed:
                return False
        # RULE 122 energy: "unless you pay an amount of {E} equal to its
        # mana value." (Volatile Stormdrake, MEC-43) — the same
        # affordability check `GameEngine._can_pay_activation_cost` already
        # makes for an activated ability's own `pay_energy` component; this
        # shared pay-or-lose-it machinery (ward/sacrifice_unless_pay/
        # counter_unless_pays) had never gained it before, since no prior
        # card printed an energy-costed "unless" clause.
        if cost.pay_energy and player.counters.get("energy", 0) < cost.pay_energy:
            return False
        # "…sacrifice a nonland permanent of their choice or discard a
        # card." (Tergrid's Lantern, MEC-43 round 4E) — payable when
        # *either* half is (the payer's own later choice, `_pay_player_
        # cost`), not both.
        if cost.sacrifice_or_discard and not self._can_sacrifice_or_discard(player):
            return False
        if cost.collect_evidence and not self.collect_evidence_possible(
            player, cost.collect_evidence
        ):
            return False
        if cost.forage and not self.forage_possible(player):
            return False
        if cost.blight and not self.blight_possible(player):
            return False
        if source is not None and self._source_counter_removal(source, cost) is False:
            return False
        return True
    def _source_counter_removal(
        self, source: GameObject, cost: ActivationCost
    ) -> Optional[tuple[str, int]]:
        """The ``(kind, count)`` a "you may remove a `<kind>` counter from ~" payment takes off
        ``source`` (PAR-140 — Biting-Palm Ninja, Kappa Tech-Wrecker), ``None`` when ``cost`` has no
        such component, ``False`` when ``source`` doesn't carry enough. A fixed count only: the
        X/any-number sentinels need an announcement `pay_cost_then` doesn't have, so they stay
        unpayable here rather than guessed at. **Documented simplification:** "a counter" of no
        named kind ("remove a counter from ~", Slumbering Walker) takes the source's first kind."""
        if not cost.remove_counters or cost.remove_counters_from:
            return None
        kind, count = cost.remove_counters
        if count <= 0:
            return False
        counters = {k: v for k, v in (source.counters or {}).items() if v and v > 0}
        if kind == REMOVE_COUNTERS_ANY_KIND:
            kind = next(iter(counters), "")
        if counters.get(kind, 0) < count:
            return False
        return kind, count
    def _can_sacrifice_or_discard(self, player: Player) -> bool:
        """Whether ``player`` could pay a `sacrifice_or_discard` cost right
        now — a nonland permanent to sacrifice, or a card in hand."""
        has_nonland = any(
            _matches_permanent_type(obj, "nonland")
            for obj in self.state.permanents_controlled_by(player.id)
        )
        return has_nonland or bool(player.hand)
    def _discard_pool(
        self, player: Player, cost: ActivationCost, source: Optional[GameObject] = None
    ) -> list[GameObject]:
        """The hand cards that can pay ``cost``'s discard component -- the whole hand for a plain
        "discard a card", the type-line-filtered subset for "discard a land card" (ENG-49)."""
        from ..game_engine import GameEngine  # function-scoped: import cycle

        return GameEngine(self.state, rules=self)._discard_cost_pool(
            player, None, cost.discard_filter, getattr(source, "name", None),
        )

    def _pay_player_cost(
        self, player: Player, cost: ActivationCost, source: Optional[GameObject] = None
    ) -> None:
        """Charge ``player`` a cost's components — reuses the same per-kind
        payment primitives `GameEngine.activate_ability` charges an activated
        ability's cost with. The payment half of `_can_pay_player_cost`."""
        if cost.mana.symbols:
            if not player.mana_pool.can_pay(cost.mana, life_available=player.life):
                from ..game_engine import GameEngine

                GameEngine(self.state, rules=self).auto_tap_for(player, cost=cost.mana)
            life_spent = player.mana_pool.pay(cost.mana, life_available=player.life)
            self.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.lose_life(player, cost.pay_life, cause="cost")
        if cost.discard and cost.discard_filter and cost.discard != DISCARD_HAND:
            # RULE 601.2b / 118.3: "discard a land card" is the payer's own pick among the cards that
            # qualify (Mox Diamond's "you may discard a land card instead"); forced when only
            # ``cost.discard`` of them are in hand. Pausing here is fine: the "if you do" half waits
            # for it (`_resume_pay_cost_then` parks `DEFERRED_PAID_COST`).
            self._request_choose_objects(
                player, self._discard_pool(player, cost, source), "discard", count=cost.discard,
                prompt="Wähle eine Karte zum Abwerfen", source=source,
            )
        elif cost.discard:
            self.discard(player, len(player.hand) if cost.discard == DISCARD_HAND else cost.discard)
        if cost.sacrifice:
            # "another"/"other …": the source is not a legal pick (RULE 109.5).
            self.sacrifice(
                player, cost.sacrifice, 1, exclude=source if _names_other_word(cost.sacrifice) else None, source=source,
            )
        if cost.sacrifice_count and isinstance(cost.sacrifice_count[0], int):
            self.sacrifice(player, cost.sacrifice_count[1], cost.sacrifice_count[0], source=source)
        if cost.pay_energy:
            self.add_player_counters(player, -cost.pay_energy, "energy")
        if cost.sacrifice_or_discard:
            self._pay_sacrifice_or_discard(player)
        if cost.collect_evidence:
            self.collect_evidence(player, cost.collect_evidence)
        if cost.forage:
            self.forage(player)
        if cost.blight:
            # RULE 701.68 — auto-pick (payment can't pause for a chooser).
            self.blight(player, cost.blight, interactive=False)
        if source is not None:
            removal = self._source_counter_removal(source, cost)
            if removal:
                self.add_counters(source, -removal[1], removal[0])
    def _pay_sacrifice_or_discard(self, player: Player) -> None:
        """Pay a `sacrifice_or_discard` cost component — the payer's own
        choice of *which* half (Tergrid's Lantern, MEC-43 round 4E). Forced
        (no prompt) when only one half is actually available, the same
        "asking would be theatre" idiom `_request_choose_objects` uses; with
        both available, opens the small dedicated `sacrifice_or_discard`
        choice below, then `_resume_sacrifice_or_discard` dispatches
        into the existing interactive `sacrifice`/`discard_choice`
        machinery (each already its own "which one" chooser)."""
        can_sacrifice = any(
            _matches_permanent_type(obj, "nonland")
            for obj in self.state.permanents_controlled_by(player.id)
        )
        can_discard = bool(player.hand)
        if can_sacrifice and can_discard:
            self.open_choice({
                "kind": "sacrifice_or_discard",
                "player_id": player.id,
                "prompt": "Eine bleibende Karte opfern oder eine Karte abwerfen?",
                "options": [
                    {"id": "sacrifice", "label": "Bleibende Karte opfern"},
                    {"id": "discard", "label": "Karte abwerfen"},
                ],
            })
            return
        if can_sacrifice:
            self.sacrifice(player, "nonland", 1)
        elif can_discard:
            self.discard_choice(player, 1)
    @continuations.choice(
        "sacrifice_or_discard",
        answer=continuations.ANSWER_STR,
        rule="701.21",
    )
    def _resume_sacrifice_or_discard(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `sacrifice_or_discard` choice — ``"sacrifice"``
        opens the interactive "which permanent" chooser, ``"discard"`` the
        interactive "which card" one; anything else re-checks both halves
        defensively (the board can have changed since the offer was made)
        rather than silently paying nothing."""
        player = self.state.player_by_id(choice["player_id"])
        if answer == "discard":
            self.discard_choice(player, 1)
        elif answer == "sacrifice":
            self.sacrifice(player, "nonland", 1)
        else:
            self._pay_sacrifice_or_discard(player)
    @continuations.choice("ward", answer=continuations.ANSWER_STR, rule="702.21")
    def _resume_ward(self, choice: dict[str, Any], answer: Optional[str]) -> None:
        """Answer a pending `ward` choice (RULE 702.21).

        ``answer == "pay"`` charges the *caster* the cost and leaves the
        item on the stack; anything else counters it. Either way, if
        another ward ability is still on the stack (RULE 702.21c, a
        different warded target of the same spell/ability), it simply
        becomes the new top of the stack and resolves next through the
        ordinary stack loop — no extra bookkeeping needed here.
        """
        pending = self.state.pending_ward
        self.state.pending_ward = None
        if pending is None:
            return
        item, cost, caster_id = pending["item"], pending["cost"], pending["caster_id"]
        # RULE 702.21a: a departed item cannot be countered or require payment.
        # Check the exact StackItem, even if its object is reused on the stack.
        if self._stack_item_for(item) is None:
            return
        if answer == "pay" and cost is not None and caster_id:
            try:
                caster = self.state.player_by_id(caster_id)
            except KeyError:
                caster = None
            if caster is not None:
                self._pay_player_cost(caster, cost)
            return
        if item is not None:
            self.counter_spell(item, countered_by=choice.get("countered_by"))
