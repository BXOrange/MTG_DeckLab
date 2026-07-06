"""Structured mana cost model (RULE 202, RULE 601.2f).

Reference: docs/07_GAME_LOOP_EFFECT_SYSTEM.md (PART 2, `ManaCost` used by
`ActivatedAbility`/casting), backend/Done_Backend.md "Mana cost model".

The `Card.mana_cost` dict (`models/card.py`) flattens a cost to a plain
per-color pip tally and loses *how* a pip can be paid — a hybrid `{W/U}`
becomes indistinguishable from a plain `{W}`, a Phyrexian `{W/P}` loses
that it can be paid with life, and generic `{2}` is dropped entirely.
That is fine for the "how many colored pips" displays the frontend does
today, but the game engine has to know the *actual legal ways* to pay a
cost before it can decide whether a `ManaPool` can afford a spell.

This module models a cost faithfully as an ordered list of
`ManaSymbol`s parsed from a Scryfall mana-cost string (e.g.
``"{2}{W}{U/B}{G/P}"``). Each symbol knows the concrete payment
*options* it offers; `ManaPool.can_pay`/`pay` (models/mana_pool.py)
consume that to solve payment, including hybrid choice and Phyrexian
life payment.
"""

from __future__ import annotations

import re
from typing import Any, Optional

#: The five colors plus generic colorless mana, as single-letter symbols.
_COLORS: frozenset[str] = frozenset({"W", "U", "B", "R", "G"})

#: Regex capturing the contents of each ``{...}`` token in a mana string.
_TOKEN_RE = re.compile(r"\{([^}]+)\}")

# Symbol kinds.
GENERIC = "generic"        # {2} — pay N mana of any type
VARIABLE = "variable"      # {X} — chosen when cast; 0 until set
COLOR = "color"            # {W} — pay 1 of that color
COLORLESS = "colorless"    # {C} — pay 1 colorless specifically
HYBRID = "hybrid"          # {W/U} — pay 1 of either color
MONO_HYBRID = "mono_hybrid"  # {2/W} — pay N generic OR 1 of that color
PHYREXIAN = "phyrexian"    # {W/P} — pay 1 of that color OR 2 life


class ManaSymbol:
    """A single symbol within a mana cost, and the ways it can be paid.

    A *payment option* is a ``(color, generic, life)`` tuple: pay one
    mana of ``color`` (or ``None`` for no colored-mana spend), plus
    ``generic`` additional generic mana, plus ``life`` life. Exactly the
    combinations a payer may legally choose between for this symbol.
    """

    __slots__ = ("kind", "color", "amount")

    def __init__(self, kind: str, color: Optional[str] = None, amount: int = 0) -> None:
        self.kind = kind
        self.color = color
        self.amount = amount

    @property
    def cmc(self) -> int:
        """This symbol's contribution to the mana value (RULE 202.3)."""
        if self.kind in (GENERIC, MONO_HYBRID):
            return self.amount
        if self.kind == VARIABLE:
            return 0
        return 1  # color, colorless, hybrid, phyrexian each count as 1

    @property
    def colors(self) -> set[str]:
        """Colors this symbol can contribute to a color identity.

        Hybrid symbols store both halves as ``"W/U"``; both count.
        """
        if not self.color:
            return set()
        return {half for half in self.color.split("/") if half in _COLORS}

    def payment_options(self) -> list[tuple[Optional[str], int, int]]:
        """Legal ``(color, generic, life)`` ways to pay this symbol.

        Generic/variable symbols return ``[]`` — they are not paid by a
        single fixed choice but as a lump of "any N mana", handled by the
        payer after the constrained symbols are assigned.
        """
        if self.kind == COLOR:
            return [(self.color, 0, 0)]
        if self.kind == COLORLESS:
            return [("C", 0, 0)]
        if self.kind == HYBRID:
            # color holds "W/U"; either half pays it.
            return [(half, 0, 0) for half in self.color.split("/")]
        if self.kind == MONO_HYBRID:
            return [(self.color, 0, 0), (None, self.amount, 0)]
        if self.kind == PHYREXIAN:
            return [(self.color, 0, 0), (None, 0, 2)]
        return []  # generic / variable

    def __repr__(self) -> str:
        return f"ManaSymbol(kind={self.kind!r}, color={self.color!r}, amount={self.amount!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ManaSymbol):
            return NotImplemented
        return (self.kind, self.color, self.amount) == (other.kind, other.color, other.amount)


class ManaCost:
    """An ordered cost, faithfully preserving hybrid/Phyrexian/generic.

    Build from a Scryfall mana-cost string with :meth:`parse`. The empty
    string (lands, most tokens) parses to a free cost (``is_free``).
    """

    def __init__(self, symbols: Optional[list[ManaSymbol]] = None, raw: str = "") -> None:
        self.symbols: list[ManaSymbol] = list(symbols) if symbols else []
        self.raw = raw

    @classmethod
    def from_card(cls, card: Any) -> "ManaCost":
        """The cost of a card, from its raw ``mana_cost_string``.

        Falls back to reconstructing a plain cost from the card's lossy
        per-color pip tally (``mana_cost``) plus its mana value
        (``converted_mana_cost``) when no raw string is stored — e.g. a
        row cached before ``mana_cost_string`` existed. Without this, an
        empty raw string is indistinguishable from a genuinely free cost,
        so such a card would be castable for *no mana* (the Sol Ring bug).

        The reconstruction can't recover hybrid/Phyrexian nuance (that was
        never in the flat dict), but it gets the total and colors right
        for plain costs, so the card correctly costs *something*. Freshly
        resolved cards carry the exact ``mana_cost_string`` and skip this.
        """
        raw = getattr(card, "mana_cost_string", "") or ""
        if raw:
            return cls.parse(raw)

        counts = getattr(card, "mana_cost", None) or {}
        pip_types = ("W", "U", "B", "R", "G", "C")
        colored_total = sum(counts.get(pip, 0) for pip in pip_types)
        generic = max(0, int(getattr(card, "converted_mana_cost", 0) or 0) - colored_total)

        parts: list[str] = []
        if generic:
            parts.append(f"{{{generic}}}")
        for pip in pip_types:
            parts.extend([f"{{{pip}}}"] * counts.get(pip, 0))
        return cls.parse("".join(parts))

    @classmethod
    def parse(cls, mana_cost: str) -> "ManaCost":
        """Parse a Scryfall cost string like ``"{2}{W}{U/B}{G/P}"``.

        Unknown/unsupported tokens (e.g. ``{S}`` snow) are treated as a
        single generic pip so the total mana value stays sane rather than
        raising — this engine doesn't model those payment types yet.
        """
        symbols: list[ManaSymbol] = []
        for token in _TOKEN_RE.findall(mana_cost or ""):
            symbols.append(cls._parse_token(token))
        return cls(symbols, raw=mana_cost or "")

    @staticmethod
    def _parse_token(token: str) -> ManaSymbol:
        token = token.strip().upper()

        if token.isdigit():
            return ManaSymbol(GENERIC, amount=int(token))
        if token in {"X", "Y", "Z"}:
            return ManaSymbol(VARIABLE)
        if token in _COLORS:
            return ManaSymbol(COLOR, color=token)
        if token == "C":
            return ManaSymbol(COLORLESS)

        if "/" in token:
            parts = token.split("/")
            if "P" in parts:
                # Phyrexian: the other half is the payable color.
                color = next((p for p in parts if p != "P"), None)
                if color in _COLORS:
                    return ManaSymbol(PHYREXIAN, color=color)
            elif any(p.isdigit() for p in parts):
                # Monocolored hybrid, e.g. {2/W}.
                amount = int(next(p for p in parts if p.isdigit()))
                color = next((p for p in parts if p in _COLORS), None)
                if color is not None:
                    return ManaSymbol(MONO_HYBRID, color=color, amount=amount)
            elif all(p in _COLORS for p in parts):
                return ManaSymbol(HYBRID, color="/".join(parts))

        # Unknown symbol (snow {S}, {C/W} oddities, etc.): count as one
        # generic pip so mana value is preserved.
        return ManaSymbol(GENERIC, amount=1)

    @property
    def converted_mana_cost(self) -> int:
        """Total mana value (RULE 202.3). {X} counts as 0."""
        return sum(s.cmc for s in self.symbols)

    @property
    def color_identity(self) -> set[str]:
        """Colors appearing anywhere in the cost (hybrid halves included)."""
        identity: set[str] = set()
        for symbol in self.symbols:
            identity |= symbol.colors
        return identity

    @property
    def is_free(self) -> bool:
        """A cost with no symbols at all (e.g. a land's ``""``)."""
        return not self.symbols

    @property
    def has_variable(self) -> bool:
        """Whether this cost contains an unset ``{X}`` (RULE 107.3c)."""
        return any(s.kind == VARIABLE for s in self.symbols)

    def with_x(self, x: int) -> "ManaCost":
        """A copy with every ``{X}`` symbol resolved to the announced value.

        RULE 601.2b: a player announces X when casting a spell with {X} in
        its cost, before paying. `ManaSymbol.cmc` still reports 0 for a
        `VARIABLE` symbol regardless (RULE 202.3b only counts the chosen
        value on the stack/battlefield, not in this static cost model), but
        `ManaPool` sums `amount` when solving payment, so this is enough to
        make X actually cost something.
        """
        if x < 0:
            raise ValueError("X must be >= 0")
        resolved = [
            ManaSymbol(s.kind, s.color, x) if s.kind == VARIABLE else s
            for s in self.symbols
        ]
        return ManaCost(resolved, raw=self.raw)

    def reduce_generic(self, amount: int) -> "ManaCost":
        """A copy with generic mana lowered by ``amount`` (floored at 0).

        Cost reductions like "this spell costs {2} less" only ever reduce the
        *generic* part of a cost (RULE 601.2f) — coloured/hybrid/Phyrexian pips
        are untouched. ``amount <= 0`` returns an equivalent copy unchanged.
        """
        if amount <= 0:
            return ManaCost(list(self.symbols), raw=self.raw)
        remaining = amount
        reduced: list[ManaSymbol] = []
        for symbol in self.symbols:
            if remaining > 0 and symbol.kind == GENERIC:
                take = min(remaining, symbol.amount)
                remaining -= take
                if symbol.amount - take > 0:
                    reduced.append(ManaSymbol(GENERIC, amount=symbol.amount - take))
            else:
                reduced.append(symbol)
        return ManaCost(reduced, raw=ManaCost(reduced).render())

    def increase_generic(self, amount: int) -> "ManaCost":
        """A copy with ``amount`` generic mana added (a "cost {N} more" tax).

        Merges into an existing generic symbol so the cost keeps one ``{N}``.
        """
        if amount <= 0:
            return ManaCost(list(self.symbols), raw=self.raw)
        symbols = [
            ManaSymbol(GENERIC, amount=s.amount + amount) if s.kind == GENERIC else s
            for s in self.symbols
        ]
        if not any(s.kind == GENERIC for s in self.symbols):
            symbols.insert(0, ManaSymbol(GENERIC, amount=amount))
        return ManaCost(symbols, raw=ManaCost(symbols).render())

    def render(self) -> str:
        """Reconstruct a Scryfall-style ``{…}`` cost string from the symbols."""
        parts: list[str] = []
        for s in self.symbols:
            if s.kind == GENERIC:
                parts.append(f"{{{s.amount}}}")
            elif s.kind == VARIABLE:
                parts.append("{X}")
            elif s.kind == COLORLESS:
                parts.append("{C}")
            elif s.kind == MONO_HYBRID:
                parts.append(f"{{{s.amount}/{s.color}}}")
            elif s.kind == PHYREXIAN:
                parts.append(f"{{{s.color}/P}}")
            else:  # COLOR, HYBRID ("W/U")
                parts.append(f"{{{s.color}}}")
        return "".join(parts)

    def __repr__(self) -> str:
        return f"ManaCost({self.raw!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ManaCost):
            return NotImplemented
        return self.symbols == other.symbols

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "converted_mana_cost": self.converted_mana_cost,
            "color_identity": sorted(self.color_identity),
        }
