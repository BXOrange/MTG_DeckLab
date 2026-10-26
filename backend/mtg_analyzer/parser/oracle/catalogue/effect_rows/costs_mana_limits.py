"""Exchange, pay-cost-then, counter-unless-pay, mana, transform and activation-limit rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import json
import re

from typing import Any, Callable, Optional
from ..clause_hooks import parse_effect_body
from ..clause_reading import ClauseReading
from ..clause_primitives import (
    ACTION_ONCE_PER_TURN_MARKER,
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    announces_creature_target,
    ONCE_PER_TURN_MARKER,
    ONLY_BEFORE_ATTACKERS_MARKER,
    ONLY_DURING_YOUR_TURN_MARKER,
    SORCERY_SPEED_MARKER,
    TRIGGER_ONCE_PER_TURN_MARKER,
    X_CAP_MARKER,
    X_SPEND_COLOR_MARKER,
)
from ..count_phrase import parse_count_phrase
from ..counters import KEYWORD_COUNTER_KINDS
from ..static_handlers import activation_attached_condition, static_condition
from ..subgrammars import (
    count_of,
    NUMBER,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_is_optional,
    target_kind_allowed,
)
from ...normalize import SELF
from ...spec import EffectSpec, GROUP_SUBJECT_KEY_SENTINEL, if_you_do_antecedent_ok
from .shared import (
    ATTACHED_SUBJECT,
    BECOMES_TARGET_EVENT,
    COLOR_WORDS,
    compile_clause,
    EffectHandler,
    ENTERING_CONTROLLER,
    EVENT_PLAYER_EVENTS_KEY,
    fight_kind,
    MULTI_TARGET_ALT,
    MULTI_TARGET_DISTINCT_CONTROLLERS,
    multi_target_params,
    MULTI_TARGET_QUANTIFIER,
    optional_param,
    PREVIOUS_SUBJECT,
    SACRIFICE_EDICT_WHAT_WORDS,
    SELECTOR_WORD_MAP,
    SELF_SUBJECT,
    TARGET_B,
    THEN,
)


def _choose_targets(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Choose target creature you control and target creature you don't
    control." (RULE 601.2c) — announces the pair the following clauses act on
    by pronoun; see `effects.ChooseTargetsEffect`."""
    first = fight_kind(m.group("target"))
    second = fight_kind(m.group("target_b"))
    if first is None or second is None:
        return None
    return [EffectSpec("choose_targets", {"kinds": [first, second]})]


def _choose_targets_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Choose two target creatures controlled by different players." (PAR-1,
    Run Away Together) — the quantified-*group* sibling of `_choose_targets`
    just above: one requirement picking N objects of the *same* kind (the
    `_multi_target_params` shape `destroy`/`exile`'s own multi-target rows
    already use) rather than two independently-kinded single picks. Still an
    announcement only — see `effects.ChooseTargetsEffect`'s ``count``/
    ``distinct_controllers`` widening and `_return_previous_group`, the
    "Return those creatures…" clause that reads the group back.
    """
    params = multi_target_params(m)
    if params is None:
        return None
    kind = params.pop("target_kind")
    return [EffectSpec("choose_targets", {"kinds": [kind], **params})]


def _choose_target_single(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """A bare target announcement consumed by a following pronoun clause.

    PAR-130's per-player bodies print this as "choose [up to one] target X
    that player controls"; the per-player wrapper stamps the resulting
    requirement exactly like it does an ordinary destroy/exile effect.
    """
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {"kinds": [kind], "optional": target_is_optional(m)}
    # "choose target blocking creature" / "…attacking creature whose controller controls an Island" (Dwarven Sea
    # Clan, MEC-131): `resolve_target_kind` collapses the combat-state adjective onto the bare kind, so without the
    # filter the announcement would accept any creature.
    creature_filter = dict(resolve_target_creature_state_filter(m.group("target")) or {})
    if kind == "attacking_or_blocking_creature":
        # The announcement keeps the plain creature kind and carries the combat-state pair as a filter key, which the
        # announcement-time and resolution-time legality checks both read (RULE 608.2b).
        params["kinds"] = ["creature"]
        creature_filter["attacking_or_blocking"] = True
    land = m.groupdict().get("controls_land")
    if land:
        # RULE 305.6: an Island is a land with the Island subtype.
        creature_filter["controller_controls_land_subtype"] = land.lower()
    if creature_filter:
        params["creature_filter"] = creature_filter
    return [EffectSpec("choose_targets", params)]


# RULE 701.10 "exchange control of `<X>` and `<Y>`" (PAR-29) — three
# distinct printed shapes, each onto `effects.ExchangeControlEffect`'s own
# matching mode: this permanent plus one target (`_exchange_control_self`,
# Avarice Totem/Phyrexian Infiltrator-shaped — the mandatory sibling of the
# already-hand-authored Gilded Drake "up to one"); two independently-typed
# targets named in full (`_exchange_control_two_explicit`, Chromeshell
# Crab's "target creature you control and target creature an opponent
# controls"); and "N target `<same kind>`[ controlled by different
# players]" (`_exchange_control_multi`, Shifting Borders/Modify Memory —
# reusing `_multi_target_params`'s own quantifier/`distinct_controllers`
# grammar rather than a new one, same as `_choose_targets_group` just
# above). "Controlled by different players" only ever reaches
# `_exchange_control_multi`'s `distinct_controllers` as an *offer-time*
# constraint (`targeting.TargetSpec`'s own docstring — it has no
# equivalent for the two-explicit-target shape's independent specs); a
# same-controller pick there still can't actually exchange anything
# (`ExchangeControlEffect.apply`'s own runtime `mine.controller_id !=
# theirs.controller_id` check), so nothing incorrect resolves either way.
_EXCHANGE_CONTROL_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control",
     "permanent", "permanent_you_control", "permanent_you_dont_control",
     "nonland_permanent", "nonland_permanent_you_control",
     "nonland_permanent_you_dont_control", "artifact", "land",
     "land_you_control", "land_you_dont_control"}
)


def _exchange_control_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _EXCHANGE_CONTROL_TARGET_KINDS):
        return None
    return [EffectSpec("exchange_control", {
        "target_kind": kind, **optional_param(m),
    })]


#: PAR-30 RULE 701.10 residue — the optional trailing cross-target predicate
#: on an "exchange control of X and Y" clause, checked at resolution by
#: `effects.ExchangeControlEffect._cross_target_ok`:
#:   * "…that share[s] {a card type | a permanent type | 1 of those types}
#:     [with it]" (Daring Thief / Legerdemain / Role Reversal / Shifting
#:     Loyalties / Trickster-God's Heist) — all fold to ``shares_type="card"``
#:     (RULE 205.2: two battlefield permanents sharing a permanent type ⇔
#:     sharing a card type);
#:   * "…with equal or lesser mana value" (Puca's Mischief).
_EXCHANGE_XTARGET_TAIL = (
    r"(?:,? (?P<xt_share>that shares? (?:a (?:card|permanent) type|1 of those types)"
    r"(?: with it)?)"
    r"|,? with (?P<xt_mv>equal or lesser mana value))?"
)


def _exchange_xtarget_params(m: re.Match[str]) -> dict:
    gd = m.groupdict()
    params: dict = {}
    if gd.get("xt_share"):
        params["shares_type"] = "card"
    if gd.get("xt_mv"):
        params["second_not_greater"] = "mana_value"
    return params


def _exchange_control_two_explicit(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    first = resolve_target_kind(m.group("target"))
    second = resolve_target_kind(m.group("target_b"))
    if not (target_kind_allowed(first, _EXCHANGE_CONTROL_TARGET_KINDS)
            and target_kind_allowed(second, _EXCHANGE_CONTROL_TARGET_KINDS)):
        return None
    return [EffectSpec("exchange_control", {
        "first_target_kind": first, "target_kind": second,
        **_exchange_xtarget_params(m),
    })]


def _exchange_control_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = multi_target_params(m)
    if params is None:
        return None
    params.update(_exchange_xtarget_params(m))
    return [EffectSpec("exchange_control", params)]


#: Spawnbroker — "target creature you control and target creature **with
#: power less than or equal to that creature's power** an opponent controls".
#: The comparison sits *inside* the second target phrase (before "an opponent
#: controls"), so `_TARGET_B` can't consume it; its own row.
_EXCHANGE_CONTROL_SPAWNBROKER_RE = compile_clause(
    r"exchange control of target creature you control and target creature "
    r"with power less than or equal to that creature'?s power an opponent controls"
)


def _exchange_control_spawnbroker(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_control", {
        "first_target_kind": "creature_you_control",
        "target_kind": "creature_you_dont_control",
        "second_not_greater": "power",
    })]


# RULE 701.10's life-total half — "exchange life totals with target
# opponent/player" (this effect's own controller + one target, Magus of the
# Mirror/Mirror Universe-shaped) and "N target players exchange life
# totals" (two independent targets, Soul Conduit/Axis of Mortality's own
# "have" phrasing — the same causative verb `_THEN`'s neighborhood already
# tolerates for "have it fight").
def _exchange_life_totals_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_life_totals", {"target_kind": "player"})]


def _exchange_life_totals_two_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exchange_life_totals", {})]


_CHOOSE_TARGETS_RE = compile_clause(rf"choose {TARGET} and {TARGET_B}")
#: "choose two target creatures [controlled by different players]." (PAR-1)
#: — the `_MULTI_TARGET_QUANTIFIER`/`_MULTI_TARGET_ALT`/`_MULTI_TARGET_
#: DISTINCT_CONTROLLERS` grammar `destroy`/`exile`'s own multi-target rows
#: use, repurposed as a bare announcement (see `_choose_targets_group`).
_CHOOSE_TARGETS_GROUP_RE = compile_clause(
    rf"choose {MULTI_TARGET_QUANTIFIER}(?P<target>{MULTI_TARGET_ALT})"
    rf"{MULTI_TARGET_DISTINCT_CONTROLLERS}"
)
_CHOOSE_TARGET_SINGLE_RE = compile_clause(
    rf"choose {TARGET}(?: whose controller controls an? (?P<controls_land>island|forest|mountain|plains|swamp))?"
)


# --- The one-sided fight ("deals damage equal to its power") ----------------
# Same subject vocabulary as a fight, half the damage: "target creature you
# control deals damage equal to its power to target creature you don't
# control." (Rabid Bite), "when ~ dies, it deals damage equal to its power to
# any target." — `effects.DamageEqualToPowerEffect`.

#: Kinds that can *take* this damage (RULE 115.4-ish) — deliberately narrower
#: than the whole `TARGET` table: "target permanent"/"target artifact" as a
#: damage recipient would be a mis-model, since damage means nothing to a
#: land or an enchantment in this engine.
_DAMAGE_RECIPIENT_KINDS: frozenset[str] = frozenset(
    {
        "any", "creature", "creature_you_control", "creature_you_dont_control", "player",
        "player_or_planeswalker",
        # Sinstriker's Will: the combat-qualified creature is still a
        # creature recipient, with its legality supplied by TargetFrame.
        "attacking_or_blocking_creature",
        # PAR-127: "… to target creature or planeswalker [you don't control]"
        # (Bite Down, Domri's Ambush) — damage to a planeswalker removes
        # loyalty (RULE 120.3c) through the same `deal_damage`.
        "creature_or_planeswalker",
    }
)
_DEALS_POWER = r"deals? damage equal to its power to"


def _power_recipient(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if target_kind_allowed(kind, _DAMAGE_RECIPIENT_KINDS) else None


def _damage_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dealer = fight_kind(m.group("target"))
    recipient = _power_recipient(m.group("target_b"))
    if dealer is None or recipient is None:
        return None
    params: dict = {"dealer_kind": dealer, "target_kind": recipient}
    if target_is_optional(m):
        params["dealer_optional"] = True
    if target_is_optional(m, "_b"):
        params["optional"] = True
    return [EffectSpec("damage_equal_to_power", params)]


def _damage_equal_to_power_implicit(dealer_kind: Optional[str]):
    """The self/host/previous-target dealer forms — one requirement wide."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        recipient = _power_recipient(m.group("target"))
        if recipient is None:
            return None
        params: dict = {"target_kind": recipient, **optional_param(m)}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


def _damage_equal_to_power_selector(dealer_kind: Optional[str]):
    """"… to each opponent." — an untargeted recipient group (RULE 601.2c),
    the same closed vocabulary `_damage_selector` uses."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = SELECTOR_WORD_MAP.get(m.group("selector").lower())
        if selector is None:
            return None
        params: dict = {"selector": selector, "target_kind": None}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


# "<creature> deals damage to itself equal to its power." — the dealer *is*
# the recipient (Justice Strike / Inner Struggle / Wrack with Madness on a
# target, Wave of Reckoning / Solar Blaze as an "each creature" mass form).
# `damage_equal_to_power` with `to_self`; the "each" form is `each_creature`
# selector + no dealer target, each creature reading its own power.
_SELF_DAMAGE_POWER = r"deals? damage to itself equal to its power"
_POWER_DAMAGE_TO_SELF_TARGET_RE = compile_clause(rf"{TARGET} {_SELF_DAMAGE_POWER}")
_POWER_DAMAGE_TO_SELF_EACH_RE = compile_clause(rf"each creature {_SELF_DAMAGE_POWER}")


def _damage_to_self_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dealer = fight_kind(m.group("target"))
    if dealer is None:
        return None
    return [EffectSpec("damage_equal_to_power", {
        "dealer_kind": dealer, "target_kind": None, "to_self": True,
        **optional_param(m),
    })]


def _damage_to_self_equal_to_power_each(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage_equal_to_power", {
        "selector": "each_creature", "target_kind": None, "to_self": True,
    })]


#: The subset of `_SELECTOR_WORD_MAP` a *damage* clause can legally match —
#: "each other player" is a lose_life/rad-counter-only phrasing (no card
#: prints "deals damage to each other player"), so these selector rows must
#: not inherit it just because the lookup dict is shared with lose_life's.
_DAMAGE_SELECTOR_KEYS = ("each creature", "each player", "each opponent", "that player")
_DAMAGE_SELECTOR_ALT = "|".join(_DAMAGE_SELECTOR_KEYS)
_POWER_DAMAGE_TWO_TARGETS_RE = compile_clause(rf"{TARGET} {_DEALS_POWER} {TARGET_B}")
_POWER_DAMAGE_SELF_RE = compile_clause(rf"{re.escape(SELF)} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PRONOUN_RE = compile_clause(rf"it {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_ATTACHED_RE = compile_clause(rf"{ATTACHED_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PREVIOUS_RE = compile_clause(rf"{THEN}{PREVIOUS_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_SELF_SELECTOR_RE = compile_clause(
    rf"{re.escape(SELF)} {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)
_POWER_DAMAGE_PRONOUN_SELECTOR_RE = compile_clause(
    rf"it {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)
#: PAR-30: "<subject> deals damage equal to its power to each opponent." as
#: a *triggered-ability body* where the damage source and its amount are the
#: same object — the trigger's own subject (Champion of the Path's
#: just-entered Elemental / Pyrotechnic Performer's turned-face-up creature
#: → `group_subject_only`) or "~" itself (Giggling Skitterspike / Gau, Feral
#: Youth → `self_subject_only`). Routed to the dedicated
#: `subject_damages_each_opponent_equal_to_power` effect, which resolves the
#: subject from `GameContext.trigger_event` at resolution — the plain
#: `damage_equal_to_power` selector rows source from ``self.source``, which
#: is wrong when "it" is a *different* creature every firing.
_SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE = compile_clause(
    r"(?:it|that creature) deals? damage equal to its power to each opponent"
)


def _subject_damages_each_opponent_equal_to_power(
    m: "re.Match[str]",
) -> list[EffectSpec]:
    return [EffectSpec("subject_damages_each_opponent_equal_to_power", {})]

#: The one-sided fight's own registration table (see `_FIGHT_ROW_SPECS`'s
#: matching note) — two rows wider than fight's, since a creature can deal
#: damage to a mass selector ("… to each opponent") but can't "fight" one,
#: so `damage_equal_to_power` alone gets the `_self_selector`/
#: `_pronoun_selector` rows.
_POWER_DAMAGE_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    ("damage_equal_to_power", _POWER_DAMAGE_TWO_TARGETS_RE, _damage_equal_to_power, {}),
    # "it/that creature deals damage equal to its power to each opponent."
    # — before the generic pronoun/self selector rows so the dedicated
    # trigger-subject effect wins for the "each opponent" recipient (PAR-30).
    (
        "subject_damage_each_opponent_power_group",
        _SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE,
        _subject_damages_each_opponent_equal_to_power, {"requires": ClauseReading(group_subject=True)},
    ),
    (
        "subject_damage_each_opponent_power_self",
        _SUBJECT_POWER_DAMAGE_EACH_OPPONENT_RE,
        _subject_damages_each_opponent_equal_to_power, {"requires": ClauseReading(self_subject=True)},
    ),
    (
        "damage_equal_to_power_self", _POWER_DAMAGE_SELF_RE,
        _damage_equal_to_power_implicit(None), {},
    ),
    (
        "damage_equal_to_power_self_selector", _POWER_DAMAGE_SELF_SELECTOR_RE,
        _damage_equal_to_power_selector(None), {},
    ),
    (
        "damage_equal_to_power_pronoun", _POWER_DAMAGE_PRONOUN_RE,
        _damage_equal_to_power_implicit(None), {"requires": ClauseReading(self_subject=True)},
    ),
    (
        "damage_equal_to_power_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector(None),
        {"requires": ClauseReading(self_subject=True), "fallback_for": ("subject_damage_each_opponent_power_self",)},
    ),
    # PAR-123: under a RULE 603.1 group trigger "it" is the firing creature, not the
    # source (Stalking Vengeance, Warstorm Surge) — the same `trigger_subject`
    # dealer `fight` already reads (MEC-99).
    (
        "damage_equal_to_power_group_pronoun", _POWER_DAMAGE_PRONOUN_RE,
        _damage_equal_to_power_implicit("trigger_subject"), {"requires": ClauseReading(group_subject=True)},
    ),
    (
        "damage_equal_to_power_group_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector("trigger_subject"),
        {"requires": ClauseReading(group_subject=True), "fallback_for": ("subject_damage_each_opponent_power_group",)},
    ),
    (
        "damage_equal_to_power_attached", _POWER_DAMAGE_ATTACHED_RE,
        _damage_equal_to_power_implicit("attached_permanent"), {},
    ),
    (
        "damage_equal_to_power_previous", _POWER_DAMAGE_PREVIOUS_RE,
        _damage_equal_to_power_implicit("previous_target"), {"requires": ClauseReading(previous_subject=True)},
    ),
    # "… deals damage to itself equal to its power." — dealer == recipient.
    (
        "damage_to_self_equal_to_power", _POWER_DAMAGE_TO_SELF_TARGET_RE,
        _damage_to_self_equal_to_power, {},
    ),
    (
        "damage_to_self_equal_to_power_each", _POWER_DAMAGE_TO_SELF_EACH_RE,
        _damage_to_self_equal_to_power_each, {},
    ),
]


#: A single mana symbol run — "add {b}{b}{b}." (Dark Ritual-shaped). Only a
#: *pure* run of colour/colourless symbols claims (fail-closed): "add 1 mana
#: of any color" has no ``{…}`` symbols to capture, so it's left unclaimed
#: rather than guessed at (that's a player choice, not modeled yet).
_MANA_SYMBOL = r"\{[wubrgc]\}"
#: "add an additional {g}" (a triggered mana ability's bonus mana — Badgermole Cub, Leyline of Abundance) adds exactly
#: what "add {g}" does; "additional" only says it comes on top of what the tap produced.
_ADD_MANA_RE = compile_clause(rf"add (?:an additional )?(?P<syms>(?:{_MANA_SYMBOL}){{1,20}})")
#: "add 1 mana of any color" (number words already folded to digits by
#: `normalize`) — a genuine resolve-time player choice (RULE 106.4), unlike
#: the fixed pip run above. Deliberately narrow: real cards only print this
#: singular form (a multi-mana "any color" clause is always templated "any
#: *one* color" instead, a different, not-yet-modeled shape — guessing it
#: means the same thing here would be wrong).
_ADD_MANA_ANY_COLOR_RE = compile_clause(r"add (?:an additional )?1 mana of any colou?r")


def _add_mana(m: re.Match[str]) -> list[EffectSpec]:
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors})]


#: "add 6 {R}." (Avatar Roku, Firebender), "add 8 {C}." (Su-Chi Cave Guard) — a count in front of one symbol — and
#: "add 2 mana of any 1 color." (Branch of Vitu-Ghazi: one colour pick, that many mana). The count form is
#: `AddManaEffect`'s variable-count ``amount``/``color``; the any-colour form its ``any_amount``.
_ADD_MANA_COUNTED_RE = compile_clause(
    r"add (?:(?P<n>\d+) (?P<sym>" + _MANA_SYMBOL + r")|(?P<k>\d+) mana of any (?:1|one) colou?r)"
)


#: "add that much {G}." (Sakiko, Mother of Summer; Raphael, Ninja Destroyer) — the firing damage event's own amount,
#: `AddManaEffect.amount_from_trigger_event`.
_ADD_MANA_THAT_MUCH_RE = compile_clause(r"add that much (?P<sym>" + _MANA_SYMBOL + r")")


def _add_mana_that_much(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {
        "color": m.group("sym").strip("{}").upper(), "amount_from_trigger_event": "amount",
    })]


#: "add X mana in any combination of colors" / "add that much mana in any combination of {R} and/or {G}" (Grand Warlord
#: Radha, Klauth) and "add that much mana of any 1 color" (Photon), and the two-colour choice "add {R} or {G}" (Kessig
#: Naturalist): `AddManaEffect`'s ``"ANY"`` offer, narrowed to the named colours. A fixed count is that many single picks;
#: **documented simplification** for a variable amount (as for Culling Ritual): one colour pick covers the whole amount
#: instead of splitting it mana by mana.
_ADD_MANA_ANY_COMBINATION_RE = compile_clause(
    r"add (?:(?P<amount>x|that much|\d+) mana (?:in any combination of (?P<cols>colou?rs|"
    r"\{[wubrg]\}(?:(?:, | and/or |, and/or )\{[wubrg]\})*)|(?P<one_color>of any (?:1|one) colou?r))"
    r"|(?P<first>\{[wubrg]\}) or (?P<second>\{[wubrg]\}))"
)


def _add_mana_any_combination(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("first"):
        return [EffectSpec("add_mana", {
            "colors": ["ANY"], "any_color_choices": [m.group("first").strip("{}").upper(), m.group("second").strip("{}").upper()],
        })]
    amount = m.group("amount")
    if m.group("one_color") and amount.isdigit():
        # RULE 106.1: "N mana of any 1 color" is one colour pick covering all N (`add_mana_counted`'s ``any_amount``),
        # not N independent picks; only the variable "that much mana of any 1 color" (Photon) is built here.
        return None
    params: dict = {"colors": ["ANY"]}
    cols = m.group("cols")
    if cols and cols not in ("color", "colors", "colour", "colours"):
        params["any_color_choices"] = [c.upper() for c in re.findall(r"\{([wubrg])\}", cols)]
    if amount == "that much":
        params["any_amount_from_trigger_event"] = "amount"
    elif amount == "x":
        params["any_amount"] = "x"
    elif amount.isdigit() and int(amount) > 1:
        # A fixed "N mana in any combination" is exactly N independent single picks (RULE 106.1) — no simplification.
        return [EffectSpec("add_mana", dict(params)) for _ in range(int(amount))]
    return [EffectSpec("add_mana", params)]


def _add_mana_counted(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("k"):
        return [EffectSpec("add_mana", {"colors": ["any"], "any_amount": int(m.group("k"))})]
    return [EffectSpec("add_mana", {"color": m.group("sym").strip("{}").upper(), "amount": int(m.group("n"))})]


def _add_mana_any_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {"colors": ["any"]})]


#: PAR-124: "…, that player adds an additional {b}." (Bubbling Muck/High
#: Tide's own "whenever a player taps a `<land>` for mana" body) — "that
#: player" is RULE 605.1's tapper, not this ability's own controller,
#: reading `GameContext.trigger_event["controller_id"]` via `AddManaEffect.
#: recipient="event_controller"` (already built for Wild Growth's
#: identical "its controller adds…" shape).
_ADD_MANA_ADDITIONAL_EVENT_PLAYER_RE = compile_clause(
    rf"that player adds an additional (?P<syms>(?:{_MANA_SYMBOL}){{1,20}})"
)
#: "…its controller adds an additional `<mana>`" under "whenever enchanted land is tapped for mana" (Wild Growth,
#: Overgrowth, Dawn's Reflection, Market Festival) — the land's controller, who need not be the Aura's. The mana is
#: a symbol run, "1 mana of any color", or "2 mana in any combination of colors" — which is exactly two single
#: any-colour mana, each picked on its own (RULE 106.1), so no combination chooser is needed.
_ADD_MANA_ADDITIONAL_ITS_CONTROLLER_RE = compile_clause(
    r"its controller adds an additional (?:(?P<syms>(?:" + _MANA_SYMBOL + r"){1,20})|(?P<any>1 mana of any colou?r)"
    r"|(?P<combo>2 mana in any combination of colou?rs))"
)


def _add_mana_additional_event_player(m: re.Match[str]) -> list[EffectSpec]:
    groups = m.groupdict()
    if groups.get("any") or groups.get("combo"):
        return [
            EffectSpec("add_mana", {"colors": ["any"], "recipient": "event_controller"})
            for _ in range(2 if groups.get("combo") else 1)
        ]
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors, "recipient": "event_controller"})]


#: "Add `<sym>` / 1 mana of any color for each `<kind>` counter removed this
#: way." (Coalition Relic/Ventifact Bottle, PAR-66) — `GameContext.
#: counters_removed_this_way`'s own accumulator (bumped by a preceding
#: `remove_counters` clause in the same resolution), read through
#: `AddManaEffect.amount_from_context`/``any_amount_from_context`` exactly
#: like `permanents_destroyed_this_way` already feeds Culling Ritual's
#: hand-authored entry — this is the oracle-text route to the same
#: primitive. The counter *kind* word itself isn't re-checked here (a
#: single `remove_counters` clause only ever strips one named kind per
#: card today), so any kind word claims.
_ADD_MANA_PER_COUNTER_REMOVED_RE = compile_clause(
    r"add (?:(?P<any>1 mana of any colou?r)|(?P<sym>\{[wubrgc]\}))"
    r" for each [a-z]+ counters? removed this way"
)


def _add_mana_per_counter_removed(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("any"):
        return [EffectSpec("add_mana", {
            "colors": ["any"], "any_amount_from_context": "counters_removed_this_way",
        })]
    color = m.group("sym").strip("{}").upper()
    return [EffectSpec("add_mana", {
        "color": color, "amount_from_context": "counters_removed_this_way",
    })]


#: "you may pay {E}{E}. If/When you do, <effect>." (RULE 122, Aether Chaser/
#: Herder/Inspector/Swooper) — a resolve-time optional energy payment gating
#: a follow-up. The follow-up is recursively parsed; a follow-up the parser
#: can't model leaves the whole clause unclaimed. "If you do" targets are
#: announced by the enclosing ability; targeted "when you do" needs a
#: separate RULE 603.12 reflexive trigger and remains fail-closed here.
_PAY_ENERGY_THEN_RE = compile_clause(
    r"you may pay (?P<pips>(?:\{e\})+)\.\s*(?P<link>if|when) you do,?\s*(?P<effect>.+)"
)


def _pay_energy_then(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:

    amount = m.group("pips").count("{e}")
    if len(re.findall(r"\btarget\b", m.group("effect"))) > 1:
        # Independent target groups need separate continuation groups;
        # this wrapper currently forwards one announced group only.
        return None
    sub = parse_effect_body(m.group("effect").strip(), reading=reading)
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if m.group("link") == "when" and re.search(r"\btarget\b", m.group("effect")):
        # RULE 603.12: a reflexive target is chosen after payment, unlike
        # an "if you do" target announced with the enclosing ability.
        return None
    return [EffectSpec("pay_energy_then", {"amount": amount, "effects": [s.to_dict() for s in sub]})]


#: MEC-18/RULE 603.5's general "You may `<cost-shaped action>`. When/If you
#: do, `<effect>`." — generalizes `_pay_cost_then_draw`/`_pay_energy_then`
#: from one hardcoded antecedent (a bare mana cost / `{E}` pips) and, for
#: the first, one hardcoded consequence (draw a card) to the *whole*
#: `ActivationCost` vocabulary `pay_cost_then`/`RulesEngine.
#: _request_pay_cost_then` already supports server-side (mana, sacrifice,
#: discard, life — see that method's own docstring) plus an arbitrary
#: recursively-parsed follow-up. No new engine primitive: `pay_cost_then`
#: was already general, just never had an oracle-text recognizer past the
#: two narrow shapes above.
#:
#: `<cost>` is matched against a **closed** whitelist of atomic clause
#: shapes rather than run through `costs.py`'s lenient substring search —
#: that search only *finds* a cost fragment inside arbitrary text, it
#: doesn't confirm the fragment is the *entire* clause, so a compound
#: antecedent ("discard your hand and draw two cards") could otherwise have
#: its un-matched tail silently dropped. The mana alternative excludes the
#: `{E}` symbol on purpose — `_can_pay_player_cost`/`_pay_player_cost` don't
#: charge `ActivationCost.pay_energy` at all (that's `pay_energy_then`'s own
#: job, tried above and first-match-wins), so letting it through here would
#: silently make an energy antecedent free. A targeted "If you do" payoff
#: announces targets with the enclosing spell/ability (RULE 601.2c);
#: "When you do" instead creates a reflexive trigger (RULE 603.12).
#:
#: Exported (not module-private in spirit, just in naming convention) so
#: `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE` can protect the exact same
#: shapes from its own generic "you may " stripping — that peel is a
#: *different*, outer RULE 601.2c optionality (the whole ability, not this
#: sub-clause's cost), and the two must never drift apart or a clause this
#: handler recognizes would get its "you may" eaten before reaching here.
#:
#: The sacrifice alternative deliberately excludes the bare **self**-
#: sacrifice forms ("sacrifice it"/"this `<type>`"/"~") that `segmenter.
#: _SACRIFICE_THEN_WHEN_YOU_DO_RE` already claims (a plain, unconditional
#: sequence — sacrificing yourself is always legal once declared, so RULE
#: 603.5's antecedent can never fail, and that older path is strictly more
#: permissive than this one since it allows a *targeted* follow-up).
#: Routing self-sacrifice through here too would only lose coverage: this
#: handler's `_can_pay_player_cost` gate can genuinely fail an antecedent
#: (no legal permanent of the named type/no cards in hand), which is real
#: and worth being interactive about for a *typed* sacrifice/discard/life
#: payment. Self-sacrifice is handled by that separate antecedent path.
MAY_COST_THEN_CLAUSE = (
    # PAR-204 (RULE 118.8, a cost made of several parts): "you may pay {1} and 1 life / {1} and sacrifice an artifact /
    # {2}{R} and sacrifice a nonland permanent / {1}{R} and discard a card" (Miara, Sokenzan Smelter, Dreamshaper
    # Shaman) — mana plus ONE further part from the vocabulary `ActivationCost` charges whole (`_can_pay_player_cost`
    # / `_pay_player_cost`), so the payer is only asked when every part is affordable.
    r"pay (?:\{[wubrgcx0-9/]+\})+(?: and (?:sacrifice an? (?:nonland permanent|\w+)|discard a card|\d+ life))?"
    # PAR-148: "sacrifice another creature or an artifact" (Gut) — `costs.py`'s type-union words.
    r"|sacrifice an? (?:nonland permanent|\w+(?: or (?:an? )?\w+)?)"
    r"|sacrifice another \w+(?: or (?:an? )?\w+)?"
    # PAR-152 (Strefan): "sacrifice two Blood tokens" — `costs.ActivationCost.sacrifice_count`.
    r"|sacrifice \d+ \w+(?: tokens)?"
    r"|discard (?:your hand|a card|\d+ cards?|[a-z]+ cards?)"
    r"|pay \d+ life"
    # RULE 701.59a — a non-mana graveyard cost sized by total mana value;
    # `costs.parse_activation_cost` recognises it and `_can/_pay_player_cost`
    # charge it (`RulesEngine.collect_evidence`, PAR-29).
    r"|collect evidence \d+"
    # RULE 701.61a — "exile three graveyard cards or sacrifice a Food"
    # (`ActivationCost.forage`; `RulesEngine.forage`, PAR-29).
    r"|forage"
    # RULE 701.68 — "put N -1/-1 counters on a creature you control"
    # (`ActivationCost.blight`; `RulesEngine.blight(interactive=False)`, PAR-29).
    r"|blight \d+"
    # PAR-140 — "you may remove a menace counter from ~/it. When you do, …" (Biting-Palm Ninja,
    # Kappa Tech-Wrecker, Slumbering Walker's kindless form): charged off the ability's own source
    # (`RulesEngine._source_counter_removal`). "it" is only the source under a self trigger —
    # `_pay_cost_then_general` refuses it under a group trigger.
    r"|remove (?:a|an|\d+) (?:[+\-]\d/[+\-]\d |[a-z]+(?: strike)? )?counters? from (?:~|it|this [a-z]+)"
)
def _cost_text(cost: str) -> str:
    """The matched cost phrase as `costs.parse_activation_cost` reads it: a compound cost's bare "and 1 life" part is
    only recognised as "and pay 1 life" (otherwise it is left unrecognised and the life would never be charged)."""
    return re.sub(r" and (\d+ life)$", r" and pay \1", cost)


_PAY_COST_THEN_GENERAL_RE = compile_clause(
    r"you may (?P<cost>" + MAY_COST_THEN_CLAUSE + r")\.\s*(?P<link>if|when) you do,?\s*(?P<effect>.+)"
)
#: RULE 603.5's *negative* antecedent: "you may `<cost>`. If you don't,
#: `<effect>`." (Chaos Spewer, Gutsplitter Gang, Scuzzback Scrounger — the
#: PAR-29 Blight batch's "if you don't" shape). The mirror of
#: `_PAY_COST_THEN_GENERAL_RE`: the effect goes in `pay_cost_then`'s
#: ``else_effects`` branch (`game/effects/core.py`'s `PayCostThenEffect`), which
#: fires only when the optional cost is *declined* or unpayable.
_PAY_COST_THEN_OR_ELSE_RE = compile_clause(
    r"you may (?P<cost>" + MAY_COST_THEN_CLAUSE + r")\.\s*if you don't,?\s*(?P<effect>.+)"
)


#: Spellings of "read this from the trigger's event", which is gone once a payment has been made.
_LIVE_EVENT_MARKERS = (
    '"trigger_subject": true', '"target_kind": "trigger_subject"', '"dealer_event_key"',
    '"trigger_event_key"', '"referent": "trigger_event"', '"amount_from_trigger_event"',
    '"count_from_trigger_event"',
)


def _remembered_group_referent(specs: "list[EffectSpec]") -> Optional[list[EffectSpec]]:
    """PAR-123: a payment's "if you do" body runs after the trigger's event window has closed, so a
    group-trigger pronoun inside it must read the subject `PayCostThenEffect` remembers rather than
    the event. Rewrites the firing-object sentinel to ``remembered``; ``None`` if anything else still
    needs the live event (it would resolve to nothing)."""
    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: rewrite(v) for k, v in node.items()}
            params = out.get("params") or {}
            if out.get("type") == "trigger_subject_referent" and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL:
                out["params"] = {**params, "event_key": "remembered"}
            elif out.get("type") == "copy_permanent" and params.get("referent") == "trigger_event":
                # "create a token that's a copy of it": the copy reads the remembered object as the
                # referent instead of the event that is no longer live.
                return {"type": "trigger_subject_referent", "params": {
                    "event_key": "remembered",
                    "effects": [{**out, "params": {**params, "referent": "previous"}}],
                }}
            elif out.get("type") == "grant_keyword_to_trigger_subject" and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL:
                # "…it gains haste until end of turn" after a payment (Olivia): the remembered
                # object, granted through the ordinary previous-pick pump.
                return {"type": "trigger_subject_referent", "params": {
                    "event_key": "remembered",
                    "effects": [{"type": "pump", "params": {
                        "keywords": [params.get("keyword", "haste")], "previous_subject": True,
                    }}],
                }}
            if out.get("trigger_subject_key") == GROUP_SUBJECT_KEY_SENTINEL:
                out["trigger_subject_key"] = "remembered"
            return out
        if isinstance(node, list):
            return [rewrite(v) for v in node]
        return node

    rewritten = [rewrite(spec.to_dict()) for spec in specs]
    text = json.dumps(rewritten, default=str)
    if GROUP_SUBJECT_KEY_SENTINEL in text or any(marker in text for marker in _LIVE_EVENT_MARKERS):
        return None
    return [EffectSpec(d["type"], d.get("params") or {}, condition=d.get("condition")) for d in rewritten]


#: Composition nodes whose body is announced with the node (RULE 601.2c): a target inside one is the node's own.
_BODY_ANNOUNCING_NODES = frozenset({"seq", "bind"})


def _body_has_target(effects: Any) -> bool:
    """Whether any effect of a serialized ``seq`` / ``bind`` body announces a RULE 115 target (recursing through nested
    bodies) -- PAR-203's "choose a card name, then target player reveals …" wraps its tail in one."""
    for effect in effects or []:
        params = effect.get("params") or {}
        if params.get("target_kind"):
            return True
        if effect.get("type") in _BODY_ANNOUNCING_NODES and _body_has_target(params.get("effects")):
            return True
    return False


#: PAR-204 (RULE 107.3a): "…you may pay {X}. If you do, draw X cards. X can't be greater than the amount of life you
#: gained this turn." (Shanna, Purifying Blade / Mortarion) — the announced X is capped by a turn-total the engine
#: already tracks; the quantity is a `continuous.count_selector` name.
_X_CAP_QUANTITIES: dict[str, str] = {
    "the amount of life you gained this turn": "life_gained_this_turn",
    "the amount of life you lost this turn": "life_lost_this_turn",
}
_X_CAP_RIDER_RE = re.compile(
    r"\.\s*x can'?t be greater than (?P<quantity>" + "|".join(map(re.escape, _X_CAP_QUANTITIES)) + r")\.?$",
    re.IGNORECASE,
)


def _pay_cost_then_general(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    group = reading.group_clause
    if group and re.match(r"remove .* from it$", m.group("cost")):
        return None  # under a group trigger "it" is the firing object, not the source that pays
    effect_text = m.group("effect").strip()
    x_cap = _X_CAP_RIDER_RE.search(effect_text)
    if x_cap is not None:
        if "{x}" not in m.group("cost"):
            return None  # a cap on an X nobody announces
        effect_text = effect_text[:x_cap.start()].rstrip(". ") + "."
    parts = re.split(r"\.\s*otherwise,?\s+", effect_text, maxsplit=1)
    if group:
        # The branch runs once the payment is made, after the trigger's event window has closed, so
        # a pronoun in it names the object `remember_trigger_subject` stamped on the source: read as
        # the previous pick, behind a seed of that remembered object.
        sub = parse_effect_body(parts[0], reading=ClauseReading(previous_subject=True))
        if sub:
            sub = [EffectSpec("trigger_subject_referent", {"event_key": "remembered"}), *sub]
        else:
            grouped = parse_effect_body(parts[0], reading=ClauseReading(group_subject=True))
            sub = _remembered_group_referent(grouped) if grouped else None
    else:
        sub = parse_effect_body(parts[0], reading=ClauseReading(self_subject=True))
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if m.group("link") == "when" and any(
        s.params.get("target_kind")
        or (s.type in _BODY_ANNOUNCING_NODES and _body_has_target(s.params.get("effects")))
        or (s.type == "fight" and s.params.get("other_kind") not in (None, "previous_target", "previous_target_2", "trigger_subject", "attached_permanent")) for s in sub
    ):
        # RULE 603.12: only "When you do" creates a reflexive trigger.
        # "If you do" uses the enclosing spell/ability's announced targets.
        if len(parts) > 1:
            return None  # an otherwise rider on a reflexive trigger is ambiguous
        return [EffectSpec("pay_cost_then", {
            "cost": _cost_text(m.group("cost")),
            "then_trigger": [s.to_dict() for s in sub],
            **({"remember_trigger_subject": True} if group else {}),
        })]
    params: dict = {"cost": _cost_text(m.group("cost")), "effects": [s.to_dict() for s in sub]}
    if x_cap is not None:
        params["x_cap_selector"] = _X_CAP_QUANTITIES[x_cap.group("quantity").lower()]
    if len(parts) > 1:
        otherwise = parse_effect_body(
            parts[1], reading=ClauseReading(self_subject=True, previous_subject=announces_creature_target(sub)),
        )
        if not otherwise or any(s.params.get("target_kind") for s in otherwise):
            return None
        params["else_effects"] = [s.to_dict() for s in otherwise]
    if group or any(s.params.get("trigger_subject_key") == "remembered" for s in sub):
        params["remember_trigger_subject"] = True
    return [EffectSpec("pay_cost_then", params)]


#: MEC-103 (RULE 701.21, 603.12): "[you may] sacrifice any number of / up to N
#: `<type>`. When you sacrifice one or more `<type>` this way, `<payoff>`" — the
#: payoff reads "that many", the count actually sacrificed (Ravenous Rotbelly,
#: Nyssa of Traken). Kept apart from `pay_cost_then_general`, whose cost is a
#: fixed "sacrifice a `<type>`": here the *number* is the player's choice.
#: `<what>` is one bare (plural) type/subtype word, singularized below.
_SACRIFICE_CHOSEN_THEN_RE = compile_clause(
    r"(?:you may )?sacrifice (?:any number of|up to (?P<n>\d+)) (?P<what>[a-z]+?)s?\.\s*"
    r"when you sacrifice (?:1|one) or more [a-z]+ this way,?\s*(?P<effect>[^.]+\.?)"
)
#: "that many" bound to a placeholder count the parsed body is rewritten from.
_THAT_MANY_PLACEHOLDER = 2
_THAT_MANY_COUNT_KEYS = ("count", "count_max", "amount")


def _bind_that_many(value: Any) -> Any:
    """Turn the placeholder count back into the ``"x"`` sentinel (bound to the
    sacrificed count at resolve time, `RulesEngine._apply_choose_objects_tail`)."""
    if isinstance(value, dict):
        return {
            k: ("x" if k in _THAT_MANY_COUNT_KEYS and v == _THAT_MANY_PLACEHOLDER else _bind_that_many(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_bind_that_many(v) for v in value]
    return value


def _sacrifice_chosen_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    effect = m.group("effect").strip()
    if "that many" not in effect or re.search(r"\d", effect):
        return None  # only the "that many" payoff; any other number would be rewritten wrongly
    sub = parse_effect_body(
        effect.replace("that many", str(_THAT_MANY_PLACEHOLDER)), reading=ClauseReading(self_subject=True),
    )
    if not sub:
        return None
    params: dict = {
        "what": m.group("what"),
        "count": int(m.group("n")) if m.group("n") else "any",
        "trigger": [_bind_that_many(s.to_dict()) for s in sub],
    }
    return [EffectSpec("sacrifice_chosen_then", params)]


#: MEC-104: "draw cards equal to the number of opponents dealt damage this way. If you do,
#: discard that many cards." (Hordewing Skaab) — the count is the trigger's own
#: ``matching_opponents`` (`binding.core`'s contributor capture); the "you may" is the ability's.
_DRAW_OPPONENTS_DAMAGED_DISCARD_RE = compile_clause(
    r"draw cards equal to the number of opponents dealt damage this way\.\s*"
    r"if you do,? discard that many cards\.?"
)


def _draw_opponents_damaged_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    field = "matching_opponents"
    return [
        EffectSpec("draw", {"count_from_trigger_event": field}),
        EffectSpec("discard", {"count_from_trigger_event": field}),
    ]


def _pay_cost_then_or_else(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"you may `<cost>`. If you don't, `<effect>`." — the else-branch
    sibling of `_pay_cost_then_general` (PAR-29 Blight batch)."""

    sub = parse_effect_body(m.group("effect").strip(), reading=ClauseReading(self_subject=True))
    if not sub:
        return None
    if any(s.params.get("target_kind") not in (None, "source") for s in sub):
        return None  # a targeted else-branch can't resolve off-stack either ("source" is not a pick)
    return [EffectSpec("pay_cost_then", {
        "cost": _cost_text(m.group("cost")),
        "effects": [],
        "else_effects": [s.to_dict() for s in sub],
    })]


#: PAR-79 seventh increment: "return another/`<N>` other `<type>`[s] you
#: control to its/their owner's/owners' hand" (Biblioplex Kraken) and "tap
#: another/`<N>` other untapped `<type>`[s] you control" (Gravelgill
#: Scoundrel/Tidal Terror) as ordinary resolve-time effect bodies — RULE
#: 608.2c's "the resolving effect itself makes this choice", not a RULE 115
#: target (neither clause has the word "target", so there's no announced
#: target to fizzle if the chosen creature becomes illegal between trigger
#: and resolution, unlike modeling this as a `target_kind` pick would risk).
#: No new engine primitive: `ChooseObjectsEffect`/`"choose_objects"`
#: (`RulesEngine._request_choose_objects`, ``action="tap"``/
#: ``"return_to_hand"``) already is this project's general "which one of my
#: own permanents" chooser (Tevesh Szat's "sacrifice another creature or
#: planeswalker", Cloudstone Curio's bounce) — ``exclude_self`` already
#: existed for the "another"/"other" exclusion, and only
#: ``require_untapped`` (this increment) was missing, for the "untapped"
#: qualifier "tap another untapped creature" needs. Once these parse as an
#: ordinary (non-targeted) effect body, `_may_effect_then` right below
#: (the sixth increment's "You may `<effect>`. If you do, `<effect2>`."
#: wrapper) picks them up with no changes of its own — it already rejects
#: only a *targeted* antecedent, and neither of these is one.
_RETURN_ANOTHER_YOU_CONTROL_RE = compile_clause(
    r"return (?:another|(?P<n>\d+) other) (?P<type>[a-z]+?)s? you control "
    r"to (?:its owner's|their owners') hand"
)


def _return_another_you_control(m: re.Match[str]) -> list[EffectSpec]:
    count = int(m.group("n")) if m.group("n") else 1
    return [EffectSpec("choose_objects", {
        "action": "return_to_hand", "what": m.group("type"),
        "count": count, "exclude_self": True,
    })]


_TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE = compile_clause(
    r"tap (?:another|(?P<n>\d+) other) untapped (?P<type>[a-z]+?)s? you control"
)


def _tap_another_untapped_you_control(m: re.Match[str]) -> list[EffectSpec]:
    count = int(m.group("n")) if m.group("n") else 1
    return [EffectSpec("choose_objects", {
        "action": "tap", "what": m.group("type"),
        "count": count, "exclude_self": True, "require_untapped": True,
    })]


#: Exported so `segmenter._PAY_ENERGY_THEN_PEEL_GUARD_RE` can protect these
#: antecedent shapes from `peel_optional` the same way it already
#: protects `MAY_COST_THEN_CLAUSE` (same "so this guard can never drift
#: out of sync" reasoning that constant's own docstring gives). A plain
#: (non-capturing) mirror of `_RETURN_ANOTHER_YOU_CONTROL_RE`/
#: `_TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE` rather than their own
#: ``.pattern`` — both use the same group names (``n``/``type``), and the
#: guard embeds this alongside `MAY_COST_THEN_CLAUSE` in one compiled
#: regex, where a repeated group name is a `re.error`, not just a style
#: nit.
MAY_EFFECT_THEN_ANTECEDENT_PHRASES = (
    r"return (?:another|\d+ other) [a-z]+?s? you control to (?:its owner's|their owners') hand"
    r"|tap (?:another|\d+ other) untapped [a-z]+?s? you control"
    # PAR-124 (Magitek Scythe): "you may attach it to target creature you
    # control. if you do, `<effect>`." — see `_MAY_ATTACH_IF_YOU_DO_RE`'s
    # own docstring for why this one *keeps* its RULE 115 target (unlike
    # every other antecedent above, which are all targetless) instead of
    # going through `_may_effect_then`'s target-rejecting composition.
    r"|attach it to target creature you control"
    # MEC-99 (Gaze of Pain): "you may choose to have it deal damage equal to
    # its power to a target creature. if you do, `<effect>`." — a plain
    # (non-capturing) mirror of `_MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE`'s
    # own target phrase, for the same reason the Magitek Scythe row above
    # keeps its RULE 115 target un-peeled instead of going through `_may_
    # effect_then`'s target-rejecting composition.
    r"|choose to have it deal damage equal to its power to (?:a |up to (?:one|1) )?target [a-z]+"
    # PAR-152 (Ultra Magnus): "you may put a `<type>` card from your hand onto the battlefield tapped and attacking.
    # If you do, …" — the pick itself is the "may" (`PutFromHandOntoBattlefieldEffect` is optional), so the
    # un-peeled `optional` wrapper carries both halves and `_fold_placement_tails` moves the follow-up inside.
    r"|put an? [a-z ,]+? card from your hand onto the battlefield tapped and attacking"
    # PAR-152 (Fireflux Squad): `_MAY_EXILE_TARGET_IF_YOU_DO_RE` keeps its target un-peeled like the attach row.
    r"|exile (?:another |other )?target [a-z ]+? you control"
)


#: PAR-79 sixth increment: "You may `<effect>`. If you do, `<effect2>`."
#: (Biblioplex Kraken/Gravelgill Scoundrel/Tidal Terror/Saprazzan Breaker-
#: shaped) — `_PAY_COST_THEN_GENERAL_RE`'s antecedent is cost-shaped only
#: (`MAY_COST_THEN_CLAUSE`'s closed vocabulary); these cards' antecedent is
#: itself an ordinary *resolving effect* ("return another creature you
#: control to its owner's hand", "tap another untapped creature you
#: control", "mill a card"), not a cost payment at all — a genuinely
#: different shape, not a wider cost vocabulary. No new engine primitive,
#: though: `OptionalEffect`'s own docstring already spells out exactly this
#: composition — "'You may sacrifice a creature. If you do, draw two
#: cards.' is this node around a seq, not a new fused type" — RULE 603.5's
#: "if you do" is automatically satisfied by sequencing both effects inside
#: one `optional` wrapper, since the whole body (including the "if you do"
#: half) simply never runs at all when the player declines. Tried *after*
#: `pay_cost_then_general`/`pay_cost_then_or_else` (first-match-wins) so a
#: genuinely cost-shaped antecedent still gets the more faithful
#: interactive-affordability handling those give it, not this cruder wrap.
_MAY_EFFECT_THEN_RE = compile_clause(
    r"you may (?P<effect1>.+?)\.\s*if you do,\s*(?P<effect2>.+)"
)


#: PAR-124: "you may attach it to target creature you control. if you do,
#: `<effect>`." (Magitek Scythe's own ETB) — unlike every `_may_effect_
#: then` antecedent, this one keeps a real RULE 115 target: `AttachEffect`'s
#: `target_kind="creature_you_control"` is announced normally when this
#: triggered ability goes on the stack (RULE 601.2c), same as any other
#: printed target — `_may_effect_then`'s own "no way to announce a target
#: mid-resolution" reasoning doesn't apply here at all, since nothing is
#: announced mid-resolution; only *whether* the optional body runs is
#: decided at resolution (RULE 601.2b), which `OptionalEffect.target_specs`
#: is explicitly built to support (its own docstring's Choking Tethers
#: precedent — "you may tap target creature"). The follow-up's own "that
#: creature" is the ordinary `previous_subject` referent onto the same
#: chosen target (`_apply_effects_partitioned`'s shared "who did the
#: previous clause act on" tracking, threaded through `OptionalEffect`'s own
#: `_run`), exactly as if "attach" were any other targeted antecedent
#: clause in an ordinary (non-optional) body.
_MAY_ATTACH_IF_YOU_DO_RE = compile_clause(
    r"you may attach it to target creature you control\.\s*if you do,\s*(?P<effect2>.+)"
)


def _may_attach_if_you_do(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    second = parse_effect_body(m.group("effect2").strip(), reading=ClauseReading(previous_subject=True))
    if not second:
        return None
    if any(s.params.get("target_kind") for s in second):
        return None  # a second RULE 115 target has nowhere to be announced from
    attach_spec = EffectSpec("attach", {"target_kind": "creature_you_control"})
    return [EffectSpec("optional", {
        "effects": [attach_spec.to_dict()] + [s.to_dict() for s in second],
        "if_you_do_from": 1,  # RULE 608.2c: the follow-up needs the attach to have happened
    })]


#: PAR-152 (Fireflux Squad): "you may exile another target attacking creature you control. If you do, `<effect>`." —
#: the exile keeps its RULE 115 target (announced when the trigger goes on the stack, `OptionalEffect` only decides
#: at resolution whether it happens, like `_MAY_ATTACH_IF_YOU_DO_RE`); the follow-up runs only if it was exiled.
_MAY_EXILE_TARGET_IF_YOU_DO_RE = compile_clause(
    r"you may exile (?P<target>(?:another |other )?target [a-z ]+? you control)\.\s*if you do,\s*(?P<effect2>.+)"
)


def _may_exile_target_if_you_do(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    first = parse_effect_body(f"exile {m.group('target')}")
    second = parse_effect_body(m.group("effect2").strip())
    if not first or len(first) != 1 or first[0].type != "exile" or not second:
        return None
    if any(s.params.get("target_kind") for s in second):
        return None  # a second RULE 115 target has nowhere to be announced from
    return [EffectSpec("optional", {
        "effects": [first[0].to_dict()] + [s.to_dict() for s in second], "if_you_do_from": 1,  # RULE 608.2c
    })]


#: MEC-99: "you may choose to have it deal damage equal to its power to
#: `<target>`. if you do, it assigns no combat damage this turn." (Gaze of
#: Pain's own turn-scoped trigger body, RULE 510.1e) — a `damage_equal_to_
#: power` dealer plus a `prevent_combat_damage_dealt` flag, both wrapped in
#: one `optional`, and both reading "it" as the RULE 603.1 group-subject
#: creature that fired this trigger (``dealer_kind="trigger_subject"``/
#: ``subject="trigger_subject"``) rather than the ability's own source — a
#: temporary triggered ability granted by a sorcery has no combat-relevant
#: source of its own to flag. Narrowly matched rather than routed through
#: the generic `_may_effect_then`/`_MAY_EFFECT_THEN_RE` composition: that
#: recursion parses each half with ``self_subject=True``, never ``group_
#: subject=True``, so it can reach neither the group-subject dealer nor the
#: group-subject "it assigns no combat damage" clause — both primitives
#: already exist (`effects.DamageEqualToPowerEffect`/`PreventCombatDamage
#: DealtEffect`), this is only the recognition.
_MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE = compile_clause(
    rf"you may choose to have it deal damage equal to its power to (?:a )?{TARGET}\.\s*"
    r"if you do,\s*it assigns no combat damage this turn\.?"
)


def _may_have_it_deal_damage_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    recipient = _power_recipient(m.group("target"))
    if recipient is None:
        return None
    return [EffectSpec("optional", {
        "effects": [
            EffectSpec("damage_equal_to_power", {
                "dealer_kind": "trigger_subject", "target_kind": recipient,
                **optional_param(m),
            }).to_dict(),
            EffectSpec("assign_no_combat_damage", {"subject": "trigger_subject"}).to_dict(),
        ],
    })]


#: PAR-111: "whenever a creature an opponent controls enters, you may **have that player lose N life**."
#: (Blood Seeker, Suture Priest) — the controller of the firing object loses the life, while the ability's own
#: controller is the one asked: `segmenter.peel_optional` has already taken the "you may" off the body (the
#: trigger is optional), so this is the group-subject `lose_life` row with the entering creature's controller
#: (`_ENTERING_CONTROLLER`) as the player.
_HAVE_THAT_PLAYER_LOSE_LIFE_RE = compile_clause(rf"have that player lose {NUMBER} life")


def _have_that_player_lose_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {"amount": int(m.group("n")), "player": ENTERING_CONTROLLER})]


def _may_effect_then(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # The attached-host fact travels into both halves: "you may sacrifice it" under an equipped-creature trigger
    # names the host, which no row may read as the source.
    inner_reading = ClauseReading(self_subject=True, attached_subject=reading.attached_subject)
    first = parse_effect_body(m.group("effect1").strip(), reading=inner_reading)
    if not first:
        return None
    # PAR-204 (Cyclone Sire/Noyan Dar/Wall of Resurgence): "you may put 3 +1/+1 counters on target land you control.
    # If you do, that land becomes a 0/0 Elemental creature …". A single targeted antecedent keeps its RULE 115
    # target: it is announced when the ability goes on the stack (RULE 601.2c, `OptionalEffect.target_specs`), only
    # *whether* it happens is decided at resolution, and the follow-up's "that land" is the same pick.
    targeted_antecedent = (
        len(first) == 1 and bool(first[0].params.get("target_kind"))
        and re.search(r"\btarget\b", m.group("effect1")) is not None and announces_creature_target(first)
    )
    if targeted_antecedent:
        inner_reading = ClauseReading(previous_subject=True, attached_subject=reading.attached_subject)
    # Any other targeted antecedent needs its own announced-target step this off-stack wrapper has no way to give
    # it (same reasoning `_pay_cost_then_general`/`_pay_cost_then_or_else` already apply to a targeted follow-up)
    # — fail closed rather than silently drop the target.
    elif any(s.params.get("target_kind") for s in first):
        return None
    second = parse_effect_body(m.group("effect2").strip(), reading=inner_reading)
    if not second:
        return None
    if any(s.params.get("target_kind") for s in second):
        return None
    # RULE 608.2c: "if you do" -- the second part waits for the first to have been performed (`IfYouDoEffect`), which
    # the engine can only see for antecedents with an observable footprint; any other stays unclaimed.
    if not if_you_do_antecedent_ok([s.to_dict() for s in first]):
        return None
    return [EffectSpec("optional", {
        "effects": [s.to_dict() for s in first] + [s.to_dict() for s in second],
        "if_you_do_from": len(first),
    })]


#: MEC-19's "counter it/that spell[or ability] unless that player/its
#: controller pays `<cost>`." — a `_BECOMES_TARGET_TRIGGER_RE`-anchored
#: triggered ability's own resolution body, the un-keyworded-Ward-shaped
#: cycle's single most common effect (~90 real cards). The captured cost is
#: normalized to its imperative form ("pays"→"pay", "discards"→"discard")
#: before being handed to `costs.parse_activation_cost` at resolve time —
#: that parser's regexes anchor on the imperative ("pay\s+", "discard\s+"),
#: so the printed "pays"/"discards" would otherwise silently fail to match
#: and the cost would resolve as free.
_COUNTER_UNLESS_PAY_RE = compile_clause(
    r"counter (?:it|that spell or ability|that spell|that ability) unless "
    r"(?:that player|its controller) (?P<verb>pays|discards) "
    r"(?P<amount>(?:\{[wubrgcx0-9/]+\})+|\d+ life|a card)"
)


#: PAR-132: "counter that spell or ability." under a becomes-the-target head (Glyph Keeper, the Glasskites): the stack
#: item that targeted is the firing BECOMES_TARGET event's ``stack_id`` (`CounterSpellEffect`). Any other head has no
#: such antecedent, so the marker `gate._event_player_antecedent_ok` checks keeps the clause unclaimed there.
_COUNTER_THAT_SPELL_OR_ABILITY_RE = compile_clause(r"counter that spell or ability")


def _counter_that_spell_or_ability(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("counter", {
        "target_from_trigger_event": "stack_id", EVENT_PLAYER_EVENTS_KEY: [BECOMES_TARGET_EVENT],
    })]


#: "~ becomes the target of a spell or ability, **that spell or ability's controller** sacrifices a land of their
#: choice." (Lava Runner): the targeting object's controller is the event's ``player_id``.
_SPELL_CONTROLLER_SACRIFICES_RE = compile_clause(
    rf"that spell or ability's controller sacrifices (?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(SACRIFICE_EDICT_WHAT_WORDS)})s? of their choice"
)


def _spell_controller_sacrifices(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("nontoken"):
        return None
    what = SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    count = 1 if m.group("count") in ("a", "an") else int(m.group("count"))
    return [EffectSpec("sacrifice", {
        "what": what, "count": count, "player": {"of": "event_player"},
        EVENT_PLAYER_EVENTS_KEY: [BECOMES_TARGET_EVENT],
    })]


def _counter_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    verb = "pay" if m.group("verb") == "pays" else "discard"
    return [EffectSpec("counter_unless_pay", {"cost": f"{verb} {m.group('amount')}"})]


#: Perplex — unlike the BECOMES_TARGET family above, this has a normal RULE
#: 115 spell target and a non-mana "unless" cost.
_COUNTER_TARGET_SPELL_UNLESS_DISCARD_HAND_RE = compile_clause(
    r"counter target spell unless its controller discards their hand"
)


def _counter_target_spell_unless_discard_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("counter_unless_pay", {
        "cost": "discard your hand",
        "target_kind": "spell",
    })]


#: "you get {E}{E}" (RULE 122 energy production, the reminder-text
#: parenthetical already stripped by `normalize`) — N energy counters to the
#: effect's controller, the resolve-time sibling of the "Pay {E}" cost. Uses
#: the same generic `add_player_counters` primitive `rad`/`poison` do.
_GET_ENERGY_RE = compile_clause(r"you get (?P<pips>(?:\{e\})+)")


def _get_energy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_player_counters", {"amount": m.group("pips").count("{e}"), "kind": "energy"})]


#: "you get that many {E}." (Empyreal Voyager, Aurora Shifter, Peema Trailblazer) — the combat damage just dealt.
_GET_THAT_MANY_ENERGY_RE = compile_clause(r"you get that many \{e\}")


def _get_that_many_energy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_player_counters", {"kind": "energy", "amount_from_trigger_event": "amount"})]


def _transform(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transform", {})]


#: RULE 610.3: modern "exile <target> until ~ leaves" is one instruction.
#: The engine returns the exiled incarnation immediately after departure;
#: old two-ability wording retains an ordinary separate return trigger.
_EXILE_UNTIL_LEAVES_RE = compile_clause(
    r"(?P<head>exile (?:target .+?|up to .+?|another target .+?|other target .+?|that creature|it)) "
    r"until ~ leaves the battlefield"
)


def _exile_until_leaves(m: re.Match[str], reading: ClauseReading) -> Optional[list[EffectSpec]]:
    # RULE 610.3: duration is independent of the target's type, qualities,
    # mana-value bound and controller. Let the existing exile grammar read
    # those axes rather than duplicating its target vocabulary here.
    effects = parse_effect_body(m.group("head"), reading=reading)
    if effects is None or len(effects) != 1 or effects[0].type != "exile":
        return None
    effect = effects[0]
    if effect.params.get("target_kind") is None:
        return None
    return [EffectSpec("exile", {**effect.params, "until_source_leaves": True}, condition=effect.condition)]


#: "return it/~ to the battlefield transformed under its owner's control"
#: (RULE 400.7 + RULE 712.8, Bruce Banner-shaped) — the graveyard-sourced
#: sibling of `_EXILE_RETURN_TRANSFORMED_RE` above: a dies trigger's own
#: "return it..." (no "exile ~, then" prefix — dying already put it in the
#: graveyard, so this clause returns straight from there) rather than an
#: exile-and-blink. Always self/untargeted, same as that sibling.
_RETURN_FROM_GRAVEYARD_TRANSFORMED_RE = compile_clause(
    rf"return (?:{re.escape(SELF)}|it) to the battlefield transformed under "
    r"(?:your control|(?:its|his|her) owner'?s control)"
)


def _return_from_graveyard_transformed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_from_graveyard_transformed", {})]


# "Return this card from your graveyard to the battlefield[, tapped]."/"…to
# your hand." — an activated/triggered ability's own untargeted self-
# reanimation (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple, PAR-10's
# discovery: 69+ cache cards) or self-recursion (Abzan Devotee/Aurora
# Eidolon/Chandra's Phoenix, PAR-16: 70+ more). Unlike
# `_RETURN_FROM_GRAVEYARD_TRANSFORMED_RE` above, real printed text says
# "this card" here, not "it"/"~" — there's no antecedent pronoun to fold
# onto, since this is the clause's own opening subject rather than a
# dies-trigger's continuation of "When ~ dies, …". One regex, two
# destinations (a named ``hand`` group rather than two near-duplicate
# regex/handler pairs) since only the tail differs.
#: PAR-143: the card's own name folds to ``~`` ("return ~ from your graveyard …", Narfi, Llanowar
#: Greenwidow), and a battlefield entry may also be "tapped and attacking" (Interceptor).
_RETURN_SELF_FROM_GRAVEYARD_RE = compile_clause(
    r"return (?:this card|~) from your graveyard to "
    r"(?:the battlefield(?P<tapped> tapped)?(?P<atk> and attacking)?"
    # "…with 2 +1/+1 counters on it" (Retrofitted Transmogrant, Phoenix Chick) — the enters-with rider
    # the targeted row already reads, same counter vocabulary.
    rf"(?: with (?P<ewc_n>a|an|\d+) (?P<ewc_kind>-1/-1|\+1/\+1|finality|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
    # "…attached to that creature" (Dragon Breath cycle, Smoke Shroud, PAR-193): the host is the
    # creature whose entering fired the trigger.
    r"(?P<attached> attached to that creature)?"
    r"|(?P<hand>your hand))"
)


def _return_self_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.group("hand"):
        return [EffectSpec("return_self_from_graveyard_to_hand", {})]
    if m.group("atk") and not m.group("tapped"):
        return None
    params: dict = {"tapped": bool(m.group("tapped"))}
    if m.group("attached"):
        if m.group("tapped") or m.group("atk") or m.group("ewc_kind"):
            return None
        params["attach_to_trigger_subject"] = True
    if m.group("atk"):
        params["attacking"] = True
    if m.group("ewc_kind"):
        params["extra_counters"] = {"kind": m.group("ewc_kind"), "count": count_of(m.group("ewc_n"))}
    return [EffectSpec("return_self_from_graveyard", params)]


#: "When ~ dies, return it to the battlefield [tapped] under its owner's/
#: your control[ with a +1/+1 counter on it]." (RULE 400.7 self-recursion,
#: the "it"-pronoun continuation of a dies trigger — the Feign Death /
#: Demonic Gifts / Ashcloud Phoenix-adjacent cycle). `_SELF_SUBJECT`'s bare
#: "it" the same ungated way `_tap_self` reads it — this row only ever
#: fires when the clause literally opens "return it/~/this creature …".
_RETURN_SELF_TO_BATTLEFIELD_RE = compile_clause(
    rf"return (?:{SELF_SUBJECT}|this card) to the battlefield(?P<tapped> tapped)? under "
    r"(?P<whose>its owner'?s|your) control"
    # "…with 2 +1/+1 counters on it" (Infernal Vessel, PAR-142) — an amount and the same counter
    # vocabulary the targeted graveyard row reads (a +N/+N with N > 1 is no counter kind: it is N of +1/+1).
    rf"(?: with (?P<cn_n>a|an|\d+) (?P<cn_kind>-1/-1|\+1/\+1|{'|'.join(KEYWORD_COUNTER_KINDS)}) counters? on it)?"
)


#: "If it was a creature, return it to the battlefield under its owner's control. It's an
#: enchantment." (Enduring Courage / Curiosity / Innocence / Tenacity / Friendship; Enduring
#: Vitality is the hand-authored original) — `DiesReturnAsEnchantmentEffect`.
_DIES_RETURN_AS_ENCHANTMENT_RE = compile_clause(
    rf"(?:if it was a creature, )?return (?:{SELF_SUBJECT}) to the battlefield under its owner'?s "
    r"control\. it'?s an enchantment\.?"
)


def _return_self_to_battlefield(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"tapped": bool(m.group("tapped"))}
    if m.group("whose").lower() == "your":
        params["under_your_control"] = True
    if m.groupdict().get("cn_kind"):
        params["extra_counters"] = {"kind": m.group("cn_kind"), "count": count_of(m.group("cn_n"))}
    return [EffectSpec("return_self_to_battlefield", params)]


#: PAR-124/PAR-125: "When target creature dies this turn, return **that
#: card** to the battlefield under its owner's control." (Graceful
#: Reprieve) — `CreateTurnTriggerEffect.target_kind` keeps the ability
#: bound to its own source (the spell, PAR-125's own fix), so "that card"
#: is read live off the firing DIES event instead
#: (`ReturnSelfToBattlefieldEffect.target_kind="trigger_subject"`, the
#: same live-event-reference idiom `TapEffect`'s own group-subject
#: pronoun already uses) rather than via `self.source` identity. Kept as
#: its own, `self_subject_only`-gated row rather than folded into
#: `_RETURN_SELF_TO_BATTLEFIELD_RE`: "that card" already means something
#: *else* (PAR-18/30's own previous-clause pronoun) everywhere this
#: dispatch isn't the target-bound-as-source shape, so it must only be
#: offered when the caller has actually rewritten "target creature
#: `<verb>`" into this self-subject form.
_RETURN_TARGET_TO_BATTLEFIELD_SELF_RE = compile_clause(
    r"return that card to the battlefield(?P<tapped> tapped)? under "
    r"(?P<whose>its owner'?s|your) control"
)


def _return_target_to_battlefield_self(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"tapped": bool(m.group("tapped")), "target_kind": "trigger_subject"}
    if m.group("whose").lower() == "your":
        params["under_your_control"] = True
    return [EffectSpec("return_self_to_battlefield", params)]


def _become_prepared(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("become_prepared", {})]


#: "if your library has no cards in it, you win the game" (Jace, Wielder of
#: Mysteries' "-8: Draw seven cards. Then if your library has no cards in
#: it, you win the game." tail, RULE 104.2) — a plain conditional one-shot,
#: not the standing replacement `catalogue.replacements`' sibling clause
#: covers (that one gates a *draw*, this one gates an already-resolved
#: loyalty ability's own follow-up sentence).
def _win_if_empty_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("win_game", {"if_empty_library": True})]


_ONCE_PER_TURN_RE = compile_clause(r"activate (?:this ability )?only once each turn")


def _once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONCE_PER_TURN_MARKER, {})]


_TRIGGER_ONCE_PER_TURN_RE = compile_clause(r"this ability triggers only once each turn")


def _trigger_once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(TRIGGER_ONCE_PER_TURN_MARKER, {})]


_ACTION_ONCE_PER_TURN_RE = compile_clause(r"do this only once each turn")


def _action_once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ACTION_ONCE_PER_TURN_MARKER, {})]


_SORCERY_SPEED_RE = compile_clause(
    r"activate (?:this ability )?only "
    r"(?:as a sorcery|any time you could cast a sorcery)"
)


def _sorcery_speed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(SORCERY_SPEED_MARKER, {})]


_X_SPEND_COLOR_RE = compile_clause(r"spend only (?P<color>white|blue|black|red|green) mana on x")


#: MEC-131 / RULE 107.3: "X can't be greater than the number of snow lands you control." (Winter's Chill) — a bound on the
#: announced X, kept as a structured count selector (`count_phrase`), never as text the engine would interpret.
_X_CAP_RE = compile_clause(r"x can't be greater than the number of (?P<what>[a-z' ]+)")


def _x_cap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = parse_count_phrase(m.group("what"))
    if selector is None or selector.get("zone") != "battlefield":
        return None
    return [EffectSpec(X_CAP_MARKER, {"selector": selector})]


def _x_spend_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(X_SPEND_COLOR_MARKER, {"color": COLOR_WORDS[m.group("color").lower()]})]


_ONLY_DURING_YOUR_TURN_RE = compile_clause(r"activate (?:this ability )?only during your turn")


def _only_during_your_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {})]


#: PAR-163 (Snowslope Hunter): the two restrictions in one sentence -- "Activate only during your turn and only once
#: each turn." -- are exactly the two markers above, each folded into its own `ActivationCost` flag by the binder.
_ONLY_DURING_YOUR_TURN_ONCE_RE = compile_clause(r"activate (?:this ability )?only during your turn and only once each turn")


def _only_during_your_turn_once(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {}), EffectSpec(ONCE_PER_TURN_MARKER, {})]


_ONLY_BEFORE_ATTACKERS_RE = compile_clause(r"activate (?:this ability )?only during your turn, before attackers are declared")


def _only_before_attackers(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {}), EffectSpec(ONLY_BEFORE_ATTACKERS_MARKER, {})]


_ACTIVATION_CONDITION_RES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], dict]]] = [
    # PAR-98: the legendary-matters activation gate shared by Rivendell and
    # Haunt of the Dead Marshes.  It is a live board count, not a spell-cast
    # history condition.
    (re.compile(r"you control a legendary creature", re.I),
     lambda m: {"kind": "control_count", "selector": "legendary_creatures_you_control", "min": 1}),
    # PAR-64 / Raid: player-scoped declaration history, deliberately unlike
    # Boast's source_attacked_this_turn condition.
    (re.compile(r"you attacked this turn", re.I),
     lambda m: {"kind": "you_attacked_this_turn"}),
    (re.compile(r"you have (?P<n>\d+) or more cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_least", "amount": int(m.group("n"))}),
    (re.compile(r"you have (?P<n>\d+) or fewer cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": int(m.group("n"))}),
    (re.compile(r"there are (?P<n>\d+) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    (re.compile(r"an opponent has (?P<n>\d+) or more cards in (?:their|his or her) graveyard", re.I),
     lambda m: {"kind": "opponent_count", "selector": "cards_in_your_graveyard",
                "min": int(m.group("n"))}),
    (re.compile(r"you'?ve cast an instant or sorcery spell this turn", re.I),
     lambda m: {"kind": "cast_instant_or_sorcery_this_turn"}),
    # PAR-98 (Seeker of Insight, Tapestry of the Ages): the same shared
    # `static_conditions` predicate the "beginning of combat … if you've cast a
    # noncreature spell this turn" triggers (Franklin Richards) already read.
    (re.compile(r"you'?ve cast a noncreature spell this turn", re.I),
     lambda m: {"kind": "cast_noncreature_spell_this_turn"}),
    # PAR-120: "creatures you control have total power N or greater/less"
    # (Atarka Beastbreaker/Crater Elemental/Glade Watcher-shaped Formidable
    # activation gates) — the same `total_power_creatures_you_control`
    # `count_selector` reading, and the same `control_count` condition kind,
    # `static_handlers._STATIC_CONDITION_RES` already carries for this
    # phrase's other three surfaces (leading "if", trigger "while", RULE
    # 613.6 "as long as"); this table's own entries above already duplicate
    # a few of that one's rows by hand rather than falling back to it, so
    # this row does the same rather than reopening that separate question.
    (re.compile(r"creatures you control have total power (?P<n>\d+) or (?P<cmp>greater|less)", re.I),
     lambda m: {
         "kind": "control_count", "selector": "total_power_creatures_you_control",
         ("min" if m.group("cmp") == "greater" else "max"): int(m.group("n")),
     }),
    # PAR-120: "you control a desert or there is a desert card in your
    # graveyard" (Wall of Forgotten Pharaohs) — the same `any`-combined
    # compound `static_handlers.static_condition`'s own generic "`<A>` or
    # `<B>`" fallback already builds for the other three surfaces this
    # phrase reaches; this table doesn't share that fallback (see the
    # module-level note on `_ACTIVATION_CONDITION_RES` duplicating
    # `_STATIC_CONDITION_RES` by hand), so it gets its own matching row.
    (re.compile(r"you control a desert or there is a desert card in your graveyard", re.I),
     lambda m: {"kind": "any", "conditions": [
         {"kind": "control_count",
          "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "desert"}}, "min": 1},
         {"kind": "subtype_in_graveyard", "subtype": "desert"},
     ]}),
]


def activation_condition_dict(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _ACTIVATION_CONDITION_RES:
        match = pattern.fullmatch(stripped)
        if match is not None:
            return build(match)
    # PAR-120: every row above is a hand-copied duplicate of a phrase
    # `static_handlers._STATIC_CONDITION_RES`/`static_condition()` already
    # recognizes for this same condition's other three surfaces (leading
    # "if", trigger "while", "as long as") — this table's own module note
    # has said so at each of this session's four additions to it (commander,
    # total power twice, the desert compound) without ever taking the actual
    # architectural step. Tried only once every row above has declined, so
    # an existing row's own kind spelling (`control_legendary_subtype` vs.
    # `control_count`/`legendary_creatures_you_control`, the dedicated
    # `cast_noncreature_spell_this_turn` flag vs. the newer generic
    # `event_this_turn` reading) is preserved exactly for any phrase this
    # table already recognized — zero behaviour change for an already-
    # shipped card — and only a phrase genuinely new to *both* tables reaches
    # the shared vocabulary for the first time.

    return static_condition(stripped) or activation_attached_condition(stripped)


_SORCERY_SPEED_AND_CONDITION_RE = compile_clause(
    r"activate (?:this ability )?only as a sorcery and only if (?P<cond>.+)"
)


def _sorcery_speed_and_condition(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [
        EffectSpec(SORCERY_SPEED_MARKER, {}),
        EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition}),
    ]


_ACTIVATE_ONLY_IF_RE = compile_clause(r"activate (?:this ability )?only if (?P<cond>.+)")
_ACTIVATE_DURING_YOUR_TURN_AND_IF_RE = compile_clause(
    r"activate (?:this ability )?only during your turn and only if (?P<cond>.+)"
)


def _activate_during_your_turn_and_if(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": {
        "kind": "all", "conditions": [{"kind": "your_turn"}, condition],
    }})]


def _activate_only_if(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition})]


#: PAR-176 (RULE 602.5): "Activate only <restriction>[ and only <restriction>]..." -- one grammar for the whole
#: printed restriction sentence instead of a row per pairing.  Each atom is either a timing window (RULE 602.5d, 500.1),
#: a per-turn / per-game cap (RULE 602.5b), or an "if <condition>" gate over the shared `static_conditions` vocabulary.
#: Every atom must be enforceable by `can_activate`; one unknown atom refuses the whole sentence (fail closed).
_ACTIVATE_ONLY_ANY_RE = compile_clause(r"activate (?:this ability )?only (?P<rest>.+)")
_RESTRICTION_SPLIT_RE = re.compile(r"(?:,\s*(?:and\s+)?|\s+and\s+)only\s+")

#: Oracle step words -> the engine's `current_step` names (RULE 500.1, `phases.default_turn_sequence`).
_RESTRICTION_STEP_WORDS: dict[str, str] = {
    "upkeep": "upkeep",
    "draw": "draw",
    "beginning of combat": "begin_combat",
    "declare attackers": "declare_attackers",
    "declare blockers": "declare_blockers",
    "combat damage": "combat_damage",
    "end of combat": "end_combat",
    "end": "end",
}
_RESTRICTION_STEP_ALT = "|".join(sorted((re.escape(w) for w in _RESTRICTION_STEP_WORDS), key=len, reverse=True))

_RESTRICTION_ATOM_RES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], tuple[list[EffectSpec], list[dict]]]]] = [
    # RULE 602.5d: sorcery timing; "as an instant" is the default timing, so it restricts nothing.
    (re.compile(r"as a sorcery|any time you could cast a sorcery", re.I),
     lambda m: ([EffectSpec(SORCERY_SPEED_MARKER, {})], [])),
    (re.compile(r"as an instant|any time you could cast an instant", re.I), lambda m: ([], [])),
    # RULE 602.5b: the per-turn / per-game caps ("once each turn" must be tried before "once").
    (re.compile(r"once each turn", re.I), lambda m: ([EffectSpec(ONCE_PER_TURN_MARKER, {})], [])),
    (re.compile(r"once", re.I), lambda m: ([EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {})], [])),
    (re.compile(r"during your turn", re.I), lambda m: ([EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {})], [])),
    (re.compile(r"during your upkeep", re.I), lambda m: ([], [{"kind": "your_upkeep"}])),
    (re.compile(r"during (?:any|each) upkeep(?: step)?", re.I), lambda m: ([], [{"kind": "during_step", "step": "upkeep"}])),
    (re.compile(r"during combat", re.I), lambda m: ([], [{"kind": "during_phase", "phase": "combat"}])),
    (re.compile(rf"during the (?P<step>{_RESTRICTION_STEP_ALT}) step", re.I),
     lambda m: ([], [{"kind": "during_step", "step": _RESTRICTION_STEP_WORDS[m.group("step").lower()]}])),
    (re.compile(rf"before the (?P<step>{_RESTRICTION_STEP_ALT}) step", re.I),
     lambda m: ([], [{"kind": "before_step", "step": _RESTRICTION_STEP_WORDS[m.group("step").lower()]}])),
    (re.compile(r"before attackers are declared", re.I), lambda m: ([], [{"kind": "before_step", "step": "declare_attackers"}])),
]


def _activate_only_compound(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    specs: list[EffectSpec] = []
    conditions: list[dict] = []
    for atom in _RESTRICTION_SPLIT_RE.split(m.group("rest").strip().rstrip(".")):
        atom = atom.strip()
        gate = re.fullmatch(r"if (?P<cond>.+)", atom, re.I)
        if gate is not None:
            condition = activation_condition_dict(gate.group("cond"))
            if condition is None:
                return None
            conditions.append(condition)
            continue
        for pattern, build in _RESTRICTION_ATOM_RES:
            hit = pattern.fullmatch(atom)
            if hit is not None:
                atom_specs, atom_conditions = build(hit)
                specs.extend(atom_specs)
                conditions.extend(atom_conditions)
                break
        else:
            return None
    if conditions:
        merged = conditions[0] if len(conditions) == 1 else {"kind": "all", "conditions": conditions}
        specs.append(EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": merged}))
    # "Activate only as an instant" restricts nothing (RULE 602.5d's default); an empty conjunction records that
    # the sentence was understood without inventing a marker the binder would have to learn.
    return specs or [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": {"kind": "all", "conditions": []}})]


ROWS: list[EffectHandler] = [
    # "Choose target creature you control and target creature you don't
    # control." — the target announcement those pair clauses read back.
    EffectHandler("choose_targets", _CHOOSE_TARGETS_RE, _choose_targets),
    # "Choose two target creatures controlled by different players." (PAR-1)
    # — the quantified-group announcement `_return_previous_group` (below)
    # reads back via "those creatures".
    EffectHandler("choose_targets_group", _CHOOSE_TARGETS_GROUP_RE, _choose_targets_group),
    EffectHandler("choose_target_single", _CHOOSE_TARGET_SINGLE_RE, _choose_target_single),
    # RULE 701.10 "exchange control of `<X>` and `<Y>`" (PAR-29) — three
    # printed shapes, longest/most-specific first (the file's usual
    # convention): two fully-named independent targets, then "N target
    # `<kind>`[ controlled by different players]", then this permanent plus
    # one target.
    EffectHandler(
        "exchange_control_spawnbroker",
        _EXCHANGE_CONTROL_SPAWNBROKER_RE,
        _exchange_control_spawnbroker,
    ),
    EffectHandler(
        "exchange_control_two_explicit",
        compile_clause(rf"exchange control of {TARGET} and {TARGET_B}{_EXCHANGE_XTARGET_TAIL}"),
        _exchange_control_two_explicit,
    ),
    EffectHandler(
        "exchange_control_multi",
        compile_clause(
            rf"exchange control of {MULTI_TARGET_QUANTIFIER}(?:other )?"
            rf"(?P<target>{MULTI_TARGET_ALT}){MULTI_TARGET_DISTINCT_CONTROLLERS}"
            rf"{_EXCHANGE_XTARGET_TAIL}"
        ),
        _exchange_control_multi,
    ),
    EffectHandler(
        "exchange_control_self",
        compile_clause(rf"exchange control of ~ and {TARGET}"),
        _exchange_control_self,
    ),
    # RULE 701.10's life-total half.
    EffectHandler(
        "exchange_life_totals_self",
        compile_clause(r"exchange life totals with (?:target opponent|target player)"),
        _exchange_life_totals_self,
    ),
    EffectHandler(
        "exchange_life_totals_two_target",
        compile_clause(r"(?:have )?2 target players exchange life totals"),
        _exchange_life_totals_two_target,
    ),
    # The one-sided fight (RULE 701.14's shape minus the damage back):
    # "target creature you control deals damage equal to its power to target
    # creature you don't control" and its six implicit-dealer/selector
    # siblings — same subject vocabulary as the fight family above, half the
    # damage (see `_POWER_DAMAGE_ROW_SPECS`'s own note on why only the
    # registration, not the grammar/builders, is factored here too).
    *(
        EffectHandler(name, regex, build, **flags)
        for name, regex, build, flags in _POWER_DAMAGE_ROW_SPECS
    ),
    # "you may pay {E}{E}. If you do, <effect>." (Aether Chaser) — tried
    # before the bare mana/effect handlers since it wraps a whole clause.
    EffectHandler(
        "pay_energy_then",
        _PAY_ENERGY_THEN_RE,
        _pay_energy_then,
        reading_aware=True,
    ),
    # MEC-18: "you may <sacrifice/discard/pay-mana/pay-life>. when/if you
    # do, <effect>." — the general RULE 603.5 optional-antecedent family.
    # Tried after `pay_energy_then`/`pay_cost_then_draw` (both narrower,
    # both correct) so first-match-wins never lets this one preempt them.
    EffectHandler(
        "pay_cost_then_general",
        _PAY_COST_THEN_GENERAL_RE,
        _pay_cost_then_general,
        reading_aware=True,
    ),
    # MEC-103: "sacrifice up to N / any number of <type>. When you sacrifice
    # one or more this way, <payoff with "that many">."
    EffectHandler(
        "sacrifice_chosen_then",
        _SACRIFICE_CHOSEN_THEN_RE,
        _sacrifice_chosen_then,
    ),
    # MEC-104: Hordewing Skaab's "draw cards equal to the number of opponents dealt damage this
    # way. If you do, discard that many cards."
    EffectHandler(
        "draw_opponents_damaged_discard",
        _DRAW_OPPONENTS_DAMAGED_DISCARD_RE,
        _draw_opponents_damaged_discard,
    ),
    # PAR-29 (Blight batch): the "If you don't, <effect>." else-branch
    # sibling — same clause shape, opposite antecedent, into
    # `pay_cost_then`'s `else_effects`.
    EffectHandler(
        "pay_cost_then_or_else",
        _PAY_COST_THEN_OR_ELSE_RE,
        _pay_cost_then_or_else,
    ),
    # PAR-79 seventh increment: "return another/<N> other <type>[s] you
    # control to its/their owner's/owners' hand" / "tap another/<N> other
    # untapped <type>[s] you control" as ordinary resolve-time effect
    # bodies — feeds `may_effect_then` right below automatically.
    EffectHandler(
        "return_another_you_control",
        _RETURN_ANOTHER_YOU_CONTROL_RE,
        _return_another_you_control,
    ),
    EffectHandler(
        "tap_another_untapped_you_control",
        _TAP_ANOTHER_UNTAPPED_YOU_CONTROL_RE,
        _tap_another_untapped_you_control,
    ),
    # PAR-124: "you may attach it to target creature you control. if you
    # do, <effect>." — tried before the generic `may_effect_then` row
    # below, whose own builder explicitly rejects a targeted antecedent.
    EffectHandler(
        "may_attach_if_you_do",
        _MAY_ATTACH_IF_YOU_DO_RE,
        _may_attach_if_you_do,
    ),
    EffectHandler("may_exile_target_if_you_do", _MAY_EXILE_TARGET_IF_YOU_DO_RE, _may_exile_target_if_you_do),
    # MEC-99: "you may choose to have it deal damage equal to its power to
    # <target>. if you do, it assigns no combat damage this turn." (Gaze of
    # Pain) — tried before the generic `may_effect_then` row below for the
    # same reason `may_attach_if_you_do` is: only reachable under a RULE
    # 603.1 group-subject trigger, which that generic row's own recursive
    # `self_subject=True` parse can never unlock.
    EffectHandler(
        "may_have_it_deal_damage_equal_to_power",
        _MAY_HAVE_IT_DEAL_DAMAGE_EQUAL_TO_POWER_RE,
        _may_have_it_deal_damage_equal_to_power,
        requires=ClauseReading(group_subject=True),
    ),
    EffectHandler(
        "have_that_player_lose_life",
        _HAVE_THAT_PLAYER_LOSE_LIFE_RE,
        _have_that_player_lose_life,
        requires=ClauseReading(group_subject=True),
    ),
    # PAR-79 sixth increment: "You may <effect>. If you do, <effect2>." with
    # a resolving-effect antecedent rather than a cost — tried after both
    # cost-shaped rows above so a genuine cost antecedent keeps the more
    # faithful `pay_cost_then` handling.
    EffectHandler(
        "may_effect_then",
        _MAY_EFFECT_THEN_RE,
        _may_effect_then,
        fallback_for=("pay_cost_then_general",), reading_aware=True,
    ),
    # MEC-19: "counter it unless that player pays <cost>" — the
    # un-keyworded-Ward-shaped `BECOMES_TARGET` trigger's own resolution.
    EffectHandler(
        "counter_unless_pay",
        _COUNTER_UNLESS_PAY_RE,
        _counter_unless_pay,
    ),
    EffectHandler("counter_that_spell_or_ability", _COUNTER_THAT_SPELL_OR_ABILITY_RE, _counter_that_spell_or_ability),
    EffectHandler("spell_controller_sacrifices", _SPELL_CONTROLLER_SACRIFICES_RE, _spell_controller_sacrifices),
    EffectHandler(
        "counter_target_spell_unless_discard_hand",
        _COUNTER_TARGET_SPELL_UNLESS_DISCARD_HAND_RE,
        _counter_target_spell_unless_discard_hand,
    ),
    # "you get {E}{E}" — energy-counter production (RULE 122).
    EffectHandler(
        "get_energy",
        _GET_ENERGY_RE,
        _get_energy,
    ),
    EffectHandler("get_that_many_energy", _GET_THAT_MANY_ENERGY_RE, _get_that_many_energy),
    # "add `<sym>`/1 mana of any color for each `<kind>` counter removed
    # this way" — tried before both rows below since either would otherwise
    # (fail to) match only the leading "add …" fragment.
    EffectHandler(
        "add_mana_per_counter_removed",
        _ADD_MANA_PER_COUNTER_REMOVED_RE,
        _add_mana_per_counter_removed,
    ),
    # "add 1 mana of any color" — a genuine resolve-time colour choice,
    # tried before the fixed-pip pattern below since it has no {…} symbols
    # for that one to (fail to) match anyway.
    EffectHandler(
        "add_mana_any_color",
        _ADD_MANA_ANY_COLOR_RE,
        _add_mana_any_color,
    ),
    # "add {b}{b}{b}." (Dark Ritual-shaped bare mana-symbol spell body).
    EffectHandler(
        "add_mana",
        _ADD_MANA_RE,
        _add_mana,
    ),
    EffectHandler("add_mana_counted", _ADD_MANA_COUNTED_RE, _add_mana_counted),
    EffectHandler("add_mana_that_much", _ADD_MANA_THAT_MUCH_RE, _add_mana_that_much),
    EffectHandler("add_mana_any_combination", _ADD_MANA_ANY_COMBINATION_RE, _add_mana_any_combination),
    # "that player adds an additional {b}." (Bubbling Muck/High Tide).
    EffectHandler(
        "add_mana_additional_event_player",
        _ADD_MANA_ADDITIONAL_EVENT_PLAYER_RE,
        _add_mana_additional_event_player,
    ),
    # "…its controller adds an additional {g}" (Wild Growth/Overgrowth/Dawn's Reflection) — the host's controller.
    EffectHandler(
        "add_mana_additional_its_controller",
        _ADD_MANA_ADDITIONAL_ITS_CONTROLLER_RE,
        _add_mana_additional_event_player,
        requires=ClauseReading(attached_subject=True),
    ),
    # "transform ~" / "transform it" / "transform this permanent"/"creature"
    # (RULE 712.8) — the self-transform shape a loyalty "[0]: Transform ~."
    # or a "whenever ~ attacks, transform it" trigger uses.
    EffectHandler(
        "transform",
        # RULE 701.28a: to convert a permanent is to turn it over exactly as transforming does ("convert ~", Ultra Magnus).
        compile_clause(rf"(?:transform|convert) (?:{re.escape(SELF)}|it|her|him|this permanent|this creature)"),
        _transform,
    ),
    # RULE 610.3: modern duration-bound exile returns immediately when the
    # source leaves; old two-ability O-Ring wording keeps its own trigger.
    EffectHandler(
        "exile_until_leaves",
        _EXILE_UNTIL_LEAVES_RE,
        _exile_until_leaves, reading_aware=True,
    ),
    # "return it/~ to the battlefield transformed under its owner's
    # control" (RULE 400.7 + RULE 712.8, Bruce Banner-shaped) — a dies
    # trigger's own graveyard-sourced sibling of the exile-and-blink shape
    # just above (no "exile ~, then" prefix: dying already put it there).
    EffectHandler(
        "return_from_graveyard_transformed",
        _RETURN_FROM_GRAVEYARD_TRANSFORMED_RE,
        _return_from_graveyard_transformed,
    ),
    # "Return this card from your graveyard to the battlefield[, tapped]."
    # (PAR-10 discovery) — the plain, non-transforming sibling just above.
    EffectHandler(
        "return_self_from_graveyard",
        _RETURN_SELF_FROM_GRAVEYARD_RE,
        _return_self_from_graveyard,
    ),
    # "When ~ dies, return it to the battlefield [tapped] under its
    # owner's/your control[ with a +1/+1 counter on it]." (Demonic Gifts /
    # Feign Death / Abnormal Endurance cycle).
    EffectHandler(
        "return_self_to_battlefield",
        _RETURN_SELF_TO_BATTLEFIELD_RE,
        _return_self_to_battlefield,
    ),
    # "When ~ dies, if it was a creature, return it to the battlefield under its owner's control.
    # It's an enchantment." (Enduring cycle) — the effect reads "if it was a creature" off the DIES
    # event itself (RULE 400.7), so the intervening-if is part of the claimed text, not a gate.
    EffectHandler(
        "dies_return_as_enchantment",
        _DIES_RETURN_AS_ENCHANTMENT_RE,
        lambda m: [EffectSpec("dies_return_as_enchantment", {})],
        requires=ClauseReading(self_subject=True),
    ),
    # "return that card to the battlefield under its owner's control"
    # (Graceful Reprieve) — the self-subject-bound-target spelling.
    EffectHandler(
        "return_target_to_battlefield_self",
        _RETURN_TARGET_TO_BATTLEFIELD_SELF_RE,
        _return_target_to_battlefield_self,
        requires=ClauseReading(self_subject=True),
    ),
    # "~ becomes prepared" / "it becomes prepared" / "this permanent"/
    # "this creature becomes prepared" (RULE 722.3a) — a preparation card's
    # own "whenever X, ~ becomes prepared" trigger; the self-only shape
    # mirrors "transform" above (RULE 722.3a has no targeted form).
    EffectHandler(
        "become_prepared",
        compile_clause(rf"(?:{re.escape(SELF)}|it|this permanent|this creature) becomes prepared"),
        _become_prepared,
    ),
    # "Activate only once each turn." (Quirion Ranger/Scryb Ranger-shaped) —
    # a per-instance activation cap, not a real effect; see
    # `ONCE_PER_TURN_MARKER`'s docstring for how the binder strips it.
    EffectHandler(
        "once_per_turn",
        _ONCE_PER_TURN_RE,
        _once_per_turn,
    ),
    # "This ability triggers only once each turn." (PAR-14) — a triggered
    # ability's own once-per-turn cap, not a real effect; see
    # `TRIGGER_ONCE_PER_TURN_MARKER`'s docstring for how `segment_line`
    # strips it into `AbilitySpec.trigger["limit"]`.
    EffectHandler(
        "trigger_once_per_turn",
        _TRIGGER_ONCE_PER_TURN_RE,
        _trigger_once_per_turn,
    ),
    # "Do this only once each turn." (PAR-135) — the optional action's own cap; see
    # `ACTION_ONCE_PER_TURN_MARKER`.
    EffectHandler(
        "action_once_per_turn",
        _ACTION_ONCE_PER_TURN_RE,
        _action_once_per_turn,
    ),
    # "Activate only as a sorcery." / "… only any time you could cast a
    # sorcery." — a RULE 602.5d timing restriction, not a real effect; see
    # `SORCERY_SPEED_MARKER`'s docstring for how the binder folds it into the
    # cost's `sorcery_speed_only` flag.
    EffectHandler(
        "sorcery_speed",
        _SORCERY_SPEED_RE,
        _sorcery_speed,
    ),
    EffectHandler("x_spend_color", _X_SPEND_COLOR_RE, _x_spend_color),
    EffectHandler("x_cap", _X_CAP_RE, _x_cap),
    # "Activate only during your turn." — RULE 602.5d's wider sibling
    # (Wishclaw Talisman); see `ONLY_DURING_YOUR_TURN_MARKER`'s docstring.
    EffectHandler(
        "only_during_your_turn",
        _ONLY_DURING_YOUR_TURN_RE,
        _only_during_your_turn,
    ),
    EffectHandler("only_before_attackers", _ONLY_BEFORE_ATTACKERS_RE, _only_before_attackers),
    EffectHandler(
        "only_during_your_turn_once",
        _ONLY_DURING_YOUR_TURN_ONCE_RE,
        _only_during_your_turn_once,
    ),
    # PAR-10: "Activate only as a sorcery and only if `<condition>`." — tried
    # before the bare `_SORCERY_SPEED_RE`/`_ACTIVATE_ONLY_IF_RE` rows since a
    # `fullmatch` against the *whole* compound sentence is what makes this
    # one, not either of them, the actual match.
    EffectHandler(
        "sorcery_speed_and_condition",
        _SORCERY_SPEED_AND_CONDITION_RE,
        _sorcery_speed_and_condition,
    ),
    # "Activate only if `<condition>`." (no sorcery-speed restriction) —
    # Potioner's Trove-shaped.
    EffectHandler(
        "activate_during_your_turn_and_if",
        _ACTIVATE_DURING_YOUR_TURN_AND_IF_RE,
        _activate_during_your_turn_and_if,
    ),
    EffectHandler(
        "activate_only_if",
        _ACTIVATE_ONLY_IF_RE,
        _activate_only_if,
    ),
    # PAR-176: every remaining "Activate only ..." sentence -- tried last so the exact rows above keep their specs.
    # "during your turn and only if <cond>" is also the exact row above, which spells the own-turn gate as a
    # `your_turn` condition instead of the flag: same legality, declared as the older row's fallback.
    EffectHandler("activate_only_compound", _ACTIVATE_ONLY_ANY_RE, _activate_only_compound,
                  fallback_for=("activate_during_your_turn_and_if",)),
    # "you win the game." (RULE 104.2 — Felidar Sovereign, Test of Endurance: the upkeep trigger's body after its
    # intervening "if you have 40 or more life"). The conditional library-empty form is the row below.
    EffectHandler("win_game", compile_clause(r"you win the game"), lambda m: [EffectSpec("win_game", {})]),
    # "if your library has no cards in it, you win the game" (Jace, Wielder
    # of Mysteries' -8 tail).
    EffectHandler(
        "win_if_empty_library",
        compile_clause(r"(?:then )?if your library has no cards? in it, you win the game"),
        _win_if_empty_library,
    ),
]
