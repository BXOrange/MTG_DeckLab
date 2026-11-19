"""Static-ability helpers: self statics (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ...spec import EffectSpec
from ..replacements import REPLACEMENT_CLAUSE_EFFECT_TYPES, replacement_clause_specs
from ..subgrammars import DEVOTION
from ..clause_hooks import static_effect_specs, trigger_condition_dict
from ..count_phrase import parse_amount_phrase, parse_count_phrase
from ..trigger_doubler import parse_trigger_doubler
from .object_scope import object_filter
from .combat_restrictions import ATTACHED_SUBJECT_PATTERN, permission_tail_params
from .keyword_flags import DURING_YOUR_TURN_TRAILING_KEYWORD_RE, flag_keywords
from .granted_abilities import type_addition_params
from .static_conditions import (
    AS_LONG_AS_LEADING_RE,
    AS_LONG_AS_TRAILING_RE,
    attached_pronoun_characteristic,
    attached_state_condition,
    pronoun_attached_condition,
    static_condition,
)

#: "During your turn, <static>." (ENG-28, RULE 613.6's other common gate
#: phrasing besides "as long as" — Ahn-Crop Invader/Blood Burglar/Grand
#: Abolisher-shaped, 156 solo-blocked cards cache-wide). Fixed to the
#: ``your_turn`` condition rather than routed through `static_condition`,
#: since the phrase itself is the whole condition — there's no separate
#: ``cond``/``inner`` split to parse a *kind* out of. Leading-only: every
#: sampled card prints the gate first, and a trailing "…during your turn."
#: form risks colliding with an "activate only during your turn" *activation*
#: timing restriction (a different, `condition_query.py` concept) if ever
#: added later, so that form is deliberately not claimed here.
#: "During turns other than yours, `<static>`" (Mesa Lynx, Glory of Warfare, Warden of the Wall) is the same gate with the
#: opposite polarity (`not_your_turn`).
#: "~ is a 2/3 Gargoyle artifact creature with flying" / "~ is an artifact creature" — the gated self-animation of
#: Warden of the Wall and Midnight Mangler, a layer-4 `type_change` (with the base P/T when printed) plus a keyword
#: grant. Only reachable from under a "during …" gate: ungated, the same words would be a printed characteristic.
_SELF_ANIMATION_RE = re.compile(
    r"~ is an? (?:(?P<p>\d+)/(?P<t>\d+) )?(?P<words>[a-z]+(?: [a-z]+)*? creature)(?: with (?P<kw>[a-z]+(?:, [a-z]+)*))?",
    re.IGNORECASE,
)


def _self_animation_specs(text: str) -> Optional[list[EffectSpec]]:
    m = _SELF_ANIMATION_RE.fullmatch(text.strip().rstrip("."))
    if m is None:
        return None
    type_params = type_addition_params(m.group("words"))
    if type_params is None or "creature" not in type_params.get("add_types", []):
        return None
    if (m.group("p") is None) != (m.group("t") is None):
        return None
    if m.group("p") is not None:
        type_params = {**type_params, "power": int(m.group("p")), "toughness": int(m.group("t"))}
    specs = [EffectSpec("type_change", {"affects": "self", **type_params})]
    if m.group("kw"):
        keywords = flag_keywords(m.group("kw"))
        if keywords is None:
            return None
        specs.append(EffectSpec("grant_keyword", {"affects": "self", "keywords": keywords}))
    return specs


_DURING_YOUR_TURN_LEADING_RE = re.compile(
    r"during (?P<which>your turn|turns other than yours|each opponent'?s end step),\s*(?P<inner>.+)", re.IGNORECASE
)


#: "~ gets +N/+N [and has <keywords>]" / "~ has <keywords>" — the **self**
#: -scoped anthem/grant, `ATTACHED_ANTHEM_RE`'s sibling for a permanent
#: talking about itself. Real cards print this shape essentially only inside
#: a RULE 613.6 conditional ("As long as ~ is monstrous, it has trample.") —
#: unconditionally a creature just prints the keyword on its own line — but
#: the rows are written standalone so the conditional wrapper stays a pure
#: wrapper, with no grammar of its own.
#:
#: Both rows accept a trailing combat *permission* ("…and can attack as
#: though it didn't have defender") — the compound MEC-13 shape. It is its
#: own group rather than part of the keyword list because a permission is a
#: `combat_restriction` param entry, not a grantable keyword.
#: The trailing ``, and attacks each combat if able`` on ``SELF_ANTHEM_RE``
#: (RULE 702.137 Delirium's own compound shape — "~ gets +2/+2, has flying,
#: and attacks each combat if able.", Dragon's Rage Channeler-shaped) is an
#: Oxford-comma third list item, not another " and "-joined clause, so both
#: the ``kw``/``attacks`` separators accept a bare comma as well as " and ".
#: `ATTACKS_IF_ABLE_RE` already proves "attacks each combat if able" is
#: just the synthetic flag keyword ``"attacks_if_able"`` through the *same*
#: `grant_keyword` machinery as "has flying" — no new spec shape, just one
#: more keyword folded into the same list (or its own `grant_keyword` when
#: there's no ``kw`` tail to join).
SELF_ANTHEM_RE = re.compile(
    r"~ gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)"
    r"(?:(?:,\s*|\s+and\s+)has (?P<kw>[a-z][a-z, ]*?))?"
    r"(?:\s+and (?P<perm>can (?:attack|block)[a-z0-9 ']*))?"
    r"(?:(?:,\s*and\s+|,\s*|\s+and\s+)(?P<attacks_if_able>attacks each combat if able))?",
    re.IGNORECASE,
)
#: RULE 202.2f/700.6 "~ gets +X/+X, where X is your devotion to
#: `<colour(s)/wedge/hybrid>`." (Blended Twistling-shaped) — a standing,
#: self-scoped anthem whose amount is `continuous.count_selector`'s
#: `devotion_to_<key>` vocabulary rather than a literal digit, unlike
#: `SELF_ANTHEM_RE` above.
ANTHEM_DEVOTION_SELF_RE = re.compile(
    rf"~ gets? \+x/\+x, where x is {DEVOTION}", re.IGNORECASE,
)
#: PAR-30: "~ gets +P/+T for each `<subtype>` card in your graveyard"
#: (Katara, Seeking Revenge — "+1/+1 for each lesson card in your
#: graveyard"). A standing self-anthem whose per-unit +P/+T scales by
#: `continuous.count_selector`'s `<subtype>_cards_in_your_graveyard` prefix
#: (a live type-line scan). Bounded to a single subtype word so it stays
#: fail-closed for any other "for each" quantity.
SELF_ANTHEM_FOR_EACH_GY_SUBTYPE_RE = re.compile(
    r"~ gets \+(?P<p>\d+)/\+(?P<t>\d+) for each (?P<sub>[a-z][a-z-]+) card in your graveyard",
    re.IGNORECASE,
)

#: PAR-43: "~ gets +P/+T for each `<X>`" — the general standing self-anthem
#: whose per-unit +P/+T scales by a `continuous.count_selector` value
#: (Akiri, Line-Slinger "+1/+0 for each artifact you control"; Adelbert
#: Steiner "+1/+1 for each Equipment you control"; Nemata "+1/+1 for each
#: Saproling…" &c.). ``<X>`` is matched against a fixed whitelist of phrases
#: that **already have a `count_selector`** (`_SELF_ANTHEM_FOR_EACH_
#: SELECTORS` + the `<basic land type> you control` special-case) — any
#: other quantity fails closed, exactly like `PT_CDA_RE` / the GY-subtype
#: row above, since an anthem reading an unmodeled count would silently
#: apply +0. Tried after the GY-subtype row (more specific) and before
#: `SELF_ANTHEM_RE` (whose fixed-digit `[+-]\d+/[+-]\d+` would claim the
#: "+1/+1" prefix and drop the "for each …" scaling).
# RULE 613.4c: the per-unit amount may be negative ("~ gets -1/-1 for each card in your hand" — Dread Slag,
# Geralf's Masterpiece); the signed value multiplies the count each time layer 7c is evaluated.
SELF_ANTHEM_FOR_EACH_RE = re.compile(
    r"~ gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) for each (?P<what>.+?)\.?",
    re.IGNORECASE,
)
#: PAR-43: the attached-permanent sibling of `SELF_ANTHEM_FOR_EACH_RE`
#: ("equipped/enchanted `<subject>` gets +N/+N for each `<X>` [and has
#: `<keywords>`]" — All That Glitters, Cranial Plating, Blanchwood Armor
#: &c.). Shares `_SELF_ANTHEM_FOR_EACH_SELECTORS`/`for_each_count_selector`
#: with the self-scoped row: `affects="attached_permanent"` already makes
#: `continuous._pt_mod_count` evaluate every count against the *affected*
#: creature (RULE 613.7c/604.3's per-object scoping already handles
#: "Equipment/Aura attached to it" correctly for both forms — "it" there is
#: always the creature the anthem currently affects), so only the subject
#: line and the optional keyword tail differ from `ATTACHED_ANTHEM_RE`.
#: Tried before `ATTACHED_ANTHEM_RE` for the same reason
#: `SELF_ANTHEM_FOR_EACH_RE` is tried before `SELF_ANTHEM_RE` — its
#: fixed-digit pattern would otherwise claim the "+1/+1" prefix and drop the
#: "for each …" scaling.
# RULE 107.3c / 613.4c: attached bonuses may define X independently of costs.
ATTACHED_ANTHEM_X_RE = re.compile(
    rf"(?P<subject>~|{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-](?:x|\d+))/(?P<t>[+-](?:x|\d+)), where x is (?P<what>.+?)\.?",
    re.IGNORECASE,
)

ATTACHED_ANTHEM_FOR_EACH_RE = re.compile(
    # RULE 613.4c: a shrinking bonus scales the same way ("enchanted creature gets -1/-1 for each Swamp you control").
    rf"(?P<subject>{ATTACHED_SUBJECT_PATTERN}) gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) for each (?P<what>.+?)"
    # PAR-109: the comma before the grant is optional ("…for each counter on it, and has trample and lifelink.",
    # Luxior and Shadowspear).
    r"(?:,? and has (?P<kw>[a-z][a-z, ]*?))?\.?",
    re.IGNORECASE,
)
#: PAR-120 (PARSER_VERSION 472): 17 of the original 30 entries retired —
#: `for_each_count_selector` tries the shared `count_phrase` grammar first
#: now, and these were exactly the phrases it already covers (verified
#: individually, not assumed; see below for the ones that looked coverable
#: but weren't). What's left is genuinely outside `{zone, of, filter}`:
#: per-object attachment counts (not a zone/filter scope at all), the
#: open-vocabulary "other `<X>`" guesses the grammar's `not_reference`/
#: "another" axis doesn't reach through this entry point, a DFC-state flag,
#: two *player*-level counters (poison/experience — not object counts),
#: Domain, a characteristic-defining self-read ("of its colors"), and RULE
#: 700.8's party bipartite match.
_SELF_ANTHEM_FOR_EACH_SELECTORS: dict[str, str] = {
    # "for each Equipment attached to it" / "for each Aura attached to it" /
    # both at once — the affected creature's *own* attachments (Nemata/Kor
    # Spiritdancer-adjacent), unlike the board-wide "Equipment you control"
    # entry the grammar now reaches.
    "equipment attached to it": "equipment_attached_to_self",
    "aura attached to it": "auras_attached_to_self",
    "aura and equipment attached to it": "equipment_and_auras_attached_to_self",
    "other enchantment on the battlefield": "other_enchantments_on_the_battlefield",
    "other creature you control": "other_creatures_you_control",
    "other artifact you control": "other_artifacts_you_control",
    "transformed permanent you control": "transformed_permanents_you_control",
    "poison counter your opponents have": "poison_counters_opponents_have",
    "experience counter you have": "experience_counters_you_have",
    "dilemma you've faced this turn": "dilemmas_faced_this_turn",  # RULE 700.17
    "opponent you attacked this turn": "opponents_attacked_this_turn",  # Battlefront
    "basic land type among lands you control": "basic_land_types_among_lands_you_control",
    "of its colors": "source_colors_count",
    # PAR-72: "equipped creature gets +1/+0 for each creature in your party
    # and has menace." (Ravager's Mace) — `continuous.count_selector`'s
    # already-shipped `"creatures_in_your_party"` branch (PAR-53).
    "creature in your party": "creatures_in_your_party",
}
def for_each_count_selector(what: str, *, self_form: bool) -> "Optional[str | dict]":
    """Resolve a "for each `<X>`" quantity to a `continuous.count_selector`
    argument (structured or named), shared by `SELF_ANTHEM_FOR_EACH_RE` and
    `ATTACHED_ANTHEM_FOR_EACH_RE`.

    ``self_form`` gates the bare "on it" counter phrasing: in a self-scoped
    clause "it" can only mean ``~`` (the only noun in the sentence,
    Necrosquito's "oil counter on it"), but in an Aura/Equipment's own
    clause "it" is the *equipped/enchanted permanent* — the closer noun —
    not the Aura/Equipment itself (Luxior, Giada's Gift's loyalty-counter
    "for each counter on it" counts counters on the creature it turns into
    a planeswalker, not on Luxior). Only the unambiguous "on ~" is
    recognised for the attached form; "on it" there fails closed rather
    than risk reading the wrong object's counters.
    """
    # Checked *before* the shared grammar: the table's "other `<X>`" rows
    # would otherwise be shadowed by the grammar's `not_reference` reading.
    selector = _SELF_ANTHEM_FOR_EACH_SELECTORS.get(what)
    if selector is not None:
        return selector

    structured = parse_count_phrase(what)
    if structured is not None:
        return structured
    m = re.fullmatch(r"([a-z][a-z]*) counters? on ~", what)
    if m:
        return f"source_{m.group(1)}_counters"
    if what == "counter on ~":
        return "total_counters_on_source"
    if not self_form and what in ("counter on it", "counters on it"):
        # PAR-109 (Luxior, Giada's Gift; Luxior and Shadowspear): in an Aura/Equipment's clause "it" is the
        # equipped/enchanted permanent, so the count is every counter on the creature the bonus applies to.
        return "total_counters_on_affected"
    if self_form:
        m = re.fullmatch(r"([a-z][a-z]*) counters? on it", what)
        if m:
            return f"source_{m.group(1)}_counters"
        if what == "counter on it":
            return "total_counters_on_source"
    return _amount_grammar_selector(what, self_form=self_form)


def _selector_has_key(node: Any, key: str) -> bool:
    """True when ``key`` is a key anywhere in the selector tree (dicts and lists; values are not searched)."""
    if isinstance(node, dict):
        return key in node or any(_selector_has_key(v, key) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_selector_has_key(v, key) for v in node)
    return False


def _amount_grammar_selector(what: str, *, self_form: bool) -> "Optional[str | dict]":
    """PAR-284: the shared amount grammar's reading of a "for each `<X>`" quantity (RULE 613.4c: the static's
    count is re-measured at every layer pass), or ``None``. "on it" names the object the bonus applies to
    outside the self form (RULE 301.5a), so a counter read there is measured on the affected object; a compound
    amount with a per-object pronoun needs per-term referent tracking and stays unclaimed."""
    # The amount grammar spells the count with its "the number of" head and a plural counter noun.
    selector = parse_amount_phrase("the number of " + re.sub(r"\bcounter on\b", "counters on", what, count=1))
    if selector is None:
        return None
    if not self_form and _selector_has_key(selector, "not_reference"):
        return None  # "other" would exclude the Aura / anthem source, not the object the bonus applies to
    if isinstance(selector, dict) and "terms" in selector and re.search(r"\b(?:on|of|attached to) it\b", what):
        return None
    if isinstance(selector, dict) and selector.get("counters_on") == "source" and what.endswith(" on it") and not self_form:
        selector = {**selector, "counters_on": "affected"}
    return selector


SELF_GRANT_RE = re.compile(
    # ``0-9`` in the keyword capture is ENG-31's parametric self-grant ("~
    # has firebending 2 as long as there's a lesson card in your graveyard"
    # — Fire Nation Cadets); `split_keywords_with_parametric` splits a
    # "<name> N" entry off into ``parametric_keywords`` and fail-closes on
    # any other numbered keyword.
    r"~ has (?P<kw>[a-z][a-z, 0-9]*?)"
    r"(?: and (?P<perm>can (?:attack|block)[a-z0-9 ']*))?",
    re.IGNORECASE,
)

#: The inner clause of a conditional static says "it" where the standalone
#: form says "~" ("As long as ~ is monstrous, **it** has trample."). The
#: pronoun can only mean the source here — the condition has already named
#: it, and a static clause has no target to compete for the referent.
_INNER_SELF_PRONOUN_RE = re.compile(r"^it\b", re.I)
#: "it's a creature in addition ..." contracts the pronoun with its verb; spell the verb out first so the rewrite
#: yields "<subject> is a creature ..." and not "<subject>'s a creature ...".
_INNER_PRONOUN_CONTRACTION_RE = re.compile(r"^it's\b", re.I)


def _rewrite_inner_pronoun(inner: str, subject: str) -> str:
    """The inner clause of a conditional static with its leading "it" replaced by ``subject``."""
    return _INNER_SELF_PRONOUN_RE.sub(subject, _INNER_PRONOUN_CONTRACTION_RE.sub("it is", inner))

#: …except when the condition named the *attached permanent* instead ("As
#: long as enchanted permanent is a Vehicle, **it**'s a creature…", Aerial
#: Modification): the antecedent is then that permanent, not the Aura, so
#: the pronoun is rewritten to whichever attached-subject phrase the
#: condition used and the inner clause parses through the ordinary
#: `_ATTACHED_*` rows with ``affects="attached_permanent"``.
_CONDITION_ATTACHED_SUBJECT_RE = re.compile(rf"({ATTACHED_SUBJECT_PATTERN})", re.I)


def self_permission_spec(m: "re.Match[str]"):
    """A self-grant row's optional permission tail → its `EffectSpec`.

    Three-valued on purpose: ``None`` (no tail — the ordinary case),
    an `EffectSpec` (a recognised permission), or ``False`` (a tail that
    isn't in the vocabulary, which must fail the *whole* clause rather than
    granting the keywords and dropping the permission).
    """
    tail = m.groupdict().get("perm")
    if not tail:
        return None
    params = permission_tail_params(tail)
    if params is None:
        return False
    return EffectSpec("combat_restriction", {**params, "affects": "self"})


def _static_or_replacement_specs(inner: str) -> Optional[list[EffectSpec]]:
    """The inner clause of a "as long as `<cond>`, `<X>`"/"during your
    turn, `<X>`" wrapper may be either a standing static ability
    (`static_effect_specs`) or a standing replacement effect
    (`catalogue.replacements.replacement_clause_specs`, PAR-78 — "as long
    as you control a permanent of each color, prevent all damage that
    would be dealt to you." needs the latter) — tried in that order, same
    as `segmenter.segment_line`'s own top-level permanent fallback."""
    specs = static_effect_specs(inner)
    if specs:
        return specs
    return replacement_clause_specs(inner)


def _condition_reads_host(condition: dict) -> bool:
    """Whether ``condition`` (or any combinator part of it) is read off an Aura/Equipment's host (``of="attached"``).

    RULE 303.4: the clause that follows says "it" for that host, so the pronoun rewrite must see through the
    ``any`` / ``all`` / ``not`` combinators, not only a top-level ``of`` key ("enchanted permanent is red or green, it
    has ...", "enchanted creature isn't legendary, it doesn't untap ...")."""
    if condition.get("of") == "attached":
        return True
    parts = condition.get("conditions") or ([condition["condition"]] if isinstance(condition.get("condition"), dict) else [])
    return any(_condition_reads_host(part) for part in parts)


def conditional_static_specs(text: str) -> Optional[list[EffectSpec]]:
    """"As long as `<cond>`, `<static>`" / "`<static>` as long as `<cond>`" →
    the inner static's specs, each carrying an ``active_if`` gate.

    ``None`` when the clause isn't conditional at all, *or* when either half
    fails to parse — an unrecognised condition must not degrade into an
    ungated static (RULE 613.6: a static whose gate is dropped applies when
    it shouldn't, which is worse than an unmodeled card).
    """
    for pattern in (AS_LONG_AS_LEADING_RE, AS_LONG_AS_TRAILING_RE):
        m = pattern.fullmatch(text)
        if m is None:
            continue
        inner = m.group("inner").strip().rstrip(",").strip()
        host = re.match(rf"({ATTACHED_SUBJECT_PATTERN})\b", inner, re.I)
        # The pronoun form already names the host in `inner`, so it needs no rewrite below.
        pronoun_condition = (
            pronoun_attached_condition(m.group("cond"), host.group(1).lower()) if host else None
        )
        # RULE 303.4: "it" in an Aura/Equipment's condition is the host. A characteristic word reads the host; any
        # other pronoun phrase would be tested against the Aura itself, so it fails closed instead.
        host_pronoun = bool(host) and re.match(r"it(?:'s| is| has| entered| isn't|n't)\b", m.group("cond").strip()) is not None
        if pronoun_condition is None and host_pronoun:
            pronoun_condition = attached_pronoun_characteristic(m.group("cond"))  # "inner" already names the host
        condition = (
            pronoun_condition
            or attached_state_condition(m.group("cond"))
            or (None if host_pronoun else static_condition(m.group("cond")))
        )
        if condition is None:
            return None
        if _condition_reads_host(condition) and pronoun_condition is None:
            subject = _CONDITION_ATTACHED_SUBJECT_RE.search(m.group("cond"))
            if subject is None:
                return None  # fail closed — no phrase to rewrite the pronoun to
            inner = _rewrite_inner_pronoun(inner, subject.group(1).lower())
        else:
            inner = _rewrite_inner_pronoun(inner, "~")
        specs = _static_or_replacement_specs(inner)
        if not specs:
            return None
        for spec in specs:
            # A `combat_restriction` keeps its own ``condition`` param for the
            # combat-time vocabulary; the RULE 613.6 gate is always
            # ``active_if``, on every spec shape alike.
            previous = spec.params.get("active_if")
            spec.params["active_if"] = ({"kind": "all", "conditions": [previous, dict(condition)]}
                                        if previous else dict(condition))
        return specs

    m = _DURING_YOUR_TURN_LEADING_RE.fullmatch(text)
    if m is not None:
        inner = _INNER_SELF_PRONOUN_RE.sub("~", m.group("inner").strip())
        specs = _static_or_replacement_specs(inner) or _self_animation_specs(inner)
        if not specs:
            return None
        which = m.group("which").lower()
        if "end step" in which:
            # RULE 500.1/513: an opponent's turn (not yours) and its end step.
            gate = {"kind": "all", "conditions": [{"kind": "not_your_turn"}, {"kind": "during_step", "step": "end"}]}
        else:
            gate = {"kind": "your_turn" if which == "your turn" else "not_your_turn"}
        for spec in specs:
            previous = spec.params.get("active_if")
            spec.params["active_if"] = ({"kind": "all", "conditions": [previous, gate]} if previous else gate)
        return specs
    m = DURING_YOUR_TURN_TRAILING_KEYWORD_RE.fullmatch(text)
    if m is not None:
        inner = f"~ has {m.group('inner').strip()}"
        specs = static_effect_specs(inner)
        if not specs:
            return None
        for spec in specs:
            spec.params["active_if"] = {"kind": "your_turn"}
        return specs
    return None


#: "<conditional static>. Otherwise, <static>." -- the printed pair of Bonds of Faith, Serra's Boon, Nyx Infusion,
#: Tahngarth's Rage and Evolved Spinoderm. Exactly two sentences; the second names its subject with "it".
_OTHERWISE_PAIR_RE = re.compile(r"(?P<first>[^.]+)\.\s+otherwise,\s+(?P<other>[^.]+)", re.I)


def conditional_otherwise_specs(text: str) -> Optional[list[EffectSpec]]:
    """"`<static> as long as <cond>`. Otherwise, `<static>`." -> both statics, the second gated on ``not <cond>``.

    RULE 613.6 / 604.1: each sentence is its own static ability of the same source, so the pair is two specs whose
    ``active_if`` gates are exact complements (``cond`` / ``not cond``); exactly one applies at any time. The gate is
    read back off the first sentence's own specs, so the two can never drift apart. ``it`` in the second sentence is
    the subject the first sentence names (the host for an Aura, the source otherwise). Anything that does not parse on
    both sides fails the whole line closed.
    """
    m = _OTHERWISE_PAIR_RE.fullmatch(text)
    if m is None:
        return None
    first = conditional_static_specs(m.group("first").strip())
    if not first:
        return None
    gates = [spec.params.get("active_if") for spec in first]
    if not gates[0] or any(gate != gates[0] for gate in gates):
        return None
    subject = None
    for pattern in (AS_LONG_AS_LEADING_RE, AS_LONG_AS_TRAILING_RE):
        parts = pattern.fullmatch(m.group("first").strip())
        if parts is not None:
            host = re.match(rf"({ATTACHED_SUBJECT_PATTERN})\b", parts.group("inner").strip(), re.I)
            if host is None and _condition_reads_host(gates[0]):
                # "As long as you control enchanted creature, it gets +2/+2. Otherwise, it can't block." -- the
                # condition names the host the second sentence's "it" refers to (RULE 303.4), not the Aura.
                host = _CONDITION_ATTACHED_SUBJECT_RE.search(parts.group("cond"))
                if host is None:
                    return None
            subject = host.group(1).lower() if host else "~"
            break
    if subject is None:
        return None
    second = _static_or_replacement_specs(_rewrite_inner_pronoun(m.group("other").strip(), subject))
    if not second or any(spec.params.get("active_if") for spec in second):
        return None
    # The pair binds as one static ability; a replacement/prevention half (Armament of Nyx) binds through the
    # replacement path instead and cannot share it, so that pair stays unclaimed.
    if any(spec.type in REPLACEMENT_CLAUSE_EFFECT_TYPES for spec in (*first, *second)):
        return None
    for spec in second:
        spec.params["active_if"] = {"kind": "not", "condition": dict(gates[0])}
    return [*first, *second]


def granted_trigger_doubler(inner: str) -> Optional[EffectSpec]:
    """A quoted trigger doubler granted to the attached permanent → a `trigger_doubler`
    spec with ``affects="attached_permanent"`` (its "~"/"this creature" is that host)."""
    body = inner.strip().rstrip(".").strip()
    if not body.lower().startswith("if ") or "triggers an additional time" not in body.lower():
        return None

    doubler = parse_trigger_doubler(body, trigger_condition_dict)
    if doubler is None:
        return None
    doubler.params["affects"] = "attached_permanent"
    return doubler



#: PAR-139: "Each [other] `<kind>` you control enters with an additional +1/+1 counter on it." (Grumgully,
#: Bramblewood Paragon, Dragonstorm Globe, Metallic Mimic, Master Biomancer's sibling clause …) — the
#: *others* form of a RULE 614.1 entry-counter replacement, `extra_etb_counter` with a ``filter``.
#: The kind is one `object_filter` plural phrase ("warrior creatures", "dragons", "non-human creatures").
_EXTRA_ETB_COUNTER_RE = re.compile(
    r"each (?P<other>other )?(?P<phrase>[a-z' -]+?) you control(?P<adv> that has an adventure)? "
    r"enters? with an additional "
    r"(?:(?P<n>\d+|an?|one) )?(?P<kind>[+\-]\d+/[+\-]\d+) counters? on it",
    re.IGNORECASE,
)


#: PAR-264: the plural form, "Other creatures you control enter with an additional +1/+1 counter on them."
#: (Deanna Troi, Psychic Counsel; Master Chef's quoted grant is the same clause) -- RULE 614.1c.
_EXTRA_ETB_COUNTER_PLURAL_RE = re.compile(
    r"(?P<other>other )?(?P<phrase>[a-z' -]+?) you control enter with an additional "
    r"(?:(?P<n>\d+|an?|one) )?(?P<kind>[+\-]\d+/[+\-]\d+) counters? on them",
    re.IGNORECASE,
)


#: "`<kind>` you control enter with `<n>` additional `<counter>` counters on them." (Zefram Cochrane: Spacecraft and
#: two charge counters) -- RULE 614.1c; the count precedes "additional" and the counter kind is a named counter.
_EXTRA_ETB_NAMED_COUNTER_RE = re.compile(
    r"(?P<other>other )?(?P<phrase>[a-z' -]+?) you control enter with (?P<n>\d+|an?|one) additional "
    r"(?P<kind>[a-z]+) counters? on them",
    re.IGNORECASE,
)


def _etb_counter_count(word: Optional[str]) -> int:
    """The printed counter count of an entry-counter clause ("an"/"one"/absent = 1)."""
    n = (word or "1").lower()
    return int(n) if n.isdigit() else 1


def extra_etb_counter_specs(text: str) -> Optional[list[EffectSpec]]:
    m = _EXTRA_ETB_COUNTER_RE.fullmatch(text)
    plural = False
    if m is None:
        m = _EXTRA_ETB_COUNTER_PLURAL_RE.fullmatch(text) or _EXTRA_ETB_NAMED_COUNTER_RE.fullmatch(text)
        plural = True
    if m is None:
        return None
    phrase = m.group("phrase").strip().lower()
    if plural:
        filt = object_filter(phrase)
        return [EffectSpec("extra_etb_counter", {
            "kind": m.group("kind"), "count": _etb_counter_count(m.group("n")), "filter": filt,
            "other": bool(m.group("other")),
        })] if filt else None
    filt = object_filter(phrase + "s") or (
        object_filter(re.sub(r"f$", "ves", phrase)) if phrase.endswith("f") else None
    )
    if not filt:
        return None
    if m.group("adv"):
        filt = {**filt, "has_adventure": True}  # Mysterious Pathlighter
    return [EffectSpec("extra_etb_counter", {
        "kind": m.group("kind"), "count": _etb_counter_count(m.group("n")), "filter": filt,
        "other": bool(m.group("other")),
    })]


#: PAR-284, RULE 614.1c: "~ enters with a +1/+1 counter on it for each other Kithkin you control." / "~ enters with X
#: +1/+1 counters on it, where X is the number of other creatures on the battlefield." / "~ enters with a number of
#: +1/+1 counters on it equal to the number of lands you control." -- a self entry replacement counted as the
#: permanent enters (`enters_with_counters_count`, read by `RulesEngine._apply_entry_counters`). Only a quantity the
#: shared selector grammar reads is claimed; a tally of a prior clause or of its own cast ("for each mana spent")
#: stays unclaimed.
_ENTERS_WITH_COUNT_RE = re.compile(
    # The counted phrase may name a counter kind ("for each other creature you control with a +1/+1 counter on it").
    r"(?P<removal>as ~ enters, remove all counters from all permanents\. )?"
    r"~ enters with (?:"
    r"(?P<n>\d+|an?) (?P<kind_a>[a-z0-9+/\-]+) counters? on it for each (?P<each>[a-z0-9+' ,/-]+?)"
    r"|x (?P<kind_x>[a-z0-9+/\-]+) counters on it, where x is the number of (?P<where>[a-z0-9+' ,/-]+?)"
    r"|a number of (?P<kind_n>[a-z0-9+/\-]+) counters on it equal to the number of (?P<equal>[a-z0-9+' ,/-]+?)"
    # PAR-284 milestone 23: "x +1/+1 counters on it, where x is the greatest power among creatures you control and
    # creature cards in your graveyard" (Ambitious Dragonborn) -- an aggregate, read as the permanent enters.
    r"|x (?P<kind_g>[a-z0-9+/\-]+) counters on it, where x is (?P<aggregate>the (?:greatest|total) [a-z ]+? among [a-z0-9+' ,/-]+?)"
    r")\.?",
    re.IGNORECASE,
)

#: PAR-284, RULE 614.1c: quantities only an entry replacement can read, mapped to the `continuous.count_selector`
#: name that measures them as the permanent enters. "creature that died this turn" is every player's tally (RULE
#: 700.4), "under your control" the controller's own; "mana spent to cast it" is the payment recorded on the entering
#: object (RULE 601.2h); the commander tally is `Player.commander_casts` (RULE 903.8). Deliberately not in
#: `for_each_count_selector`: a continuous anthem would re-read these at every layer pass.
_ENTRY_COUNT_SELECTORS: dict[str, str] = {
    "creature that died this turn": "creatures_died_this_turn",
    "creature that died under your control this turn": "creatures_you_controlled_died_this_turn",
    "mana spent to cast it": "mana_spent_to_cast",
    "time you've cast your commander from the command zone this game": "commander_casts_this_game",
    "time you've cast a commander from the command zone this game": "commander_casts_this_game",
}

#: PAR-284, RULE 122.1 / 614.1c: "as ~ enters, remove all counters from all permanents. ~ enters with ... for each
#: counter removed this way" (Thief of Blood): the engine strips every counter as the entry replacement runs and
#: multiplies what it removed (`enters_with_counters_count`'s ``remove_counters_scope``).
_REMOVED_THIS_WAY = "counter removed this way"
REMOVE_SCOPE_ALL_PERMANENTS = "all_permanents"


def enters_with_counters_count_specs(text: str) -> Optional[list[EffectSpec]]:
    m = _ENTERS_WITH_COUNT_RE.fullmatch(text.strip())
    if m is None:
        return None
    kind = (m.group("kind_a") or m.group("kind_x") or m.group("kind_n") or m.group("kind_g")).lower()
    multiplier = _etb_counter_count(m.group("n")) if m.group("n") else 1
    if m.group("aggregate"):
        aggregate = parse_amount_phrase(m.group("aggregate").lower())
        if aggregate is None:
            return None
        return [EffectSpec("enters_with_counters_count", {
            "kind": kind, "base": 0, "multiplier": multiplier, "count_selector": aggregate,
        })]
    what = (m.group("each") or m.group("where") or m.group("equal")).lower()
    if m.group("removal") or what == _REMOVED_THIS_WAY:
        if not (m.group("removal") and what == _REMOVED_THIS_WAY):
            return None  # a removal tally without its removal sentence (or the reverse) is another card's shape
        return [EffectSpec("enters_with_counters_count", {
            "kind": kind, "base": 0, "multiplier": multiplier, "count_selector": "",
            "remove_counters_scope": REMOVE_SCOPE_ALL_PERMANENTS,
        })]
    # "+1/+1 counter among other creatures you control" is the same sum as "... counters on other creatures".
    what = re.sub(r"\bcounters? among\b", "counters on", what)
    selector = _ENTRY_COUNT_SELECTORS.get(what) or for_each_count_selector(what, self_form=True)
    if selector is None:
        return None
    return [EffectSpec("enters_with_counters_count", {
        "kind": kind, "base": 0, "multiplier": multiplier, "count_selector": selector,
    })]
