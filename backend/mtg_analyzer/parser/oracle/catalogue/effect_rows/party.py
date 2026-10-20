"""Party-count rows (PAR-72) and the trailing dig/damage rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Optional
from ..dig import parse_dig, parse_reveal_top_branch
from ..subgrammars import resolve_target_kind, SELF_SUBJECT_PREFIX, TARGET
from ...spec import EffectSpec
from ..clause_hooks import match_clause
from .shared import compile_clause, EffectHandler, split_token_mid_words


# --- PAR-72: Party (RULE 700.8) generalized into a resolve-time amount -----
# `continuous.count_selector`'s ``"creatures_in_your_party"`` branch (PAR-53)
# was previously wired only into the cost-reduction/"full party" static
# forms. This section widens the already-generic `amount_from_count_
# selector`/`count_selector` family (PAR-32/36/43 &c.) to also recognize the
# fixed phrase "for each creature in your party"/"the number of creatures
# in your party" across the one-shot effect verbs real cards print it on —
# one handler per distinct verb/template, this codebase's established
# convention (no single "for each X" grammar spans every effect type).

#: "Add `<sym>` for each creature in your party." (Ardent Electromancer) —
#: `AddManaEffect.amount_selector` (Burnt Offering's own hand-authored
#: field, MEC-43) is the oracle-text route: additive with ``colors``, so
#: this sets only ``color``, leaving ``colors`` empty (no unconditional
#: pip of its own — the whole amount comes from the party count).
_ADD_MANA_PARTY_RE = compile_clause(r"add (?P<sym>\{[wubrgc]\}) for each creature in your party")


def _add_mana_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {
        "color": m.group("sym").strip("{}").upper(),
        "amount_selector": "creatures_in_your_party",
    })]


#: "When ~ enters, put a +1/+1 counter on it for each creature in your
#: party." (Emeria Captain) — the self-ETB sibling of
#: `_choose_target_add_counters_party` below, both reusing `AddCountersEffect.
#: amount_from_count_selector`.
_ADD_COUNTERS_SELF_PARTY_RE = compile_clause(
    r"put a \+1/\+1 counter on it for each creature in your party"
)


def _add_counters_self_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {"amount_from_count_selector": "creatures_in_your_party"})]


#: "Choose target creature you control. Put a +1/+1 counter on it for each
#: creature in your party." (Strength of Solidarity) — a sorcery with no
#: trigger wrapper, so the whole two-sentence body is one clause; modeled
#: directly as a single targeted `add_counters` rather than a separate
#: "choose"/previous-subject pair (the target IS the thing counters land on,
#: nothing else in the body reads it).
_CHOOSE_TARGET_ADD_COUNTERS_PARTY_RE = compile_clause(
    r"choose target creature you control\. put a \+1/\+1 counter on it for each creature in your party"
)


def _choose_target_add_counters_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "target_kind": "creature_you_control",
        "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Whenever ~ attacks, it gets +1/+0 until end of turn for each creature in
#: your party." (Grotag Bug-Catcher) — a self, power-only
#: `PumpEffect.amount_from_count_selector` (the count *is* the pump amount;
#: no separate per-unit multiplier, matching every "+1/+X for each" shape
#: in this family — the printed magnitude is always exactly 1 per unit).
_PUMP_SELF_POWER_PARTY_RE = compile_clause(r"it gets \+1/\+0 until end of turn for each creature in your party")


def _pump_self_power_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "amount_from_count_selector": "creatures_in_your_party",
        "amount_from_count_selector_axis": "power",
    })]


#: "When ~ enters, target creature gets +1/+1 until end of turn for each
#: creature in your party." (Kabira Outrider) — the targeted, both-axis
#: sibling of `_pump_self_power_party` above.
_PUMP_TARGET_BOTH_PARTY_RE = compile_clause(
    r"target creature gets \+1/\+1 until end of turn for each creature in your party"
)


def _pump_target_both_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature", "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Up to two target creatures each get +X/+X until end of turn, where X is
#: the number of creatures in your party." (Allied Assault) — the multi-
#: target sibling of `_pump_up_to_two`, scaled instead of a fixed digit.
_PUMP_UP_TO_TWO_PARTY_RE = compile_clause(
    r"up to 2 target creatures each get \+x/\+x until end of turn, "
    r"where x is the number of creatures in your party"
)


def _pump_up_to_two_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 2, "optional": True,
        "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "When ~ enters, target creature an opponent controls gets -X/-X until
#: end of turn, where X is the number of creatures in your party." (Drana's
#: Silencer) — the negative-both-axis sibling, `amount_from_count_selector_
#: negative` flips the sign the same way every other "-X/-X, where X is …"
#: row in this file does.
_PUMP_TARGET_OPPONENT_NEGATIVE_PARTY_RE = compile_clause(
    r"target creature an opponent controls gets -x/-x until end of turn, "
    r"where x is the number of creatures in your party"
)


def _pump_target_opponent_negative_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "target_kind": "creature_you_dont_control",
        "amount_from_count_selector": "creatures_in_your_party",
        "amount_from_count_selector_negative": True,
    })]


#: "You gain 2 life for each creature in your party." (Shepherd of Heroes)
#: — the 2-life-per-unit sibling of every other 1-per-unit ``count_
#: selector`` gain_life row, using `GainLifeEffect.count_selector_
#: multiplier` (PAR-72's own new field — every existing ``count_selector``
#: gain_life shape prints exactly 1 life per unit, so no prior card needed
#: a multiplier).
_GAIN_LIFE_PARTY_RE = compile_clause(r"you gains? 2 life for each creature in your party")


def _gain_life_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {
        "count_selector": "creatures_in_your_party", "count_selector_multiplier": 2,
    })]


#: "Create a 1/1 white Kor Warrior creature token for each creature in your
#: party." (Squad Commander) — `CreateTokenEffect.count_selector` directly
#: (the count *is* the token count, no multiplier); ``<mid>`` (colors +
#: subtypes) reuses `_split_token_mid_words`, the same word-splitter every
#: other inline-stat token handler in this file shares.
_CREATE_TOKEN_PARTY_RE = compile_clause(
    r"create a (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]+) creature tokens? "
    r"for each creature in your party"
)


def _create_token_party(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors, subtypes, is_artifact = split_token_mid_words(m.group("mid"))
    if not subtypes:
        return None
    params: dict = {
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes,
        "count_selector": "creatures_in_your_party",
    }
    if is_artifact:
        params["is_artifact"] = True
    return [EffectSpec("create_token", params)]


#: "Scry X, where X is the number of creatures in your party." (Cascade
#: Seer) — `ScryEffect.count_from_count_selector` (PAR-72's own new field).
_SCRY_PARTY_RE = compile_clause(r"scry x, where x is the number of creatures in your party")


def _scry_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("scry", {"count_from_count_selector": "creatures_in_your_party"})]


#: "Each opponent loses X life and you gain X life, where X is the number
#: of creatures in your party." (Malakir Blood-Priest) — the party-count
#: sibling of `_lose_life_and_gain_life_devotion`; must stay one clause for
#: the same reason that row does (the generic " and " connector split would
#: otherwise hand the first half's bare "x" to `_lose_life_selector`'s
#: RULE-107.3c announced-X reading, which crashes with no X to substitute).
_LOSE_LIFE_AND_GAIN_LIFE_PARTY_RE = compile_clause(
    r"each opponent loses x life and you gains? x life, where x is the number of creatures in your party"
)


def _lose_life_and_gain_life_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("lose_life", {
            "amount_from_count_selector": "creatures_in_your_party", "selector": "each_opponent",
        }),
        EffectSpec("gain_life", {"count_selector": "creatures_in_your_party"}),
    ]


#: "Choose target attacking or blocking creature. ~ deals damage to that
#: creature equal to twice the number of creatures in your party."
#: (Practiced Tactics) — folded into one targeted `damage` effect
#: (`DealDamageEffect.amount_multiplier`, "twice" = 2) the same way
#: `_choose_target_add_counters_party` folds its own "choose … put …" body.
_DAMAGE_ATTACKING_OR_BLOCKING_TWICE_PARTY_RE = compile_clause(
    r"choose target attacking or blocking creature\. ~ deals damage to that creature "
    r"equal to twice the number of creatures in your party"
)


def _damage_attacking_or_blocking_twice_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "target_kind": "attacking_or_blocking_creature",
        "amount_from_count_selector": "creatures_in_your_party", "amount_multiplier": 2,
    })]


#: "Look at the top X cards of your library, where X is 3 plus the number
#: of creatures in your party. Put 3 of those cards into your hand and the
#: rest on the bottom of your library in a random order." (Skyclave
#: Plunder) — `InspectTopChooseEffect.count_from_count_selector`/
#: ``count_plus`` (PAR-72's own new fields); ``max_picks=3`` is a forced
#: (not "up to") pick since the party-scaled X is always >= 3.
_LOOK_TOP_PUT_THREE_PARTY_RE = compile_clause(
    r"look at the top x cards of your library, where x is 3 plus the number of creatures in your party\. "
    r"put 3 of those cards into your hand and the rest on the bottom of your library in a random order"
)


def _look_top_put_three_party(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("inspect_top_choose", {
        "count_from_count_selector": "creatures_in_your_party", "count_plus": 3,
        "action": "library_to_hand", "max_picks": 3, "rest_destination": "library_bottom_random",
    })]


#: PAR-144: the general dig — "Look at/Reveal the top N cards of your library. You may reveal a
#: `<kind>` card from among them and put it into your hand/onto the battlefield. Put the rest on
#: the bottom of your library / into your graveyard." (`dig.py` parses everything after the first
#: sentence; this row only owns that sentence, so a body the dig grammar can't read returns None
#: and falls through to the rows below.)
#: An ``x`` count is the spell's / ability's announced {X}; `gate._dig_x_ok` refuses it under a trigger,
#: where no X was announced.
_DIG_RE = compile_clause(r"(?:look at|reveal) the top (?P<n>\d+|x) cards of your library\.\s+(?P<rest>.+)")


def _dig(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count = m.group("n").lower()
    return parse_dig("x" if count == "x" else int(count), m.group("rest"), match_clause)


#: "~ deals 4 damage to target creature and X damage to that creature's
#: controller, where X is the number of creatures in your party."
#: (Synchronized Spellcraft) — two `damage` effects sharing one RULE 115
#: target: the first's own target (`_apply_effects_partitioned` records it
#: into `GameContext.previous_targets`), the second reads its controller via
#: `DealDamageEffect.recipient_subject="previous_subject_controller"`
#: (`_DAMAGE_TO_SUBJECT_CONTROLLER_RE`'s own idiom) — found and fixed a
#: latent gap while building this: that recipient path read raw
#: `self.amount` instead of `_amount_for`, so `amount_from_count_selector`/
#: `amount_from_trigger_event` were silently dropped whenever combined with
#: `recipient_subject` (no shipped card had combined them before now).
_DAMAGE_TARGET_AND_CONTROLLER_PARTY_RE = compile_clause(
    rf"{SELF_SUBJECT_PREFIX}deals? (?P<n>\d+) damage to target creature and x damage to "
    r"that creature'?s controller, where x is the number of creatures in your party"
)


def _damage_target_and_controller_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": "creature"}),
        EffectSpec("damage", {
            "recipient_subject": "previous_subject_controller",
            "amount_from_count_selector": "creatures_in_your_party",
        }),
    ]


#: "When ~ enters, it deals X damage to target creature or planeswalker,
#: where X is the number of creatures in your party." (Thundering
#: Sparkmage) — `resolve_target_kind`'s existing "target creature or
#: planeswalker" → ``"creature"`` row (a project-wide documented
#: simplification — this engine's ``creature`` kinds are creature-only) is
#: reused as-is, unchanged by this ticket.
_DAMAGE_TARGET_PARTY_RE = compile_clause(
    rf"it deals x damage to {TARGET}, where x is the number of creatures in your party"
)


def _damage_target_party(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {
        "target_kind": kind, "amount_from_count_selector": "creatures_in_your_party",
    })]


#: "Whenever ~ attacks, defending player loses X life and you create X
#: Treasure tokens, where X is the number of creatures in your party."
#: (Burakos, Party Leader's attack trigger — the card's own static "~ is
#: also a Cleric, Rogue, Warrior, and Wizard" makes it count toward its own
#: party) — `LoseLifeEffect.selector="defending_player"` (afflict's own
#: idiom) combined with `amount_from_count_selector`, plus a plain
#: `CreateTokenEffect.count_selector` Treasure.
_BURAKOS_ATTACK_PARTY_RE = compile_clause(
    r"defending player loses x life and you create x treasure tokens, "
    r"where x is the number of creatures in your party"
)


def _burakos_attack_party(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("lose_life", {
            "selector": "defending_player", "amount_from_count_selector": "creatures_in_your_party",
        }),
        EffectSpec("create_token", {
            "token_name": "Treasure", "count_selector": "creatures_in_your_party",
        }),
    ]


ROWS: list[EffectHandler] = [
    # PAR-72: Party generalized into a resolve-time amount (see the
    # dedicated section above `HANDLERS`) — one row per distinct verb the
    # fixed "for each creature in your party"/"the number of creatures in
    # your party" phrase appears on.
    EffectHandler("add_mana_party", _ADD_MANA_PARTY_RE, _add_mana_party),
    EffectHandler("add_counters_self_party", _ADD_COUNTERS_SELF_PARTY_RE, _add_counters_self_party),
    EffectHandler(
        "choose_target_add_counters_party",
        _CHOOSE_TARGET_ADD_COUNTERS_PARTY_RE, _choose_target_add_counters_party,
    ),
    EffectHandler("pump_self_power_party", _PUMP_SELF_POWER_PARTY_RE, _pump_self_power_party),
    EffectHandler("pump_target_both_party", _PUMP_TARGET_BOTH_PARTY_RE, _pump_target_both_party),
    EffectHandler("pump_up_to_two_party", _PUMP_UP_TO_TWO_PARTY_RE, _pump_up_to_two_party),
    EffectHandler(
        "pump_target_opponent_negative_party",
        _PUMP_TARGET_OPPONENT_NEGATIVE_PARTY_RE, _pump_target_opponent_negative_party,
    ),
    EffectHandler("gain_life_party", _GAIN_LIFE_PARTY_RE, _gain_life_party),
    EffectHandler("create_token_party", _CREATE_TOKEN_PARTY_RE, _create_token_party),
    EffectHandler("scry_party", _SCRY_PARTY_RE, _scry_party),
    EffectHandler(
        "lose_life_and_gain_life_party",
        _LOSE_LIFE_AND_GAIN_LIFE_PARTY_RE, _lose_life_and_gain_life_party,
    ),
    EffectHandler(
        "damage_attacking_or_blocking_twice_party",
        _DAMAGE_ATTACKING_OR_BLOCKING_TWICE_PARTY_RE, _damage_attacking_or_blocking_twice_party,
    ),
    EffectHandler("look_top_put_three_party", _LOOK_TOP_PUT_THREE_PARTY_RE, _look_top_put_three_party),
    EffectHandler("dig_top_choose", _DIG_RE, _dig),
    # PAR-148: the one-card reveal whose hit is forced and whose miss is routed ("otherwise, put it into your hand").
    EffectHandler(
        "reveal_top_branch", compile_clause(r"(?:you may )?reveal the top card of your library\..+"),
        lambda m: parse_reveal_top_branch(m.group(0)),
    ),
    EffectHandler(
        "damage_target_and_controller_party",
        _DAMAGE_TARGET_AND_CONTROLLER_PARTY_RE, _damage_target_and_controller_party,
    ),
    EffectHandler("damage_target_party", _DAMAGE_TARGET_PARTY_RE, _damage_target_party),
    EffectHandler("burakos_attack_party", _BURAKOS_ATTACK_PARTY_RE, _burakos_attack_party),
]
