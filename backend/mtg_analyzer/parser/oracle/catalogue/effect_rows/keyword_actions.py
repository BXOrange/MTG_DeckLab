"""Scry, connive, explore, vote, bolster, goad and other keyword-action rows (PAR-172 M2: moved mechanically out of `handlers.py`; row order is fixed by `handlers.HANDLERS`)."""

from __future__ import annotations

import re

from typing import Any, Optional
from ..clause_hooks import parse_effect_body
from ..clause_primitives import TARGET_PARAM_KEYS
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..static_handlers import enter_as_copy_tail
from ..subgrammars import (
    count_or_x_of,
    DEVOTION,
    devotion_selector,
    NUMBER,
    resolve_target_creature_state_filter,
    resolve_target_kind,
    TARGET,
    target_kind_allowed,
)
from ...spec import EffectSpec
from .shared import (
    compile_clause,
    counter_sign,
    DELAYED_TAIL_INNER,
    EffectHandler,
    NAMED_TOKEN_WORDS,
    optional_param,
    xx_token_mid_params,
)


#: MEC-90 / RULE 706: these ordinary effect bodies consume the prior die
#: result through ENG-37's generic ``bind`` node, instead of each effect
#: class gaining its own ``amount_from_die_result`` parameter. The same inner
#: specs work after a roll and in its RULE 603.11 ``then_trigger`` body.
_DIE_RESULT_AMOUNT = {"kind": "die_result"}


def _bind_die_result(effect_type: str, params: dict) -> list[EffectSpec]:
    return [EffectSpec("bind", {
        "name": "die", "amount": dict(_DIE_RESULT_AMOUNT),
        "effects": [{"type": effect_type, "params": params}],
    })]


_GAIN_LIFE_DIE_RESULT_RE = compile_clause(r"you gain life equal to the result")


def _gain_life_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("gain_life", {"amount": "$die"})


_DRAW_DIE_RESULT_RE = compile_clause(r"(?:you )?draw cards equal to the result")


def _draw_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("draw", {"count": "$die"})


_NO_MAX_HAND_SIZE_REST_OF_GAME_RE = compile_clause(
    r"you have no maximum hand size for the rest of the game"
)


def _no_max_hand_size_rest_of_game(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("no_max_hand_size_rest_of_game", {})]


_CREATE_NAMED_TOKEN_DIE_RESULT_RE = compile_clause(
    r"you create a number of (?P<name>[a-z]+) tokens equal to the result"
)


def _create_named_token_die_result(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    name = m.group("name")
    if name not in NAMED_TOKEN_WORDS:
        return None
    return _bind_die_result("create_token", {
        "count": "$die", "token_name": NAMED_TOKEN_WORDS[name],
    })


_CREATE_CREATURE_TOKEN_DIE_RESULT_RE = compile_clause(
    r"you create a number of (?P<p>\d+)/(?P<t>\d+) (?P<mid>[a-z ]*?)"
    r"creature tokens?(?: with (?P<kw>[a-z, ]+))? equal to the result"
)


def _create_creature_token_die_result(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return _bind_die_result("create_token", {
        **params, "count": "$die", "power": int(m.group("p")), "toughness": int(m.group("t")),
    })


_ADD_COUNTERS_DIE_RESULT_RE = compile_clause(
    r"put x (?P<kind>\+1/\+1|-1/-1|−1/−1) counters on each of up to "
    r"(?P<targets>\d+) target creatures, where x is the result"
)


def _add_counters_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("add_counters", {
        "count": "$die", "kind": counter_sign(m.group("kind")),
        "target_kind": "creature", "target_count": int(m.group("targets")), "optional": True,
    })


_RETURN_CREATURES_DIE_RESULT_RE = compile_clause(
    r"put any number of target creature cards with total mana value x or less from "
    r"graveyards onto the battlefield under your control, where x is the result"
)


def _return_creatures_die_result(m: re.Match[str]) -> list[EffectSpec]:
    return _bind_die_result("return_creatures_total_mana_value", {"budget": "$die"})


# "fateseal N" (RULE 701.29a) — scry on an *opponent's* library. `FateSeal
# Effect` (registered `fateseal`) auto-picks the opponent (first living one,
# a documented simplification like Clash's). The optional leading "you " is
# the redundant subject a trigger body spells out; "you may fateseal N"
# (Mesmeric Sliver's quoted grant) reaches this after `peel_optional`
# strips the "you may", the ability itself carrying `optional=True`.
def _fateseal(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("fateseal", {"count": int(m.group("n"))})]


# RULE 701.69a "heal all damage from <permanent>" / "damage … dealt to
# <permanent> is healed" — remove all marked damage (`HealEffect` /
# `RulesEngine.heal`). Only ever prints for "all" damage, never "heal N".
# The Wolverine, Fierce Fighter "…is healed" *replacement* clause is a
# separate recognizer (`replacements._HEAL_OTHERS_ON_DAMAGE_RE`).
_HEAL_GROUP_SELECTOR = {
    "each creature you control": "creatures_you_control",
    "creatures you control": "creatures_you_control",
    "each creature": "all_creatures",
    "all creatures": "all_creatures",
}
_HEAL_RE = compile_clause(
    r"(?:heal all damage (?:from|dealt to|marked on)|(?:all )?damage (?:already )?dealt to) "
    r"(?P<who>~|it|this creature|each creature you control|"
    r"creatures you control|each creature|all creatures)"
    r"(?: is healed)?"
)


def _heal(m: re.Match[str]) -> list[EffectSpec]:
    # ~/it/this creature → self (no selector); group phrases → a
    # `group_selector_objects` name. No "target creature" form: no card
    # prints one, and emitting a target-less `heal` would silently claim
    # nothing.
    selector = _HEAL_GROUP_SELECTOR.get(m.group("who").lower())
    return [EffectSpec("heal", {"selector": selector} if selector else {})]


# RULE 701.42a "if you both own and control ~ and a[n] <type> named <X>,
# exile them, then meld them into <Y>." — the body of a meld card's own
# activated ability ({cost}: … , Hanweir Battlements / Urza, Lord Protector)
# or a phase trigger (`segmenter._MELD_TRIGGER_RE` reaches the same builder).
# The leading "if you both own and control" RULE 603.4 gate is dropped:
# `MeldEffect` re-checks own+control of the named partner at resolution and
# fails closed (nothing exiled) if it isn't there, so the outcome is
# identical. Partner/result names carry commas ("Bruna, the Fading Light"),
# so the two are pinned by the fixed ", exile them, then meld them into "
# and end-of-clause anchors.
_MELD_BODY_RE = compile_clause(
    r"if you both own and control ~ and (?:an?|the) [a-z ]*?named (?P<partner>.+?), "
    r"exile them, then meld them into (?P<result>.+?)"
)


def _meld(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("meld", {
        "partner_name": m.group("partner").strip(),
        "result_name": m.group("result").strip(),
    })]


def _scry_or_surveil(m: re.Match[str]) -> list[EffectSpec]:
    # "[you] scry N" (RULE 701.18) / "[you] surveil N" (RULE 701.31) —
    # identical grammar and params, differing only in which verb was
    # matched; the matched word is itself the EffectSpec type string. The
    # optional leading "you " is the redundant subject a trigger body
    # spells out ("whenever enchanted creature attacks, you scry 2" —
    # Psychic Impetus; "then you scry 2" — Overwhelmed Apprentice): scry is
    # always the controller's, so it drops to the same self effect.
    return [EffectSpec(m.group("verb"), {"count": count_or_x_of(m.group("n"))})]


#: "Look at the top N cards of your library, then put them back in any
#: order." (Sensei's Divining Top/Sylvan Library-shaped, RULE 701.18's own
#: unabbreviated old-templating spelling — ~27 cache-wide cards) — this
#: engine's non-interactive `scry(N)` resolution already covers every
#: legal outcome of "put them back in any order" (Ponder's own existing
#: entry documents why), so it's the same `"scry"` EffectSpec, just a
#: different printed phrasing reaching it.
#: Since the target form ("look at the top 3 cards of target player's library", Elemental Augury /
#: Architects of Will) arrived, both are `LookReorderTopEffect` — scry minus the bottom option, which
#: the printed text never offered. ``x`` takes its value from a "where x is …" tail like any X clause.
_LOOK_TOP_REORDER_RE = compile_clause(
    rf"look at the top (?P<n>\d+|x) cards? of (?:(?P<owner>your)|target player's) library, "
    r"then put (?:it|them) back in any order"
    # "You may shuffle." / "You may have that player shuffle." (Omen, Pondering Mage, Natural Selection, Portent).
    r"(?:\.\s*you may (?P<shuffle>shuffle|have that player shuffle))?"
)


def _look_top_reorder(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    count: object = "x" if m.group("n") == "x" else int(m.group("n"))
    params: dict = {"count": count}
    if not m.group("owner"):
        params["target_kind"] = "player"
    if m.group("shuffle"):
        # "shuffle" is the looker's own library, "have that player shuffle" the target's: each must name its owner.
        if (m.group("shuffle") == "shuffle") != bool(m.group("owner")):
            return None
        params["may_shuffle"] = True
    return [EffectSpec("look_reorder_top", params)]


# "Unlock a locked door of up to one target Room you control." (RULE 709.5f, Ghostly Keybearer), "unlock a locked
# door of a Room you control" (untargeted, chosen on resolution) and "lock or unlock a door of target Room you
# control" (RULE 709.5g, Marina Vendrell/Keys to the House) — the door itself is always chosen on resolution.
def _unlock_door(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if m.group("target"):
        params["target_kind"] = "room_you_control"
        if m.group("upto"):
            params["optional"] = True
    if m.group("lock"):
        params["lock_or_unlock"] = True
    return [EffectSpec("unlock_door", params)]


# "Venture into the dungeon." (RULE 701.49) and its RULE 701.49d "venture
# into [quality]" variant ("venture into Undercity") — the named form keeps
# the dungeon's name as a param, which is what `RulesEngine.
# venture_into_the_dungeon` uses to skip the RULE 309.2a choice.
def _venture(m: re.Match[str]) -> list[EffectSpec]:
    named = (m.groupdict().get("dungeon") or "").strip()
    params: dict = {}
    if named and named != "the dungeon":
        # `normalize` lowercases, so the catalogue lookup is case-folded too.
        params["dungeon"] = named
    return [EffectSpec("venture", params)]


# "Monstrosity 3." (RULE 701.37a) and "Monstrosity X." — always the body of
# the permanent's own activated ability, so there is nothing to target and
# nothing to scope; the whole clause is its amount. "X" is passed through as
# the ``"x"`` sentinel `RulesEngine._substitute_x` rewrites with the announced
# {X} at resolution, which is also what RULE 701.37c's "other abilities may
# refer to that X" reads back.
def _monstrosity(m: re.Match[str]) -> list[EffectSpec]:
    raw = m.group("n")
    return [EffectSpec("monstrosity", {"amount": "x" if raw == "x" else int(raw)})]


# "Adapt 2." (RULE 701.46a) — monstrosity's sibling, gated on the creature's
# own +1/+1 counters rather than a designation. No real adapt card prints
# "adapt X", so this stays a literal (fail-closed: an "adapt X" would leave
# its card UNMODELED rather than silently adapting 0).
def _adapt(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("adapt", {"amount": int(m.group("n"))})]


# "Harness ~." (MEC-79 / RULE 701.64a) — the Marvel Infinity Stones' activated
# body. 701.64a only ever spells the self form ("[this permanent]"), and every
# printing names itself, so after `normalize` folds the card name this is just
# "harness ~" (or the rules-literal "harness this permanent"). No params — the
# designation flip is the whole effect.
def _harness(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("harness", {})]


# RULE 701.50d's optional "connives X, where X is …" tail, embedded at the
# end of every connive verb form below. Two readings: a firing trigger's own
# event field ("the amount of damage it dealt to that player", Mask of the
# Schemer — `GameContext.trigger_event`, the `DealDamageEffect.
# amount_from_trigger_event` idiom) or a live board count (`{DEVOTION}`'s
# "the number of attacking creatures"/"creatures that died this turn").
_CONNIVE_AMOUNT = (
    r"(?: x, where x is (?:"
    r"(?P<connive_damage>the amount of damage it dealt to that player)"
    rf"|{DEVOTION}"
    r"))?"
)


# "~ connives[ X]." / "it connives[ X]." (RULE 701.50a/d, PAR-29) — the
# conniving permanent is the ability's own source (`self.source`, including
# a triggered ability whose subject was retargeted onto e.g. an attached
# permanent before this builder ever sees it). Two subjects: the explicit
# self ("~ connives", an activated ability's body or a self-subject trigger
# where `normalize` kept the card name) and the "it/he/she" pronoun of a
# self-subject trigger ("when ~ enters, it connives", `self_subject_only`).
# A pronoun bound to an *earlier clause's* target ("target Villain you
# control gains menace. It connives.", Doctor Doom) is deliberately left
# unclaimed — the bare-self row would connive the wrong permanent; that
# needs `_connive_previous` below instead, and no real card in the cache
# pairs that exact pronoun shape with a *target* antecedent yet.
# "connives X, where X is …" (RULE 701.50d) is `_CONNIVE_AMOUNT`'s optional
# tail, shared by every connive row in this family — a literal repeat count
# never appears on a real card (only "connives" or "connives X"), so there
# is no plain-integer form to parse.
def _connive_amount_params(m: re.Match[str]) -> dict:
    if m.groupdict().get("connive_damage"):
        return {"times_from_trigger_event": "amount"}
    selector = devotion_selector(m)
    if selector:
        return {"times_from_count_selector": selector}
    return {}


def _connive(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", _connive_amount_params(m))]


# "target creature [you control/an opponent controls] connives[ X]" (RULE
# 601.2c targeting on 701.50a) and "that creature connives" — the two
# subject shapes `_goad`/`_explore` already established, adapted for
# connive. Only a creature-shaped target row is meaningful (RULE 701.47's
# "permanent" is narrowed to creatures by every printed connive card);
# anything else leaves the clause unclaimed rather than conniving the wrong
# kind of object.
_CONNIVE_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)


def _connive_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, _CONNIVE_TARGET_KINDS):
        return None
    params: dict = {"target_kind": kind, **optional_param(m), **_connive_amount_params(m)}
    # "target attacking creature connives X" (Raffine, Scheming Seer) — see
    # `_destroy`'s own comment: `resolve_target_kind` alone drops the
    # qualifier. `ConniveEffect.creature_filter` is new alongside this fix.
    state_filter = resolve_target_creature_state_filter(m.group("target"))
    if state_filter:
        params["creature_filter"] = state_filter
    return [EffectSpec("connive", params)]


def _connive_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", {"previous_subject": True, **_connive_amount_params(m)})]


# "Each of X target creatures you control connive." (Change of Plans) — the
# spell's own announced {X} (`GameObject.x_paid`), the same
# `count_selector="source_x_paid"` reading March of Swirling Mist's "up to X
# target creatures phase out" already uses.
def _connive_each_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("connive", {
        "target_kind": "creature_you_control", "count_selector": "source_x_paid", "optional": True,
    })]


# "Recruit." (RULE 701.70a — Tales of Middle-earth: "draw a card, then
# discard a card. If you discarded a nonland card, create a 1/1 white
# Human Soldier creature token."). Bare word only — every real card says
# just "recruit" (as an ETB or attack trigger's whole body).
# `RulesEngine.recruit` / `effects.RecruitEffect` (registered as ``recruit``).
def _recruit(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("recruit", {})]


# "Learn." (RULE 701.48a — Strixhaven). Bare word only — every real card
# says just "learn." (as a spell effect, or an ETB/dies/activated-ability
# body). `RulesEngine.learn` / `effects.LearnEffect` (registered as
# ``learn``) — the "Lesson from outside the game" branch is dropped (no
# sideboard), so it collapses to an optional discard-a-card-then-draw.
def _learn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("learn", {})]


# "You may collect evidence N." (RULE 701.59a, PAR-29) with no "if you do"
# rider — Corpseberry Cultivator / Evidence Examiner / Surveillance Monitor
# each print it as a bare optional cost whose *only* payoff is the separate
# "whenever you collect evidence, …" trigger firing. Modeled as
# `pay_cost_then` with an empty effect list (an optional cost payment,
# nothing else); `RulesEngine.collect_evidence` fires
# `EventType.COLLECTED_EVIDENCE` when paid.
def _collect_evidence_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": f"collect evidence {m.group('n')}",
        "effects": [],
    })]


# Bare "collect evidence N" (RULE 701.59a) — what's left after the segmenter
# peels a triggered ability's outer "you may " (`AbilitySpec.optional`).
# `CollectEvidenceEffect` (registered as ``collect_evidence``) does the
# exile + `EventType.COLLECTED_EVIDENCE`; the peeled "you may" carries the
# optionality.
def _collect_evidence(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("collect_evidence", {"amount": int(m.group("n"))})]


# "You may forage." (RULE 701.61a, PAR-29) with no "if you do" rider —
# Corpseberry Cultivator: a bare optional cost whose only payoff is the
# separate "whenever you forage, …" trigger. `pay_cost_then` with an empty
# effect list, same shape as `_collect_evidence_bare`.
def _forage_bare(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {"cost": "forage", "effects": []})]


# Bare "forage" — what's left after the segmenter peels a triggered
# ability's outer "you may ". `ForageEffect` (registered as ``forage``).
def _forage(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("forage", {})]


# "Discover N." (RULE 701.57a) — exile from the top of your library until a
# nonland card with mana value N or less, free-cast it or put it in hand,
# rest to the bottom. `effects.DiscoverEffect` (registered as ``discover``,
# a sibling of Cascade) already does all of it; only the parser row was
# missing. Literal N only: "discover X, where X is <count-selector>"
# (Pantlaza/Aloy/…) is a dynamic amount `DiscoverEffect` can't take yet, so
# it stays UNMODELED (fail-closed) rather than discovering 0.
def _discover(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value": int(m.group("n"))})]


#: PAR-71: "discover X, where X is that spell's mana value." (Monstrous
#: Vortex's cast trigger) — `DiscoverEffect.mana_value_from_trigger_event`,
#: the discover-cap sibling of `_pump_mana_value`/`_mill_spell_mv`. "Counter
#: target artifact or creature spell. Discover X, where X is that spell's
#: mana value." (Hurl into History) prints the identical tail but "that
#: spell" there is the *countered* target, not a cast-trigger event —
#: `context.trigger_event` is `None` for a plain resolving spell, so this
#: row alone would silently discover 0; its own `previous_subject_only`
#: sibling right below (offered only when `segmenter.
#: announces_creature_target` sees a preceding ``counter`` spec, widened
#: for exactly this shape) claims that case correctly instead.
def _discover_spell_mv(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value_from_trigger_event": "mana_value"})]


#: The "counter target spell. `<effect>`, where X is that spell's mana
#: value" cluster's shapes (Hurl into History/Access Denied/Spell Swindle/
#: Overwhelming Intellect) — "that spell" is the countered RULE 115 target,
#: read via `GameContext.previous_targets`/`_characteristic_of_subject`'s
#: ``"previous_subject_mana_value"`` (RULE 608.2h last-known information:
#: the countered spell is in a graveyard, with no controller, by the time
#: this clause resolves) rather than a `SPELL_CAST` trigger event, since
#: there isn't one. Each row below is ``previous_subject_only`` for exactly
#: the reason `_discover_spell_mv`'s own docstring documents: the identical
#: printed tail also appears after a genuine cast trigger, where this
#: referent would be wrong.
def _discover_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("discover", {"mana_value_from_subject": "previous_subject_mana_value"})]


#: "Draw cards equal to that spell's mana value." (Overwhelming Intellect) —
#: the `draw`-spec sibling, `DrawCardEffect.amount_from_subject` (the same
#: field `_draw_eq_its_self` already reads for other referents).
def _draw_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"amount_from_subject": "previous_subject_mana_value"})]


#: "Create X 1/1 colorless Thopter artifact creature tokens with flying,
#: where X is that spell's mana value." (Access Denied) — the inline-stats
#: token count, `CreateTokenEffect.count_from_subject` (the same field
#: `AddCountersEffect`/`CreateTokenEffect` already read for other
#: ``"<who>_<char>"`` referents), reusing `_xx_token_mid_params`'s shared
#: colour/subtype/keyword-word splitting.
_CREATE_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE = compile_clause(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?, where x is that spell'?s mana value"
)


def _create_token_xx_spell_mv_previous_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    params.update({
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_from_subject": "previous_subject_mana_value",
    })
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", params)]


#: "Create X Treasure tokens, where X is that spell's mana value." (Spell
#: Swindle) — the named-token sibling of the row just above.
_CREATE_NAMED_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE = compile_clause(
    rf"create x (?P<name>{'|'.join(NAMED_TOKEN_WORDS)}) tokens?, "
    r"where x is that spell'?s mana value"
)


def _create_named_token_xx_spell_mv_previous_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "token_name": NAMED_TOKEN_WORDS[m.group("name")],
        "count_from_subject": "previous_subject_mana_value",
    })]


# "<permanent> explores." (RULE 701.44) — `RulesEngine.explore` owns the
# whole procedure (reveal top card; land → hand, else +1/+1 counter + a
# "may bin it" choice). Same three subject shapes as `_goad`/`_connive`:
#   • "~ explores" / "it/he/she explores" — the ability's own source, i.e.
#     "when ~ enters, it explores" (the 15-card bulk of the mechanic);
#   • "that creature explores" — a creature an earlier clause chose
#     (`previous_subject_only`, e.g. "return target creature card … that
#     creature explores");
#   • "target creature [you control] explores" — off the shared TARGET rows.
# "explores, then it explores again" (Defossilize) and "each Merfolk you
# control explores" (a mass selector) stay unclaimed — different shapes.
def _explore_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("explore", {})]


def _explore_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("explore", {"previous_subject": True})]


def _explore_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None  # only a creature explores on a real card (RULE 701.44)
    return [EffectSpec("explore", {"target_kind": kind, **optional_param(m)})]


# "<permanent> endures N." (RULE 701.63a — Bloomburrow): its controller
# either puts N +1/+1 counters on it or creates an N/N white Spirit token.
# `RulesEngine.endure` / `effects.EndureEffect` (registered as ``endure``)
# own the modal choice. Same subject shapes as `_explore`:
#   • "~ endures N" / "it endures N" — the ability's own source (the bulk:
#     "when ~ enters, it endures 3");
#   • "that creature endures N" — a previous clause's pick;
#   • "target creature you control endures N" — off the shared TARGET rows.
# The "you may pay {cost}. If you do, it endures N" wrapper (Descendant of
# Storms) is a separate pay-cost-then build. Literal N only.
def _endure_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": int(m.group("n"))})]


# "~ endures x" (PAR-29, Krumar Initiate) — X is the activated ability's own
# announced/paid {X}, the plain ``"x"`` sentinel `RulesEngine._substitute_x`
# already resolves generically on any effect's ``amount`` attribute.
def _endure_self_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": "x"})]


def _endure_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("endure", {"amount": int(m.group("n")), "previous_subject": True})]


def _endure_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if not target_kind_allowed(kind, ("creature", "creature_you_control", "creature_you_dont_control")):
        return None
    return [EffectSpec("endure", {
        "amount": int(m.group("n")), "target_kind": kind, **optional_param(m),
    })]


# "Populate[ X times]." (RULE 701.36a, PAR-29) — put a token onto the
# battlefield that's a copy of a creature token you control. `RulesEngine.
# populate` owns the procedure (and the "which token?" choice);
# `effects.PopulateEffect` is registered as ``populate``. Never a target or
# a pronoun subject. "X times" (Full Flowering) rides the plain ``"x"``
# sentinel `RulesEngine._substitute_x` already resolves generically on any
# effect's ``count`` — no dynamic-amount plumbing needed here.
def _populate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("populate", {})]


def _populate_x_times(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("populate", {"count": "x"})]


# "You control target opponent during that player's next turn." (RULE 720,
# MEC-51) — Mindslaver / Worst Fears / Sorin Markov's −7 / Emrakul the
# Promised End's cast trigger; "…during their next combat phase." (Secret
# of Bloodbending) is the ``scope="combat"`` form. `effects.
# ControlPlayerEffect` installs a `GameState.TurnControl` and `services/
# game_session.py` routes the controlled seat's decisions/priority to the
# controller for the window. "you gain control of" is an equivalent
# wording. Riders the segmenter splits off stay UNMODELED, fail-closed
# (Emrakul's own "after that turn, that player takes an extra turn" tail is
# hand-authored on the card, not reached here).
_CONTROL_PLAYER_RE = compile_clause(
    r"you (?:gain )?control(?: of)? target (?P<who>opponent|player) during "
    r"(?:that player's|their) next (?P<scope>turn|combat phase)"
)


def _control_player(m: re.Match[str]) -> list[EffectSpec]:
    scope = "combat" if m.group("scope") == "combat phase" else "turn"
    return [EffectSpec("control_player", {
        "scope": scope,
        "target_kind": "opponent" if m.group("who") == "opponent" else "player",
    })]


# "Take an extra turn after this one." (RULE 500.7, PAR-30) — the plain
# Time Walk / Temporal Manipulation / Capture of Jingzhou body, and the
# modelable half of Plea for Power's vote outcome. `effects.TakeExtraTurn
# Effect` (registered ``take_extra_turn``) queues the effect's controller
# onto `GameState.extra_turns`; `GameEngine.begin_turn` takes it right
# after the current turn. No target, no pronoun subject. "one" normalises
# to "1"; a leading "you " (Mu Yanling) is the same controller-scoped
# action. Riders the segmenter splits off stay UNMODELED, fail-closed:
# "skip the untap step of that turn" (Savor the Moment), "during that
# turn, damage can't be prevented" (Alchemist's Gambit), "at the beginning
# of that turn's end step, you lose the game" (Last Chance). "…for each
# coin that comes up heads" / "…if an opponent cast a blue spell this
# turn" don't fullmatch this row either — those keep their own count /
# condition and are their own tickets.
_TAKE_EXTRA_TURN_RE = compile_clause(r"(?:you )?take an extra turn after this 1")


def _take_extra_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("take_extra_turn", {})]


# "Incubate N." (RULE 701.53, PAR-29) — create an Incubator token (a
# power/toughness-less colourless artifact token) with N +1/+1 counters on
# it. No new engine primitive: the `Incubator` catalogue entry
# (`card_registry/red_spells.py`) already binds "{2}: Transform this
# token" (→ a 0/0 Phyrexian artifact creature) onto every token so named,
# and `create_token`'s `extra_counters` places the counters — the exact
# spec shape Glissa, Herald of Predation's hand-authored entry already
# emits. "You incubate N" (a "when you do" continuation) is the same
# action, "you" subject and all. The dynamic "incubate X, where X is …"
# form needs `extra_counters` to take a count-selector/`"x"` sentinel — a
# follow-up, tracked in BACKLOG.
def _incubate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("create_token", {
        "count": 1,
        "token_name": "Incubator",
        "extra_counters": {"kind": "+1/+1", "count": int(m.group("n"))},
    })]


#: "Incubate X, where X is `<count>`." / "Incubate X twice, where X is
#: `<count>`." (PAR-30) — the dynamic-amount sibling of `_incubate`. "Twice"
#: makes two Incubator tokens (each with X counters), which is exactly
#: `create_token`'s own ``count`` — one Incubator per repetition. The X
#: vocabulary is a small closed map onto `continuous.count_selector` plus
#: the firing spell's mana value (`CreateTokenEffect.extra_counters`'
#: new ``count_from_count_selector`` / ``count_from_trigger_event`` keys).
#: "…where X is **its power**" (Bloated Processor, Furnace Gremlin — a
#: "when ~ dies" trigger) reads the dying creature's own last-known power
#: off the DIES event's snapshotted ``power`` field (RULE 400.7 / 603.6e),
#: the same firing-event idiom `EarthbendEffect.amount_from_trigger_event`
#: uses for "earthbend X, where X is that creature's power".
#:
#: "**Its controller** incubates X, where X is **its mana value**" (Excise
#: the Imperfect — the "its" is the just-exiled previous target, already
#: gone: RULE 608.2h last-known info) → `create_token`'s
#: ``creators="previous_target_controller"`` + ``extra_counters``'
#: ``count_from_subject="previous_subject_mana_value"``.
#:
#: "…where X is the number of creatures **exiled this way**" (Sunfall) →
#: ``extra_counters``' ``count_from_context="objects_exiled_this_way"``
#: (`GameContext`'s exile-count accumulator, sibling of
#: `permanents_destroyed_this_way`).
#:
#: Still UNMODELED, fail-closed: "incubate N **that many times**"
#: (Phyrexian Incubator — a search-result count across a `pending_choice`
#: suspension) and "incubate N **X times**" reading a source's own
#: ``x_paid`` (Progenitor Exarch, an {X}{X} creature — also blocked on its
#: "transform target Incubator token" ability).
_INCUBATE_X_SELECTORS: dict[str, str] = {
    "the number of lands you control": "lands_you_control",
    "the number of creature cards in your graveyard": "creature_cards_in_your_graveyard",
}
_INCUBATE_X_ALT = "|".join(re.escape(p) for p in _INCUBATE_X_SELECTORS)
_INCUBATE_X_RE = compile_clause(
    r"(?:you |(?P<prev_ctrl>its controller ))?incubates? x(?: (?P<twice>twice))?, where x is "
    r"(?:(?P<selector>" + _INCUBATE_X_ALT + r")"
    r"|(?P<spell_mv>that spell'?s mana value)"
    r"|(?P<its_power>its power)"
    r"|(?P<its_mv>its mana value)"
    r"|(?P<exiled_this_way>the number of creatures exiled this way))"
)


def _incubate_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    extra: dict[str, Any] = {"kind": "+1/+1"}
    params: dict[str, Any] = {
        "count": 2 if m.group("twice") else 1,
        "token_name": "Incubator",
    }
    if m.group("its_power"):
        # "when ~ dies, incubate X, where X is its power" — the DIES event
        # carries the dying object's ``power`` snapshotted before the move
        # (RULE 400.7); read it fresh at resolve time exactly like the
        # "that spell's mana value" branch reads the firing event.
        extra["count_from_trigger_event"] = "power"
    elif m.group("its_mv"):
        # "its controller incubates X, where X is its mana value" (Excise
        # the Imperfect) — "its" = the just-exiled previous target (RULE
        # 608.2h last-known info).
        extra["count_from_subject"] = "previous_subject_mana_value"
    elif m.group("exiled_this_way"):
        extra["count_from_context"] = "objects_exiled_this_way"
    elif m.group("spell_mv"):
        extra["count_from_trigger_event"] = "mana_value"
    else:
        selector = _INCUBATE_X_SELECTORS.get(m.group("selector"))
        if selector is None:
            return None  # fail closed — an X phrasing we don't model
        extra["count_from_count_selector"] = selector
    if m.group("prev_ctrl"):
        params["creators"] = "previous_target_controller"
    params["extra_counters"] = extra
    return [EffectSpec("create_token", params)]


# "Clash with an opponent." / "Clash with defending player." (RULE 701.30,
# PAR-29) — reveal the top card of your (and one opponent's) library;
# `RulesEngine.clash` / `effects.ClashEffect` (registered as ``clash``) own
# the procedure and RULE 701.30d win check. The "if you win, `<effect>`. /
# otherwise, `<effect>`." branch is a *separate* condition-gated spec
# (`segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE`), so this
# handler is only the clash itself — a bare "clash with defending player."
# (Marvo, Deep Operative) with no branch at all is the whole clause.
def _clash(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("clash", {})]


# RULE 705.1 (PAR-151): "Flip a coin." / "flip 3 coins." / "flip X coins." / "flip a coin until
# you lose a flip." — `effects.CoinFlipEffect`'s *recording* form (registered as ``coin_flip``):
# it flips and leaves the outcome on `GameContext.coin_outcome`. The "if you win/lose the flip,
# `<effect>`" branches are separate ``coin_won``-gated specs (`segmenter._COIN_FLIP_RESULT_RE`),
# so a branch's target is announced with the spell or ability (RULE 601.2c) — the clash idiom.
_COIN_FLIP_RE = compile_clause(r"flip (?:(?P<one>a coin)|(?P<n>\d+|x) coins)(?P<until> until you lose a flip)?")


def _coin_flip(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {}
    if m.group("until"):
        if m.group("one") is None:
            return None  # "flip N coins until …" is not printed
        params["until_lose"] = True
    elif m.group("n"):
        count = m.group("n")
        params["count"] = "x" if count == "x" else int(count)
    return [EffectSpec("coin_flip", params)]


# RULE 705.1 / 603.12 (PAR-151): "Flip a coin. When you win the flip, `<effect>`. When you lose the
# flip, `<effect>`." — each branch is a *reflexive triggered ability* put on the stack after the
# flip (Breeches), so a target in it is chosen then rather than when the flip's own ability is
# announced; both branches are optional individually, but at least one must be given.
_COIN_REFLEXIVE_RE = compile_clause(
    r"flip a coin\. when you (?P<r1>win|lose) the flip, (?P<b1>.+?)"
    r"(?:\. when you (?P<r2>win|lose) the flip, (?P<b2>.+))?"
)


def _coin_reflexive(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    branches = {m.group("r1").lower(): m.group("b1")}
    if m.group("r2"):
        if m.group("r2").lower() in branches:
            return None
        branches[m.group("r2").lower()] = m.group("b2")
    params: dict = {}
    for result, body in branches.items():
        sub = parse_effect_body(body)
        if not sub or any(spec.condition is not None for spec in sub):
            return None
        params[f"{result}_trigger"] = [spec.to_dict() for spec in sub]
    return [EffectSpec("coin_flip", params)]


# RULE 705.1 / 603.7 (PAR-151): a delayed flip - "Flip a coin at end of combat. If you lose the flip,
# an opponent gains control of ~." (Fickle Efreet) / "Flip a coin at the beginning of the next end
# step. If you lose the flip, sacrifice that creature." (Goblin Kites). One delayed triggered
# ability holds the flip and its gated branch, so the branch reads the flip made when it fires. The
# branch is limited to the delayed vocabulary that already captures its referent at arm time
# (sacrifice | exile | destroy of "it | that creature | ~", `_DELAYED_TAIL_INNER`) and to a bare
# "an opponent gains control of ~"; anything else stays unclaimed.
_COIN_DELAYED_RE = compile_clause(
    r"flip a coin (?P<when>at the beginning of the next end step|at end of combat)\.\s*"
    r"if you (?P<res>win|lose) the flip, (?P<body>.+)"
)
_COIN_DELAYED_BODY_RE = compile_clause(
    r"(?P<verb>sacrifice|exile|destroy) (?:(?P<obj>it|that creature)|(?P<obj_self>~))"
)


def _coin_delayed(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    won = {"kind": "coin_won"}
    gate = won if m.group("res").lower() == "win" else {"kind": "not", "condition": won}
    body = m.group("body").strip()
    hit = _COIN_DELAYED_BODY_RE.fullmatch(body)
    if hit is not None:
        branch = {"type": DELAYED_TAIL_INNER[hit.group("verb").lower()], "params": {}}
        capture = "self" if hit.group("obj_self") else "previous_or_self"
    else:
        sub = parse_effect_body(body)
        if not sub or len(sub) != 1 or sub[0].type != "gain_control_by_source" or sub[0].condition is not None:
            return None
        branch = sub[0].to_dict()
        capture = "self"
    branch["condition"] = gate
    step = "end_combat" if m.group("when").lower() == "at end of combat" else "end"
    return [EffectSpec("create_delayed_trigger", {
        "step": step, "scope": "any", "capture": capture,
        "effects": [EffectSpec("coin_flip", {}).to_dict(), branch],
    })]


# RULE 705.1 / 101.4 (PAR-151): per-object flips — "flip a coin for each opponent you have",
# "for each blocking creature, flip a coin", "each player flips a coin" — followed by the
# branches that read *that* flip: "if you win|lose the flip, `<effect>`", "for each flip you
# win|lose, `<effect>`" (one flip per pass, so the same gate) and "`<verb>` each creature | player
# whose coin comes up tails". One ``for_each`` pass per object holds the flip and its gated
# branches, so a branch sees its own pass's outcome and its own object (handed to the body as its
# target, exactly as `segmenter._player_scope_specs` does). Fails closed on a branch that names a
# real target, on a loop group the selector grammar can't read, and on a body that
# targets anything but the iterated kind.
_COIN_EACH_RE = compile_clause(
    r"(?:flip a coin for each (?P<g1>[^.]+?)|for each (?P<g2>[^.,]+?), flip a coin"
    r"|(?P<pl>each player|each opponent) flips a coin)\.\s*(?P<rest>.+)"
)
_COIN_EACH_BRANCH_RES = (
    compile_clause(r"if you (?P<res>win|lose) the flip, (?P<body>.+)"),
    compile_clause(r"for each flip you (?P<res>win|lose), (?P<body>.+)"),
)
_COIN_EACH_WHOSE_RE = compile_clause(
    r"(?P<pre>.*?)\s*\beach (?P<kind>player|creature) whose coin comes up (?P<face>heads|tails)(?P<post>.*)"
)
_COIN_EACH_EXCLUDED_RE = compile_clause(
    r"creature that isn't an? (?P<first>[a-z]+)(?P<more>(?:,? (?:or )?[a-z]+)*)"
)
_COIN_EACH_PLAYERS = {"opponent you have": "each_opponent", "opponent": "each_opponent",
                      "player": "each_player", "each player": "each_player",
                      "each opponent": "each_opponent"}


def _coin_each_group(m: re.Match[str]) -> Optional[tuple[dict, str]]:
    """The loop's ``over`` and the kind (``player``/``creature``) its items are."""

    group = (m.group("g1") or m.group("g2") or m.group("pl")).strip().lower()
    if group in _COIN_EACH_PLAYERS:
        return {"players": _COIN_EACH_PLAYERS[group]}, "player"
    excluded = _COIN_EACH_EXCLUDED_RE.fullmatch(group)
    if excluded is not None:
        names = [excluded.group("first")] + re.findall(r"(?:, | or )(?:or )?([a-z]+)", excluded.group("more"))
        return {"selector": {"zone": "battlefield", "of": "any", "filter": {
            "card_type": "creature", "without_subtype": [n.capitalize() for n in names],
        }}}, "creature"
    selector = parse_count_phrase(group)
    if (selector is None or selector.get("zone") != "battlefield" or "terms" in selector
            or (selector.get("filter") or {}).get("card_type") != "creature"):
        return None
    return {"selector": selector}, "creature"


def _coin_each(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    group = _coin_each_group(m)
    if group is None:
        return None
    over, item_kind = group
    effects: list[dict] = [EffectSpec("coin_flip", {"by_item": True} if m.group("pl") else {}).to_dict()]
    won = {"kind": "coin_won"}
    branches = 0
    for sentence in re.split(r"\.\s+", m.group("rest").strip().rstrip(".")):
        for branch_re in _COIN_EACH_BRANCH_RES:
            hit = branch_re.fullmatch(sentence)
            if hit is not None:
                won_branch = hit.group("res").lower() == "win"
                body = hit.group("body")
                if re.search(r"\b(?:target|each|another|other)\b", body, re.I):
                    return None
                body = re.sub(r"\bthat (player|creature)\b", r"target \1", body, flags=re.I)
                break
        else:
            hit = _COIN_EACH_WHOSE_RE.fullmatch(sentence)
            if hit is None or hit.group("kind") != item_kind:
                return None
            won_branch = hit.group("face").lower() == "heads"
            body = f"{hit.group('pre')} target {item_kind}{hit.group('post')}".strip()
            if not hit.group("pre"):
                body = f"target {item_kind}{hit.group('post')}"
        sub = parse_effect_body(body)
        if not sub:
            return None
        for spec in sub:
            named = [spec.params[k] for k in TARGET_PARAM_KEYS if spec.params.get(k) is not None]
            if (named not in ([], [item_kind]) or spec.condition is not None
                    or spec.type in ("for_each", "bind", "if_else", "seq")):
                return None
            effects.append(EffectSpec(
                spec.type, dict(spec.params),
                condition=won if won_branch else {"kind": "not", "condition": won},
            ).to_dict())
        branches += 1
    if not branches:
        return None
    return [EffectSpec("for_each", {"over": over, "effects": effects})]


# RULE 706.1: "Roll a d20." / "Roll a six-sided die." / "Roll two d6." —
# `RulesEngine.roll_die` / `effects.RollDieEffect` (registered as
# ``roll_die``) own the roll, the `EventType.DICE_ROLLED` firing and RULE
# 706.3a's optional results table (attached by `gate._split_dice_table_
# block`, never by this bare-clause handler). This handler is only the roll
# itself — the whole clause for a card that rolls and then reads the result
# in a *separate* sentence (Barbarian Class' "+2/+0" tail is its own
# `whenever you roll` trigger), or as an activated/ETB body the ordinary
# `<cost>:`/`when ~ enters,` wrappers pick up once the roll parses.
_DICE_COUNT_WORDS = {"a": 1, "two": 2, "three": 3, "2": 2, "3": 3}
_ROLL_DIE_RE = compile_clause(
    r"roll (?:a|(?P<c>two|three|x|\d+)) "
    r"(?:d(?P<sides_d>\d+)|(?P<sides_s>\d+)-sided (?:die|dice))"
    # RULE 706 (PAR-147): "roll X six-sided dice, where X is the number of Bobbleheads you control" — the count is
    # measured when the roll happens (a `bind` would lose the kept dice to the nested resolution).
    r"(?:, where x is (?P<where>.+)| and choose (?P<choose>1|one) result"
    # RULE 706.4 (PAR-147): "roll a d20 and add the number of cards in your hand" — the modifier changes the result.
    r"| and (?P<mod_op>add|subtract) (?P<mod>.+))?"
)


def _roll_die(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    sides = int(m.group("sides_d") or m.group("sides_s"))
    word = (m.group("c") or "a").lower()
    params: dict = {"sides": sides}
    if word == "x":
        if m.group("where"):

            counted = parse_amount_phrase(m.group("where"))
            if counted is None:
                return None
            params["count_amount"] = {"kind": "count_selector", "selector": counted}
        else:
            params["count"] = "x"  # the announced {X} (0 when nothing announced one)
        return [EffectSpec("roll_die", params)]
    if m.group("where"):
        return None  # a "where x is" tail only defines a rolled-X count
    if m.group("mod"):

        if word != "a":  # a modifier on a multi-die roll is not a printed shape
            return None
        phrase = m.group("mod").strip().rstrip(".")
        if phrase.isdigit():
            params["modifier"] = int(phrase)
        else:
            counted = parse_amount_phrase(phrase)
            if counted is None:
                return None
            params["modifier_amount"] = {"kind": "count_selector", "selector": counted}
        if m.group("mod_op") == "subtract":
            params["modifier_subtract"] = True
        return [EffectSpec("roll_die", params)]
    if m.group("choose"):
        params["choose"] = 1  # the Endeavor cycle: roll two, keep one result (RULE 706.2)
    count = int(word) if word.isdigit() else _DICE_COUNT_WORDS.get(word)
    if count is None:  # a spelled count outside the small known set — fail closed
        return None
    if count != 1:
        params["count"] = count
    return [EffectSpec("roll_die", params)]


# --- MEC-50: Clash (RULE 701.30) win/otherwise-branch bodies. Each is the
# `<rest>` a `segmenter._IF_YOU_WIN_CLASH_RE` / `_OTHERWISE_CLASH_RE` peel
# hands to `parse_effect_body`; the segmenter re-wraps the result with
# `condition={"clash_won": True/False}`, so these builders emit the bare
# effect only. -----------------------------------------------------------------

#: "…If you win, **that spell's controller** mills four cards." (Broken
#: Ambitions) — "that spell" is the countered spell an earlier clause of
#: this same resolution targeted (`GameContext.previous_targets[0]`, now in
#: a graveyard, RULE 608.2h last-known — `MillEffect.selector=
#: "previous_subject_controller"` reads its `owner_id`).
_MILL_PREV_SPELL_CONTROLLER_RE = compile_clause(
    r"that spell'?s controller mills (?P<n>\d+) cards?"
)


def _mill_prev_spell_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("mill", {
        "count": int(m.group("n")), "selector": "previous_subject_controller",
    })]


#: "Otherwise, **that player** discards a card." (Pulling Teeth) — "that
#: player" is the same player an earlier clause RULE 115-targeted
#: (`DiscardEffect.previous_subject`, reads `GameContext.previous_targets[0]`,
#: a `Player`).
_THAT_PLAYER_DISCARDS_RE = compile_clause(
    r"that player discards (?P<n>a|\d+) cards?(?P<at_random> at random)?"
)


def _that_player_discards(m: re.Match[str]) -> list[EffectSpec]:
    n = m.group("n")
    params: dict = {"count": 1 if n == "a" else int(n), "previous_subject": True}
    if m.groupdict().get("at_random"):
        params["random"] = True
    return [EffectSpec("discard", params)]


#: "If you win, **gain control of enchanted creature**. Otherwise, **that
#: player gains control of enchanted creature**." (Captivating Glance) — an
#: indefinite control change of this Aura's host
#: (`GainControlAttachedEffect`); recipient is the ability's controller
#: (win) or `GameContext.clashed_opponent` (otherwise).
_GAIN_CONTROL_ATTACHED_RE = compile_clause(
    r"(?P<who>you gain|gain|that player gains) control of enchanted creature"
)


def _gain_control_attached(m: re.Match[str]) -> list[EffectSpec]:
    recipient = "clashed_opponent" if m.group("who") == "that player gains" else "controller"
    return [EffectSpec("gain_control_attached", {"recipient": recipient})]


#: "If you win, **creatures that player controls don't untap during the
#: player's next untap step**." (Pollen Lullaby) — "that player" is
#: `GameContext.clashed_opponent`; `SkipNextUntapEffect.subject=
#: "clashed_opponent"` flags every creature that player currently controls.
_CLASHED_OPP_CREATURES_NO_UNTAP_RE = compile_clause(
    r"creatures that player controls don'?t untap during (?:the player'?s|their) next untap step"
)


def _clashed_opp_creatures_no_untap(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"subject": "clashed_opponent"})]


# "Planeswalk." (RULE 901.10) / "Chaos ensues." (RULE 901.13) — the two
# outcome bodies of Path of the Animist / Path of the Enigma's "each
# player votes for planeswalk or chaos" vote (reached through
# `_vote_majority`'s `parse_effect_body`), and "planeswalk" as a
# standalone body (Plain Walker). `effects.PlaneswalkEffect` /
# `ChaosEnsuesEffect` wrap `RulesEngine.planeswalk` / `trigger_chaos`;
# both no-op outside a Planechase game. Fullmatch-only, so "planeswalk to
# <plane>" (Seek Bolas's Counsel) and "you may planeswalk" (TARDIS) stay
# UNMODELED, fail-closed — those cards are blocked on other clauses too.
def _planeswalk(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("planeswalk", {})]


def _chaos_ensues(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("chaos_ensues", {})]


# "Starting with you, each player votes for `<A>` or `<B>`. If `<A>` gets
# more votes, `<X>`. If `<B>` gets more votes or the vote is tied, `<Y>`."
# (RULE 701.38, PAR-29). `RulesEngine._request_vote` / `effects.VoteEffect`
# own the APNAP sweep and outcome. Two shapes: a majority branch (this
# handler) and per-vote scaling ("… for each `<A>` vote", `_vote_per_vote`
# below). Only the 2-option majority form here — 3+-option votes
# (Council Guardian) and "vote for a permanent/card" (Council's Judgment)
# stay UNMODELED, fail-closed.
_VOTE_HEADER_RE = compile_clause(
    r"starting with you, each player votes for (?P<opts>[a-z][a-z, /'-]+?)\.\s+(?P<rest>.+)"
)
_VOTE_MAJORITY_BODY_RE = re.compile(
    r"^if (?P<a>[a-z'-]+) gets more votes, (?P<x>.+?)\.\s*"
    r"if (?P<b>[a-z'-]+) gets more votes or the vote is tied, (?P<y>.+?)\.?$",
    re.IGNORECASE,
)


def _split_vote_options(raw: str) -> list[str]:
    parts = re.split(r",?\s+or\s+|,\s+", raw.strip())
    return [p.strip() for p in parts if p.strip()]


def _vote_majority(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    options = _split_vote_options(m.group("opts"))
    if len(options) != 2:
        return None
    mm = _VOTE_MAJORITY_BODY_RE.match(m.group("rest").strip())
    if mm is None:
        return None
    a, b = mm.group("a").lower(), mm.group("b").lower()
    if {a, b} != {o.lower() for o in options}:
        return None
    x_specs = parse_effect_body(mm.group("x").strip())
    y_specs = parse_effect_body(mm.group("y").strip())
    if not x_specs or not y_specs:
        return None
    if any(
        s.params.get("target_kind") and not s.params.get("players")
        for s in (*x_specs, *y_specs)
    ):
        # A *targeted* branch can't resolve off-stack (see
        # `_pay_cost_then_general`); a mass `players`-scoped return
        # (`target_kind` there is just the card filter, not a RULE 115
        # choice) is fine.
        return None
    lowered = [o.lower() for o in options]
    idx_a = lowered.index(a)
    majority: list[Optional[list[dict]]] = [None, None]
    majority[idx_a] = [s.to_dict() for s in x_specs]
    majority[1 - idx_a] = [s.to_dict() for s in y_specs]
    return [EffectSpec("vote", {
        "options": options,
        "majority_specs": majority,
        "tie_index": lowered.index(b),
    })]


#: "… for each `<option>` vote" — the per-vote-scaling outcome shape
#: (Lieutenants of the Guard / Orchard Elemental / Messenger Jays). Each
#: segment's body parses as a *unit* effect (`add_counters` count 1/2,
#: `create_token` count 1, `gain_life` amount 3, `draw` count 1); `Vote
#: Effect`'s `per_vote_specs` then multiplies that ``count``/``amount`` by
#: the option's vote total at resolve time.
_VOTE_PER_VOTE_SEG_RE = re.compile(
    r"(?P<body>.+?)\s+for each (?P<opt>[a-z'-]+) votes?"
    r"(?:\s*\.\s*|\s*,\s*(?:and\s+)?|\s+and\s+|\s*$)",
    re.IGNORECASE,
)


def _vote_per_vote(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    options = _split_vote_options(m.group("opts"))
    if len(options) != 2:
        return None
    lowered = [o.lower() for o in options]
    rest = m.group("rest").strip()
    segments = list(_VOTE_PER_VOTE_SEG_RE.finditer(rest))
    if not segments:
        return None
    # every segment must be consumed — a trailing non-"for each" clause
    # (Messenger Jays' "for each card drawn this way, discard a card") is
    # not modeled, fail-closed.
    if segments[-1].end() != len(rest):
        return None
    # A later segment split on a bare "and" can silently lose a per-player
    # subject carried from the first ("each opponent sacrifices … *and*
    # discards a card for each taxes vote" — the "discards" clause is still
    # each opponent's, Capital Punishment). Lift the leading "each player /
    # each opponent" off segment 0 and prepend it to any subject-less
    # later segment so both scope the same way.
    #: the leading "each player / each opponent" of segment 0, to carry
    #: onto a subject-less later segment (Capital Punishment)
    _CARRY_SUBJ_RE = re.compile(r"^(each (?:player|opponent))\s+", re.IGNORECASE)
    #: any explicit subject a later segment might already carry — "you" is
    #: always the caster and resolves fine on its own, so it's included
    #: here only to *stop* the carry, not to trip the fail-closed guard
    _HAS_SUBJ_RE = re.compile(
        r"^(?:you|each (?:player|opponent)|target|that player)\b", re.IGNORECASE
    )
    #: a later segment's own *scoped* per-player subject (not "you")
    _SCOPED_SUBJ_RE = re.compile(
        r"^(?:each (?:player|opponent)|target|that player)\b", re.IGNORECASE
    )
    _first_subj = _CARRY_SUBJ_RE.match(segments[0].group("body").strip())
    carried_subject = _first_subj.group(1) if _first_subj else None

    per_vote: list[dict] = []
    for i, seg in enumerate(segments):
        opt = seg.group("opt").lower()
        if opt not in lowered:
            return None
        body = seg.group("body").strip()
        if i > 0 and carried_subject and not _HAS_SUBJ_RE.match(body):
            body = f"{carried_subject} {body}"
        # A later segment naming its own scoped per-player subject other
        # than the carried one isn't a shared-subject shape — fail-closed.
        if i > 0 and _SCOPED_SUBJ_RE.match(body) and not (
            carried_subject and body.lower().startswith(carried_subject.lower())
        ):
            return None
        body_specs = parse_effect_body(body)
        if not body_specs:
            return None
        if any(s.params.get("target_kind") for s in body_specs):
            return None
        # `_tally_and_apply_vote`'s per-vote branch scales an int
        # ``count``/``amount`` by the option's vote total. An effect with
        # no such param can't scale — "take an extra turn … for each time
        # vote" (Expropriate) would resolve once, not N times — so
        # fail-closed rather than half-model it.
        if any(s.type == "take_extra_turn" for s in body_specs):
            return None
        per_vote.append({
            "option": lowered.index(opt),
            "effects": [s.to_dict() for s in body_specs],
            "scale": 1,
        })
    return [EffectSpec("vote", {"options": options, "per_vote_specs": per_vote})]


# MEC-46 — "each player votes for `<colours>`. This creature gains
# protection from each color with the most votes or tied for most votes."
# (Council Guardian). Each option that ties for most votes contributes an
# indefinite (RULE 611, no duration) self-scoped "protection from
# `<colour>`" grant, carried in the vote's `winner_specs`.
_VOTE_WINNER_PROTECTION_BODY_RE = re.compile(
    r"^(?:this creature|~|it) gains protection from each color "
    r"with the most votes or tied for most votes\.?$",
    re.IGNORECASE,
)
_VOTE_COLOUR_WORDS = {"white", "blue", "black", "red", "green"}


def _vote_winner_protection(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    options = _split_vote_options(m.group("opts"))
    if len(options) < 2 or not all(o.lower() in _VOTE_COLOUR_WORDS for o in options):
        return None
    if _VOTE_WINNER_PROTECTION_BODY_RE.match(m.group("rest").strip()) is None:
        return None
    winner_specs = [
        [{
            "type": "grant_until",
            "params": {
                "static": {
                    "type": "grant_protection_static",
                    "params": {"protections": [opt.lower()]},
                },
                "duration": "rest_of_game",
                "self_subject": True,
            },
        }]
        for opt in options
    ]
    return [EffectSpec("vote", {"options": options, "winner_specs": winner_specs})]


# MEC-46 — the tally-over-objects vote (`ObjectVoteEffect` /
# `RulesEngine._request_object_vote`): "each player votes for a nonland
# permanent you don't control. Exile each permanent with the most votes or
# tied for most votes." (Council's Judgment) / "…an artifact, creature, or
# enchantment card in your graveyard. Return each card … to your hand."
# (Custodi Squire). The vote is over board / graveyard *objects*, not
# named options.
_VOTE_OBJECT_PERMANENT_RE = re.compile(
    r"^a nonland permanent you don't control\.\s+"
    r"exile each permanent with the most votes or tied for most votes\.?$",
    re.IGNORECASE,
)
_VOTE_OBJECT_GRAVEYARD_RE = re.compile(
    r"^an? (?P<types>[a-z, ]+?) card in your graveyard\.\s+"
    r"return each card with the most votes or tied for most votes to your hand\.?$",
    re.IGNORECASE,
)
_VOTE_OBJECT_CARD_TYPES = {"artifact", "creature", "enchantment", "land", "planeswalker"}


def _vote_object(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    full = f"{m.group('opts').strip()}. {m.group('rest').strip()}"
    if _VOTE_OBJECT_PERMANENT_RE.match(full) is not None:
        return [EffectSpec("vote_object", {
            "pool": "nonland_permanents_opponents", "outcome": "exile",
        })]
    grave = _VOTE_OBJECT_GRAVEYARD_RE.match(full)
    if grave is not None:
        raw = re.split(r",\s*(?:or\s+)?|\s+or\s+", grave.group("types").strip())
        types = [t.strip().lower() for t in raw if t.strip()]
        if not types or any(t not in _VOTE_OBJECT_CARD_TYPES for t in types):
            return None
        return [EffectSpec("vote_object", {
            "pool": "graveyard_cards", "outcome": "return_to_hand", "card_types": types,
        })]
    return None


# MEC-46 — Expropriate's "For each time vote, take an extra turn after this
# one. For each money vote, choose a permanent owned by the voter and gain
# control of it. Exile Expropriate." The time body scales `take_extra_turn`
# by the number of time votes; the money body is a per-*ballot* gain-control
# (`VoteEffect.per_vote_specs`' ``per_voter_gain_control`` shape). The
# normalizer has already turned "one" → "1" and the card name → "~".
_VOTE_EXPROPRIATE_RE = re.compile(
    r"^for each (?P<a>time|money) vote, take an extra turn after this (?:one|1)\.\s+"
    r"for each (?P<b>time|money) vote, choose a permanent owned by the voter "
    r"and gain control of it\.\s+exile ~\.?$",
    re.IGNORECASE,
)


def _vote_expropriate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    options = _split_vote_options(m.group("opts"))
    if {o.lower() for o in options} != {"time", "money"}:
        return None
    mm = _VOTE_EXPROPRIATE_RE.match(m.group("rest").strip())
    if mm is None or mm.group("a").lower() != "time" or mm.group("b").lower() != "money":
        return None
    lowered = [o.lower() for o in options]
    return [
        EffectSpec("vote", {
            "options": options,
            "per_vote_specs": [
                {
                    "option": lowered.index("time"),
                    "effects": [{"type": "take_extra_turn", "params": {"count": 1}}],
                    "scale": 1,
                },
                {"option": lowered.index("money"), "per_voter_gain_control": True},
            ],
        }),
        EffectSpec("exile", {"target_kind": None}),
    ]


# MEC-46 (RULE 701.38f) — "You choose how each player votes this turn."
# (Illusion of Choice). `SetForcedVoterEffect` marks the caster as the
# answerer of every seat's ballot for the rest of the turn.
def _forced_vote(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("set_forced_voter", {})]


# "`<player>` faces a villainous choice — `<A>`, or `<B>`." (RULE 701.55,
# PAR-29). `RulesEngine._request_villainous_choice` / `effects.FaceVillainous
# ChoiceEffect` own the APNAP sweep (each facing player applies their own
# pick). Each option is mini-parsed with the facing player as the target:
# "they/that player `<verb>`" → a player-targeted `sacrifice`/`discard`/
# `lose_life`, "you `<verb>`" stays controller-scoped. Only the options
# both parse — cards whose option is "cast a spell without paying", "put a
# permanent from hand", "create a copy of that card", "exile until …" &c.
# stay UNMODELED (tracked in PAR-30).
_VILLAINOUS_HEADER_RE = compile_clause(
    r"(?P<subj>each opponent(?: who lost (?P<mll>\d+) or more life this turn)?"
    r"|that player|that opponent|target opponent|target player|defending player) "
    r"faces a villainous choice\s*[—-]\s*(?P<opts>.+)"
)
_VILLAINOUS_SUBJECTS: dict[str, str] = {
    "each opponent": "each_opponent",
    "target opponent": "target",
    "target player": "target",
    "that player": "trigger_target_player",
    "that opponent": "trigger_target_player",
    "defending player": "trigger_target_player",
}
_VILLAINOUS_SAC_WHAT: dict[str, str] = {
    "creature": "creature", "nontoken creature": "nontoken_creature",
    "artifact": "artifact", "permanent": "permanent", "land": "land",
}
_VILLAINOUS_SAC_RE = re.compile(
    r"^(?:they|that player|that opponent) sacrifices? an? (?P<what>[a-z ]+?)"
    r"(?: of their choice)?$",
    re.IGNORECASE,
)


def _villainous_option_specs(body: str):
    """One villainous-choice option → serialized specs, or ``None``.

    A "you …" clause parses controller-scoped as-is. A "they/that player
    `<verb>`" clause is retried as "target player `<verb>`" (the facing
    player is the effect's target — `_request_villainous_choice` applies
    each option with ``targets=[facing]``); a bare edict ("they sacrifice
    a creature of their choice") maps straight to a player-less
    `sacrifice` spec.
    """

    body = body.strip().rstrip(".")
    sac = _VILLAINOUS_SAC_RE.match(body)
    if sac is not None:
        what = _VILLAINOUS_SAC_WHAT.get(sac.group("what").strip().lower())
        if what is None:
            return None
        return [{"type": "sacrifice", "params": {"what": what, "count": 1}}]
    lowered = body.lower()
    candidates: list[str] = []
    if lowered.startswith("they "):
        # "they lose 2 life" → "target player loses 2 life" (3rd-person-
        # singular verb), tried *first* so the resolution binds to this
        # effect's own `targets=[facing]` rather than a `selector=
        # "event_player"` that won't be live once the choice is answered.
        candidates.append(re.sub(
            r"^they (lose|discard|exile|mill|shuffle|draw|gain)\b",
            lambda mm: "target player " + mm.group(1) + "s",
            body, count=1, flags=re.IGNORECASE,
        ))
    elif lowered.startswith(("that player ", "that opponent ")):
        candidates.append(re.sub(
            r"^that (?:player|opponent) ", "target player ", body, count=1,
            flags=re.IGNORECASE,
        ))
    candidates.append(body)
    _TRIGGER_SELECTORS = {"event_player", "event_controller", "defending_player", "triggering_player"}
    for cand in candidates:
        specs = parse_effect_body(cand)
        if not specs:
            continue
        if any(s.params.get("selector") in _TRIGGER_SELECTORS for s in specs):
            continue  # depends on a trigger event that won't be live at resolve time
        if all(s.params.get("target_kind") in (None, "player") for s in specs):
            return [s.to_dict() for s in specs]
    return None


def _face_villainous_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    min_life_lost = m.groupdict().get("mll")
    if min_life_lost is not None:
        # "each opponent **who lost N or more life this turn**" (Davros) —
        # an `each_opponent` sweep narrowed by `subject_min_life_lost`.
        subject = "each_opponent"
    else:
        subject = _VILLAINOUS_SUBJECTS.get(m.group("subj").lower())
    if subject is None:
        return None
    opts = m.group("opts").strip()
    # Split on ", or " — try each occurrence, accept the partition where
    # both halves are modelable (option bodies can carry internal commas).
    parts = [i for i in range(len(opts)) if opts[i:i + 5].lower() == ", or "]
    for cut in parts:
        a_specs = _villainous_option_specs(opts[:cut])
        b_specs = _villainous_option_specs(opts[cut + 5:])
        if a_specs and b_specs:
            params: dict = {
                "subject": subject,
                "option_a": a_specs,
                "option_b": b_specs,
            }
            if min_life_lost is not None:
                params["subject_min_life_lost"] = int(min_life_lost)
            return [EffectSpec("face_villainous_choice", params)]
    return None


# "Bolster N." (RULE 701.39a) — put N +1/+1 counters on a least-toughness
# creature you control (your choice on a tie). `RulesEngine.bolster` /
# `effects.BolsterEffect` (registered as ``bolster``) own the procedure and
# the tie-break choice.
def _bolster(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bolster", {"amount": int(m.group("n"))})]


# "Bolster X, where X is `<quantity>`." (PAR-29) — PAR-120: the quantity is
# read by the shared amount vocabulary (`count_phrase.parse_amount_phrase`).
def _bolster_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    selector = parse_amount_phrase(m.group("selector"))
    if selector is None:
        return None
    return [EffectSpec("bolster", {"amount_from_count_selector": selector})]


# "Blight N." (Bloomburrow — "put N -1/-1 counters on a creature you
# control"). `RulesEngine.blight` / `effects.BlightEffect` (registered as
# ``blight``). Only the standalone-verb form ("whenever ~ attacks, blight
# 1", "draw a card and blight 1"). The *cost* forms — "{cost}, Blight N:
# <effect>" and "as an additional cost … blight N" — and the "you may
# blight N. If you do, <effect>" pay-cost-then wrapper stay UNMODELED
# (they need `ActivationCost`/cast-cost integration, not an effect). "blight
# X" (Soul Immolation, a dynamic amount) also stays UNMODELED, fail-closed.
def _blight(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("blight", {"amount": int(m.group("n"))})]


# "Airbend [up to N] [other] target `<X>` [you control]." (RULE 701.65,
# Avatar: The Last Airbender — "Exile it. While it's exiled, its owner may
# cast it for {2} rather than its mana cost."). Reuses `ExileEffect`'s
# existing `grant_owner_play_permission` (→ `GameState.exile_cast_
# condition`) plus `owner_play_permission_cost` ("{2}" → `GameState.exile_
# cast_cost_override`, consulted by `GameEngine.effective_cast_cost`).
# "airbend that creature" (a trigger-subject pronoun — Monk Gyatso) is the
# sibling `_AIRBEND_TRIGGER_SUBJECT_RE` below; "airbend … creature or spell"
# (exile off the stack — Aang, Swift Savior) stays UNMODELED, fail-closed.
_AIRBEND_TARGET_CAP = 10  # "any number of" — the shared `_ANY_NUMBER_TARGET_CAP` sentinel
_AIRBEND_RE = compile_clause(
    r"airbend "
    r"(?:(?:up to |exactly )?(?P<n>\d+) |(?P<any>any number of )?)"
    r"(?:(?P<other>other|another) )?"
    r"target (?P<what>nonland permanent|creature)s?"
    r"(?P<yc> you control)?"
    r"(?P<orspell> or spell)?"
)


def _airbend(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    base = "nonland_permanent" if m.group("what") == "nonland permanent" else "creature"
    params: dict[str, Any] = {
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
        # RULE 701.6x: mark this exile as an airbend so `ExileEffect` fires
        # `EventType.BENT` (Avatar Aang's "whenever you … airbend" trigger).
        "bend_kind": "airbend",
    }
    if m.group("orspell"):
        # "airbend up to one other target creature or spell" (Aang, Swift
        # Savior) — airbending a *spell* exiles it off the stack (RULE
        # 400.1, `RulesEngine.move_spell_off_stack`) and grants the same
        # owner-recast-for-{2} permission. Reuses the MEC-43 `spell_or_
        # creature` targeting union; `spell_or_permanent` tells `ExileEffect`
        # to take the stack path when the chosen target is a live spell.
        if base != "creature":
            return None  # fail closed — only "creature or spell" is a real template
        params["target_kind"] = "spell_or_creature"
        params["spell_or_permanent"] = True
    elif m.group("yc"):
        # "another target creature you control" → the source-excluding kind;
        # "target creature you control" → the plain one (which now *includes*
        # the source, per the cEDH-cube fix).
        params["target_kind"] = (
            "other_creature_you_control"
            if (base == "creature" and m.group("other"))
            else f"{base}_you_control"
        )
    else:
        # "another target creature" (no "you control") ≈ "target creature":
        # this engine's `targeting.py` already excludes the effect's own
        # source from a plain creature/permanent pick, and airbend's source
        # is usually a spell or an ETB'ing creature anyway.
        params["target_kind"] = base
    if m.group("any"):
        params["count"] = _AIRBEND_TARGET_CAP
        params["optional"] = True
    elif m.group("n") is not None:
        params["count"] = int(m.group("n"))
        params["optional"] = True  # "up to N" / "exactly N" both read as N here
    return [EffectSpec("exile", params)]


#: "airbend that creature / that permanent / it" — a trigger-subject
#: pronoun (Monk Gyatso: "Whenever another creature you control becomes the
#: target of a spell or ability, you may airbend that creature."). Reuses
#: `ExileEffect`'s `target_kind="trigger_subject"` (MEC-38), which reads
#: the firing event's own `instance_id`; the airbend permission params ride
#: along unchanged. The "you may" is peeled by the BECOMES_TARGET dispatch
#: (`peel_optional`), so this only claims the bare verb.
_AIRBEND_TRIGGER_SUBJECT_RE = compile_clause(
    r"airbend (?:that creature|that permanent|it)"
)


def _airbend_trigger_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {
        "target_kind": "trigger_subject",
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
        "bend_kind": "airbend",  # RULE 701.6x — see `_airbend`
    })]


# "Earthbend N." (RULE 701.66, Avatar: The Last Airbender — "target land you
# control becomes a 0/0 creature with haste that's still a land. Put N +1/+1
# counters on it."). `RulesEngine.earthbend` / `effects.EarthbendEffect`
# (registered as ``earthbend``). Only the literal ``earthbend N`` form; the
# "then untap that land" pronoun tail stays UNMODELED, fail-closed.
def _earthbend(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("earthbend", {"amount": int(m.group("n"))})]


#: "Earthbend X, where X is **that creature's power**." (PAR-30 — Beifong's
#: Bounty Hunters, on a "whenever a nonland creature you control dies"
#: trigger). "that creature" is the dying creature; `EarthbendEffect.
#: amount_from_trigger_event="power"` reads the DIES event's RULE 400.7
#: last-known-power snapshot (`damage_death_mixin`). Deliberately anchored
#: on "that creature's power" so it only claims the dying-subject shape;
#: "its power" / "that creature's toughness" / other reads stay UNMODELED.
_EARTHBEND_THAT_CREATURES_POWER_RE = compile_clause(
    r"(?:you )?earthbend x, where x is that creature's power"
)


def _earthbend_that_creatures_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("earthbend", {"amount_from_trigger_event": "power"})]


#: "Earthbend X, where X is [twice] the number of `<count>`." (PAR-30 —
#: Rockalanche "forests you control", The Boulder, Ready to Rumble
#: "creatures you control with power 4 or greater", Bumi's Feast Lecture
#: "twice the number of Foods you control"). A small self-contained count
#: vocabulary (rather than reusing `subgrammars.DEVOTION`, whose
#: `count_subtype` group would mis-read a *land* subtype like "forests" as
#: a creature type) onto `continuous.count_selector`'s existing entries.
_EARTHBEND_X_SUBTYPE_SELECTORS: dict[str, str] = {
    "forests": "lands_you_control_of_type_forest",
    "islands": "lands_you_control_of_type_island",
    "swamps": "lands_you_control_of_type_swamp",
    "mountains": "lands_you_control_of_type_mountain",
    "plains": "lands_you_control_of_type_plains",
    "foods": "foods_you_control",
}
_EARTHBEND_X_RE = compile_clause(
    r"(?:you )?earthbend x, where x is (?P<mult>twice )?the number of (?:"
    r"(?P<ebsub>" + "|".join(_EARTHBEND_X_SUBTYPE_SELECTORS) + r") you control"
    r"|creatures you control with power (?P<ebpow_n>\d+) or (?P<ebpow_cmp>less|greater)"
    r"|(?P<ebbare>creatures|permanents|artifacts|lands|enchantments) you control"
    r")"
)


def _earthbend_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    sub = m.groupdict().get("ebsub")
    if sub:
        selector = _EARTHBEND_X_SUBTYPE_SELECTORS[sub]
    elif m.groupdict().get("ebpow_n"):
        op = "le" if m.group("ebpow_cmp") == "less" else "ge"
        selector = f"creatures_you_control_with_power_{op}_{m.group('ebpow_n')}"
    elif m.groupdict().get("ebbare"):
        selector = f"{m.group('ebbare')}_you_control"
    else:
        return None  # fail closed — an X phrasing we don't model
    params: dict[str, Any] = {"amount_from_count_selector": selector}
    if m.groupdict().get("mult"):
        params["amount_multiplier"] = 2
    return [EffectSpec("earthbend", params)]


# "Support N." (RULE 701.41a) — put a +1/+1 counter on each of up to N
# target creatures. Needs no effect of its own: it's the exact spec shape
# `_add_counters_multi_target` already emits for "put a +1/+1 counter on
# each of up to two target creatures", so it rides the existing
# `add_counters` multi-target path. RULE 701.41c ("a creature's own support
# can't put a counter on itself") falls out for free — `targeting`'s plain
# ``"creature"`` kind already excludes the ability's source. Literal N only.
def _support(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": "+1/+1", "target_kind": "creature",
        "target_count": int(m.group("n")), "optional": True,
    })]


# "Support X." (PAR-29, Blitzball Stadium/The Crowd Goes Wild) — the same
# alias, X read off the spell/ability's own announced {X}
# (`TargetSpec.count_selector="source_x_paid"`) rather than a literal N.
def _support_x(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": 1, "kind": "+1/+1", "target_kind": "creature",
        "target_count_selector": "source_x_paid", "optional": True,
    })]


# "Goad all creatures your opponents control." / "…you don't control." — the
# untargeted mass form (RULE 601.2c), the same selector shape
# `_tap_selector`/`_add_counters_selector` use.
def _goad_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"selector": "creatures_opponents_control"})]


# "For each opponent, goad up to one target creature that player controls."
# (RULE 601.2c — 4 cards: Sontaran General, Havoc Eater, Baldur's Gate
# Wilderness, and the same clause inside Dungeon room text). One requirement
# whose *count* is the number of opponents, not N separate requirements: the
# "that player" half is RULE 115's already-modeled `distinct_controllers`
# constraint, applied by `GoadEffect` when it sees this selector.
def _goad_per_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "goad",
            {
                "target_kind": "creature_you_dont_control",
                "optional": True,
                "count_selector": "opponents",
            },
        )
    ]


# "Goad up to X target creatures your opponents control." (Death Kiss) — the
# other dynamic count: X is the monstrosity this same permanent just
# announced (RULE 701.37c lets another ability refer to it), which
# `GameObject.monstrosity_x` records for exactly this.
def _goad_up_to_x(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "goad",
            {
                "target_kind": "creature_you_dont_control",
                "optional": True,
                "count_selector": "source_monstrosity_x",
            },
        )
    ]
#: "~ becomes a copy of [another] target `<creature|permanent>`[ until end of turn][, except `<tail>`]" (Cursed
#: Mirror, Shameless Charlatan, Cryptoplasm — "…you may have ~ become…" after `peel_optional`). PAR-142 added the
#: copy's own "except …" clause: "it has this ability" keeps the object's own abilities; the rest is the same
#: type/keyword/legendary vocabulary an enter-as-copy replacement reads (`static_handlers.enter_as_copy_tail`).
_BECOME_COPY_RE = compile_clause(
    r"(?:(?:you may )?have )?~ becomes? a copy of (?:another )?target (?P<what>creature|permanent)"
    r"(?P<eot> until end of turn)?(?:,? except (?P<tail>.+))?"
)


def _become_copy_of_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:

    params: dict = {"target_kind": m.group("what").lower()}
    tail = m.group("tail")
    if tail:
        keep_own = re.search(r"(?:,\s*(?:and\s+)?|\s+and\s+)?\bit has this ability\b", tail)
        if keep_own is not None:
            params["keep_own_abilities"] = True
            tail = (tail[: keep_own.start()] + tail[keep_own.end():]).strip(" ,.")
        if tail:
            extra = enter_as_copy_tail(tail)
            if extra is None or "extra_counters_from_x" in extra:
                return None
            params.update(extra)
    return [EffectSpec(
        "become_copy_until_eot" if m.group("eot") else "become_copy_permanent", params,
    )]


ROWS: list[EffectHandler] = [
    # "scry 2" (RULE 701.18) / "surveil 2" (RULE 701.31) — both a self effect
    # (the controller scries/surveils), same grammar, one handler.
    EffectHandler(
        "scry_or_surveil",
        compile_clause(r"(?:you )?(?P<verb>scry|surveil) (?P<n>\d+|x)"),
        _scry_or_surveil,
    ),
    # "fateseal N" (RULE 701.29a) — scry aimed at an opponent's library.
    EffectHandler(
        "fateseal",
        compile_clause(rf"(?:you )?fateseal {NUMBER}"),
        _fateseal,
    ),
    # "heal all damage from ~ / each creature you control" (RULE 701.69a).
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_mec78_heal.py (the heal clause form).
    EffectHandler(
        "heal",
        _HEAL_RE,
        _heal,
    ),
    # "if you both own and control ~ and a … named X, exile them, then meld
    # them into Y" (RULE 701.42a) — a meld card's activated-ability body.
    EffectHandler(
        "meld",
        _MELD_BODY_RE,
        _meld,
    ),
    EffectHandler(
        "look_top_reorder",
        _LOOK_TOP_REORDER_RE,
        _look_top_reorder,
    ),
    EffectHandler(
        "unlock_door",
        compile_clause(
            r"(?:(?P<lock>lock or unlock a door)|unlock a locked door) of "
            r"(?:(?P<upto>up to 1 )?(?P<target>target room you control)|a room you control)"
        ),
        _unlock_door,
    ),
    # "venture into the dungeon" (RULE 701.49) / "venture into Undercity"
    # (RULE 701.49d).
    EffectHandler(
        "venture",
        compile_clause(r"venture into (?P<dungeon>the dungeon|undercity)"),
        _venture,
    ),
    # "monstrosity 3" / "monstrosity x" (RULE 701.37a).
    EffectHandler(
        "monstrosity",
        compile_clause(r"monstrosity (?P<n>x|\d+)"),
        _monstrosity,
    ),
    # "adapt 2" (RULE 701.46a).
    EffectHandler(
        "adapt",
        compile_clause(rf"adapt {NUMBER}"),
        _adapt,
    ),
    # "harness ~" (MEC-79 / RULE 701.64a) — designation flip, no amount.
    EffectHandler(
        "harness",
        compile_clause(r"harness (?:~|this permanent)"),
        _harness,
    ),
    # "~ connives[ X]" (RULE 701.50a/d) — explicit self reference
    # (activated-ability body / self-subject trigger with the name kept).
    EffectHandler(
        "connive_self_named",
        compile_clause(rf"~ connives?{_CONNIVE_AMOUNT}"),
        _connive,
    ),
    # "it connives[ X]" / "he connives" / "she connives" — the self-subject
    # trigger pronoun; only offered when the body's "it" really is the source
    # (`self_subject_only`), never an earlier clause's pick.
    EffectHandler(
        "connive_self_pronoun",
        compile_clause(rf"(?:it|he|she) connives?{_CONNIVE_AMOUNT}"),
        _connive,
        self_subject_only=True,
    ),
    # "that creature connives" — the previous-clause pronoun ("target
    # creature you control gains menace. That creature connives.").
    EffectHandler(
        "connive_previous",
        compile_clause(rf"(?:it|that creature) connives?{_CONNIVE_AMOUNT}"),
        _connive_previous,
        previous_subject_only=True,
    ),
    # "each of x target creatures you control connive" (Change of Plans).
    EffectHandler(
        "connive_each_x",
        compile_clause(r"each of x target creatures you control connive"),
        _connive_each_x,
    ),
    # "target creature [you control/an opponent controls] connives[ X]"
    # (RULE 601.2c targeting on 701.50a/d).
    EffectHandler(
        "connive_target",
        compile_clause(rf"{TARGET} connives?{_CONNIVE_AMOUNT}"),
        _connive_target,
    ),
    # "recruit" (RULE 701.70a) — bare word (an ETB/attack trigger's whole body).
    EffectHandler(
        "recruit",
        compile_clause(r"recruit"),
        _recruit,
    ),
    # "learn" (RULE 701.48a) — bare word (spell effect / ETB / dies / cost body).
    EffectHandler(
        "learn",
        compile_clause(r"learn"),
        _learn,
    ),
    # "you may collect evidence N" (RULE 701.59a) — bare, no "if you do" rider.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par29_collect_evidence.py (clause form; the printed cards use the costed rows).
    EffectHandler(
        "collect_evidence_bare",
        compile_clause(r"you may collect evidence (?P<n>\d+)"),
        _collect_evidence_bare,
    ),
    # bare "collect evidence N" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "collect_evidence",
        compile_clause(r"collect evidence (?P<n>\d+)"),
        _collect_evidence,
    ),
    # "you may forage" (RULE 701.61a) — bare, no "if you do" rider.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par29_forage.py (clause form; the printed cards use the costed rows).
    EffectHandler(
        "forage_bare",
        compile_clause(r"you may forage"),
        _forage_bare,
    ),
    # bare "forage" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "forage",
        compile_clause(r"forage"),
        _forage,
    ),
    # "discover 3" (RULE 701.57a) — literal mana value only.
    EffectHandler(
        "discover",
        compile_clause(r"discover (?P<n>\d+)"),
        _discover,
    ),
    # Tried before `discover_spell_mv` below: when the preceding clause
    # countered a spell, this reads the right referent; when it didn't
    # (a genuine cast trigger), the gate skips this row and falls through.
    EffectHandler(
        "discover_spell_mv_previous_target",
        compile_clause(r"discover x, where x is that spell'?s mana value"),
        _discover_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "discover_spell_mv",
        compile_clause(r"discover x, where x is that spell'?s mana value"),
        _discover_spell_mv,
    ),
    EffectHandler(
        "draw_spell_mv_previous_target",
        compile_clause(r"draws? cards? equal to that spell'?s mana value"),
        _draw_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "create_token_xx_spell_mv_previous_target",
        _CREATE_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE,
        _create_token_xx_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    EffectHandler(
        "create_named_token_xx_spell_mv_previous_target",
        _CREATE_NAMED_TOKEN_XX_SPELL_MV_PREVIOUS_TARGET_RE,
        _create_named_token_xx_spell_mv_previous_target,
        previous_subject_only=True,
    ),
    # "target creature [you control] explores" (RULE 701.44) — before the
    # bare/pronoun rows so its TARGET isn't stolen by a looser match.
    EffectHandler(
        "explore_target",
        compile_clause(rf"{TARGET} explores"),
        _explore_target,
    ),
    # "~ explores" — explicit self (activated body / self-subject trigger
    # with the name kept, "when ~ enters, ~ explores").
    EffectHandler(
        "explore_self_named",
        compile_clause(r"~ explores"),
        _explore_self,
    ),
    # "it explores" / "he explores" / "she explores" — self-subject trigger
    # pronoun ("when ~ enters, it explores").
    EffectHandler(
        "explore_self_pronoun",
        compile_clause(r"(?:it|he|she) explores"),
        _explore_self,
        self_subject_only=True,
    ),
    # "that creature explores" — a creature an earlier clause of this same
    # resolution chose ("return target creature card … that creature
    # explores", Defossilize's first half).
    EffectHandler(
        "explore_previous",
        compile_clause(r"(?:it|that creature) explores"),
        _explore_previous,
        previous_subject_only=True,
    ),
    # "target creature you control endures N" (RULE 701.63a) — before the
    # bare/pronoun rows so its TARGET isn't stolen.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par29_endure.py (subject-shape coverage of the RULE 701.63 endure verb).
    EffectHandler(
        "endure_target",
        compile_clause(rf"{TARGET} endures (?P<n>\d+)"),
        _endure_target,
    ),
    # "~ endures N" — explicit self ("when ~ enters, ~ endures 3").
    EffectHandler(
        "endure_self_named",
        compile_clause(r"~ endures (?P<n>\d+)"),
        _endure_self,
    ),
    # "~ endures x" (PAR-29, Krumar Initiate) — X is this activated
    # ability's own announced {X}.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par29_endure.py (subject-shape coverage of the RULE 701.63 endure verb).
    EffectHandler(
        "endure_self_named_x",
        compile_clause(r"~ endures x"),
        _endure_self_x,
    ),
    # "it endures N" / "he/she endures N" — self-subject trigger pronoun.
    EffectHandler(
        "endure_self_pronoun",
        compile_clause(r"(?:it|he|she) endures (?P<n>\d+)"),
        _endure_self,
        self_subject_only=True,
    ),
    # "it endures N" / "that creature endures N" — a previous clause's pick.
    # PAR-169 (kept): no card in the pool reaches this row; covered by tests/test_par29_endure.py (subject-shape coverage of the RULE 701.63 endure verb).
    EffectHandler(
        "endure_previous",
        compile_clause(r"(?:it|that creature) endures (?P<n>\d+)"),
        _endure_previous,
        previous_subject_only=True,
    ),
    # "populate" (RULE 701.36a) — copy a creature token you control.
    EffectHandler(
        "populate",
        compile_clause(r"populate"),
        _populate,
    ),
    # "populate x times" (RULE 701.36a, Full Flowering).
    EffectHandler(
        "populate_x_times",
        compile_clause(r"populate x times"),
        _populate_x_times,
    ),
    # "clash with an opponent" / "clash with defending player" (RULE 701.30).
    EffectHandler(
        "clash",
        compile_clause(r"clash with (?:an opponent|defending player)"),
        _clash,
    ),
    # "flip a coin" / "flip 3 coins" / "flip a coin until you lose a flip" (RULE 705).
    EffectHandler("coin_flip", _COIN_FLIP_RE, _coin_flip),
    EffectHandler("coin_flip_each", _COIN_EACH_RE, _coin_each),
    EffectHandler("coin_flip_delayed", _COIN_DELAYED_RE, _coin_delayed),
    EffectHandler("coin_flip_reflexive", _COIN_REFLEXIVE_RE, _coin_reflexive),
    # "roll a d20" / "roll a six-sided die" / "roll two d6" (RULE 706.1).
    EffectHandler(
        "roll_die",
        _ROLL_DIE_RE,
        _roll_die,
    ),
    # MEC-90: non-pump bodies whose amount is a preceding die-roll result.
    EffectHandler("gain_life_die_result", _GAIN_LIFE_DIE_RESULT_RE, _gain_life_die_result),
    EffectHandler("draw_die_result", _DRAW_DIE_RESULT_RE, _draw_die_result),
    EffectHandler(
        "no_max_hand_size_rest_of_game", _NO_MAX_HAND_SIZE_REST_OF_GAME_RE,
        _no_max_hand_size_rest_of_game,
    ),
    EffectHandler(
        "create_named_token_die_result", _CREATE_NAMED_TOKEN_DIE_RESULT_RE,
        _create_named_token_die_result,
    ),
    EffectHandler(
        "create_creature_token_die_result", _CREATE_CREATURE_TOKEN_DIE_RESULT_RE,
        _create_creature_token_die_result,
    ),
    EffectHandler("add_counters_die_result", _ADD_COUNTERS_DIE_RESULT_RE, _add_counters_die_result),
    EffectHandler(
        "return_creatures_die_result", _RETURN_CREATURES_DIE_RESULT_RE,
        _return_creatures_die_result,
    ),
    # MEC-50: Clash win/otherwise-branch bodies (RULE 701.30d).
    EffectHandler(
        "mill_prev_spell_controller",
        _MILL_PREV_SPELL_CONTROLLER_RE,
        _mill_prev_spell_controller,
    ),
    EffectHandler(
        "that_player_discards",
        _THAT_PLAYER_DISCARDS_RE,
        _that_player_discards,
    ),
    EffectHandler(
        "gain_control_attached",
        _GAIN_CONTROL_ATTACHED_RE,
        _gain_control_attached,
    ),
    EffectHandler(
        "clashed_opp_creatures_no_untap",
        _CLASHED_OPP_CREATURES_NO_UNTAP_RE,
        _clashed_opp_creatures_no_untap,
    ),
    # "planeswalk" / "chaos ensues" (RULE 901.10 / 901.13) — Planechase
    # vote outcome bodies (Path of the Animist/Enigma) + standalone.
    EffectHandler("planeswalk", compile_clause(r"planeswalk"), _planeswalk),
    EffectHandler("chaos_ensues", compile_clause(r"chaos ensues"), _chaos_ensues),
    # "take an extra turn after this one" (RULE 500.7) — plain Time Walk body.
    EffectHandler(
        "take_extra_turn",
        _TAKE_EXTRA_TURN_RE,
        _take_extra_turn,
    ),
    # "you control target opponent/player during that player's next
    # turn / combat phase" (RULE 720, MEC-51).
    EffectHandler("control_player", _CONTROL_PLAYER_RE, _control_player),
    # "starting with you, each player votes for A or B. if A gets more
    # votes, X. if B gets more votes or the vote is tied, Y." (RULE 701.38,
    # PAR-29) — the 2-option majority form. Tried before the per-vote form
    # below since its "if … gets more votes" tail is more specific.
    EffectHandler(
        "vote_majority",
        _VOTE_HEADER_RE,
        _vote_majority,
    ),
    # MEC-46 — "each player votes for <colours>. ~ gains protection from
    # each color with the most votes or tied for most votes." (Council
    # Guardian). Before the per-vote form since that one fail-closes on a
    # 3+-option vote anyway.
    EffectHandler(
        "vote_winner_protection",
        _VOTE_HEADER_RE,
        _vote_winner_protection,
    ),
    # MEC-46 — "each player votes for a nonland permanent you don't control
    # / a card in your graveyard. Exile / return each <object> …" (Council's
    # Judgment, Custodi Squire) — a tally over objects.
    EffectHandler(
        "vote_object",
        _VOTE_HEADER_RE,
        _vote_object,
    ),
    # MEC-46 — Expropriate: "For each time vote, take an extra turn … . For
    # each money vote, choose a permanent owned by the voter and gain
    # control of it. Exile ~." Before the generic per-vote form (whose
    # "<body> for each <opt> vote" order is the reverse of Expropriate's).
    EffectHandler(
        "vote_expropriate",
        _VOTE_HEADER_RE,
        _vote_expropriate,
    ),
    # "starting with you, each player votes for A or B. <body1> for each A
    # vote[ and <body2> for each B vote]." (RULE 701.38, PAR-29) — the
    # per-vote scaling form.
    EffectHandler(
        "vote_per_vote",
        _VOTE_HEADER_RE,
        _vote_per_vote,
    ),
    # MEC-46 (RULE 701.38f) — "You choose how each player votes this turn."
    # (Illusion of Choice).
    EffectHandler(
        "forced_vote",
        compile_clause(r"you choose how each player votes this turn"),
        _forced_vote,
    ),
    # "<player> faces a villainous choice — <A>, or <B>." (RULE 701.55,
    # PAR-29) — each facing player applies their own pick.
    EffectHandler(
        "face_villainous_choice",
        _VILLAINOUS_HEADER_RE,
        _face_villainous_choice,
    ),
    # "incubate X, where X is <count>" / "incubate X twice, where X is …"
    # (PAR-30) — tried before the plain-N row below (its regex would not
    # match "incubate x" anyway, but keep the dynamic form first by
    # convention).
    EffectHandler(
        "incubate_x",
        _INCUBATE_X_RE,
        _incubate_x,
    ),
    # "incubate N" / "you incubate N" (RULE 701.53).
    EffectHandler(
        "incubate",
        compile_clause(r"(?:you )?incubate (?P<n>\d+)"),
        _incubate,
    ),
    # "time travel" (RULE 701.56, Doctor Who) — remove a time counter from
    # each suspended card you own / add one to each Vanishing-style
    # permanent you control. "time travel, then time travel" is two of
    # these from `parse_effect_body`'s ", then" split.
    EffectHandler(
        "time_travel",
        compile_clause(r"(?:you )?time travel"),
        lambda _m: [EffectSpec("time_travel", {})],
    ),
    # "bolster N" (RULE 701.39a) — N +1/+1 counters on a least-toughness
    # creature you control.
    EffectHandler(
        "bolster",
        compile_clause(r"bolster (?P<n>\d+)"),
        _bolster,
    ),
    # "bolster x, where x is <board count>" (PAR-29).
    EffectHandler(
        "bolster_x",
        compile_clause(r"bolster x, where x is (?P<selector>.+)"),
        _bolster_x,
    ),
    # "blight N" (Bloomburrow) — N -1/-1 counters on a creature you control.
    EffectHandler(
        "blight",
        compile_clause(r"blight (?P<n>\d+)"),
        _blight,
    ),
    # "earthbend X, where X is [twice] the number of <count>" (PAR-30) —
    # tried before the plain-N row (its regex needs a digit, so no overlap).
    EffectHandler(
        "earthbend_x",
        _EARTHBEND_X_RE,
        _earthbend_x,
    ),
    # "earthbend X, where X is that creature's power" (PAR-30, Beifong's
    # Bounty Hunters) — the dying-subject read; also digit-free, no overlap.
    EffectHandler(
        "earthbend_that_creatures_power",
        _EARTHBEND_THAT_CREATURES_POWER_RE,
        _earthbend_that_creatures_power,
    ),
    # "earthbend N" (RULE 701.66, Avatar: TLA) — target land you control
    # becomes a 0/0 haste creature that's still a land + N +1/+1 counters.
    EffectHandler(
        "earthbend",
        compile_clause(r"(?:you )?earthbend (?P<n>\d+)"),
        _earthbend,
    ),
    # "airbend that creature / it" (RULE 701.65) — a trigger-subject pronoun
    # (Monk Gyatso). Before the targeted row: "that creature" has no "target".
    EffectHandler(
        "airbend_trigger_subject",
        _AIRBEND_TRIGGER_SUBJECT_RE,
        _airbend_trigger_subject,
    ),
    # "airbend [up to N] [other] target <X> [you control]" (RULE 701.65,
    # Avatar: TLA) — exile it, its owner may cast it from exile for {2}.
    EffectHandler(
        "airbend",
        _AIRBEND_RE,
        _airbend,
    ),
    # "support N" (RULE 701.41a) — +1/+1 counter on each of up to N target
    # creatures (rides the existing `add_counters` multi-target path).
    EffectHandler(
        "support",
        compile_clause(r"support (?P<n>\d+)"),
        _support,
    ),
    # "support x" (PAR-29) — X is the spell/ability's own announced {X}.
    EffectHandler(
        "support_x",
        compile_clause(r"support x"),
        _support_x,
    ),
    # "goad all creatures your opponents control" (RULE 701.15a) — the mass
    # form first: the targeted row below can't match it (no "target"), but
    # the mass one is the more specific phrase and reads better up here.
    EffectHandler(
        "goad_selector",
        compile_clause(r"goad all creatures (?:your opponents control|you don't control)"),
        _goad_selector,
    ),
    # "for each opponent, goad up to one target creature that player
    # controls" — a per-opponent requirement (RULE 601.2c). Before the plain
    # `goad` row, whose `TARGET` would otherwise claim the tail and silently
    # goad exactly one creature.
    EffectHandler(
        "goad_per_opponent",
        compile_clause(
            r"for each opponent, goad up to 1 target creature "
            r"that (?:player|opponent) controls"
        ),
        _goad_per_opponent,
    ),
    # "goad up to X target creatures your opponents control" (Death Kiss).
    EffectHandler(
        "goad_up_to_x",
        compile_clause(r"goad up to x target creatures (?:your opponents control|you don't control)"),
        _goad_up_to_x,
    ),
    # "goad target creature **that player** controls" (Popular Entertainer's
    # granted trigger, PAR-32 — "that player" = whoever the firing
    # `CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` event named). Tried before
    # the generic `goad {TARGET}` row, whose `resolve_target_kind` doesn't
    # know this event-scoped phrase.
    EffectHandler(
        "goad_that_player",
        compile_clause(r"goad target creature that player controls"),
        lambda m: [EffectSpec("goad", {"target_kind": "creature_that_player_controls"})],
    ),
    # RULE 605.1b: "[that player] add(s) one mana of any type that land produced" (Mana
    # Flare, Mirari's Wake, PAR-119) — the type is read off the firing `TAPPED_FOR_MANA`
    # event's ``produced``; "that player" is whoever tapped the land.
    EffectHandler(
        "mirror_produced_mana",
        compile_clause(r"(?P<that>that player adds|add) 1 mana of any type that (?:land|permanent) produced"),
        lambda m: [EffectSpec("mirror_produced_mana", {
            "count": 1,
            **({"player": {"of": "event_player", "as": "controller"}}
               if m.group("that").startswith("that") else {}),
        })],
    ),
    # "~ becomes a copy of [another] target creature[ until end of turn]."
    # (Cursed Mirror's EOT form; Shameless Charlatan's granted permanent
    # form, PAR-32) — the "another" is enforced by the effect's own
    # `target is self.source` guard, so no distinct target kind is needed.
    EffectHandler(
        "become_copy_of_target",
        _BECOME_COPY_RE,
        _become_copy_of_target,
    ),
]
