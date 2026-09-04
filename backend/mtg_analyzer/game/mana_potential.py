"""Per-player mana-potential simulation — "what could I still tap for?"

Reference: docs/implementation-state/Done_Backend.md "Mana-Potenzial".

Nothing in this module mutates game state or taps a real permanent — every
check here is a non-mutating "what if" dry run over untapped mana sources
(battlefield permanents via `mana_abilities_for` + hand-zone Spirit-Guide-
style abilities via `hand_mana_abilities_for`), kept deliberately separate
from the real, mutating taps in `game/engine/mana_mixin.py`
(`GameEngine.tap_for_mana`/`activate_hand_mana_ability`) that this module's
callers eventually replay a found plan through.

Two distinct questions, two distinct algorithms:

- **"offenes Potenzial" (open potential), `open_potential_summary`** — an
  aggregate, per-colour *display* number: the most of each colour (W U B R
  G C) a player could still produce this turn from sources not yet
  tapped/exiled. Six independent greedy maximizations (one per colour),
  each starting from an **empty** virtual pool — a deliberate
  approximation (no simultaneous joint allocation across all six colours
  at once) that keeps this cheap (O(sources) per colour) and, crucially,
  keeps ``open + used`` (`used_potential_summary`, `GameState.
  mana_produced_this_turn`) equal to "total mana capacity accessed this
  turn": mana already sitting in the real pool was produced by a source
  that's already unavailable to this "still open" count, so counting it
  again here would double-count it. **Do not** seed this from the real
  pool — see `find_tap_plan` below for the one place that's correct.
- **A specific cost, `find_tap_plan`/`is_castable_via_potential`** — "can I
  pay *this* `ManaCost` right now, using anything at my disposal" — seeded
  from the player's **real, current** `ManaPool` (floating mana is
  genuinely spendable) plus whichever untapped sources are needed. This
  drives both hand-card castable-highlighting and the real, executable
  `GameEngine.auto_tap_for` action (`game/engine/mana_mixin.py`), including
  the automatic top-up `cast_spell`/`activate_ability` attempt on their own
  when mana is the only thing blocking an otherwise-legal play (`game/
  engine/casting_mixin.py`/`activation_mixin.py`'s own
  ``assume_mana_available`` probe). **Only ever taps sources whose cost is
  just tapping (plus, rarely, a life payment)** — never a source whose cost
  sacrifices a permanent (a Treasure token, Ashnod's Altar) or exiles a
  card from hand (Elvish/Simian Spirit Guide): consuming a resource to make
  mana is a real decision a player should make deliberately by tapping
  that specific source themselves, not something either the explicit
  auto-tap action or the automatic pre-cast hook should ever do silently
  (`_auto_tappable_candidates`). `open_potential_summary`'s aggregate
  display is deliberately **not** restricted this way — it still shows the
  true maximum including those sources, since the display's job is honest
  information, not a decision about what to spend.

Both algorithms prefer a net-mana-positive "pay one mana, get more mana
back" converter (Selvala, Heart of the Wilds' own ``{G}`` cost; and the
**filter lands** — Twilight Mire's ``{B/G}, {T}: Add {B}{B}, {B}{G}, or
{G}{G}.`` — now that the oracle parser turns that second line into a
``ManaAbility`` with a mana cost of its own) over a plain zero-cost
producer, per `_is_net_positive_converter` — a search-order heuristic, not
a correctness requirement: it makes the common case find the true maximum
instead of leaving a converter's value on the table by trying it last (or
not at all, once the search's node budget runs out). A filter land needs
two things a lone Selvala never did: its multi-option production
(``{B}{B}`` / ``{B}{G}`` / ``{G}{G}``) has to be steered by simulating the
filter's own cost payment and picking the option that then covers the cost
(`_choose_option`), not the first option that merely contains a needed
colour, and its cheaper sibling ``{T}: Add {C}.`` must not be
allowed to spend the land's one tap before the filter ability can be fed
(`find_tap_plan`'s second pass — RULE 605.1a: a permanent's mana
abilities share the one activation).

Cost-payability for a candidate mana ability's own `ActivationCost`
(`game/costs.py`) is checked against a private, per-simulation *scratch*
bookkeeping (`_Commitment`) rather than by calling `GameEngine.
_can_pay_activation_cost`/`_pay_activation_cost` directly — those are
hard-wired to the real, live `player.mana_pool`/`GameObject.tapped`, not a
scratch copy, and mutating real state just to answer "what if" is exactly
what this module exists to avoid. `_Commitment` is a deliberately
lightweight, parallel re-implementation of the *shared-resource* half of
that pair (which permanents are already tapped/sacrificed/committed this
simulation, how much life/graveyard/library is left to spend) — covering
the cost shapes real mana abilities actually use (mana, ``{T}``/``{Q}``,
pay life, sacrifice, tap-others, discard-N, exile-from-graveyard,
exile-top-of-library, return-to-hand, add-counters, unattach-self,
pay-energy). A handful of `ActivationCost` fields that no real mana
ability pairs with a mana-producing effect (loyalty, ``discard_self``,
``pay_life``/``remove_counters``'s "X"/"any number" sentinels, class-level/
sorcery-speed gates) are treated as simply unpayable here — fail-soft, the
same "approximate the long tail rather than guess" convention
`mana_abilities.py` already documents for itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.mana_cost import ManaCost
from ..models.mana_pool import MANA_TYPES, ManaPool
from ..models.player import Player
from . import continuous
from .costs import DISCARD_HAND, PAY_LIFE_X, REMOVE_COUNTERS_ANY, REMOVE_COUNTERS_X
from .mana_abilities import ManaAbility, hand_mana_abilities_for, mana_abilities_for, mana_source_kind_for

#: The six mana types WUBRGC potential is tracked/displayed in, matching
#: `ManaPool.MANA_TYPES`'s own set (order doesn't matter here).
_ALL_TYPES: tuple[str, ...] = MANA_TYPES

#: Search-node budget for `find_tap_plan`'s candidate search — bounds the
#: worst case so a pathological board can't blow the per-test pytest
#: timeout (`backend/pytest.ini`, CLAUDE.md) or make a live view() slow.
#: A real board/hand rarely offers more than a couple dozen mana sources.
_MAX_CANDIDATES_TRIED = 32


# --------------------------------------------------------------------------
# Candidate sources
# --------------------------------------------------------------------------


@dataclass
class _Candidate:
    """One untapped mana ability, on the battlefield or in hand."""

    kind: str  # "battlefield" | "hand"
    obj: Any  # GameObject
    ability_index: int
    ability: ManaAbility


def _battlefield_candidates(engine: Any, player: Player) -> list[_Candidate]:
    out: list[_Candidate] = []
    for obj in engine.state.permanents_controlled_by(player.id):
        if continuous.activation_prohibited(engine.state, obj, is_mana_ability=True):
            continue
        for idx, ability in enumerate(mana_abilities_for(obj, state=engine.state)):
            if ability.options:
                out.append(_Candidate("battlefield", obj, idx, ability))
    return out


def _hand_candidates(engine: Any, player: Player) -> list[_Candidate]:
    out: list[_Candidate] = []
    for obj in player.hand:
        for idx, ability in enumerate(hand_mana_abilities_for(obj, state=engine.state)):
            if ability.options:
                out.append(_Candidate("hand", obj, idx, ability))
    return out


def _all_candidates(engine: Any, player: Player) -> list[_Candidate]:
    return _battlefield_candidates(engine, player) + _hand_candidates(engine, player)


def _auto_tappable_candidates(engine: Any, player: Player) -> list[_Candidate]:
    """`_all_candidates`, minus any source auto-tap (`find_tap_plan`, and
    therefore both `GameEngine.auto_tap_for` and the automatic pre-cast
    top-up) must never spend on its own: every hand-zone (exile-from-hand)
    source — Elvish/Simian Spirit Guide — and every battlefield source
    whose own cost sacrifices a permanent — a Treasure token, Ashnod's
    Altar. Both consume a resource beyond "just tap it", so using one is a
    real decision left to the player's own explicit `tap_for_mana`/
    `activate_hand_mana_ability` click, never silently spent for them (see
    module docstring). `open_potential_summary`'s display keeps using the
    unrestricted `_all_candidates` — this filter is specific to spending.
    """
    return [
        c for c in _all_candidates(engine, player)
        if c.kind != "hand" and not c.ability.cost.sacrifice
    ]


def _is_net_positive_converter(ability: ManaAbility) -> bool:
    """A mana ability whose own cost itself spends mana, for a net gain —
    "pay one mana, get more mana back" (Selvala, Heart of the Wilds' own
    ``{G}``; a filter land's ``{B/G}, {T}: Add {B}{B}, {B}{G}, or {G}{G}.``).
    Generic: keys only off ``cost.mana``/production shape, not any specific
    card name.
    """
    if not ability.cost.mana.symbols:
        return False
    best_production = max((sum(opt.values()) for opt in ability.options), default=0)
    return best_production > ability.cost.mana.converted_mana_cost


def _producible_colors(ability: ManaAbility) -> set:
    """Every colour any of ``ability``'s production options can make — the
    fixed-option counterpart of `_flexible_colors` (which only answers for
    an `any_combination` split). Used to tell whether a filter land's
    converter ability can help with a colour the cost is still short of."""
    return {color for opt in ability.options for color in opt}


def _flexible_colors(ability: ManaAbility) -> Optional[set]:
    """The colours a candidate's production can be steered into, or
    ``None`` when it isn't flexible at all (a fixed single-colour/dual
    option list where the payer only ever picks *one* of the printed
    options, not a distribution)."""
    if ability.any_combination:
        return {c for opt in ability.options for c in opt}
    return None


# --------------------------------------------------------------------------
# Scratch bookkeeping shared across one simulation pass
# --------------------------------------------------------------------------


@dataclass
class _Commitment:
    """Shared resources already spoken for during one simulation pass —
    the lightweight stand-in for what `_pay_activation_cost` would really
    mutate, scoped to exactly the cost shapes a mana ability's own
    `ActivationCost` realistically uses (see module docstring)."""

    tapped: set = field(default_factory=set)  # instance_ids unavailable to {T}
    exiled_hand: set = field(default_factory=set)  # hand instance_ids already spent
    sacrificed: set = field(default_factory=set)
    tap_others_used: set = field(default_factory=set)
    discarded: set = field(default_factory=set)
    returned: set = field(default_factory=set)
    unattached: set = field(default_factory=set)
    life: int = 0
    energy: int = 0
    graveyard_left: int = 0
    library_left: int = 0

    @classmethod
    def fresh(cls, engine: Any, player: Player) -> "_Commitment":
        tapped = {
            o.instance_id
            for o in engine.state.permanents_controlled_by(player.id)
            if o.tapped
        }
        return cls(
            tapped=tapped,
            life=player.life,
            energy=player.counters.get("energy", 0),
            graveyard_left=len(player.graveyard),
            library_left=len(player.library),
        )


def _sacrifice_pool(engine: Any, player: Player, what: str, commitment: _Commitment) -> list:
    return [
        o
        for o in engine.state.permanents_controlled_by(player.id)
        if engine._matches_sacrifice_type(o, what) and o.instance_id not in commitment.sacrificed
    ]


def _tap_others_pool(engine: Any, player: Player, subtype: str, commitment: _Commitment) -> list:
    return [
        o
        for o in engine._tap_others_pool(player, None, subtype)
        if o.instance_id not in commitment.tapped and o.instance_id not in commitment.tap_others_used
    ]


def _discard_pool(player: Player, exclude_id: Any, commitment: _Commitment) -> list:
    return [
        c
        for c in player.hand
        if c.instance_id != exclude_id
        and c.instance_id not in commitment.discarded
        and c.instance_id not in commitment.exiled_hand
    ]


def _return_to_hand_candidate(engine: Any, player: Player, subtype: str, commitment: _Commitment):
    for obj in engine.state.permanents_controlled_by(player.id):
        if continuous.has_subtype(obj, subtype) and obj.instance_id not in commitment.returned:
            return obj
    return None


def _non_mana_cost_payable(
    engine: Any, player: Player, candidate: _Candidate, commitment: _Commitment
) -> bool:
    """Whether every cost component of ``candidate``'s ability *except* its
    mana portion (checked separately against a `ManaPool`) is payable given
    ``commitment``'s already-spoken-for resources — without committing
    anything yet (a pure check, mirroring `_can_pay_activation_cost`'s
    read-only shape)."""
    cost = candidate.ability.cost
    obj = candidate.obj

    if candidate.kind == "battlefield":
        if cost.taps_self and (
            obj.instance_id in commitment.tapped or engine._summoning_sick_for_tap(obj)
        ):
            return False
        if cost.untaps_self and obj.instance_id not in commitment.tapped:
            return False
    if candidate.kind == "hand" and obj.instance_id in commitment.exiled_hand:
        return False

    # Unsupported-in-practice shapes (see module docstring) — no real
    # mana ability pairs these with mana production, so failing closed
    # here is a documented simplification, not a regression.
    if cost.loyalty is not None or cost.discard_self or cost.put_hand_card_on_library:
        return False
    if cost.pay_life == PAY_LIFE_X:
        return False
    if cost.remove_counters and cost.remove_counters[1] in (REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY):
        return False

    if cost.pay_life and commitment.life - cost.pay_life < 0:
        return False
    if cost.pay_energy and commitment.energy - cost.pay_energy < 0:
        return False
    if cost.remove_counters:
        kind, count = cost.remove_counters
        if obj.counters.get(kind, 0) < count:
            return False
    if cost.exile_from_graveyard and commitment.graveyard_left - cost.exile_from_graveyard < 0:
        return False
    if cost.exile_top_of_library and commitment.library_left < cost.exile_top_of_library:
        return False
    if cost.unattach_self and (obj.attached_to is None or obj.instance_id in commitment.unattached):
        return False
    if cost.sacrifice:
        if cost.sacrifice == "self":
            if obj.instance_id in commitment.sacrificed:
                return False
        elif not _sacrifice_pool(engine, player, cost.sacrifice, commitment):
            return False
    if cost.tap_others:
        count, subtype = cost.tap_others
        if len(_tap_others_pool(engine, player, subtype, commitment)) < count:
            return False
    if cost.discard and cost.discard != DISCARD_HAND:
        exclude_id = obj.instance_id if candidate.kind == "hand" else None
        if len(_discard_pool(player, exclude_id, commitment)) < cost.discard:
            return False
    elif cost.discard == DISCARD_HAND:
        return False  # no fixed count to reserve — unsupported here
    if cost.return_to_hand and _return_to_hand_candidate(engine, player, cost.return_to_hand, commitment) is None:
        return False
    return True


def _commit_non_mana_cost(
    engine: Any, player: Player, candidate: _Candidate, commitment: _Commitment
) -> None:
    """Reserve ``candidate``'s non-mana cost components against
    ``commitment`` — call only after `_non_mana_cost_payable` returned
    ``True`` for the same commitment state."""
    cost = candidate.ability.cost
    obj = candidate.obj

    if candidate.kind == "battlefield" and cost.taps_self:
        commitment.tapped.add(obj.instance_id)
    if candidate.kind == "battlefield" and cost.untaps_self:
        commitment.tapped.discard(obj.instance_id)
    if candidate.kind == "hand":
        commitment.exiled_hand.add(obj.instance_id)
    if cost.pay_life:
        commitment.life -= cost.pay_life
    if cost.pay_energy:
        commitment.energy -= cost.pay_energy
    if cost.exile_from_graveyard:
        commitment.graveyard_left -= cost.exile_from_graveyard
    if cost.exile_top_of_library:
        commitment.library_left -= cost.exile_top_of_library
    if cost.unattach_self:
        commitment.unattached.add(obj.instance_id)
    if cost.sacrifice:
        if cost.sacrifice == "self":
            commitment.sacrificed.add(obj.instance_id)
        else:
            victim = _sacrifice_pool(engine, player, cost.sacrifice, commitment)[0]
            commitment.sacrificed.add(victim.instance_id)
    if cost.tap_others:
        count, subtype = cost.tap_others
        for picked in _tap_others_pool(engine, player, subtype, commitment)[:count]:
            commitment.tap_others_used.add(picked.instance_id)
    if cost.discard and cost.discard != DISCARD_HAND:
        exclude_id = obj.instance_id if candidate.kind == "hand" else None
        for picked in _discard_pool(player, exclude_id, commitment)[: cost.discard]:
            commitment.discarded.add(picked.instance_id)
    if cost.return_to_hand:
        bounced = _return_to_hand_candidate(engine, player, cost.return_to_hand, commitment)
        if bounced is not None:
            commitment.returned.add(bounced.instance_id)


def _choose_option(
    ability: ManaAbility,
    preferred_colors: set,
    *,
    cost: Optional[ManaCost] = None,
    pool: Optional[ManaPool] = None,
    life: int = 0,
) -> tuple[Optional[dict], Optional[dict]]:
    """Pick which of ``ability``'s mutually-exclusive production options to
    use (or, for an `any_combination` ability, a colour split) — favouring
    whatever's in ``preferred_colors`` when there's a real choice, an empty
    set meaning "no preference, first option is fine". Returns
    ``(option, color_split)`` — exactly one of the two is non-``None``.

    When ``cost``/``pool`` are given (`find_tap_plan`'s search), a
    multi-option converter — a filter land's ``Add {B}{B}, {B}{G}, or
    {G}{G}.`` — is steered by *simulating* its own cost payment first: the
    option preferred is the one that then makes ``cost`` payable, else the
    one covering the most of what's still short. Picking the first option
    that merely contains a needed colour would stop a ``{G}{G}`` search at
    ``{B}{G}``, and picking the most-of-one-colour option would burn the
    ``{B}`` a ``{B}{G}`` search still needs.
    """
    if ability.any_combination:
        total = sum(ability.options[0].values())
        colors = sorted(_flexible_colors(ability) or ())
        wanted = [c for c in colors if c in preferred_colors] or colors
        if not wanted:
            return {}, None
        split: dict[str, int] = {c: 0 for c in wanted}
        for i in range(total):
            split[wanted[i % len(wanted)]] += 1
        return None, split

    if not preferred_colors:
        return ability.options[0], None

    # Scratch pool = the pool as it would stand *after* paying this
    # ability's own mana cost (a converter/filter land), so both the
    # ranking and the "does this option finish the job" check see the
    # colours that payment will have consumed.
    scratch: Optional[ManaPool] = None
    if cost is not None and pool is not None:
        scratch = _copy_pool(pool)
        if ability.cost.mana.symbols:
            if scratch.can_pay(ability.cost.mana, life_available=life):
                scratch.pay(ability.cost.mana, life_available=life)
            else:
                scratch = None
    short_after = (
        _still_short_colors(cost, scratch) if (scratch is not None and cost is not None) else set()
    ) or set(preferred_colors)
    ranked = sorted(
        ability.options,
        key=lambda opt: sum(n for color, n in opt.items() if color in short_after),
        reverse=True,
    )
    if scratch is not None and cost is not None:
        for opt in ranked:
            trial = _copy_pool(scratch)
            trial.add_many(opt)
            if trial.can_pay(cost, life_available=life):
                return opt, None
    if any(color in short_after for color in ranked[0]):
        return ranked[0], None
    return ability.options[0], None


def _try_activate(
    engine: Any,
    player: Player,
    candidate: _Candidate,
    commitment: _Commitment,
    pool: ManaPool,
    preferred_colors: set,
    cost: Optional[ManaCost] = None,
) -> Optional["TapStep"]:
    """Attempt to pay ``candidate``'s full cost (mana from ``pool``,
    everything else from ``commitment``) and, on success, mutate both and
    return the `TapStep` describing what happened — ``None`` (no mutation)
    if the ability isn't payable right now. ``cost`` (the overall cost the
    search is solving) is only used to steer a multi-option converter's
    production choice — see `_choose_option`."""
    if not _non_mana_cost_payable(engine, player, candidate, commitment):
        return None
    mana_cost = candidate.ability.cost.mana
    if mana_cost.symbols and not pool.can_pay(mana_cost, life_available=commitment.life):
        return None

    option, color_split = _choose_option(
        candidate.ability, preferred_colors, cost=cost, pool=pool, life=commitment.life
    )
    produced = dict(color_split) if color_split is not None else dict(option or {})
    if not produced:
        return None

    if mana_cost.symbols:
        pool.pay(mana_cost, life_available=commitment.life)
    _commit_non_mana_cost(engine, player, candidate, commitment)
    pool.add_many(
        produced, restriction=candidate.ability.restriction,
        source_kind=mana_source_kind_for(candidate.obj),
    )

    option_index = 0
    if color_split is None and option is not None:
        option_index = candidate.ability.options.index(option)
    return TapStep(
        kind=candidate.kind,
        instance_id=candidate.obj.instance_id,
        ability_index=candidate.ability_index,
        option_index=option_index,
        color_split=color_split,
        produced=produced,
    )


# --------------------------------------------------------------------------
# Open-potential aggregate (per colour, display only)
# --------------------------------------------------------------------------


def _maximize_color(engine: Any, player: Player, color: str) -> int:
    """The most ``color`` mana producible this turn from sources not yet
    tapped/exiled — an empty virtual pool (see module docstring), every
    zero-cost candidate activated (it can only ever help: either it
    produces ``color`` directly, or it's raw material a converter might
    still need), then net-positive converters fired in a bounded
    fixed-point loop whenever doing so can only help ``color`` (flexible
    output, or fixed output that's already ``color``)."""
    pool = ManaPool()
    commitment = _Commitment.fresh(engine, player)
    candidates = _all_candidates(engine, player)
    preferred = {color}

    zero_cost = [c for c in candidates if not c.ability.cost.mana.symbols]
    converters = [c for c in candidates if c.ability.cost.mana.symbols]

    for candidate in zero_cost:
        _try_activate(engine, player, candidate, commitment, pool, preferred)

    remaining = converters
    for _ in range(len(converters) + 1):  # bounded fixed point
        fired_any = False
        still_untried = []
        for candidate in remaining:
            ability = candidate.ability
            flexible = _flexible_colors(ability)
            helps_color = (
                (flexible is not None and color in flexible)
                or any(color in opt for opt in ability.options)
            )
            if not (helps_color and _is_net_positive_converter(ability)):
                still_untried.append(candidate)
                continue
            step = _try_activate(engine, player, candidate, commitment, pool, preferred)
            if step is not None:
                fired_any = True
            else:
                still_untried.append(candidate)
        remaining = still_untried
        if not fired_any:
            break

    return pool.pool.get(color, 0)


def open_potential_summary(engine: Any, player: Player) -> dict[str, int]:
    """Per-colour (WUBRGC) maximum additional mana producible this turn
    from sources not yet tapped/exiled — six independent maximizations,
    **not** a simultaneous joint allocation (see module docstring)."""
    return {color: _maximize_color(engine, player, color) for color in _ALL_TYPES}


def max_potential_total(engine: Any, player: Player) -> int:
    """A safe (possibly generous) **upper bound** on how much mana
    ``player`` could produce this turn from every untapped/unexiled,
    plain-tap source combined — used only to bound a "how high could X/
    Kicker go" search (`GameEngine.max_affordable_x`/`max_affordable_
    kicker`/`max_affordable_kicker_x`, MEC-13), never as a castability
    claim on its own. Deliberately simpler than `open_potential_summary`'s
    six per-colour maximizations: any colour of mana pays a generic cost
    (RULE 107.3c, what X and Kicker's own `{X}` always are), so the bound
    only needs "how much mana, in total, ignoring colour" — each
    candidate's own best single-tap production, summed, with no netting
    of a converter's own cost against what it produces (an overestimate
    is fine here; the real per-value payability check downstream is what
    actually gates the answer)."""
    candidates = _auto_tappable_candidates(engine, player)
    return sum(
        max((sum(opt.values()) for opt in c.ability.options), default=0)
        for c in candidates
    )


def used_potential_summary(engine: Any, player: Player) -> dict[str, int]:
    """Mana already produced (real taps/hand-exiles) this turn, per colour
    — a thin read of `GameState.mana_produced_this_turn`, reset every
    `GameEngine.begin_turn` (`game/engine/turn_loop_mixin.py`) and
    incremented at the real production sites (`game/engine/mana_mixin.py`).
    """
    produced = engine.state.mana_produced_this_turn.get(player.id, {})
    return {color: produced.get(color, 0) for color in _ALL_TYPES}


def player_summary(engine: Any, player: Player) -> dict[str, dict[str, int]]:
    """``{"open": ..., "used": ...}`` — the whole "Mana-Potenzial" block for
    one player, as embedded in `GameSession.view()`'s per-player-id
    ``mana_potential`` dict."""
    return {
        "open": open_potential_summary(engine, player),
        "used": used_potential_summary(engine, player),
    }


def record_mana_produced(engine: Any, player: Player, produced: dict) -> None:
    """Bump `GameState.mana_produced_this_turn` for a *real* production
    event — called by `GameEngine.tap_for_mana`/`activate_hand_mana_ability`
    right next to their existing `record_stat` call, never by anything in
    this module's own simulation paths (which never touch real state)."""
    bucket = engine.state.mana_produced_this_turn.setdefault(player.id, {})
    for color, amount in produced.items():
        bucket[color] = bucket.get(color, 0) + amount


# --------------------------------------------------------------------------
# Exact(-effort) tap-plan solver for a specific cost
# --------------------------------------------------------------------------


@dataclass
class TapStep:
    kind: str  # "battlefield" | "hand"
    instance_id: Any
    ability_index: int
    option_index: int = 0
    color_split: Optional[dict] = None
    produced: dict = field(default_factory=dict)


@dataclass
class TapPlan:
    steps: list

    def total_produced(self) -> dict:
        out: dict[str, int] = {}
        for step in self.steps:
            for color, amount in step.produced.items():
                out[color] = out.get(color, 0) + amount
        return out


def _copy_pool(pool: ManaPool) -> ManaPool:
    copy = ManaPool()
    copy.pool = dict(pool.pool)
    copy.restricted = [
        {"restriction": lot["restriction"], "amounts": dict(lot["amounts"])} for lot in pool.restricted
    ]
    return copy


def _needed_colors(cost: ManaCost) -> set:
    needed: set = set()
    for symbol in cost.symbols:
        needed |= symbol.colors
        if symbol.kind == "colorless":
            needed.add("C")
    return needed


def _still_short_colors(cost: ManaCost, pool: ManaPool) -> set:
    """MEC-13: which of ``cost``'s named colour requirements ``pool``
    doesn't cover *yet* — steers a flexible/multi-option source's colour
    choice (`_choose_option`'s ``preferred_colors``) toward whatever's
    still missing, recomputed fresh before each tap, rather than
    `_needed_colors`'s one static set for the whole search.

    Without this, two untapped dual lands (each "{T}: Add {U} or {B}.")
    searching for a `{U}{B}` cost would both greedily prefer the *first*
    colour in the cost's needed set that matches one of their own options
    — the same colour, every time — producing {U}{U} or {B}{B} and never
    finding the real, obviously-available plan. A colour already at or
    past its required count is dropped from the preference so the next
    flexible source tried gets steered at whatever's actually still short
    (a slight overcount for a hybrid symbol's *other* half is harmless —
    it only means that colour stays "wanted" a little longer than
    strictly necessary, never that a real shortfall gets missed).
    """
    required: dict[str, int] = {}
    for symbol in cost.symbols:
        if symbol.kind == "colorless":
            required["C"] = required.get("C", 0) + 1
            continue
        for color in symbol.colors:
            required[color] = required.get(color, 0) + 1
    return {color for color, amount in required.items() if pool.pool.get(color, 0) < amount}


def _sorted_candidates(candidates: list[_Candidate], needed_colors: set) -> list[_Candidate]:
    def key(c: _Candidate) -> tuple:
        converter = _is_net_positive_converter(c.ability)
        flexible = _flexible_colors(c.ability)
        matches_need = bool(flexible & needed_colors) if flexible else any(
            needed_colors & set(opt) for opt in c.ability.options
        )
        best = max((sum(opt.values()) for opt in c.ability.options), default=0)
        return (not converter, not matches_need, -best)

    return sorted(candidates, key=key)


def find_tap_plan(
    engine: Any, player: Player, cost: ManaCost, *, allows_restriction=None
) -> Optional[TapPlan]:
    """A plan of untapped/unexiled mana sources to activate so ``cost``
    becomes payable, seeded from the player's **real, current** mana pool
    (unlike `open_potential_summary`'s empty-pool aggregate — see module
    docstring) — or ``None`` if no plan was found within the search
    budget (fail-soft: "not found" isn't a proof of "impossible", see the
    module docstring's own converter-ordering caveat). Never spends a
    sacrifice- or hand-exile-cost source (Treasures, Spirit Guides) — see
    `_auto_tappable_candidates`.
    """
    pool = _copy_pool(player.mana_pool)
    if pool.can_pay(cost, life_available=player.life, allows_restriction=allows_restriction):
        return TapPlan(steps=[])

    needed = _needed_colors(cost)
    candidates = _sorted_candidates(_auto_tappable_candidates(engine, player), needed)[:_MAX_CANDIDATES_TRIED]

    plan = _run_tap_search(engine, player, cost, candidates, allows_restriction)
    if plan is not None:
        return plan

    # RULE 605.1a: a permanent's mana abilities share its one activation, so
    # a filter land's cheap ``{T}: Add {C}.`` and its net-positive converter
    # ``{B/G}, {T}: Add {B}{B}/{B}{G}/{G}{G}.`` are mutually exclusive. The
    # pass above will happily spend the tap on ``{C}`` before the pool holds
    # the ``{B/G}`` the converter needs — so if it found nothing, retry once
    # with each such land's non-converter abilities held back, letting the
    # converter be fed first.
    trimmed = _prefer_converter_abilities(candidates, needed)
    if len(trimmed) < len(candidates):
        return _run_tap_search(engine, player, cost, trimmed, allows_restriction)
    return None


def _prefer_converter_abilities(
    candidates: list[_Candidate], needed_colors: set
) -> list[_Candidate]:
    """Drop the non-converter mana abilities of any permanent that also has
    a net-positive converter ability able to produce a colour in
    ``needed_colors`` — so `find_tap_plan`'s retry spends that permanent's
    single tap (RULE 605.1a) on the filter, not on its cheaper sibling."""
    guarded: set = {
        c.obj.instance_id
        for c in candidates
        if c.kind == "battlefield"
        and _is_net_positive_converter(c.ability)
        and _producible_colors(c.ability) & needed_colors
    }
    return [
        c
        for c in candidates
        if c.obj.instance_id not in guarded or _is_net_positive_converter(c.ability)
    ]


def _run_tap_search(
    engine: Any,
    player: Player,
    cost: ManaCost,
    candidates: list[_Candidate],
    allows_restriction,
) -> Optional[TapPlan]:
    """One bounded fixed-point search over ``candidates`` (already sorted
    and capped by the caller). A single linear pass would miss a converter
    tried before the plain producer that feeds its own mana cost (Selvala
    needs a Forest's {G} in the pool before *her* {G} cost is payable) — so
    failed candidates are retried every round, bounded (like
    `_maximize_color`'s converter loop) so a board that truly can't pay
    still terminates promptly."""
    pool = _copy_pool(player.mana_pool)
    commitment = _Commitment.fresh(engine, player)
    needed = _needed_colors(cost)
    steps: list[TapStep] = []
    remaining = candidates
    for _ in range(len(candidates) + 1):
        progressed = False
        still_remaining: list[_Candidate] = []
        for candidate in remaining:
            # MEC-13: recomputed fresh before each tap (not the static
            # ``needed`` the initial sort used) — see `_still_short_colors`.
            preferred = _still_short_colors(cost, pool) or needed
            step = _try_activate(engine, player, candidate, commitment, pool, preferred, cost)
            if step is None:
                still_remaining.append(candidate)
                continue
            steps.append(step)
            progressed = True
            if pool.can_pay(cost, life_available=commitment.life, allows_restriction=allows_restriction):
                return TapPlan(steps=steps)
        remaining = still_remaining
        if not progressed:
            break
    return None


def is_castable_via_potential(
    engine: Any, player: Player, cost: ManaCost, *, allows_restriction=None
) -> bool:
    """Whether `find_tap_plan` finds a way to pay ``cost`` — the predicate
    behind the frontend's castable-highlight border."""
    return find_tap_plan(engine, player, cost, allows_restriction=allows_restriction) is not None
