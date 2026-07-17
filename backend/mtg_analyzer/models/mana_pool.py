"""Per-player mana pool (RULE 106, RULE 500.4 emptying, RULE 601.2g payment).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.6 (Mana System),
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2).

A pool is a tally of available mana per type (``W U B R G C``). The
non-trivial part is *paying* a `ManaCost`: colored/colorless pips are
constrained, hybrid pips offer a choice, Phyrexian pips can be paid with
life, and generic pips accept any leftover mana. `can_pay`/`pay` solve
that assignment with a small backtracking search (costs are short, so
this is cheap and exact rather than a fallible greedy heuristic).

RULE 605.3a: some mana abilities restrict what their mana may be spent on
("Spend this mana only to cast a creature spell.") — such mana lives in a
separate, tagged *restricted lot* (``self.restricted``) rather than the
flat ``self.pool``, alongside an opaque ``restriction`` dict it was tagged
with at production time (`game/mana_abilities.py`'s ``ManaAbility.
restriction`` — the whitelisted restriction-kind vocabulary lives there,
not here: this module stays ignorant of what a restriction *means*,
matching the "models/ must not import game/" boundary, CLAUDE.md). A
caller that cares passes ``allows_restriction``, a predicate over that
dict; ``None`` (the default, and every pre-existing call site unless
updated) means no restricted lot is usable, so restricted mana already in
the pool simply can't pay anything until some caller opts in — safe and
backward compatible. When usable, restricted mana is spent before
unrestricted (`_consume`) since unlike unrestricted mana it is otherwise
just wasted when the pool next empties (RULE 500.4).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .mana_cost import GENERIC, VARIABLE, ManaCost

#: A predicate over a restriction dict (``lot["restriction"]``) — whether
#: that lot's mana may pay the cost currently being checked/paid. Built by
#: the caller (see `game/mana_abilities.py`'s `restriction_predicate_for_cast`/
#: `restriction_predicate_for_activation`); this module never inspects the
#: restriction dict's contents itself.
AllowsRestriction = Callable[[dict], bool]

#: Mana types a pool tracks, in the order generic pips are spent (see
#: ``pay``): colorless first so colored mana is preserved for later
#: colored costs, then the five colors.
MANA_TYPES: tuple[str, ...] = ("C", "W", "U", "B", "R", "G")


class ManaPool:
    """Available mana for one player during the current step/phase."""

    def __init__(self, amounts: Optional[dict[str, int]] = None) -> None:
        self.pool: dict[str, int] = {t: 0 for t in MANA_TYPES}
        #: Tagged mana lots each restricted to a subset of costs (RULE
        #: 605.3a) — a list (not merged by restriction) of
        #: ``{"restriction": dict, "amounts": {type: count}}``; a lot with
        #: an identical ``restriction`` dict is merged in-place by `add`
        #: rather than growing the list unboundedly.
        self.restricted: list[dict[str, Any]] = []
        if amounts:
            for mana_type, amount in amounts.items():
                self.add(mana_type, amount)

    def add(self, mana_type: str, amount: int = 1, restriction: Optional[dict] = None) -> None:
        """Add ``amount`` mana of ``mana_type`` (``W U B R G C``).

        ``restriction`` (RULE 605.3a, ``None`` by default) tags this mana
        as spendable only where a caller's ``allows_restriction`` predicate
        (`can_pay`/`pay`) says so — see the module docstring.
        """
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if restriction is None:
            self.pool[mana_type] += amount
            return
        for lot in self.restricted:
            if lot["restriction"] == restriction:
                lot["amounts"][mana_type] = lot["amounts"].get(mana_type, 0) + amount
                return
        self.restricted.append({"restriction": restriction, "amounts": {mana_type: amount}})

    def add_many(self, amounts: dict[str, int], restriction: Optional[dict] = None) -> None:
        for mana_type, amount in amounts.items():
            self.add(mana_type, amount, restriction=restriction)

    def set_amount(self, mana_type: str, amount: int) -> None:
        """Set ``mana_type`` to an absolute ``amount`` — the Replay editor's
        mana-pool control; normal play only ever `add`s/`pay`s/`empty`s."""
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.pool[mana_type] = amount

    def total(self) -> int:
        return sum(self.pool.values()) + sum(
            sum(lot["amounts"].values()) for lot in self.restricted
        )

    def empty(self) -> None:
        """Empty the pool (RULE 500.4: mana empties as each step/phase ends).

        Restricted mana empties the same way — being tagged for a narrower
        set of costs doesn't exempt it from the step/phase-end cleanup.
        """
        for mana_type in self.pool:
            self.pool[mana_type] = 0
        self.restricted.clear()

    def _usable_lots(self, allows_restriction: Optional[AllowsRestriction]) -> list[dict]:
        """Restricted lots ``allows_restriction`` says may pay the cost at
        hand — none at all when the caller passes ``None`` (the default),
        so restricted mana is inert unless a caller explicitly opts in."""
        if allows_restriction is None:
            return []
        return [lot for lot in self.restricted if allows_restriction(lot["restriction"])]

    def _merged_available(self, usable_lots: list[dict]) -> dict[str, int]:
        merged = dict(self.pool)
        for lot in usable_lots:
            for mana_type, amount in lot["amounts"].items():
                merged[mana_type] = merged.get(mana_type, 0) + amount
        return merged

    def can_pay(
        self,
        cost: ManaCost,
        life_available: int = 0,
        allows_restriction: Optional[AllowsRestriction] = None,
    ) -> bool:
        """Whether this pool (plus ``life_available`` life) can pay ``cost``.

        ``life_available`` is only consulted for Phyrexian pips; a life
        payment is legal only if it leaves the payer above 0 life
        (RULE 119.4 — you can't pay life you don't have). ``allows_restriction``
        (see the module docstring) opts in whichever restricted lots may
        count toward this particular cost — omitted, no restricted mana
        counts at all.
        """
        usable = self._usable_lots(allows_restriction)
        return self._find_payment(self._merged_available(usable), cost, life_available) is not None

    def pay(
        self,
        cost: ManaCost,
        life_available: int = 0,
        allows_restriction: Optional[AllowsRestriction] = None,
    ) -> int:
        """Pay ``cost`` from this pool, mutating it. Returns life spent.

        Raises:
            ValueError: If the cost cannot be paid from the current pool
                (call ``can_pay`` first to avoid this).
        """
        usable = self._usable_lots(allows_restriction)
        solution = self._find_payment(self._merged_available(usable), cost, life_available)
        if solution is None:
            raise ValueError(f"cannot pay {cost!r} from {self.pool!r}")
        colored_spends, generic_needed, life_spent = solution

        for color in colored_spends:
            self._consume(color, 1, usable)
        self._spend_generic(generic_needed, usable)
        # Lots a payment fully drained are dropped rather than left as
        # empty husks (`add` would otherwise keep merging into them forever).
        self.restricted = [lot for lot in self.restricted if sum(lot["amounts"].values())]
        return life_spent

    def _consume(self, mana_type: str, amount: int, usable_lots: list[dict]) -> None:
        """Remove ``amount`` of ``mana_type``, spending usable restricted
        lots before unrestricted mana — restricted mana left unspent is
        simply lost once the pool empties (RULE 500.4), so using it first
        never costs anything a rules-legal payment wouldn't have anyway."""
        for lot in usable_lots:
            if amount <= 0:
                break
            take = min(lot["amounts"].get(mana_type, 0), amount)
            if take:
                lot["amounts"][mana_type] -= take
                amount -= take
        if amount > 0:
            self.pool[mana_type] -= amount

    def _spend_generic(self, amount: int, usable_lots: list[dict] = ()) -> None:
        """Remove ``amount`` mana of any type, colorless-first (see MANA_TYPES)."""
        for mana_type in MANA_TYPES:
            if amount <= 0:
                break
            available = self.pool[mana_type] + sum(
                lot["amounts"].get(mana_type, 0) for lot in usable_lots
            )
            take = min(available, amount)
            if take:
                self._consume(mana_type, take, usable_lots)
                amount -= take
        if amount > 0:  # pragma: no cover - guarded by _find_payment
            raise ValueError("insufficient mana for generic cost")

    @staticmethod
    def _find_payment(
        pool: dict[str, int], cost: ManaCost, life_available: int
    ) -> Optional[tuple[list[str], int, int]]:
        """Solve payment. Returns (colored spends, generic needed, life) or None.

        Constrained symbols (color/colorless/hybrid/mono-hybrid/Phyrexian)
        are assigned by backtracking; generic and {X} pips are summed and
        checked against whatever mana remains, since generic mana accepts
        any type.
        """
        generic_needed = 0
        constrained = []
        for symbol in cost.symbols:
            if symbol.kind in (GENERIC, VARIABLE):
                generic_needed += symbol.amount
            else:
                constrained.append(symbol)

        spends: list[str] = []
        result = ManaPool._solve(pool, constrained, 0, generic_needed, life_available, spends)
        return result

    @staticmethod
    def _solve(
        pool: dict[str, int],
        constrained: list,
        index: int,
        generic_needed: int,
        life_available: int,
        spends: list[str],
    ) -> Optional[tuple[list[str], int, int]]:
        if index == len(constrained):
            if sum(pool.values()) >= generic_needed:
                return list(spends), generic_needed, 0
            return None

        for color, extra_generic, life_cost in constrained[index].payment_options():
            if color is not None:
                if pool.get(color, 0) <= 0:
                    continue
                pool[color] -= 1
                spends.append(color)
                found = ManaPool._solve(
                    pool, constrained, index + 1,
                    generic_needed + extra_generic, life_available, spends,
                )
                spends.pop()
                pool[color] += 1
                if found is not None:
                    return found
            else:
                # A life payment must leave the payer alive (RULE 119.4).
                if life_cost and life_available - life_cost <= 0:
                    continue
                found = ManaPool._solve(
                    pool, constrained, index + 1,
                    generic_needed + extra_generic,
                    life_available - life_cost, spends,
                )
                if found is not None:
                    colored, generic, life = found
                    return colored, generic, life + life_cost

        return None

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.pool)
        if self.restricted:
            # Additive — existing WUBRGC keys are unchanged, so this is
            # safe for any caller ignoring the new key (no frontend
            # display of restricted mana yet, see frontend/ToDo_Frontend.md).
            data["restricted"] = [
                {"restriction": lot["restriction"], "amounts": dict(lot["amounts"])}
                for lot in self.restricted
            ]
        return data

    def __repr__(self) -> str:
        active = {t: n for t, n in self.pool.items() if n}
        return f"ManaPool({active!r})"
