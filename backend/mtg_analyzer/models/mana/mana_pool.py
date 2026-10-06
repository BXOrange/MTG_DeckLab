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

from .mana_cost import COLOR, GENERIC, VARIABLE, ManaCost

#: RULE 118.9-adjacent alternative-payment life cost K'rrik, Son of
#: Yawgmoth's static grants a *plain* colored pip ("For each {B} in a
#: cost, you may pay 2 life rather than pay that mana.") — the same 2-life
#: price RULE 702.85a's Phyrexian mana symbol already prices a pip at
#: (`models/mana_cost.py`'s `ManaSymbol.payment_options`), just conferred
#: by a standing permission instead of printed on the symbol itself. See
#: `extra_life_color` below.
KRRIK_LIFE_PER_BLACK_PIP = 2

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

#: When mana that "doesn't empty as steps and phases end" finally does: the end of the combat phase, or the
#: end of the turn (the cleanup step, after which nothing is left to keep).
KEEP_UNTIL_END_OF_COMBAT = "end_of_combat"
KEEP_UNTIL_END_OF_TURN = "end_of_turn"
KEEP_UNTIL_VALUES: tuple[str, ...] = (KEEP_UNTIL_END_OF_COMBAT, KEEP_UNTIL_END_OF_TURN)
#: The step whose end finally empties each kind of kept mana: end of combat ends "until end of combat"; the
#: cleanup step ends "until end of turn" (and anything still kept for a combat that never ended).
_KEPT_MANA_EXPIRY_STEPS: dict[str, tuple[str, ...]] = {
    "end_combat": (KEEP_UNTIL_END_OF_COMBAT,),
    "cleanup": (KEEP_UNTIL_END_OF_COMBAT, KEEP_UNTIL_END_OF_TURN),
}


def kept_mana_expiring_at(step_name: str) -> tuple[str, ...]:
    """Which `ManaPool.kept` buckets empty when ``step_name`` ends (RULE 500.4)."""
    return _KEPT_MANA_EXPIRY_STEPS.get(step_name, ())

#: The five real colors (RULE 105.1) — the substitution set for
#: ``wildcard="color"`` below; excludes colorless (``"C"``), since RULE
#: 605.1a's "any color" never means colorless.
_FIVE_COLORS: tuple[str, ...] = ("W", "U", "B", "R", "G")


def _source_kind_matches(actual: Optional[str], required: str) -> bool:
    """An artifact creature's mana satisfies either source-type restriction."""
    return actual == required or (actual == "artifact_creature" and required in {"artifact", "creature"})


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
        #: PAR-19: RULE 605.3a's *other* direction — "spend only mana
        #: produced by Treasures/basic lands/creatures to cast this
        #: spell." (Security Rhox/Imperiosaur/Myr Superion), the inverse of
        #: ``restricted`` above: that mechanism *adds* extra usable mana
        #: opt-in; this one *subtracts* from the ordinary pool, since a
        #: spell like Imperiosaur must reject perfectly ordinary ``pool``
        #: mana that didn't come from a basic land. A per-source-kind
        #: shadow tally that always mirrors ``pool`` exactly (every ``add``
        #: with ``restriction=None`` — the only case that lands in
        #: ``pool`` — also lands here, bucketed by ``source_kind``, default
        #: bucket ``None`` for "no known/relevant origin"); never mutated
        #: except in lockstep with ``pool`` (`_add_to_source_pool`/
        #: `_consume_from_source_pool`) so the two never drift. Only
        #: consulted when a caller passes ``require_source_kind`` to
        #: `can_pay`/`pay` — every pre-existing call site (the overwhelming
        #: majority) never does, so this is pure bookkeeping overhead for
        #: them, not a behaviour change.
        self.pool_by_source: dict[Optional[str], dict[str, int]] = {}
        #: How much *restricted* mana of each source kind (``"creature"``/…) the most recent `pay` took, by
        #: ``source_kind`` — restricted lots are not in `pool_by_source`, so "mana from creatures was spent"
        #: (Inga and Esika) reads this for the restricted part of a payment.
        self.last_payment_by_kind: dict[str, int] = {}
        #: Which type(s) `pay()`'s most recent call actually drained
        #: (colored pips + whichever type(s) covered the generic portion,
        #: `_spend_generic`'s own colorless-first order) — Jeweled Amulet's
        #: "note the type of mana spent to pay this activation cost"
        #: (MEC-43) is the only reader today; every other caller ignores
        #: it, so this is pure bookkeeping overhead for them. Overwritten
        #: (not accumulated) on every `pay()` call — stale after a cost
        #: with no mana component at all, since callers skip `pay()`
        #: entirely rather than calling it with an empty cost.
        self.last_payment_types: dict[str, int] = {}
        #: How much of `pool` (per type) came from a snow-typed source (RULE
        #: 205.4g — "{S} spent", MEC-43 round 3) — a subset count, always
        #: ``<= pool[type]``, mirroring `pool_by_source`'s "shadow tally"
        #: shape but boolean-tagged rather than bucketed by permanent kind
        #: (a lot can be *both* ``source_kind="basic_land"`` and snow — a
        #: Snow-Covered Forest — so this can't reuse that single-valued
        #: field without corrupting PAR-19's own basic-land/treasure/
        #: creature bucketing). Only ever populated via `add`'s ``is_snow``
        #: flag; drained in lockstep by `_consume`, snow-first (an arbitrary
        #: but harmless deterministic order, the same tier of simplification
        #: `_spend_generic`'s own colorless-first order already is) so a
        #: payment that *could* have used snow mana is credited with having
        #: done so rather than silently preferring plain mana instead.
        self.snow_pool: dict[str, int] = {t: 0 for t in MANA_TYPES}
        #: "Until end of turn, you don't lose this mana as steps and phases end." (Brazen Collector, Savage
        #: Ventmaw, Neheb, Sakiko): how much of `pool` (per type) survives each step's emptying, bucketed by
        #: the moment it finally empties (`KEEP_UNTIL_END_OF_COMBAT` / `KEEP_UNTIL_END_OF_TURN`). Like
        #: `snow_pool` it is a subset tally that never exceeds `pool`: a payment drains the mana that would
        #: have been lost first, so `_trim_kept` only ever cuts the kept amount down to what is left.
        self.kept: dict[str, dict[str, int]] = {}
        if amounts:
            for mana_type, amount in amounts.items():
                self.add(mana_type, amount)

    def _add_to_source_pool(self, mana_type: str, amount: int, source_kind: Optional[str]) -> None:
        bucket = self.pool_by_source.setdefault(source_kind, {t: 0 for t in MANA_TYPES})
        bucket[mana_type] = bucket.get(mana_type, 0) + amount

    def add(
        self, mana_type: str, amount: int = 1, restriction: Optional[dict] = None,
        source_kind: Optional[str] = None, is_snow: bool = False, keep_until: Optional[str] = None,
    ) -> None:
        """Add ``amount`` mana of ``mana_type`` (``W U B R G C``).

        ``restriction`` (RULE 605.3a, ``None`` by default) tags this mana
        as spendable only where a caller's ``allows_restriction`` predicate
        (`can_pay`/`pay`) says so — see the module docstring. ``source_kind``
        (PAR-19, only meaningful alongside ``restriction=None``) tags which
        kind of permanent produced it (``"treasure"``/``"basic_land"``/
        ``"creature"``/…) for `pool_by_source`'s own, independent filter —
        see that field's docstring. ``is_snow`` (MEC-43 round 3) tags it as
        snow-sourced for `snow_pool`'s own independent, orthogonal count —
        see that field's docstring for why it can't reuse ``source_kind``.
        ``keep_until`` (`KEEP_UNTIL_VALUES`, unrestricted mana only) is "you don't lose this mana as steps and
        phases end" — see `kept`.
        """
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if restriction is None:
            self.pool[mana_type] += amount
            self._add_to_source_pool(mana_type, amount, source_kind)
            if is_snow:
                self.snow_pool[mana_type] = self.snow_pool.get(mana_type, 0) + amount
            if keep_until in KEEP_UNTIL_VALUES:
                bucket = self.kept.setdefault(keep_until, {})
                bucket[mana_type] = bucket.get(mana_type, 0) + amount
            return
        for lot in self.restricted:
            if lot["restriction"] == restriction and lot.get("source_kind") == source_kind:
                lot["amounts"][mana_type] = lot["amounts"].get(mana_type, 0) + amount
                return
        lot: dict[str, Any] = {"restriction": restriction, "amounts": {mana_type: amount}}
        if source_kind is not None:
            lot["source_kind"] = source_kind  # only when tagged, so untagged lots keep their original shape
        self.restricted.append(lot)

    def add_many(
        self, amounts: dict[str, int], restriction: Optional[dict] = None,
        source_kind: Optional[str] = None, is_snow: bool = False, keep_until: Optional[str] = None,
    ) -> None:
        for mana_type, amount in amounts.items():
            self.add(
                mana_type, amount, restriction=restriction, source_kind=source_kind, is_snow=is_snow,
                keep_until=keep_until,
            )

    def set_amount(self, mana_type: str, amount: int) -> None:
        """Set ``mana_type`` to an absolute ``amount`` — the Replay editor's
        mana-pool control; normal play only ever `add`s/`pay`s/`empty`s.
        Not source-tracked (`pool_by_source` is left untouched) — a direct
        editor override has no originating permanent to attribute."""
        if mana_type not in self.pool:
            raise ValueError(f"unknown mana type: {mana_type!r}")
        if amount < 0:
            raise ValueError("amount must be non-negative")
        self.pool[mana_type] = amount
        self._trim_kept()

    def _trim_kept(self) -> None:
        """Cut `kept` down to what the pool still holds (a payment spent the mana that would have been lost
        first); an emptied bucket is dropped."""
        for until in list(self.kept):
            bucket = self.kept[until]
            for mana_type in list(bucket):
                others = sum(b.get(mana_type, 0) for u, b in self.kept.items() if u != until)
                bucket[mana_type] = max(0, min(bucket[mana_type], self.pool.get(mana_type, 0) - others))
                if not bucket[mana_type]:
                    del bucket[mana_type]
            if not bucket:
                del self.kept[until]

    def total(self) -> int:
        return sum(self.pool.values()) + sum(
            sum(lot["amounts"].values()) for lot in self.restricted
        )

    def empty(self, expire: tuple[str, ...] = ()) -> None:
        """Empty the pool (RULE 500.4: mana empties as each step/phase ends).

        Restricted mana empties the same way — being tagged for a narrower
        set of costs doesn't exempt it from the step/phase-end cleanup.
        Mana tagged `kept` survives — except the buckets named in ``expire`` (the end of combat, the end of the
        turn), which are dropped first and empty with the rest.
        """
        for until in expire:
            self.kept.pop(until, None)
        survives = {t: sum(b.get(t, 0) for b in self.kept.values()) for t in self.pool}
        for mana_type in self.pool:
            self.pool[mana_type] = min(self.pool[mana_type], survives[mana_type])
            self.snow_pool[mana_type] = 0
        self.restricted.clear()
        self.pool_by_source.clear()
        if survives and any(survives.values()):
            # What stays is plain, untagged mana from here on (its origin no longer matters).
            self._add_to_source_pool_all(self.pool)

    def _add_to_source_pool_all(self, amounts: dict[str, int]) -> None:
        for mana_type, amount in amounts.items():
            if amount:
                self._add_to_source_pool(mana_type, amount, None)

    def _usable_lots(self, allows_restriction: Optional[AllowsRestriction]) -> list[dict]:
        """Restricted lots ``allows_restriction`` says may pay the cost at
        hand — none at all when the caller passes ``None`` (the default),
        so restricted mana is inert unless a caller explicitly opts in."""
        if allows_restriction is None:
            return []
        return [lot for lot in self.restricted if allows_restriction(lot["restriction"])]

    def _merged_available(
        self, usable_lots: list[dict], require_source_kind: Optional[str] = None,
    ) -> dict[str, int]:
        # PAR-19: ``require_source_kind`` swaps the ordinary "``pool`` plus
        # whatever opted-in restricted lots" base for *only* the matching
        # `pool_by_source` bucket — the subtractive direction `usable_lots`
        # can't express (see `pool_by_source`'s docstring). The two never
        # combine on any real card, so this ignores ``usable_lots`` entirely
        # rather than guessing how they'd interact.
        if require_source_kind is not None:
            return {mana_type: sum(bucket.get(mana_type, 0) for kind, bucket in self.pool_by_source.items()
                                   if _source_kind_matches(kind, require_source_kind))
                    for mana_type in MANA_TYPES}
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
        wildcard: Optional[str] = None,
        require_source_kind: Optional[str] = None,
        extra_life_color: Optional[str] = None,
    ) -> bool:
        """Whether this pool (plus ``life_available`` life) can pay ``cost``.

        ``life_available`` is only consulted for Phyrexian pips; a life
        payment is legal only if it leaves the payer above 0 life
        (RULE 119.4 — you can't pay life you don't have). ``allows_restriction``
        (see the module docstring) opts in whichever restricted lots may
        count toward this particular cost — omitted, no restricted mana
        counts at all. ``wildcard`` (RULE 605.1a — "you may spend mana as
        though it were mana of any color/type", Ragavan Nimble Pilferer/
        Mnemonic Betrayal-shaped) relaxes every colored/colorless
        constrained symbol's payment: ``"color"`` lets any of the five
        colors (never colorless) pay a colored pip, ``"type"`` lets any of
        the six mana types pay *any* constrained pip, including a ``{C}``
        one. A single WUBRG letter (MEC-23 — Quicksilver Elemental's "you
        may spend **blue** mana as though it were mana of any color…")
        narrows ``"color"`` the other way: only *that* color of mana
        substitutes for a colored pip it doesn't already match, not all
        five (real red mana still pays a red pip either way). ``None`` (the
        default) is the ordinary, unrelaxed solve. ``require_source_kind``
        (PAR-19 — "spend only mana produced by Treasures/basic lands/
        creatures to cast this spell", Security Rhox/Imperiosaur/Myr
        Superion) narrows payment to only `pool_by_source`'s matching
        bucket instead of the whole pool — see that field's docstring.
        ``extra_life_color`` (MEC-43 — K'rrik, Son of Yawgmoth's "For each
        {B} in a cost, you may pay 2 life rather than pay that mana.")
        grants a *plain* colored pip of that one WUBRG letter the same
        life-payment option a printed Phyrexian pip already has, at
        `KRRIK_LIFE_PER_BLACK_PIP` life apiece — unlike ``wildcard``, this
        doesn't relax *which* mana pays the pip, it adds a way to skip
        paying mana for it at all. ``None`` (the default) leaves every
        plain colored pip exactly as unpayable-by-life as it always was.
        """
        usable = self._usable_lots(allows_restriction)
        available = self._merged_available(usable, require_source_kind)
        return self._find_payment(available, cost, life_available, wildcard, extra_life_color) is not None

    def pay(
        self,
        cost: ManaCost,
        life_available: int = 0,
        allows_restriction: Optional[AllowsRestriction] = None,
        wildcard: Optional[str] = None,
        require_source_kind: Optional[str] = None,
        extra_life_color: Optional[str] = None,
    ) -> int:
        """Pay ``cost`` from this pool, mutating it. Returns life spent.

        ``wildcard``/``require_source_kind``/``extra_life_color`` — see
        `can_pay`.

        Raises:
            ValueError: If the cost cannot be paid from the current pool
                (call ``can_pay`` first to avoid this).
        """
        usable = self._usable_lots(allows_restriction)
        available = self._merged_available(usable, require_source_kind)
        solution = self._find_payment(available, cost, life_available, wildcard, extra_life_color)
        if solution is None:
            raise ValueError(f"cannot pay {cost!r} from {self.pool!r}")
        self.last_payment_by_kind = {}
        colored_spends, generic_needed, life_spent = solution

        for color in colored_spends:
            self._consume(color, 1, usable, require_source_kind)
        spent_generic = self._spend_generic(generic_needed, usable, require_source_kind)
        self._trim_kept()
        # Lots a payment fully drained are dropped rather than left as
        # empty husks (`add` would otherwise keep merging into them forever).
        self.restricted = [lot for lot in self.restricted if sum(lot["amounts"].values())]
        types: dict[str, int] = dict(spent_generic)
        for color in colored_spends:
            types[color] = types.get(color, 0) + 1
        self.last_payment_types = types
        return life_spent

    def _consume_from_source_pool(
        self, mana_type: str, amount: int, require_source_kind: Optional[str],
    ) -> None:
        """Decrement `pool_by_source` in lockstep with a ``pool[mana_type]``
        drain of ``amount``, keeping the two exactly in sync (see
        `pool_by_source`'s docstring). When this payment was itself
        source-filtered (``require_source_kind`` set), the mana necessarily
        came from that exact bucket. Otherwise, drain the untagged
        (``None``) bucket first — ordinary mana is spent before touching
        any source-tagged mana, so a later source-filtered need still finds
        it — falling back to whichever tagged buckets have any left, in a
        stable order, purely to keep the totals consistent."""
        if amount <= 0:
            return
        remaining = amount
        if require_source_kind is not None:
            buckets = [bucket for kind, bucket in self.pool_by_source.items()
                       if _source_kind_matches(kind, require_source_kind)]
        else:
            buckets = [self.pool_by_source.get(None)] + [
                b for k, b in self.pool_by_source.items() if k is not None
            ]
        for bucket in buckets:
            if remaining <= 0 or bucket is None:
                continue
            take = min(bucket.get(mana_type, 0), remaining)
            if take:
                bucket[mana_type] -= take
                remaining -= take

    def _consume(
        self, mana_type: str, amount: int, usable_lots: list[dict],
        require_source_kind: Optional[str] = None,
    ) -> None:
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
                kind = lot.get("source_kind")
                if kind:
                    self.last_payment_by_kind[kind] = self.last_payment_by_kind.get(kind, 0) + take
        if amount > 0:
            self.pool[mana_type] -= amount
            self._consume_from_source_pool(mana_type, amount, require_source_kind)
            # Snow-first (see `snow_pool`'s own docstring for why).
            snow_take = min(amount, self.snow_pool.get(mana_type, 0))
            if snow_take:
                self.snow_pool[mana_type] -= snow_take

    def _spend_generic(
        self, amount: int, usable_lots: list[dict] = (), require_source_kind: Optional[str] = None,
    ) -> dict[str, int]:
        """Remove ``amount`` mana of any type, colorless-first (see MANA_TYPES).

        Returns how much of each type was actually drained — ``pay()``
        folds this into `last_payment_types` (Jeweled Amulet, MEC-43:
        "note the type of mana spent to pay this activation cost", a
        wholly generic cost with no fixed pip of its own to read instead).
        This engine has no interactive "which color pays the generic
        portion" choice, so which type ends up noted is this deterministic
        colorless-first order, not a genuine player pick — the same
        simplification tier every other "spend from the pool" caller here
        already accepts.
        """
        spent: dict[str, int] = {}
        for mana_type in MANA_TYPES:
            if amount <= 0:
                break
            if require_source_kind is not None:
                available = self._merged_available([], require_source_kind).get(mana_type, 0)
            else:
                available = self.pool[mana_type] + sum(
                    lot["amounts"].get(mana_type, 0) for lot in usable_lots
                )
            take = min(available, amount)
            if take:
                self._consume(mana_type, take, usable_lots, require_source_kind)
                amount -= take
                spent[mana_type] = spent.get(mana_type, 0) + take
        if amount > 0:  # pragma: no cover - guarded by _find_payment
            raise ValueError("insufficient mana for generic cost")
        return spent

    @staticmethod
    def _find_payment(
        pool: dict[str, int],
        cost: ManaCost,
        life_available: int,
        wildcard: Optional[str] = None,
        extra_life_color: Optional[str] = None,
    ) -> Optional[tuple[list[str], int, int]]:
        """Solve payment. Returns (colored spends, generic needed, life) or None.

        Constrained symbols (color/colorless/hybrid/mono-hybrid/Phyrexian)
        are assigned by backtracking; generic and {X} pips are summed and
        checked against whatever mana remains, since generic mana accepts
        any type. ``wildcard``/``extra_life_color`` — see `can_pay`.
        """
        generic_needed = 0
        constrained = []
        for symbol in cost.symbols:
            if symbol.kind in (GENERIC, VARIABLE):
                generic_needed += symbol.amount
            else:
                constrained.append(symbol)

        spends: list[str] = []
        result = ManaPool._solve(
            pool, constrained, 0, generic_needed, life_available, spends, wildcard, extra_life_color,
        )
        return result

    @staticmethod
    def _solve(
        pool: dict[str, int],
        constrained: list,
        index: int,
        generic_needed: int,
        life_available: int,
        spends: list[str],
        wildcard: Optional[str] = None,
        extra_life_color: Optional[str] = None,
    ) -> Optional[tuple[list[str], int, int]]:
        if index == len(constrained):
            if sum(pool.values()) >= generic_needed:
                return list(spends), generic_needed, 0
            return None

        symbol = constrained[index]
        options = symbol.payment_options()
        if extra_life_color is not None and symbol.kind == COLOR and symbol.color == extra_life_color:
            # K'rrik's standing permission: this plain colored pip also
            # accepts a life payment, exactly like a printed Phyrexian pip
            # (see `KRRIK_LIFE_PER_BLACK_PIP`'s docstring).
            options = [*options, (None, 0, KRRIK_LIFE_PER_BLACK_PIP)]

        tried: set[str] = set()
        for color, extra_generic, life_cost in options:
            if color is not None:
                # RULE 605.1a "any color"/"any type" (``wildcard``): widen a
                # single fixed color option into every color/type this pool
                # actually has, rather than just the pip's own nominal
                # color — never for a bare colorless {C} requirement under
                # "any color" (still needs real colorless mana), but "any
                # type" also relaxes that. ``tried`` dedupes across a
                # symbol's own payment_options (e.g. hybrid's two color
                # choices both expanding to the same wildcard set).
                if wildcard == "type":
                    candidates = list(MANA_TYPES)
                elif wildcard == "color" and color != "C":
                    candidates = list(_FIVE_COLORS)
                elif wildcard in _FIVE_COLORS and color != "C":
                    # MEC-23: a single source color counts as a wildcard
                    # (Quicksilver Elemental's "spend blue mana as though it
                    # were mana of any color") — only that one color
                    # substitutes, alongside the pip's own real color;
                    # unlike the ``"color"`` branch above, mana of a *third*
                    # color still can't pay this pip.
                    candidates = [color, wildcard]
                else:
                    candidates = [color]
                for cand in candidates:
                    if cand in tried:
                        continue
                    tried.add(cand)
                    if pool.get(cand, 0) <= 0:
                        continue
                    pool[cand] -= 1
                    spends.append(cand)
                    found = ManaPool._solve(
                        pool, constrained, index + 1,
                        generic_needed + extra_generic, life_available, spends, wildcard, extra_life_color,
                    )
                    spends.pop()
                    pool[cand] += 1
                    if found is not None:
                        return found
            else:
                # A life payment must leave the payer alive (RULE 119.4).
                if life_cost and life_available - life_cost <= 0:
                    continue
                found = ManaPool._solve(
                    pool, constrained, index + 1,
                    generic_needed + extra_generic,
                    life_available - life_cost, spends, wildcard, extra_life_color,
                )
                if found is not None:
                    colored, generic, life = found
                    return colored, generic, life + life_cost

        return None

    def clone(self) -> "ManaPool":
        """A deep-enough copy for a read-then-mutate multi-step legality
        check — e.g. verifying a spell's printed cost is payable, then
        checking whether what's *left* can also cover Kicker's own
        distinct-color-capped ``{X}`` (`can_pay_distinct_colors` below,
        PAR-7) without actually spending the real pool first."""
        copy = ManaPool()
        copy.pool = dict(self.pool)
        copy.restricted = [
            {"restriction": lot["restriction"], "amounts": dict(lot["amounts"])} for lot in self.restricted
        ]
        copy.pool_by_source = {k: dict(v) for k, v in self.pool_by_source.items()}
        copy.snow_pool = dict(self.snow_pool)
        copy.kept = {until: dict(bucket) for until, bucket in self.kept.items()}
        return copy

    def can_pay_distinct_colors(self, n: int) -> bool:
        """RULE 605.3a-style cap: "spend only colored mana on X. No more
        than one mana of each color may be spent this way." (Emblazoned
        Golem's Kicker ``{X}``, PAR-7) — whether at least ``n`` of the five
        colors (RULE 105.1; colorless/generic never qualify) each have >=1
        *unrestricted* mana available. Ignores any restricted lot (RULE
        605.3a's other shape) — no card combines the two restrictions today.
        """
        if n <= 0:
            return True
        return sum(1 for c in _FIVE_COLORS if self.pool.get(c, 0) > 0) >= n

    def pay_distinct_colors(self, n: int) -> None:
        """Pay ``n`` mana of ``n`` distinct colors, one each — see
        `can_pay_distinct_colors`. Raises if it can't be paid; call that
        first (mirrors `pay`'s own "call `can_pay` first" contract)."""
        if n <= 0:
            return
        if not self.can_pay_distinct_colors(n):
            raise ValueError(f"cannot pay {n} distinct colors from {self.pool!r}")
        paid = 0
        for color in _FIVE_COLORS:
            if paid >= n:
                break
            if self.pool.get(color, 0) > 0:
                self.pool[color] -= 1
                paid += 1
        self._trim_kept()

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.pool)
        if self.restricted:
            # Additive — existing WUBRGC keys are unchanged, so this is
            # safe for any caller ignoring the new key (rendered by
            # gameBoardView.js's `restrictedManaHtml` as its own badge per
            # lot, distinct from the ordinary WUBRGC counts above).
            data["restricted"] = [
                {"restriction": lot["restriction"], "amounts": dict(lot["amounts"])}
                for lot in self.restricted
            ]
        return data

    def __repr__(self) -> str:
        active = {t: n for t, n in self.pool.items() if n}
        return f"ManaPool({active!r})"
