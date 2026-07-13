"""Per-player mana pool (RULE 106, RULE 500.4 emptying, RULE 601.2g payment).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.6 (Mana System),
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2).

A pool is a tally of available mana per type (``W U B R G C``). The
non-trivial part is *paying* a `ManaCost`: colored/colorless pips are
constrained, hybrid pips offer a choice, Phyrexian pips can be paid with
life, and generic pips accept any leftover mana. `can_pay`/`pay` solve
that assignment with a small backtracking search (costs are short, so
this is cheap and exact rather than a fallible greedy heuristic).
"""

from __future__ import annotations

from typing import Any, Optional

from .mana_cost import GENERIC, VARIABLE, ManaCost

#: Mana types a pool tracks, in the order generic pips are spent (see
#: ``pay``): colorless first so colored mana is preserved for later
#: colored costs, then the five colors.
MANA_TYPES: tuple[str, ...] = ("C", "W", "U", "B", "R", "G")


class ManaPool:
    """Available mana for one player during the current step/phase."""

    def __init__(self, amounts: Optional[dict[str, int]] = None) -> None:
        self.pool: dict[str, int] = {t: 0 for t in MANA_TYPES}
        if amounts:
            for mana_type, amount in amounts.items():
                self.add(mana_type, amount)

    def add(self, mana_type: str, amount: int = 1) -> None:
        """Add ``amount`` mana of ``mana_type`` (``W U B R G C``)."""
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.pool[mana_type] += amount

    def add_many(self, amounts: dict[str, int]) -> None:
        for mana_type, amount in amounts.items():
            self.add(mana_type, amount)

    def set_amount(self, mana_type: str, amount: int) -> None:
        """Set ``mana_type`` to an absolute ``amount`` — the Replay editor's
        mana-pool control; normal play only ever `add`s/`pay`s/`empty`s."""
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.pool[mana_type] = amount

    def total(self) -> int:
        return sum(self.pool.values())

    def empty(self) -> None:
        """Empty the pool (RULE 500.4: mana empties as each step/phase ends)."""
        for mana_type in self.pool:
            self.pool[mana_type] = 0

    def can_pay(self, cost: ManaCost, life_available: int = 0) -> bool:
        """Whether this pool (plus ``life_available`` life) can pay ``cost``.

        ``life_available`` is only consulted for Phyrexian pips; a life
        payment is legal only if it leaves the payer above 0 life
        (RULE 119.4 — you can't pay life you don't have).
        """
        return self._find_payment(dict(self.pool), cost, life_available) is not None

    def pay(self, cost: ManaCost, life_available: int = 0) -> int:
        """Pay ``cost`` from this pool, mutating it. Returns life spent.

        Raises:
            ValueError: If the cost cannot be paid from the current pool
                (call ``can_pay`` first to avoid this).
        """
        working = dict(self.pool)
        solution = self._find_payment(working, cost, life_available)
        if solution is None:
            raise ValueError(f"cannot pay {cost!r} from {self.pool!r}")
        colored_spends, generic_needed, life_spent = solution

        for color in colored_spends:
            self.pool[color] -= 1
        self._spend_generic(generic_needed)
        return life_spent

    def _spend_generic(self, amount: int) -> None:
        """Remove ``amount`` mana of any type, colorless-first (see MANA_TYPES)."""
        for mana_type in MANA_TYPES:
            if amount <= 0:
                break
            take = min(self.pool[mana_type], amount)
            self.pool[mana_type] -= take
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
        return dict(self.pool)

    def __repr__(self) -> str:
        active = {t: n for t, n in self.pool.items() if n}
        return f"ManaPool({active!r})"
