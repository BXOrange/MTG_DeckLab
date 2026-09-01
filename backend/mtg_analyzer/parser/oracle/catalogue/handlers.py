"""The effect-clause handler table (docs/09 "THE CATALOGUE").

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE CATALOGUE", step 3 MATCH).
A **handler** is a regex that identifies + extracts an effect clause paired
with a builder that emits `EffectSpec`s (pure data → the `EffectRegistry`,
never executed behaviour). The set covers exactly what the engine already
supports as one-shot effects — damage / draw / discard / destroy / gain_life /
counter — each factored over the shared TARGET / NUMBER sub-grammars so the
table stays small (docs/09 "Factor shared sub-grammars").

Handlers match a single **normalised effect clause** (the segmenter has
already peeled trigger/cost wrappers and split on sentence boundaries), and
they **full-match** it: a clause is claimed only if a handler consumes it
end to end, which is what makes the coverage gate fail-closed (a half-matched
clause is *not* claimed, so its card stays `UNMODELED`).

Pure regex + data — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..normalize import SELF
from ..spec import EffectSpec, ParserProvenance
from .keywords import KEYWORDS, KeywordShape, keyword_slug
from .subgrammars import (
    CANT_BE_COUNTERED_RE,
    COLOR_WORD_ALT,
    COUNT,
    COUNT_X,
    DEVOTION,
    IF_COLOR_SUFFIX,
    NUMBER,
    PERMANENT_TYPE_WORDS,
    SPELL_TARGET,
    TARGET,
    UP_TO_ONE,
    all_permanent_type_selector,
    count_of,
    count_or_x_of,
    devotion_selector,
    pluralize_permanent_type,
    resolve_color_word,
    resolve_spell_filter,
    resolve_target_kind,
    target_is_optional,
    target_macro,
)

#: Colour words → their WUBRG symbol (for a created token's colours).
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
#: Words in a token's description that are supertypes/joiners, not its subtype.
_TOKEN_NOISE_WORDS: frozenset[str] = frozenset(
    {"artifact", "enchantment", "legendary", "snow", "colorless", "and", "or"}
)


@dataclass(frozen=True)
class EffectHandler:
    """One catalogue row: a full-clause regex + a builder emitting `EffectSpec`s."""

    name: str
    regex: re.Pattern[str]
    build: Callable[[re.Match[str]], Optional[list[EffectSpec]]]
    #: A row whose clause says "**it**" about the ability's own source ("when
    #: ~ enters, it fights …"). English writes that pronoun the same way when
    #: it means something else entirely — a *previously targeted* creature
    #: ("target creature you control gets +1/+2 until end of turn. it fights
    #: target creature you don't control.", Epic Confrontation) — and a clause
    #: alone can't tell the two apart. So such a row is only offered when the
    #: caller states that the implicit subject really is the source
    #: (`match_clause`'s ``self_subject``, set by `segmenter.segment_line` for
    #: an unsplit self-subject trigger body). Claiming it blind would model
    #: Epic Confrontation as "the *sorcery* fights", which resolves to
    #: nothing at all — exactly the half-modeling the coverage gate exists to
    #: prevent.
    self_subject_only: bool = False
    #: The mirror image: a row whose clause says "it"/"that creature" about
    #: the creature an **earlier clause of the same ability** chose ("target
    #: creature you control gets +1/+2 until end of turn. **It** fights target
    #: creature you don't control."). Offered only when `segmenter.
    #: parse_effect_body` has actually parsed such a clause immediately before
    #: this one *and* it announced a creature target, so the referent really
    #: exists at resolution (`GameContext.previous_targets`). Never on at the
    #: same time as ``self_subject_only``: an unsplit trigger body has no
    #: earlier clause to point at, and a later part of a split body has no
    #: guarantee the pronoun still means the source.
    previous_subject_only: bool = False
    #: MEC-28: a row whose clause says "it"/"that creature" about *whichever
    #: object matched* a RULE 603.1 group-subject trigger condition
    #: ("whenever a creature you control attacks alone, … untap **that
    #: creature**.", Finest Hour-shaped) — a third, genuinely different
    #: pronoun referent from both flags above: not the ability's own source
    #: (`self_subject_only`), and not a creature an *earlier clause of this
    #: same body* picked (`previous_subject_only`), but the specific object
    #: that satisfied the trigger, which varies every firing. Offered only
    #: when the caller states the trigger really has a ``{"subject":
    #: "group"}`` condition; `effect_binder._retarget_implicit_subject_
    #: effects` is what turns the resulting ``target_kind: None`` into a
    #: live per-firing read at bind time.
    group_subject_only: bool = False
    #: MEC-28: a row whose clause says "they" about the *group a mass
    #: selector in the immediately preceding clause of this same body just
    #: acted on* ("untap all attacking creatures. **They** gain first
    #: strike until end of turn.", Karlach, Fury of Avernus-shaped) —
    #: distinct from `previous_subject_only`, which reads `GameContext.
    #: previous_targets` (a RULE 115 targeted group); a mass selector
    #: ("all attacking creatures") is untargeted (RULE 601.2c) and never
    #: populates that list. Offered only when the preceding split clause's
    #: own spec actually used a recognised group selector (`segmenter.
    #: _announces_group_selector`).
    previous_selector_only: bool = False

    def match(self, clause: str) -> Optional[list[EffectSpec]]:
        """Effects for ``clause`` if this handler claims it whole, else ``None``.

        A builder may still return ``None`` after a regex match (e.g. an
        unrecognised target phrase) — that also means "not claimed", keeping
        the gate fail-closed.
        """
        m = self.regex.fullmatch(clause.strip())
        return self.build(m) if m is not None else None


def _c(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# --- Builders ---------------------------------------------------------------
# Each returns the effect list, or None when the clause can't be safely modeled
# (an unknown target phrase → fail-closed, don't guess).


#: RULE 115.1a "up to one" (`subgrammars.target_is_optional`) → the
#: `{"optional": True}` param sliver every `{TARGET}`-based builder below
#: merges in, or ``{}`` for a bare "target X" (still required, unchanged).
def _optional_param(m: re.Match[str]) -> dict:
    return {"optional": True} if target_is_optional(m) else {}


#: RULE 115.1a generalized to N>=2 — "destroy **two** target creatures",
#: "destroy **up to two** target artifacts and/or enchantments", "deals N
#: damage to each of **up to two** target creatures and/or planeswalkers".
#: A deliberately separate, self-contained grammar from the shared `TARGET`
#: macro above (`_TARGET_ROWS` is singular-only and reused by many other
#: handler families — return_to_hand/tap/attach/… — that this feature
#: doesn't touch): a plural noun phrase never collides with `TARGET`'s bare
#: "target X"/"up to one target X" shapes, so there's no dispatch ambiguity
#: registering both. Wired up for `destroy`/`exile`/`damage`/`tap`/
#: `return_to_hand`/`add_counters`/`return_from_graveyard` — every effect
#: class `game/effects.py` loops a `count` over. `return_from_graveyard`
#: doesn't reuse this alternation directly (graveyard clauses have their own
#: scope/type-word grammar, `_RETURN_FROM_GRAVEYARD_MULTI_RE`) but shares
#: `_MULTI_TARGET_QUANTIFIER`.
_MULTI_TARGET_ROWS: list[tuple[str, str]] = [
    (r"target creatures and/or planeswalkers", "any"),
    (r"target artifacts and/or enchantments", "permanent"),
    (r"target creatures", "creature"),
    # "return 1 or 2 target nonland permanents to their owners' hands"
    # (Wanderwine Farewell) — tried before the bare `target permanents` row
    # below since RAW excludes lands, unlike that row.
    (r"target nonland permanents", "nonland_permanent"),
    (r"target permanents", "permanent"),
    (r"target artifacts", "permanent"),
    (r"target enchantments", "permanent"),
    (r"target lands", "permanent"),
    (r"target players", "player"),
]
_MULTI_TARGET_ALT = "|".join(f"(?:{frag})" for frag, _ in _MULTI_TARGET_ROWS)
#: "exile any number of target spells." (Mindbreak Trap) — a spell-kind
#: target row, deliberately *not* folded into the shared `_MULTI_TARGET_
#: ROWS`/`_MULTI_TARGET_ALT` every other multi-target family (destroy/
#: damage/tap/return_to_hand/…) also reads: "destroy target spells"/
#: "N damage to target spells" aren't real templates (you counter or exile
#: a spell, never destroy/damage one), so widening the shared alternation
#: would have let `destroy_multi_target` silently claim a nonsense clause
#: too (caught by `tests/test_multi_target.py`'s own unrecognized-phrase
#: regression test). Only `exile`'s own regex opts into this wider
#: alternation. Reuses the same `TargetSpec(kind="spell", …)` `CopyPermanentEffect`'s
#: "copy any number of target instant and/or sorcery spells" (Display of
#: Power) already exercises.
_MULTI_TARGET_ALT_WITH_SPELL = _MULTI_TARGET_ALT + "|(?:target spells)"


def _multi_target_kind_with_spell(phrase: str) -> Optional[str]:
    text = phrase.strip()
    if re.fullmatch(r"target spells", text, re.IGNORECASE):
        return "spell"
    return _multi_target_kind(phrase)


def _multi_target_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    for frag, kind in _MULTI_TARGET_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None


#: A numeric quantifier before a plural TARGET phrase: "two "/"three " (a
#: mandatory count — RULE 601.2c needs that many legal targets to even be
#: castable) or "up to two "/"up to three " (optional, 0..N — never locks
#: casting, same as "up to one"). Digits only — `normalize.py` already
#: folds spelled-out numbers up to twelve. PAR-15's "any number of" is a
#: third alternative — RULE 115.1a's genuinely unbounded, freely-chosen
#: count (0..however many are legal), modeled the same way this codebase's
#: one pre-existing hand-authored example already did (`ability_catalogue.
#: _fire_covenant`'s own comment: "a real board never has X-1's worth of
#: relevant creatures beyond that") — a generous fixed cap
#: (`_ANY_NUMBER_TARGET_CAP`) rather than a live `legal_targets` count,
#: since the existing "up to N, offered one at a time, stop early" round-
#: gathering machinery (`RulesEngine._continue_trigger_multi_target`)
#: already handles running out of legal targets *or* the player stopping
#: voluntarily before the cap — the cap only needs to never be the *true*
#: bottleneck.
_ANY_NUMBER_TARGET_CAP = 10
#: ENG-30: RULE 601.2c's third quantifier shape — a genuine mandatory
#: *range* ("one or two target creatures", digits already folded by
#: `normalize.py`) — at least ``range_min``, at most ``range_max``, unlike
#: "up to N" whose floor is always 0. Tried before the plain ``count``
#: alternative below so "1 or 2 " isn't swallowed by a bare `\d+` match on
#: just the "1" (`targeting.TargetSpec.count_max`).
_MULTI_TARGET_QUANTIFIER = (
    r"(?:(?P<any_number>any number of )"
    r"|(?P<range_min>\d+) or (?P<range_max>\d+) "
    r"|(?P<up_to>up to )?(?P<count>\d+) )"
)


#: An optional trailing "controlled by different players/controllers"
#: clause (Run Away Together/Protector of the Wastes-shaped, RULE 115.1a's
#: N>=2 generalized with a cross-target constraint — `targeting.TargetSpec.
#: distinct_controllers`) — appended right after `_MULTI_TARGET_ALT`'s
#: target phrase in whichever multi-target handler regex opts in.
_MULTI_TARGET_DISTINCT_CONTROLLERS = r"(?P<dc> controlled by different (?:players|controllers))?"


def _multi_target_params(m: re.Match[str], allow_spell: bool = False) -> Optional[dict]:
    """The shared ``{target_kind, count, optional?, distinct_controllers?}``
    params for a `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` match, or
    ``None`` if the target phrase isn't recognized or the count is < 2 (the
    N=1 "up to one"/bare-target case is the existing singular handler's
    job, not this one's — a count of exactly 1 here would just be a
    confusing duplicate route to the same effect). PAR-15's "any number of"
    always carries ``optional=True`` (RULE 115.1a — 0 is always a legal
    choice) and a capped ``count`` (`_ANY_NUMBER_TARGET_CAP`). ENG-30's
    "N or M" range sets ``count`` to the RULE 601.2c *minimum* and
    ``count_max`` to the ceiling (`targeting.TargetSpec.count_max`) — never
    ``optional``, since fewer than the minimum isn't a legal choice.

    ``allow_spell=True`` (only `exile_multi_target`) additionally recognizes
    "target spells" — see `_MULTI_TARGET_ALT_WITH_SPELL`'s docstring for why
    this isn't just folded into the shared alternation every caller reads.
    """
    kind = (
        _multi_target_kind_with_spell(m.group("target"))
        if allow_spell else _multi_target_kind(m.group("target"))
    )
    if kind is None:
        return None
    if m.groupdict().get("any_number"):
        params: dict = {"target_kind": kind, "count": _ANY_NUMBER_TARGET_CAP, "optional": True}
    elif m.groupdict().get("range_min") is not None:
        range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
        if range_min < 1 or range_max <= range_min:
            return None  # fail closed on a nonsensical/degenerate range
        params = {"target_kind": kind, "count": range_min, "count_max": range_max}
    else:
        count = int(m.group("count"))
        if count < 2:
            return None
        params = {"target_kind": kind, "count": count}
        if m.groupdict().get("up_to"):
            params["optional"] = True
    if m.groupdict().get("dc"):
        params["distinct_controllers"] = True
    return params


def _damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("n")), "target_kind": kind, **_optional_param(m)})]


def _damage_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {"amount": "x", "target_kind": kind, **_optional_param(m)})]


#: RULE 702.33b's *override* kicked-conditional ("~ deals 2 damage to any
#: target. If this spell was kicked, it deals 4 damage instead." — Burst
#: Lightning/Roil Eruption/Shivan Fire-shaped), distinct from the *additive*
#: "if kicked, `<effect>`." shape `EffectSpec.condition`/`ConditionalEffect`
#: already cover: this doesn't add a second effect, it replaces the first
#: one's amount. Mirrors `_prevent_divided_damage`'s own kicked-override
#: trailing group (`DealDamageEffect.amount_if_kicked`, the sibling of
#: `PreventDamageEffect.amount_if_kicked`). The optional "to that creature"
#: tail (Firebending Lesson) is cosmetic re-naming of the same already-bound
#: target, not a second target phrase.
#: The literal "if this spell was kicked, ... instead" RULE 702.33b override
#: tail shares this exact prefix across every variant below; only the
#: verb-specific middle clause ("it deals N damage"/"create N of those
#: tokens"/"prevent the next N damage this way") genuinely diverges, so only
#: the unconditionally-shared literal is factored out.
_KICKED_OVERRIDE_PREFIX = r"\. if this spell was kicked, "

_DAMAGE_KICKED_OVERRIDE_RE = _c(
    rf"(?:~|it) deals? {NUMBER} damage to {TARGET}"
    rf"{_KICKED_OVERRIDE_PREFIX}it deals (?P<n2>\d+) damage"
    r"(?: to (?:that|the) (?:creature|permanent|player))? instead"
)


def _damage_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "amount_if_kicked": int(m.group("n2")),
        "target_kind": kind, **_optional_param(m),
    })]


#: A single copy-permanent "except …" tail *modifier* — one comma/"and"-
#: separated piece of a (possibly compound) "except" clause — classified
#: into the params it safely maps to, or ``None`` if it's not one of the
#: well-defined shapes below. Deliberately still excludes anything genuinely
#: varied (a P/T override, an arbitrary granted ability, a name change, "it
#: loses all other card types") — those stay unclaimed rather than guessed
#: at, same as every other "can't safely represent this clause" case in this
#: file; a real card needing one is `game/ability_catalogue.py`'s job
#: instead (PAR-18's own compound-except residue: Espers to Magicite/
#: Haunting Imitation/Lazav, Dimir Mastermind/Soul Separator).
#: Card-type words a copy-"except" tail can't be safely reduced to a colour /
#: subtype / `add_types=["Artifact"]` — "enchantment creature" &c. would need
#: `add_types` handling this shape doesn't do, so those stay fail-closed.
_COPY_EXCEPT_REJECT_TYPE_WORDS: frozenset[str] = frozenset(
    {"enchantment", "land", "planeswalker", "permanent"}
)

#: PAR-18 residue — "…except it's a 4/4 black zombie[ creature][ in addition
#: to its other types]" (the Anikthea / Ardyn / God-Pharaoh's Gift / Hour of
#: Eternity reanimator-token cycle). P/T + colour + one creature subtype;
#: the `CopyPermanentEffect.set_power`/`set_toughness`/`set_colors`/
#: `add_subtypes` params all already existed. **Documented simplification:**
#: without "in addition to its other types" the printed clause replaces the
#: copied creature's subtypes rather than adding to them — this always
#: appends (RULE-inexact for tribal synergies only).
_COPY_EXCEPT_PT_RE = re.compile(
    r"it'?s (?:an? )?"
    r"(?:(?P<p>\d+)/(?P<t>\d+)\s*)?"
    r"(?P<mid>[a-z][a-z ]*?)?"
    r"(?:\s*creature)?"
    r"(?:\s+in addition to its other types)?",
    re.IGNORECASE,
)


def _copy_except_modifier(piece: str) -> Optional[dict]:
    piece = piece.strip()
    if re.fullmatch(r"it isn'?t legendary|it'?s not legendary", piece):
        return {"not_legendary": True}
    m = re.fullmatch(r"it'?s an? (?P<mid>[a-z ]+?) in addition to its other types", piece)
    if m:
        colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid"))
        if colors or not (is_artifact or subtypes):
            return None  # a colour word or an empty/unrecognised mid — fail closed
        out: dict = {}
        # `Card.as_copy` splices these straight into the type line
        # (`f"{main} {' '.join(add_types)}"`), no case-normalization of its
        # own — a real MTG type line is title-cased ("Artifact Creature —
        # Human"), so the words must be capitalized here, not left as the
        # lowercase tokens `_split_token_mid_words` returns.
        if is_artifact:
            out["add_types"] = ["Artifact"]
        if subtypes:
            out["add_subtypes"] = [s.capitalize() for s in subtypes]
        return out
    pt = _COPY_EXCEPT_PT_RE.fullmatch(piece)
    if pt:
        mid = (pt.group("mid") or "").strip()
        if any(w.rstrip("s") in _COPY_EXCEPT_REJECT_TYPE_WORDS for w in mid.lower().split()):
            return None
        colors, subtypes, is_artifact = _split_token_mid_words(mid)
        out = {}
        if pt.group("p") is not None:
            out["set_power"] = int(pt.group("p"))
            out["set_toughness"] = int(pt.group("t"))
        if colors:
            out["set_colors"] = colors
        if is_artifact:
            out["add_types"] = ["Artifact"]
        if subtypes:
            out["add_subtypes"] = [s.capitalize() for s in subtypes]
        return out or None  # nothing recognised in the piece → fail closed
    return None


#: PAR-18: a (possibly *compound*) "except …" tail — "except it's an
#: artifact in addition to its other types" (a single modifier) / "except
#: it's not legendary and it's an artifact in addition to its other types"
#: (Dedicated Dollmaker-shaped, 2+ modifiers in one sentence) — split on its
#: top-level ", "/" and " connectors and each piece run through
#: `_copy_except_modifier` individually, merging the (fail-closed) results.
#: A comma is split first so a trailing "X, Y and Z" list's own "and" isn't
#: mistaken for a second connector inside one already-split piece.
def _parse_copy_except_tail(tail: str) -> Optional[dict]:
    pieces: list[str] = []
    for chunk in re.split(r",\s*", tail.strip()):
        pieces.extend(p for p in re.split(r"\s+and\s+", chunk) if p.strip())
    if not pieces:
        return None
    merged: dict = {}
    for piece in pieces:
        extra = _copy_except_modifier(piece)
        if extra is None:
            return None  # one unrecognised modifier fails the whole tail closed
        for key, value in extra.items():
            if isinstance(value, list):
                merged[key] = list(dict.fromkeys(merged.get(key, []) + value))
            elif key in merged and merged[key] != value:
                return None  # conflicting modifiers (shouldn't happen; fail closed)
            else:
                merged[key] = value
    return merged


#: RULE 707/706.2's "create a token that's a copy of target X[, except
#: <modifier>[, <modifier>...][ and <modifier>]]" (Cackling Counterpart/
#: Rite of Replication/Multiversal Recruitment/Impostor Syndrome-shaped) —
#: the bare form and every safely-generalizable "except" tail
#: (`_parse_copy_except_tail`) share one row; an "except" tail with even one
#: unrecognised modifier still fails the whole clause closed rather than
#: silently dropping it.
_COPY_PERMANENT_RE = _c(
    rf"create a token that'?s a copy of {TARGET}(?:, except (?P<except_tail>.+))?"
)


def _copy_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    tail = m.groupdict().get("except_tail")
    if tail:
        extra = _parse_copy_except_tail(tail)
        if extra is None:
            return None
        params.update(extra)
    return [EffectSpec("copy_permanent", params)]


#: The RULE 702.33b kicked-override sibling — "Create a token that's a copy
#: of target creature. If this spell was kicked, create five of those
#: tokens instead." (Rite of Replication) — same override shape as
#: `_damage_kicked_override`, just replacing ``count`` instead of ``amount``
#: (`CopyPermanentEffect.count_if_kicked`).
_COPY_PERMANENT_KICKED_OVERRIDE_RE = _c(
    rf"create a token that'?s a copy of {TARGET}"
    rf"{_KICKED_OVERRIDE_PREFIX}create (?P<n2>\d+) of those tokens instead"
)


def _copy_permanent_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("copy_permanent", {
        "target_kind": kind, "count_if_kicked": int(m.group("n2")), **_optional_param(m),
    })]


#: PAR-18's own pronoun antecedent — "exile up to 1 target creature card
#: from a graveyard. Create a token that's a copy of **it**/**that
#: card**[, except <modifier(s)>]." (Ardyn, the Usurper/Anikthea, Hand of
#: Erebos-shaped): the copied object is what an *earlier clause of the same
#: ability* just targeted (RULE 608.2 resolution order, `GameContext.
#: previous_targets` — `CopyPermanentEffect.referent="previous"`), not a
#: fresh RULE 115 target of this clause's own and not the ability's own
#: source either. `previous_subject_only`-gated the same way `_goad_previous`
#: is: only offered once `segmenter.parse_effect_body` has actually split
#: off an earlier clause that announced a target. Shares
#: `_parse_copy_except_tail` with the plain-target row above.
_COPY_PERMANENT_PREVIOUS_RE = _c(
    r"create a token that'?s a copy of (?:it|that card)"
    r"(?:, except (?P<except_tail>.+))?"
)


def _copy_permanent_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"target_kind": None, "referent": "previous"}
    tail = m.groupdict().get("except_tail")
    if tail:
        extra = _parse_copy_except_tail(tail)
        if extra is None:
            return None
        params.update(extra)
    return [EffectSpec("copy_permanent", params)]


def _damage_each_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("damage", {"amount": int(m.group("amount")), **params})]


#: RULE 601.2d's "divided as you choose among any number of target(s)"
#: (PAR-15's own named biggest cluster — Fire Covenant/Aurelia's Fury/
#: Avacyn's Judgment/Bogardan Hellkite-shaped) — a *split* total, not the
#: full amount to every chosen target the way `_damage_each_multi_target`
#: above is. `DealDamageEffect(divided=True)` (RULE 601.2d) already existed
#: as an engine primitive — Shatterskull Smashing/Fire Covenant, both
#: hand-authored (`game/ability_catalogue.py`, cEDH-cube batch 19) — but no
#: oracle-text recognizer had ever reached it; this is that recognizer, not
#: a new primitive. "targets" (unqualified, RULE 115.4 "any target") vs.
#: "target creatures" are the only two real phrasings.
_DIVIDED_DAMAGE_RE = _c(
    rf"(?:(?:~|it|this creature|this land|this permanent) )?"
    rf"deals? {COUNT_X} damage divided as you choose among any number of "
    r"(?P<target>targets|target creatures)"
)


def _divided_damage(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = "creature" if m.group("target") == "target creatures" else "any"
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), "target_kind": kind,
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: ENG-30: "deals N damage divided as you choose among 1 or 2 targets"
#: (Arc Mage/Chandra's Pyrohelix/Electrolyze/Fire // Ice/Forked Bolt/
#: Skarrgan Hellkite-shaped) — the *fixed range* sibling of
#: `_DIVIDED_DAMAGE_RE`'s "any number of": a genuine RULE 601.2c minimum of
#: one. Same local ``targets|target creatures`` alternation as that row
#: (not the shared `_MULTI_TARGET_ALT`, which this family has never used).
_DIVIDED_DAMAGE_RANGE_RE = _c(
    rf"(?:(?:~|it|this creature|this land|this permanent) )?"
    rf"deals? {COUNT_X} damage divided as you choose among "
    r"(?P<range_min>\d+) or (?P<range_max>\d+) (?P<target>targets|target creatures)"
)


def _divided_damage_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature" if m.group("target") == "target creatures" else "any"
    return [EffectSpec("damage", {
        "amount": count_or_x_of(m.group("n")), "target_kind": kind,
        "count": range_min, "count_max": range_max, "divided": True,
    })]


#: ENG-30: "deals N damage to each of 1 or 2 targets" (Storm of Steel) — the
#: full-amount-to-each sibling of `_divided_damage_range` (mirrors how
#: `_damage_each_multi_target` relates to `_divided_damage` for the "any
#: number of"/"up to N" shapes), same local bare-``targets`` alternation.
_DAMAGE_EACH_RANGE_RE = _c(
    rf"(?:(?:~|it|this creature|this land|this permanent) )?"
    rf"deals? (?P<amount>\d+) damage to each of "
    r"(?P<range_min>\d+) or (?P<range_max>\d+) (?P<target>targets|target creatures)"
)


def _damage_each_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature" if m.group("target") == "target creatures" else "any"
    return [EffectSpec("damage", {
        "amount": int(m.group("amount")), "target_kind": kind,
        "count": range_min, "count_max": range_max,
    })]


#: RULE 615's targeted divided-prevention sibling of `_DIVIDED_DAMAGE_RE`
#: (PAR-15's own "prevent-divided" residue cluster — Embolden/Remedy/Angel
#: of Salvation): "prevent the next N damage that would be dealt this turn
#: to any number of targets, divided as you choose." `PreventDamageEffect`
#: already existed as the untargeted "prevent all/N damage to you" shield
#: (Riot Control/Thought Lash, hand-authored); this recognizer — and the
#: targeted/divided mode it drives — is new. The optional trailing group is
#: Pollen Remedy's own "if this spell was kicked, prevent the next N damage
#: this way instead" *override* (`PreventDamageEffect.amount_if_kicked`),
#: distinct from RULE 702.33b's additive kicked-conditional shape.
_PREVENT_DIVIDED_DAMAGE_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt this turn to "
    r"any number of targets, divided as you choose"
    rf"(?:{_KICKED_OVERRIDE_PREFIX}prevent the next (?P<n2>\d+) damage this way instead)?"
)


def _prevent_divided_damage(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "amount": int(m.group("n")), "target_kind": "any",
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    }
    if m.group("n2") is not None:
        params["amount_if_kicked"] = int(m.group("n2"))
    return [EffectSpec("prevent_damage_shield", params)]


#: RULE 615's plain single-target sibling — "prevent the next N damage that
#: would be dealt to any target this turn." (Alabaster Wall/Amulet of Kroog/
#: Aven Redeemer-shaped, usually a `{cost}: <effect>` activated ability on an
#: artifact/creature) — note the different word order from
#: `_PREVENT_DIVIDED_DAMAGE_RE` just above ("dealt **to any target** this
#: turn" vs that row's "dealt this turn **to any number of targets**"), which
#: is what keeps the two rows from colliding. `PreventDamageEffect`'s
#: ``target_kind`` branch already supports exactly one real RULE 115 target
#: with no ``divided`` flag (its default) — only this oracle-text
#: recognition was missing.
_PREVENT_DAMAGE_SINGLE_TARGET_RE = _c(
    r"prevent the next (?P<n>\d+) damage that would be dealt to any target this turn"
)


def _prevent_damage_single_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_damage_shield", {"amount": int(m.group("n")), "target_kind": "any"})]


#: RULE 615's unscoped Fog-shaped form — "Prevent all combat damage that
#: would be dealt this turn." (Fog/Darkness/Constant Mists/Holy Day/Lull/
#: Moment's Peace/…, one of the most repeated templates in the cache). No
#: recipient, no ``TARGET`` group: everyone's combat damage, not the
#: single chosen shield `_PREVENT_DAMAGE_SINGLE_TARGET_RE`/
#: `_PREVENT_DIVIDED_DAMAGE_RE` build. Deliberately just the bare clause —
#: a qualified variant ("…by non-Spider creatures"/"…except combat damage
#: dealt by enchanted creatures") would need a source-filter param this
#: engine doesn't have yet, so those stay unclaimed rather than being
#: half-modeled as unqualified.
_PREVENT_ALL_COMBAT_DAMAGE_RE = _c(r"prevent all combat damage that would be dealt this turn")


def _prevent_all_combat_damage(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_all_combat_damage", {})]


#: RULE 601.2c's mass/untargeted-selector vocabulary — shared by the
#: damage/lose_life/player-counter "each creature/player/opponent" families
#: below, not RULE 115 targeting (see `subgrammars._TARGET_ROWS`'s note on
#: why "each opponent"/"each player" stay out of that grammar). Each
#: family's own regex alternation still independently gates which of these
#: keys it can actually capture — this dict is a pure value lookup, not a
#: regex-alternation source — *except* `_DAMAGE_SELECTOR_ALT` below, which
#: intentionally reads only the damage-legal subset rather than every key
#: here, since no card prints "deals damage to each other player".
_SELECTOR_WORD_MAP: dict[str, str] = {
    "each creature": "each_creature",
    "each player": "each_player",
    "each opponent": "each_opponent",
    # "each other player" (Urborg Syphon-Mage, lose_life/rad-counter only) —
    # functionally identical to "each opponent" in this engine (no
    # team-variant life sharing, RULE 809/810/811 — PLR-14, still unbuilt).
    "each other player": "each_opponent",
    # "whenever a player casts a spell, ~ deals 2 damage to that player."
    # (Spellshock-shaped) — the player named by the trigger's own firing
    # event (`effects.DealDamageEffect`'s ``"event_player"`` selector), not
    # an untargeted group like the rows above.
    "that player": "event_player",
    # "…if it's not their turn, ~ deals 4 damage to them." (Scytheclaw
    # Raptor) — same firing-event player, just the pronoun object form
    # rather than "that player".
    "them": "event_player",
}


#: "~ deals N damage to target `<color>` or `<color>` creature." (Rending
#: Volley-shaped) — `TargetSpec.colors`' own OR narrowing (`_destroy`'s
#: single-``color`` sibling; only ever two colours on a real card so far).
_DAMAGE_TARGET_TWO_COLOR_RE = _c(
    rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to target "
    rf"(?P<c1>{COLOR_WORD_ALT}) or (?P<c2>{COLOR_WORD_ALT}) creature"
)


def _damage_target_two_color(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors = [resolve_color_word(m.group("c1")), resolve_color_word(m.group("c2"))]
    if not all(colors):
        return None
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "target_kind": "creature", "colors": colors,
    })]


def _damage_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": selector})]


#: "~ deals damage to that player equal to the number of noncreature
#: spells they've cast this turn." (Magebane Lizard) — `DealDamageEffect.
#: amount_from_noncreature_spells_cast_this_turn`'s own trigger-body
#: sibling of `_lose_life_per_spell_cast_this_turn` (a different count and
#: a different effect type, so its own dedicated row rather than sharing
#: one).
_DAMAGE_PER_NONCREATURE_SPELL_CAST_THIS_TURN_RE = _c(
    r"(?:(?:~|it) )?deals? damage to that player equal to the number of noncreature spells "
    r"they'?ve cast this turn"
)


def _damage_per_noncreature_spell_cast_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "selector": "event_player", "amount_from_noncreature_spells_cast_this_turn": True,
    })]


#: "~ deals N damage to each opponent and each creature [and planeswalker]
#: they control." (Tectonic Hazard/End the Festivities/Delayed Blast
#: Fireball-shaped board wipes) — `DealDamageEffect`'s new
#: ``each_opponent_and_their_creatures[_and_planeswalkers]`` selector
#: (opponents-only, unlike ``each_creature_and_player``'s global scope).
_DAMAGE_EACH_OPPONENT_AND_CREATURES_RE = _c(
    rf"(?:(?:~|it) )?deals? {NUMBER} damage to each opponent and each creature"
    rf"(?P<pw> and planeswalker)? they control"
)


#: "~ deals N damage to each opponent and each creature they control. If
#: this spell was cast from exile, it deals M damage to each opponent and
#: each creature they control instead." (Delayed Blast Fireball) —
#: `DealDamageEffect.amount_if_cast_from_exile`'s own override, the same
#: shape `amount_if_kicked`/`amount_if_bargained` already use.
_DAMAGE_EACH_OPPONENT_AND_CREATURES_EXILE_RE = _c(
    rf"(?:(?:~|it) )?deals? {NUMBER} damage to each opponent and each creature they control\. "
    rf"if this spell was cast from exile, it deals (?P<n2>\d+) damage to each opponent and "
    rf"each creature they control instead"
)


def _damage_each_opponent_and_creatures_exile(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {
        "amount": int(m.group("n")), "selector": "each_opponent_and_their_creatures",
        "amount_if_cast_from_exile": int(m.group("n2")),
    })]


def _damage_each_opponent_and_creatures(m: re.Match[str]) -> list[EffectSpec]:
    selector = (
        "each_opponent_and_their_creatures_and_planeswalkers" if m.group("pw")
        else "each_opponent_and_their_creatures"
    )
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": selector})]


#: RULE 202.2f/700.6 "it deals damage to each opponent equal to your
#: devotion to `<colour>`." (Fanatic of Mogis) — `_damage_selector`'s
#: devotion-amount sibling; ``it`` (not ``~``) is the ETB-trigger pronoun
#: this specific card prints, so `self_subject_only` gates it the same way
#: `_pump_self_subject` does.
_DAMAGE_SELECTOR_DEVOTION_RE = _c(
    rf"it deals damage to (?P<selector>each opponent|each player) equal to {DEVOTION}"
)


def _selector_devotion_builder(effect_type: str):
    """The shared "X to each opponent/player equal to your devotion to
    `<colour>`" body: `_damage_selector_devotion`/`_lose_life_selector_devotion`
    differ only in which `EffectSpec` type the resolved selector/devotion
    amount get attached to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = _SELECTOR_WORD_MAP[m.group("selector")]
        dsel = devotion_selector(m)
        if not dsel:
            return None
        return [EffectSpec(effect_type, {"amount_from_count_selector": dsel, "selector": selector})]

    return build


_damage_selector_devotion = _selector_devotion_builder("damage")


#: "Each creature deals N damage to its controller." (Rakdos Charm) — unlike
#: `_SELECTOR_WORD_MAP`'s rows, the subject here is "each creature"
#: itself, not "~"/the source, and the recipient varies per creature
#: (`effects.DealDamageEffect`'s ``"each_creature_controller"`` selector).
_DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE = _c(
    rf"each creature deals {NUMBER} damage to its controller"
)


def _damage_each_creature_to_controller(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": "each_creature_controller"})]


#: "draw that many cards" (Vilis, Broker of Blood's "whenever you lose
#: life, draw that many cards" — MEC-43) — "that many" refers back to the
#: firing event's own ``amount`` (RULE 603.1), the same `count_from_
#: trigger_event` idiom `_create_token_that_many`/the "put that many
#: counters" row already use for their own effect types.
_DRAW_THAT_MANY_RE = _c(r"draws? that many cards?")


def _draw_that_many(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw", {"count_from_trigger_event": "amount"})]


def _draw(m: re.Match[str]) -> list[EffectSpec]:
    # `COUNT_X` also matches a literal "x" (RULE 107.3c's own announced
    # {X}, "draw X cards" — Contaminated Drink), resolved via the same
    # ``"x"`` sentinel `RulesEngine._substitute_x` already substitutes for
    # every other one-shot effect's magnitude field.
    params: dict = {"count": count_or_x_of(m.group("n"))}
    # "target player/opponent draws a card" (Kenrith/Oona's Grace-shaped) is
    # a real RULE 115 target, mirroring `_discard`'s own ``who`` treatment —
    # without this, "target player draws a card" would have made the
    # *source's controller* draw instead of the chosen player. "each
    # player/opponent draws" is the untargeted mass form (RULE 601.2c).
    who = (m.groupdict().get("who") or "").strip()
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    elif who in ("each player", "each opponent"):
        params["selector"] = who.replace(" ", "_")
    return [EffectSpec("draw", params)]


#: RULE 118.3's "You may pay `<cost>`. If you do, draw a card." — the single
#: most common tail on the `pay_cost_then` idiom (~21 real cards, mostly
#: Spellbombs and card-draw payoffs). Matched as *one whole clause*,
#: "you may" included, rather than through the generic "you may `<effect>`"
#: peeling `_peel_optional` does elsewhere: that peeling's own
#: `AbilitySpec.optional` flag means "you may decline this trigger's whole
#: effect", a different, *outer* optionality than RULE 118.3's "the
#: trigger always happens; paying the embedded cost is what's optional" —
#: setting both would double-gate the same choice. `pay_cost_then`
#: (`game/effects.py`'s `PayCostThenEffect`) already existed as an engine
#: primitive (Mana Vault/Wandering Archaic, hand-authored); this is its
#: first oracle-text recognizer.
_PAY_COST_THEN_DRAW_RE = _c(
    r"you may pay (?P<cost>\{[a-z0-9]+\})\. if you do, draw a card"
)


def _pay_cost_then_draw(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [{"type": "draw", "params": {"count": 1}}],
    })]


def _draw_next_upkeep(m: re.Match[str]) -> list[EffectSpec]:
    """RULE 603.7 delayed trigger: "draw a card at the beginning of the next
    turn's upkeep" (Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped, ~46
    real cards). Arms via `create_delayed_trigger` — the same primitive
    Batch 22 built for Mana Drain — with ``scope="any"``: no "your"
    qualifier means the very next upkeep regardless of whose turn (RULE
    603.7a), unlike Mana Drain's own controller-scoped "your next main
    phase". A pronoun-scoped variant ("its controller may draw...", Arcane
    Denial's own first sentence) is deliberately unclaimed here — a
    different, indirect-referent grammar shape, same family of gap as
    Run Away Together's (`docs/implementation-state/BACKLOG.md`)."""
    return [EffectSpec("create_delayed_trigger", {
        "step": "upkeep",
        "scope": "any",
        "effects": [{"type": "draw", "params": {"count": count_of(m.group("n"))}}],
    })]


#: RULE 601.3b's "impulsive draw" shape (PAR-13, Dungeon of the Mad Mage's
#: "Runestone Caverns" — "Exile the top two cards of your library. You may
#: play them."; also Bonehoard Dracosaur/Painter's Studio's own trailing
#: duration variants) — `ImpulsiveDrawEffect` already existed as a
#: hand-authored-only primitive (Light Up the Stage); this is the first
#: oracle-text recognizer to reach it. A bare, undurationed "you may play
#: them" (the dungeon room's own phrasing, with no explicit window at all)
#: defaults to the effect's own "until the end of your next turn" — the
#: more common real-card convention for an unqualified "you may play them".
#: MEC-12 fourth pass widened this: the *leading*-duration word order
#: ("Until the end of your next turn, you may play those cards." — Light Up
#: the Stage/Reckless Impulse/Commune with Lava's own real printed text,
#: not the trailing form this row was first written against) is at least as
#: common cache-wide as the trailing one, "that card"/"those cards" are as
#: real as the pronoun "them"/"it", the singular "the top card" (no number)
#: needs its own alternative since ``\d+`` can't match zero digits, and
#: ``count_or_x_of`` covers "the top x cards" (Commune with Lava) via the
#: same ``"x"``-sentinel/`RulesEngine._substitute_x` idiom every other
#: X-scaled one-shot effect already uses.
#: "…until your next end step." (Opera Love Song) accepted as a third
#: duration word alongside "this turn"/"until the end of your next turn" —
#: **documented simplification**: `ImpulsiveDrawEffect`'s window is turn-
#: scoped (`_grant_temp_play_permission`'s ``same_turn_only`` sweeps at
#: *this* turn's own cleanup, the finest granularity it has), so this maps
#: to ``same_turn_only=True`` rather than a genuine step-scoped expiry.
#: Exact when cast during the caster's own turn (their next end step
#: *is* later this same turn); an instant-speed cast on an opponent's turn
#: would close the window at that turn's cleanup instead of carrying it
#: into the caster's own next end step — narrower than RAW, not wider.
_EXILE_TOP_PLAY_RE = _c(
    r"exile the top (?:(?P<n>\d+|x) cards?|card) of your library\. "
    r"(?:(?P<dur_pre>this turn|until the end of your next turn|until your next end step), )?"
    r"you may play (?:them|it|that card|those cards)"
    r"(?: (?P<dur_post>this turn|until the end of your next turn|until your next end step))?"
)


def _exile_top_play(m: re.Match[str]) -> list[EffectSpec]:
    dur = (m.groupdict().get("dur_pre") or m.groupdict().get("dur_post") or "").strip()
    same_turn_only = dur in ("this turn", "until your next end step")
    n = m.group("n")
    return [EffectSpec("impulsive_draw", {
        "count": count_or_x_of(n) if n else 1, "same_turn_only": same_turn_only,
    })]


#: "Draw N cards and reveal them. You may cast one of them without paying
#: its mana cost." (PAR-13, Dungeon of the Mad Mage's own "Mad Wizard's
#: Lair") — `DrawRevealCastOneFreeEffect`'s only oracle-text route; reveal
#: itself carries no mechanical weight to model (RULE 701.28).
_DRAW_REVEAL_CAST_FREE_RE = _c(
    r"draw (?P<n>\d+) cards? and reveal (?:them|it)\. you may cast (?:\d+|a) of "
    r"them without paying its mana cost"
)


def _draw_reveal_cast_free(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("draw_reveal_cast_one_free", {"count": int(m.group("n"))})]


#: RULE 601.2f-adjacent "Expertise" cycle template (MEC-20) — "You may cast
#: a spell with mana value N or less from your hand without paying its mana
#: cost." (Kari Zev's/Sram's/Yahenni's/Baral's/Rishkar's Expertise), its
#: ``{X}``-scaled sibling ("…mana value x or less…", Electrodominance —
#: ``COUNT_X``/``count_or_x_of``, resolved against the spell's own announced
#: {X} by `RulesEngine._substitute_x`'s existing ``criteria`` walk, no new
#: wiring needed), and the trailing "where x is the number of attacking
#: creatures" tail (Epistolary Librarian's own triggered-ability body, which
#: has no cast {X} of its own to substitute — a board-read count instead,
#: `continuous.count_selector`'s existing ``"attacking_creatures"`` entry).
#: `FreeCastFromHandEffect` (`game/effects.py`) is a resolve-time *choice*
#: among the controller's own hand, not a target — none of these print
#: "target". The leading "you may " is optional here (not required) since
#: `segmenter._peel_optional` already strips it before `parse_effect_body`
#: ever reaches a handler, for both the bare spell-effect and the
#: triggered-ability wrapper paths — MEC-18's own "the generic 'you may '
#: stripper eats the clause first" lesson, guarded against directly rather
#: than by exempting `_peel_optional` (nothing else about this clause is
#: sensitive to the optional marker: `spec.optional` is read only by the
#: ``triggered`` binder branch, never ``spell_effect``, and this effect's
#: own `request_choose_objects(optional=True)` already models the "may").
_FREE_CAST_FROM_HAND_RE = _c(
    # ENG-33 (Great Intelligence's Plan) / ENG-32 (Waterbend "cast a
    # noncreature spell without paying"): the "with mana value N or less"
    # cap and the "noncreature" qualifier are both optional — an uncapped
    # `free_cast_from_hand` offers every nonland hand card.
    # "with mana value N or less" and "from your hand" appear in either
    # order — "…spell with mana value N or less from your hand…" (the
    # Expertise cycle) and "…spell from your hand with mana value N or
    # less…" (Marvo, Deep Operative). Two positions for the cap, read back
    # by `_free_cast_from_hand` as ``n`` or ``n_after``.
    rf"(?:you may )?cast an? (?P<noncreature>noncreature )?spell"
    rf"(?: with mana value {COUNT_X} or less)? from your hand"
    rf"(?: with mana value (?P<n_after>a|an|x|\d+) or less)? "
    rf"without paying its mana cost(?P<selector>, where x is the number of attacking creatures)?"
)


def _free_cast_from_hand(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if m.groupdict().get("noncreature"):
        params["noncreature_only"] = True
    cap = m.groupdict().get("n") or m.groupdict().get("n_after")
    if m.group("selector"):
        params["max_mana_value_selector"] = "attacking_creatures"
    elif cap is not None:
        params["max_mana_value"] = count_or_x_of(cap)
    return [EffectSpec("free_cast_from_hand", params)]


#: ENG-33: "you may put a `<type>` card from your hand onto the battlefield"
#: (Dr. Eggman, Sonic's Nemesis — a villainous-choice option body).
#: `PutFromHandOntoBattlefieldEffect` already exists (Tooth and Nail); this
#: reaches it from a resolving effect. Every named type/subtype must be a
#: recognized word (fail-closed) — a bare `card_query` substring test would
#: silently match nothing on a typo.
_PUT_FROM_HAND_TYPE_WORDS: frozenset[str] = frozenset(PERMANENT_TYPE_WORDS) | {
    "construct", "robot", "vehicle", "equipment", "aura", "clue",
    "food", "treasure",
}
_PUT_FROM_HAND_RE = _c(
    r"(?:you may )?put an? (?P<types>[a-z, ]+?) card from your hand onto the battlefield"
)


def _put_from_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    words = [
        w.strip() for w in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("types"))
        if w.strip()
    ]
    if not words or any(w not in _PUT_FROM_HAND_TYPE_WORDS for w in words):
        return None
    crit = words if len(words) > 1 else words[0]
    return [EffectSpec("put_from_hand_onto_battlefield", {"criteria": {"type": crit}, "count": 1})]


#: RULE 119/701.8's "Target opponent/player reveals their hand. You choose
#: a `<filter>` card from it[ with mana value N or less]. That player
#: discards that card[. You lose N life]." (Duress/Thoughtseize/Coercion/
#: Distress/Inquisition of Kozilek-shaped — one of the most repeated hand-
#: disruption templates in the cache). Deliberately just the five real
#: filter phrasings found so far (bare/nonland/noncreature+nonland/
#: creature-or-planeswalker/artifact-or-creature) rather than a fully
#: general card-type grammar, plus the two real trailing riders (MEC-43
#: round 2: a mana-value cap on the chosen card — Inquisition of Kozilek —
#: and the caster's own life loss — Thoughtseize) — "or a card from their
#: graveyard" and any other rider stays unclaimed rather than guessed at.
_HAND_DISRUPTION_FILTERS: dict[str, dict] = {
    "a card": {},
    "a nonland card": {"exclude_land": True},
    "a noncreature, nonland card": {"exclude_land": True, "exclude_creature": True},
    "a creature or planeswalker card": {"card_types": ["creature", "planeswalker"]},
    "an artifact or creature card": {"card_types": ["artifact", "creature"]},
}
_HAND_DISRUPTION_RE = _c(
    rf"(?P<target>target opponent|target player) reveals their hand\. "
    rf"you choose (?P<filter>{'|'.join(re.escape(k) for k in _HAND_DISRUPTION_FILTERS)}) "
    rf"from it(?: with mana value (?P<mv>\d+) or less)?"
    r"\. that player discards that card(?:\. you lose (?P<life>\d+) life)?"
)


def _hand_disruption_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind != "player":
        return None
    params: dict = {"target_kind": kind, **_HAND_DISRUPTION_FILTERS[m.group("filter")]}
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    specs = [EffectSpec("reveal_hand_choose_discard", params)]
    if m.group("life"):
        specs.append(EffectSpec("lose_life", {"amount": int(m.group("life"))}))
    return specs


#: RULE 701.28's "defending player reveals the top card of their library.
#: If it's a land card, that player puts it into their hand." (Goblin
#: Guide-shaped) — a triggered-ability body (the "whenever ~ attacks,"
#: prefix that opens it is recognized separately, by the segmenter's own
#: trigger-condition grammar). Deliberately just the "defending player"
#: subject and the three real card-type words found so far.
_REVEAL_TOP_CONDITIONAL_RE = _c(
    r"defending player reveals the top card of their library\. "
    r"if it'?s an? (?P<type>land|creature|artifact) card, that player puts it into their hand"
)


def _reveal_top_conditional(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("reveal_top_conditional_to_hand", {
        "whose": "defending_player", "card_type": m.group("type"),
    })]


def _split_token_mid_words(mid: str) -> tuple[list[str], list[str], bool]:
    """A created token's "<mid>" description words (everything between its
    P/T and "creature token") → ``(colors, subtypes, is_artifact)``.

    "artifact" is a `_TOKEN_NOISE_WORDS` entry — recognized, not just
    dropped: "colorless Construct **artifact** creature token" (Construct/
    Thopter/Servo-shaped) needs `CreateTokenEffect.is_artifact` set, or the
    synthesized token silently comes out as a bare Creature missing the
    Artifact card type entirely (RULE 704.5f's zero-toughness check, a
    "sacrifice an artifact" cost, and any artifact-count anthem all read
    `Card.is_artifact`). The one shared word-splitting loop for all three
    "<mid> creature token[s]" handler shapes (`_xx_token_mid_params`,
    `_inline_create_token_params`, `_create_named_legendary_token`) — kept
    as one function specifically so a future noise word only needs adding
    here once, not independently in three near-identical copies.
    """
    colors: list[str] = []
    subtypes: list[str] = []
    is_artifact = False
    for word in mid.split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word == "artifact":
            is_artifact = True
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    return colors, subtypes, is_artifact


def _xx_token_mid_params(mid: str, kw: Optional[str]) -> Optional[dict]:
    """The shared ``colors``/``subtypes``/``keywords`` params for an X/X
    token clause's "<mid> token[ with <kw>]" tail — the same word-splitting
    `_inline_create_token_params` uses for a literal-stats token, factored
    out since neither of the two X/X handlers below share that function's
    other (count/tapped/legendary) groups."""
    colors, subtypes, is_artifact = _split_token_mid_words(mid)
    keywords: list[str] = []
    if kw:
        parsed = _token_keywords(kw)
        if parsed is None:
            return None
        keywords = parsed
    params: dict = {"colors": colors, "subtypes": subtypes, "keywords": keywords}
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    return params


#: "create an X/X blue Shark creature token with flying, where X is that
#: spell's mana value." (Shark Typhoon's spell-cast trigger) — an X/X token
#: sized off the firing `SPELL_CAST` event's own ``mana_value`` field
#: (`CreateTokenEffect.pt_from_trigger_event`), read fresh at resolve time.
_MANA_VALUE_XX_TOKEN_RE = _c(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?, "
    r"where x is that spell'?s mana value"
)


def _mana_value_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "pt_from_trigger_event": "mana_value"})]


#: The RULE 702.28c Cycling-cost sibling — "create an X/X blue Shark
#: creature token with flying." (Shark Typhoon's own "When you cycle this
#: card" bonus) — X here is the Cycling cost's own paid {X}
#: (`GameObject.cycling_x_paid`), substituted through the same ``"x"``
#: sentinel/`_substitute_x` idiom (`"cycling_x"`) every other X-scaled
#: effect uses, just a different source field.
_CYCLING_XX_TOKEN_RE = _c(
    r"create an? x/x (?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z]+(?:, [a-z]+)*(?: and [a-z]+)?))?"
)


def _cycling_xx_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    return [EffectSpec("create_token", {**params, "power": "cycling_x", "toughness": "cycling_x"})]


#: RULE 400.7's "blink" family — "exile target non-<subtype> creature you
#: control, then return that card/it to the battlefield under
#: your/its owner's control" (Restoration Angel/Icewind Stalwart-shaped).
#: The pre-existing `BlinkEffect`/`RulesEngine.blink` primitive had no
#: oracle-text recognizer at all (Ephemerate/Momentary Blink are both
#: hand-authored in `ability_catalogue.py`) — this is that recognizer, for
#: the specific "non-<subtype> creature you control" + explicit controller
#: shape those simpler cards don't need. ``subtype`` is a single word (every
#: real card in this shape names exactly one creature type); a compound
#: exclusion or any other target phrase stays unclaimed.
_BLINK_NON_SUBTYPE_RE = _c(
    r"exile target non-(?P<subtype>[a-z]+) creature you control, "
    r"then return (?:that card|it) to the battlefield under (?P<who>your|its owner'?s) control"
)


def _blink_non_subtype(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "target_kind": "creature_you_control",
        "creature_filter": {"without_subtype": m.group("subtype").capitalize()},
    }
    if m.group("who") == "your":
        params["under_your_control"] = True
    return [EffectSpec("blink", params)]


#: The plainer sibling of `_BLINK_NON_SUBTYPE_RE`, with no subtype
#: exclusion — "exile [up to N] [another] target creature/[nonland]
#: permanent you control, then return that card/it to the battlefield
#: under your/its owner's control" (Felidar Guardian/Emiel the Blessed/
#: Displacer Kitten-shaped). "another" needs no special handling: every
#: ``*_you_control`` `legal_targets` branch already excludes the source
#: object regardless (`o is not source`), so a plain and an "another"-
#: qualified target kind resolve identically. "up to N" threads through
#: to `BlinkEffect`'s own ``optional``/``count_max`` (MEC-12) rather than
#: the yes/no "you may" a *mandatory*-single-target blink relies on
#: (stripped upstream, same as `_blink_non_subtype` needs no "you may" in
#: its own pattern either).
_BLINK_PLAIN_RE = _c(
    r"exile (?:up to (?P<up_to>one|[0-9]+) )?(?:another )?target "
    r"(?P<kind>nonland permanent|permanent|creature) you control, "
    r"then return (?:that card|it) to the battlefield under (?P<who>your|its owner'?s) control"
)


def _blink_plain(m: re.Match[str]) -> list[EffectSpec]:
    kind_word = m.group("kind")
    target_kind = {
        "creature": "creature_you_control",
        "permanent": "permanent_you_control",
        "nonland permanent": "nonland_permanent_you_control",
    }[kind_word]
    params: dict = {"target_kind": target_kind}
    if m.group("who") == "your":
        params["under_your_control"] = True
    up_to = m.group("up_to")
    if up_to:
        params["optional"] = True
        params["target_count_max"] = 1 if up_to == "one" else int(up_to)
    return [EffectSpec("blink", params)]


def _discard(m: re.Match[str]) -> list[EffectSpec]:
    # "you discard"/bare "discard" is the controller (untargeted); "target
    # player/opponent discards" is a real RULE 115 target; "each player/
    # opponent discards" is the untargeted mass form (RULE 601.2c). Mirrors
    # `_gain_life`'s ``who``-group treatment — and without the target_kind
    # half, "target player discards a card" would have made the *source's
    # controller* discard instead of the chosen player.
    params: dict = {"count": count_of(m.group("n"))}
    who = (m.groupdict().get("who") or "").strip()
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    elif who == "each player":
        params["scope"] = "each_player"
    elif who == "each opponent":
        params["scope"] = "each_opponent"
    return [EffectSpec("discard", params)]


#: RULE 601.2c mass edict — "each player sacrifices a nontoken creature of
#: their choice" (Accursed Marauder-shaped) / "each player sacrifices N
#: creatures of their choice" (Liliana, Dreadhorde General's own -4) — each
#: player independently choosing their own victim(s) via `effects.
#: SacrificeEffect`'s ``selector="each_player"``/``"each_opponent"``, not a
#: random/rules-picked edict (RulesEngine.sacrifice is a real interactive
#: choice per player).
_SACRIFICE_EDICT_SELECTOR_WORDS: dict[str, str] = {
    "each player": "each_player", "each opponent": "each_opponent",
}
_SACRIFICE_EDICT_WHAT_WORDS: dict[str, str] = {
    "creature": "creature", "artifact": "artifact", "land": "land", "permanent": "permanent",
}
_SACRIFICE_EDICT_RE = _c(
    rf"(?P<selector>{'|'.join(_SACRIFICE_EDICT_SELECTOR_WORDS)}) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s? of their choice"
)


def _sacrifice_edict(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SACRIFICE_EDICT_SELECTOR_WORDS[m.group("selector")]
    what = _SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"selector": selector, "what": what, "count": count})]


#: ENG-33: "target player/opponent sacrifices [N] [nontoken] `<what>` [of
#: their choice]" (Diabolic Edict / Chainer's Edict / Dead Drop-shaped, ~21
#: SOLO cards, and the recurring villainous-choice / vote *other* option).
#: A real RULE 115 player target (`SacrificeEffect.target_kind="player"` →
#: reads `targets[0]`), the single-target sibling of `_SACRIFICE_EDICT_RE`'s
#: `each_player`/`each_opponent` mass form.
_TARGET_PLAYER_EDICT_RE = _c(
    rf"target (?P<who>player|opponent) sacrifices? "
    rf"(?P<count>a|an|\d+) (?P<nontoken>nontoken )?"
    rf"(?P<what>{'|'.join(_SACRIFICE_EDICT_WHAT_WORDS)})s?(?: of their choice)?"
)


def _target_player_edict(m: re.Match[str]) -> list[EffectSpec]:
    what = _SACRIFICE_EDICT_WHAT_WORDS[m.group("what")]
    if m.group("nontoken") and what == "creature":
        what = "nontoken_creature"
    count_word = m.group("count")
    count = 1 if count_word in ("a", "an") else int(count_word)
    return [EffectSpec("sacrifice", {"target_kind": "player", "what": what, "count": count})]


#: "Each player loses N life unless they discard a card."/"...unless they
#: sacrifice a creature, artifact, or land of their choice." (PAR-13, Tomb
#: of Annihilation's "Veils of Fear"/"Sandfall Cell" dungeon rooms) — RULE
#: 101.4's APNAP mass "unless", `RulesEngine.request_each_player_pay_or`'s
#: only oracle-text route. Only these two cost phrasings (the ones real
#: cards in the pool actually print for this shape) — a compound sacrifice
#: cost the plain-word `_SACRIFICE_RE`/`ActivationCost.sacrifice` vocabulary
#: doesn't otherwise reach (`costs._SACRIFICE_CREATURE_ARTIFACT_OR_LAND_RE`).
_EACH_PLAYER_LOSE_LIFE_UNLESS_RE = _c(
    r"each player loses (?P<n>\d+) life unless they "
    r"(?P<cost>discard a card|"
    r"sacrifice a creature,\s*(?:an?\s+)?artifact,?\s*(?:or|and)\s*(?:an?\s+)?land of their choice)"
)


def _each_player_lose_life_unless(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("each_player_pay_or", {
        "cost": m.group("cost"),
        "effects": [{
            "type": "lose_life",
            "params": {"amount": int(m.group("n")), "target_kind": "player"},
        }],
    })]


#: "Discard a card and sacrifice a creature, an artifact, and a land."
#: (PAR-13, Dungeon of the Mad Mage's "Oubliette" room) — a mandatory
#: compound cost-shaped punishment, not an "unless" choice: one `discard`
#: plus three independent `choose_objects` sacrifices (the payer's own
#: pick within each type, RULE 701.17a — `ChooseObjectsEffect` already
#: resolves with no prompt when there's nothing to choose between, and as a
#: no-op when a type has no legal candidate at all). A standalone whole-
#: clause row rather than relying on the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), since that would also split the sacrifice's
#: own internal "a creature, an artifact, **and** a land" list.
_DISCARD_AND_SACRIFICE_TRIPLE_RE = _c(
    r"discard a card and sacrifice a creature, an artifact, and a land"
)


def _discard_and_sacrifice_triple(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec("discard", {"count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "creature", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "artifact", "count": 1}),
        EffectSpec("choose_objects", {"action": "sacrifice", "what": "land", "count": 1}),
    ]


def _gain_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you gain N life" / "target player gains N life" (Abuna's Chant-shaped)
    # — a real RULE 115 target only for the latter phrasing.
    params: dict = {"amount": int(m.group("n"))}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("gain_life", params)]


#: RULE 119's "drain" idiom trailing sentence — "You gain life equal to the
#: life lost this way." (Gray Merchant of Asphodel/Exsanguinate/Kokusho, the
#: Evening Star-shaped, 16+ cache cards) — always the second sentence after
#: a "`<player(s)>` lose[s] `<amount>` life" clause that already parses on
#: its own (`_lose_life`/`_lose_life_selector`); only this trailing pronoun
#: sentence was ever unclaimed, discarding the *whole* two-sentence ability
#: fail-closed.
_GAIN_LIFE_LOST_THIS_WAY_RE = _c(r"you gain life equal to the life lost this way")


def _gain_life_lost_this_way(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "life_lost_this_way"})]


#: "Whenever a player casts a spell, they lose 1 life for each spell
#: they've cast this turn." (Rug of Smothering) — the caster's own running
#: `GameState.spells_cast_this_turn` count (`LoseLifeEffect.
#: amount_from_spells_cast_this_turn`, including the cast that fired this
#: trigger), not a flat amount — tried before the plain `_lose_life` row
#: below, whose bare `{NUMBER}` group can't match "each spell...".
_LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE = _c(
    rf"they lose {NUMBER} life for each spell they'?ve cast this turn"
)


def _lose_life_per_spell_cast_this_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_life", {
        "amount": int(m.group("n")), "selector": "event_player",
        "amount_from_spells_cast_this_turn": True,
    })]


def _lose_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you lose N life" / "target player loses N life" — same targeting
    # split as `_gain_life`. "they lose N life" (Sheoldred, the Apocalypse's
    # "whenever an opponent draws a card, they lose 2 life.") is the group-
    # subject trigger's own firing player, not a fresh RULE 115 target —
    # `LoseLifeEffect`'s ``selector="event_player"``, the same "that player"
    # idiom `_SELECTOR_WORD_MAP`'s ``"event_player"`` row already uses.
    who = (m.groupdict().get("who") or "").strip()
    params: dict = {"amount": int(m.group("n"))}
    if who == "target player":
        params["target_kind"] = "player"
    elif who == "they":
        params["selector"] = "event_player"
    return [EffectSpec("lose_life", params)]


def _lose_life_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "each opponent loses N life" / "each player loses N life" / "each
    # other player loses N life" — the shared `_SELECTOR_WORD_MAP` mass/
    # untargeted-selector shape (RULE 601.2c, not RULE 115 targeting).
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    # ``COUNT_X`` (not just digits) so "each opponent loses X life."
    # (Exsanguinate) carries the ``"x"`` sentinel `RulesEngine._substitute_x`
    # resolves against the spell's actually-announced {X} at resolve time —
    # `LoseLifeEffect.amount` is a plain attribute that sentinel already
    # walks, so no engine change was needed, just this wider capture.
    return [EffectSpec("lose_life", {"amount": count_or_x_of(m.group("n")), "selector": selector})]


#: RULE 202.2f/700.6 "each opponent loses X life, where X is your devotion
#: to `<colour>`." (Gray Merchant of Asphodel-shaped) — `_lose_life_
#: selector`'s devotion-amount sibling, tried first since "x" never matches
#: that row's `NUMBER` (``\d+``).
_LOSE_LIFE_SELECTOR_DEVOTION_RE = _c(
    rf"(?P<selector>each player|each opponent) loses x life, where x is {DEVOTION}"
)


_lose_life_selector_devotion = _selector_devotion_builder("lose_life")


#: "Each opponent loses life equal to the number of Vampires you control."
#: (Malakir Bloodwitch) — `continuous.count_selector`'s existing
#: ``creatures_you_control_of_type_<subtype>`` vocabulary (already reached
#: by `_create_token_for_each`'s "for each `<subtype>` you control" reading)
#: applied to life loss instead of a token count.
_LOSE_LIFE_SELECTOR_SUBTYPE_RE = _c(
    r"(?P<selector>each player|each opponent) loses life equal to the number of "
    r"(?P<subtype>[a-z]+) you control"
)


def _lose_life_selector_subtype(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    subtype = m.group("subtype").rstrip("s")
    return [EffectSpec("lose_life", {
        "amount_from_count_selector": f"creatures_you_control_of_type_{subtype}", "selector": selector,
    })]


#: MEC-27's own residual: the "draw"/"you gain life"/"you lose life" verb
#: families `{DEVOTION}` had never been wired to, unlike the "each player/
#: opponent loses life"/damage/counters/pump/token families above — always
#: the caster/ability's own controller (RULE 118), not a mass "each
#: player/opponent" recipient, so each is its own plain row rather than
#: routed through `_selector_devotion_builder`'s selector-word plumbing.
_DRAW_DEVOTION_RE = _c(rf"draws? x cards?, where x is {DEVOTION}")


def _draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("draw", {"amount_from_count_selector": dsel})]


_GAIN_LIFE_DEVOTION_RE = _c(rf"you gains? x life, where x is {DEVOTION}")


def _gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("gain_life", {"count_selector": dsel})]


_LOSE_LIFE_SELF_DEVOTION_RE = _c(rf"you loses? x life, where x is {DEVOTION}")


def _lose_life_self_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [EffectSpec("lose_life", {"amount_from_count_selector": dsel})]


#: The three "draw X and gain/lose X life" combined templates (Champion of
#: Dusk/Graveborn Muse/Minions' Murmurs, Nissa/Camaraderie) — two one-shot
#: effects sharing one `{DEVOTION}` amount, in the printed clause's own
#: order (RULE 608.2b). The repeated "you" (Champion of Dusk's "you draw x
#: cards and **you** lose x life") is optional since some printings drop it
#: (Painful Truths' "you draw x cards and lose x life").
_DRAW_AND_LOSE_LIFE_DEVOTION_RE = _c(
    rf"you draws? x cards? and (?:you )?loses? x life, where x is {DEVOTION}"
)
_GAIN_LIFE_AND_DRAW_DEVOTION_RE = _c(
    rf"you gains? x life and draws? x cards?, where x is {DEVOTION}"
)
_DRAW_AND_GAIN_LIFE_DEVOTION_RE = _c(
    rf"you draws? x cards? and (?:you )?gains? x life, where x is {DEVOTION}"
)


def _draw_and_lose_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
        EffectSpec("lose_life", {"amount_from_count_selector": dsel}),
    ]


def _gain_life_and_draw_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("gain_life", {"count_selector": dsel}),
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
    ]


def _draw_and_gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("draw", {"amount_from_count_selector": dsel}),
        EffectSpec("gain_life", {"count_selector": dsel}),
    ]


#: "Each opponent loses X life and you gain X life, where X is `{DEVOTION}`."
#: (Mishra, Claimed by Gix-shaped drain) — a fourth combined shape, distinct
#: from Gray Merchant's "each opponent loses X life... you gain life equal to
#: the life lost this way" (that one's already `_lose_life_selector_devotion`
#: + `_gain_life_lost_this_way`, two independently-claimed clauses): here
#: both halves name the *same* count directly, in one sentence, with no
#: {X}-cost of its own — critically, this must be claimed as **one** clause
#: rather than left to the generic `" and "` connector split
#: (`segmenter._CONNECTORS`), which would otherwise match its first half
#: ("each opponent loses x life") against the plain `_lose_life_selector`
#: row's `COUNT_X` — that row's "x" is RULE 107.3c's *announced-{X}*
#: sentinel, never substituted for a triggered ability with no X cost, so
#: the split would leave a `LoseLifeEffect(amount="x")` that crashes
#: (`"x" <= 0`) instead of reading `{DEVOTION}` at all.
_LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE = _c(
    rf"each opponent loses x life and you gains? x life, where x is {DEVOTION}"
)


def _lose_life_and_gain_life_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    return [
        EffectSpec("lose_life", {"amount_from_count_selector": dsel, "selector": "each_opponent"}),
        EffectSpec("gain_life", {"count_selector": dsel}),
    ]


def _rad_counter_amount(token: str) -> "int | str":
    # "N rad counters"/"a rad counter" (COUNT) or "X rad counters" (RULE
    # 601.2b's own announced {X} — the same ``"x"`` sentinel
    # `additional_cost`'s `pay_life` uses, substituted at resolve time).
    return "x" if token.strip().lower() == "x" else count_of(token)


#: "[you/target player/defending player] get[s] N rad counters" (RULE 728,
#: player counters — see `_gain_life`/`_lose_life`'s identical who-prefix
#: shape). ``who`` omitted (bare "get two rad counters") covers a "you may"
#: prefix already peeled by the segmenter (Tato Farmer's Landfall).
#: "defending player" (Acquired Mutation, an Aura's "whenever enchanted
#: creature attacks, defending player gets ~") reuses the same
#: ``selector="defending_player"`` afflict/Simian Sling already established
#: for `LoseLifeEffect`/`DealDamageEffect` (`AddPlayerCountersEffect`'s own
#: apply()-time resolution accounts for the Aura-vs-host source split).
_RAD_COUNTER_WHO_SELECTOR: dict[str, str] = {"defending player": "defending_player"}


def _add_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    params: dict = {"amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind")}
    if who == "target player":
        params["target_kind"] = "player"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: "each player gets N rad counters" / "each opponent gets N poison
#: counters" (RULE 601.2c mass effect, RULE 122.1/104.3d — the same
#: `AddPlayerCountersEffect` primitive parametrized by ``kind``) — the
#: player-counter sibling of `_lose_life_selector`. ``kind`` is a real
#: regex alternation (not a fixed "rad") since Infectious Bite/Prologue to
#: Phyresis-shaped poison cards use the identical "each opponent gets a
#: `<kind>` counter" template.
def _add_rad_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _SELECTOR_WORD_MAP[m.group("selector")]
    return [EffectSpec("add_player_counters", {
        "amount": _rad_counter_amount(m.group("n")), "kind": m.group("kind"), "selector": selector,
    })]


#: "target player loses all rad counters" (Survivor's Med Kit's RadAway
#: mode) — the removal sibling, always ``target player`` in practice (no
#: real card grants this to "you" untargeted), so ``target_kind`` is
#: unconditional rather than an optional ``who`` group.
def _lose_all_rad_counters(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("lose_all_player_counters", {"kind": "rad", "target_kind": "player"})]


#: "each opponent gets a number of rad counters equal to its power" (Feral
#: Ghoul's "When this creature dies, ..." — a dynamic amount tied to the
#: dying object's own power, RULE 400.7 last-known-information). Unlike
#: every other rad-counter clause above, the amount can't be a plain int/
#: "x" sentinel, so this is its own dedicated effect
#: (`DiesGrantsRadCountersEqualPowerEffect`) rather than a param shape on
#: the generic `add_player_counters`.
def _dies_rad_counters_equal_power(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("dies_grants_rad_counters_equal_power", {"kind": "rad"})]


#: "you get half X rad counters, rounded up/down" (Contaminated Drink's
#: "Draw X cards, then you get half X rad counters, rounded up.") — RULE
#: 107.1e's division-and-rounding phrasing, {X}-scaled only (no real card
#: needs a plain, non-X division yet); the ``"half_x_up"``/``"half_x_down"``
#: sentinel `RulesEngine._substitute_x` resolves against the spell's
#: actually-announced {X} at resolve time, mirroring the plain ``"x"``
#: sentinel exactly.
def _add_rad_counters_half_x(m: re.Match[str]) -> list[EffectSpec]:
    who = (m.groupdict().get("who") or "").strip().lower()
    amount = "half_x_up" if m.group("round") == "up" else "half_x_down"
    params: dict = {"amount": amount, "kind": "rad"}
    if who == "target player":
        params["target_kind"] = "player"
    elif who in _RAD_COUNTER_WHO_SELECTOR:
        params["selector"] = _RAD_COUNTER_WHO_SELECTOR[who]
    return [EffectSpec("add_player_counters", params)]


#: The single-printed-type permanent target kinds `resolve_target_kind`
#: resolves "target artifact"/"target enchantment"/"target land" to (RULE
#: 115.1c) — added to every guard tuple below that already accepted the
#: broad, untyped "target permanent" kind, so narrowing that mapping (fixing
#: e.g. Abrade's "Destroy target artifact." from wrongly offering any
#: permanent, including lands) doesn't regress these families to UNMODELED.
_SINGLE_TYPE_PERMANENT_KINDS: tuple[str, ...] = ("artifact", "enchantment", "land")


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in (
        "creature", "permanent", "permanent_you_dont_control", *_SINGLE_TYPE_PERMANENT_KINDS,
    ):
        return None
    color = resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": kind, **_optional_param(m)}
    if color:
        params["color"] = color
    return [EffectSpec("destroy", params)]


def _destroy_mv(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — a target-offer-time mana-value cap
    # (`targeting.TargetSpec.max_mana_value`), tried before the plain
    # `_destroy` handler since it's a strict superset of that shape (the
    # trailing "with mana value N or less" clause `_destroy`'s own grammar
    # doesn't recognise). MEC-40: "nonland_permanent" was missing from this
    # tuple despite the docstring already naming Abrupt Decay by name — the
    # kind itself (`targeting.py`'s "nonland_permanent" branch) already
    # honours `max_mana_value`, so this was a plain oversight, not a missing
    # engine primitive.
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent", "nonland_permanent"):
        return None
    return [EffectSpec("destroy", {"target_kind": kind, "max_mana_value": int(m.group("mv"))})]


#: A creature's power/toughness/keyword *quality* filter (RULE 115/601.2c —
#: "destroy target creature with power 4 or greater"/"…with flying"-shaped,
#: `targeting.TargetSpec.creature_filter`). English keyword word → the
#: internal snake_case token `combat.has` checks; only single-word-in-text
#: keywords a "with <keyword>" clause plausibly names are listed (extend as
#: a real card needs one — fail-closed for anything else via the ``kw``
#: alternation below).
_CREATURE_FILTER_KEYWORD_WORDS: dict[str, str] = {
    "flying": "flying", "defender": "defender", "first strike": "first_strike",
    "double strike": "double_strike", "trample": "trample", "vigilance": "vigilance",
    "deathtouch": "deathtouch", "lifelink": "lifelink", "menace": "menace",
    "haste": "haste", "indestructible": "indestructible", "hexproof": "hexproof",
    "reach": "reach",
}
#: One power/toughness/keyword clause, with named groups suffixed by
#: ``suffix`` so the same fragment can appear twice in one regex (a compound
#: "with power 4 or greater and flying" filter — two independent clauses
#: joined by "and", RULE 115/601.2c) without a group-name collision.
def _creature_filter_clause(suffix: str) -> str:
    return (
        rf"power (?P<pwr{suffix}>\d+) or (?P<pwr_cmp{suffix}>greater|less)"
        rf"|toughness (?P<tough{suffix}>\d+) or (?P<tough_cmp{suffix}>greater|less)"
        rf"|(?P<kw{suffix}>{'|'.join(_CREATURE_FILTER_KEYWORD_WORDS)})"
    )


#: The qualifier suffix shared by `_DESTROY_CREATURE_FILTER_RE`/
#: `_EXILE_CREATURE_FILTER_RE` — appended right after "target creature". The
#: trailing group is an optional second " and [with] <clause>" — only two
#: clauses (the real-card ceiling found so far); a third would need a third
#: suffixed group set.
_CREATURE_FILTER_SUFFIX = (
    rf"with (?:{_creature_filter_clause('')})"
    rf"(?: and (?:with )?(?:{_creature_filter_clause('2')}))?"
)


def _creature_quality_filter_clause(groups: dict, suffix: str) -> Optional[dict]:
    if groups.get(f"pwr{suffix}"):
        n = int(groups[f"pwr{suffix}"])
        return {"min_power": n} if groups[f"pwr_cmp{suffix}"] == "greater" else {"max_power": n}
    if groups.get(f"tough{suffix}"):
        n = int(groups[f"tough{suffix}"])
        return {"min_toughness": n} if groups[f"tough_cmp{suffix}"] == "greater" else {"max_toughness": n}
    if groups.get(f"kw{suffix}"):
        return {"keyword": _CREATURE_FILTER_KEYWORD_WORDS[groups[f"kw{suffix}"]]}
    return None


def _creature_quality_filter(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    first = _creature_quality_filter_clause(groups, "")
    if first is None:
        return None
    second = _creature_quality_filter_clause(groups, "2")
    if second is None:
        return first
    return {**first, **second}


def _quality_filter_builder(effect_type: str):
    """`_destroy_creature_filter`/`_exile_creature_filter`'s shared body —
    they differ only in which `EffectSpec` type the resolved creature-quality
    filter (power/toughness/keyword) attaches to."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        filt = _creature_quality_filter(m)
        if filt is None:
            return None
        return [EffectSpec(effect_type, {"target_kind": "creature", "creature_filter": filt})]

    return build


_destroy_creature_filter = _quality_filter_builder("destroy")
_exile_creature_filter = _quality_filter_builder("exile")


#: "destroy target non<word> creature[, optionally 'It can't be
#: regenerated.']" (RULE 105's colour-hoser *negated* adjective form,
#: Doom Blade/Dark Banishing/Cast Down-shaped — the single most repeated
#: removal template in the cache). ``neg`` covers the five colour words
#: (`combat.matches_object_filter`'s new ``without_color``) plus
#: "artifact" (its pre-existing ``without_card_type`` — Go for the Throat's
#: own filter shape, previously only reachable by hand-authoring since
#: nothing recognized this phrasing from oracle text).
_NEG_CREATURE_FILTER_WORDS: dict[str, tuple[str, str]] = {
    "black": ("without_color", "B"), "blue": ("without_color", "U"),
    "white": ("without_color", "W"), "red": ("without_color", "R"),
    "green": ("without_color", "G"),
    "artifact": ("without_card_type", "artifact"),
}
_DESTROY_NON_CREATURE_RE = _c(
    rf"destroy target non(?P<neg>{'|'.join(_NEG_CREATURE_FILTER_WORDS)}) creature"
    r"(?P<no_regen>\. it can'?t be regenerated)?"
)


def _destroy_non_creature(m: re.Match[str]) -> list[EffectSpec]:
    key, value = _NEG_CREATURE_FILTER_WORDS[m.group("neg")]
    params: dict = {"target_kind": "creature", "creature_filter": {key: value}}
    if m.group("no_regen"):
        params["can_be_regenerated"] = False
    return [EffectSpec("destroy", params)]


#: "destroy target [color] creature/permanent/artifact/enchantment/land"
#: (RULE 105's colour-hoser adjective form, Red Elemental Blast-shaped) — a
#: small dedicated noun list rather than a color slot spliced into the
#: shared `TARGET` macro's fixed rows (which many other handlers reuse
#: as-is); covers the same nouns `_destroy`'s plain `TARGET`-based match
#: already accepts. Tried before the plain `destroy` handler below — with
#: no colour word present it matches identically (same `target_kind`
#: mapping), so it never changes behaviour for an uncoloured clause.
_DESTROY_COLOR_NOUN_KINDS: dict[str, str] = {
    "creature": "creature", "permanent": "permanent", "artifact": "permanent",
    "enchantment": "permanent", "land": "permanent",
}
_DESTROY_COLOR_ADJ_RE = _c(
    rf"destroy target (?:(?P<color>{COLOR_WORD_ALT}) )?"
    rf"(?P<noun>{'|'.join(_DESTROY_COLOR_NOUN_KINDS)})"
    + IF_COLOR_SUFFIX
)


def _destroy_color_adj(m: re.Match[str]) -> list[EffectSpec]:
    color = resolve_color_word(m.groupdict().get("color")) or resolve_color_word(m.groupdict().get("cond_color"))
    params: dict = {"target_kind": _DESTROY_COLOR_NOUN_KINDS[m.group("noun")]}
    if color:
        params["color"] = color
    return [EffectSpec("destroy", params)]


def _multi_target_builder(effect_type: str, allow_spell: bool = False):
    """`_destroy_multi_target`/`_exile_multi_target`'s shared body — they
    differ only in the emitted `EffectSpec` type and whether "target spell"
    is a legal recipient (legal to exile a spell, RULE 701.20b, not to
    destroy one)."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        params = _multi_target_params(m, allow_spell=allow_spell)
        if params is None:
            return None
        return [EffectSpec(effect_type, params)]

    return build


_destroy_multi_target = _multi_target_builder("destroy")


#: RULE 601.2c mass "destroy/exile all X [with a numeric filter]" board wipe
#: (Wrath of God/Damnation/Citywide Bust-shaped) — untargeted, the same
#: `selector` vocabulary `game/effects.py`'s `DestroyEffect`/`ExileEffect`
#: already support (previously only reachable via hand-authoring individual
#: cards in `ability_catalogue.py`; this is the general oracle-text form).
#: Only the two numeric filter kinds `_mass_selector_objects` actually
#: implements are recognized here — "power N or greater" has no mass-form
#: engine support, so it's deliberately left unmatched (fail-closed) rather
#: than silently dropped.
#: Both keyed off the shared `PERMANENT_TYPE_WORDS` vocabulary
#: (`subgrammars.py`) rather than independently hand-typing the same
#: five-to-seven words twice, once per number — "destroy all nonland
#: permanents..."/"Destroy **each** nonland permanent..." (Culling Ritual,
#: MEC-40) both reach the same "all_nonland_permanents" selector
#: (`_mass_selector_objects`, built for `_return_all_nonland`'s bounce
#: sibling) this way for free.
_MASS_DESTROY_NOUNS: dict[str, str] = {
    pluralize_permanent_type(w): all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}
#: "Destroy **each** artifact with mana value X or less." (Meltdown) —
#: the singular-noun/"each" phrasing of the same mass wipe, alongside the
#: far more common plural-noun/"all" one above; same selector targets, just
#: matched against a singular noun word.
_MASS_DESTROY_NOUNS_SINGULAR: dict[str, str] = {
    w: all_permanent_type_selector(w) for w in PERMANENT_TYPE_WORDS
}
#: The mana-value bound's own magnitude accepts ``x`` (Meltdown's own
#: "with mana value X or less", X being this spell's announced {X}) as well
#: as a literal digit — `_mass_destroy_filter_dict` carries the ``"x"``
#: sentinel straight into `DestroyEffect.filter`'s ``max_mana_value``/
#: ``min_mana_value`` key, which `RulesEngine._substitute_x` now knows how
#: to walk into (a plain digit bound like Damnation's own "mana value 3 or
#: less" never reaches this branch at all).
_MASS_DESTROY_FILTER = (
    r"(?: with (?:mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less)"
    r"|toughness (?P<tough>\d+) or greater"
    r"|power (?P<power>\d+) or (?P<power_cmp>greater|less)))?"
)


def _mass_destroy_filter_dict(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    filt: dict = {}
    if groups.get("mv"):
        n: Any = int(groups["mv"]) if groups["mv"] != "x" else "x"
        filt["max_mana_value" if groups["mv_cmp"] == "less" else "min_mana_value"] = n
    if groups.get("tough"):
        filt["min_toughness"] = int(groups["tough"])
    if groups.get("power"):
        n = int(groups["power"])
        filt["max_power" if groups["power_cmp"] == "less" else "min_power"] = n
    return filt or None


_DESTROY_ALL_RE = _c(
    rf"destroy (?:all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)})"
    rf"|each (?P<noun_sg>{'|'.join(_MASS_DESTROY_NOUNS_SINGULAR)}))"
    rf"(?P<opp> your opponents control)?{_MASS_DESTROY_FILTER}"
)

#: "Destroy all enchantments **your opponents control**." (Spring Cleaning)
#: — the opponent-scoped `_mass_selector_objects` sibling exists only for
#: artifacts/enchantments so far (no card needs "destroy all lands your
#: opponents control" &c. yet), so an ``opp`` scope on any other noun
#: fails closed.
_DESTROY_ALL_OPP_SELECTORS = {
    "all_enchantments": "opponents_enchantments",
    "all_artifacts": "opponents_artifacts",
}


def _destroy_all(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    noun = m.groupdict().get("noun")
    selector = _MASS_DESTROY_NOUNS[noun] if noun else _MASS_DESTROY_NOUNS_SINGULAR[m.group("noun_sg")]
    if m.groupdict().get("opp"):
        selector = _DESTROY_ALL_OPP_SELECTORS.get(selector)
        if selector is None:
            return None
    params: dict = {"selector": selector}
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("destroy", params)]


#: The "They can't be regenerated." tail (Wrath of God's own trailing
#: sentence) as one combined whole-body match — `parse_effect_body` tries
#: the *unsplit* body first, so this must span both sentences itself; the
#: plain `_destroy_all` above only ever sees this body with the tail still
#: attached (fullmatch fails) and so correctly declines it, falling through
#: to this row instead.
_DESTROY_ALL_NO_REGEN_RE = _c(
    rf"destroy all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)}){_MASS_DESTROY_FILTER}"
    rf"\. they can'?t be regenerated"
)


def _destroy_all_no_regen(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "selector": _MASS_DESTROY_NOUNS[m.group("noun")],
        "can_be_regenerated": False,
    }
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("destroy", params)]


_EXILE_ALL_RE = _c(rf"exile all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)})")


def _exile_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"selector": _MASS_DESTROY_NOUNS[m.group("noun")]})]


def _regenerate(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("regenerate", {"target_kind": kind})]


def _regenerate_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {"target_kind": None})]


#: "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
#: Baron Sengir-shaped) — a creature-subtype-filtered target. "another" is
#: cosmetic here: the plain ``"creature"`` target kind's own `legal_targets`
#: branch already excludes the ability's own source unconditionally (every
#: real card in this shape is an activated ability on a creature of the
#: named subtype, so it would otherwise be offered as its own legal
#: target) — the same reason a bare "target creature" ability doesn't need
#: an explicit "other" qualifier to stay off itself in this engine.
_REGENERATE_ANOTHER_TARGET_RE = _c(r"regenerate another target (?P<subtype>[a-z]+)")


def _regenerate_another_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("regenerate", {
        "target_kind": "creature",
        "creature_filter": {"subtype": m.group("subtype").capitalize()},
    })]


def _counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "counter target spell" / "… target noncreature spell" / "… target
    # instant or sorcery spell" / "… target spell with mana value N" — the
    # filter is extracted by the dedicated `SPELL_TARGET` companion grammar
    # (RULE 601.2c/115), not the generic TARGET rows (a countered spell's
    # "kind" is always "spell"; only *which* spells vary). "unless its
    # controller pays <cost>" (RULE 601 "Mana Leak" template) is an optional
    # tail on the same clause, independent of the filter.
    filt = resolve_spell_filter(m.group("target"))
    if filt is None:
        return None
    params: dict = dict(filt)
    if m.groupdict().get("cost"):
        params["unless_pays"] = m.group("cost")
    cond_color = resolve_color_word(m.groupdict().get("cond_color"))
    if cond_color:
        params["color"] = cond_color
    return [EffectSpec("counter", params)]


#: "Until end of turn, target creature gains '`<cost>`: `<effect>`.'"
#: (Retraction Helix-shaped, ~23 cache-wide cards on this template) — a
#: *resolve-time* grant of a full quoted ability (activated/triggered/
#: mana), unlike every other "gains `<keyword>` until end of turn" row
#: above (a bare flag keyword, no quotes). Reuses `static_handlers.
#: _quoted_ability_grant_effects` (the Aura/Equipment quoted-grant parser,
#: already general over all three ability kinds) wrapped in `GrantUntil
#: Effect`'s existing ``duration="end_of_turn"`` resolve-time shape
#: instead of a standing layer-6 static.
_GRANT_QUOTED_ABILITY_UNTIL_EOT_RE = _c(
    r"until end of turn, target creature gains \"(?P<inner>.+)\""
)


def _grant_quoted_ability_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import _quoted_ability_grant_effects  # local: avoid a module cycle

    grant = _quoted_ability_grant_effects(m.group("inner"))
    if grant is None:
        return None
    return [EffectSpec("grant_until", {
        "static": {"type": grant.type, "params": grant.params},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })]


def _cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_countered", {})]


#: RULE 119.3's "can't gain life this turn" rider (Roiling Vortex's
#: activated-ability effect) — `PreventLifeGainEffect`'s only printed
#: ``recipient`` so far.
_CANT_GAIN_LIFE_RE = _c(r"your opponents can'?t gain life this turn")


def _cant_gain_life(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("prevent_life_gain", {"recipient": "opponents"})]


def _change_target(m: re.Match[str]) -> list[EffectSpec]:
    # "…spell or ability…" always goes through `ChangeTargetEffect`'s
    # ``spell_or_ability`` branch (ENG-26's union stack-item lookup) rather
    # than folding "with a single target" into a spell-only filter — the
    # engine's own single-existing-target MVP limit already applies inside
    # that branch regardless of what's printed (see the effect's own
    # docstring), so the printed "with a single target" here is redundant
    # with, not narrower than, that limit.
    if m.group("kind") == "spell or ability":
        return [EffectSpec("change_target", {"spell_or_ability": True})]
    return [EffectSpec("change_target", {"single_target": True})]


def _mill(m: re.Match[str]) -> list[EffectSpec]:
    # "you mill N" / bare "mill N" → self; "target player/opponent mills N" → targeted.
    who = (m.groupdict().get("who") or "").strip()
    params: dict = {"count": int(m.group("n"))}
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    return [EffectSpec("mill", params)]


def _exile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent", *_SINGLE_TYPE_PERMANENT_KINDS):
        return None
    return [EffectSpec("exile", {"target_kind": kind, **_optional_param(m)})]


_exile_multi_target = _multi_target_builder("exile", allow_spell=True)


#: The target kinds "tap/untap target X" accepts — the plain permanent
#: types plus the controller-scoped creature kinds ("tap target creature
#: **an opponent controls**", Chillbringer/Berg Strider &c.; `legal_targets`
#: resolves all three).
_TAP_TARGET_KINDS = (
    "creature", "permanent", "legendary_permanent", "forest",
    "creature_you_control", "creature_you_dont_control", "other_creature_you_control",
    *_SINGLE_TYPE_PERMANENT_KINDS,
)


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in _TAP_TARGET_KINDS:
        return None
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": kind, "untap": untap, **_optional_param(m)})]


#: "tap N target creatures" / "untap up to two target lands" (RULE 115.1a
#: generalized to N>=2, Snap-shaped — `TapEffect.count` already supported
#: this; only the grammar was missing). Restricted to the same
#: creature/permanent kinds the singular `_tap` handler allows.
def _tap_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] not in ("creature", "permanent", *_SINGLE_TYPE_PERMANENT_KINDS):
        return None
    untap = m.group("verb").lower() == "untap"
    params["untap"] = untap
    return [EffectSpec("tap", params)]


def _tap_selector(m: re.Match[str]) -> list[EffectSpec]:
    # "untap all creatures you control" (Village Bell-Ringer's ETB) /
    # "untap each other creature you control" (Copperhorn Scout's own
    # attack trigger) — an untargeted mass effect, `game/effects.py`'s
    # `TapEffect.selector`, the same shape `_add_counters_selector` uses
    # for a mass counter effect.
    untap = m.group("verb").lower() == "untap"
    other = m.groupdict().get("other_all") or m.groupdict().get("other_each")
    selector = "other_creatures_you_control" if other else "creatures_you_control"
    return [EffectSpec("tap", {"selector": selector, "untap": untap})]


#: MEC-28: "untap all attacking creatures" (Karlach, Fury of Avernus) /
#: "untap each attacking creature" (Hexplate Wallbreaker's Equipment ETB) —
#: `TapEffect.selector`'s `"attacking_creatures"` mode, unscoped by
#: controller (`continuous.group_selector_objects`'s existing branch, the
#: same one Motivated Pony's anthem already reads).
def _tap_attacking_creatures(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"selector": "attacking_creatures", "untap": untap})]


#: "Untap it and all Samurai you control." (Godo, Bandit Warlord's own
#: attack trigger) — the compound "self **and** a subtype group" untap
#: `_tap_self`/`_tap_selector` each only cover one half of; two ordinary
#: `tap` `EffectSpec`s in sequence (the ability's own effect list, RULE
#: 608.2 printed order) rather than a single effect trying to express both
#: recipients at once.
_TAP_SELF_AND_SUBTYPE_RE = _c(
    r"(?P<verb>tap|untap) it and all (?P<subtype>[a-z]+) you control"
)


def _tap_self_and_subtype(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    subtype = m.group("subtype").rstrip("s")
    return [
        EffectSpec("tap", {"target_kind": None, "untap": untap}),
        EffectSpec("tap", {"selector": f"creatures_you_control_of_type_{subtype}", "untap": untap}),
    ]


#: "Untap this creature" (Devoted Druid's counter-cost untap ability) / "tap
#: ~" — the *self* form, no RULE 115 target at all (`target_kind=None` makes
#: `TapEffect` act on its own source, mirroring `AttachEffect`'s ``~``/"it"
#: self-reference).
_SELF_SUBJECT = (
    r"(?:~|it|this permanent|this creature|this artifact|this land|this enchantment)"
)


def _tap_self(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": None, "untap": untap})]


#: MEC-28: "untap that creature" (Finest Hour's own attacks-alone trigger) —
#: the `group_subject_only` sibling of `_tap_self`'s bare "it"/"~" pronoun:
#: "that creature" is genuinely ambiguous (it means *whichever creature
#: matched this ability's group-subject trigger condition* here, but means
#: an earlier clause's own target on `_lockdown`'s `previous_subject_only`
#: row), so it's a dedicated row rather than added to `_SELF_SUBJECT`, only
#: offered when the caller confirms the trigger really has a group subject.
#: Same output shape as `_tap_self` — `effect_binder.
#: _retarget_implicit_subject_effects` is what turns the resulting
#: ``target_kind: None`` into a live per-firing read at bind time.
_TAP_GROUP_SUBJECT_RE = _c(r"(?P<verb>tap|untap) that creature")


#: "enchanted creature"/"equipped creature"/"fortified land" — an Aura/
#: Equipment/Fortify's own activated-ability body implicitly acting on
#: whatever it's attached to (RULE 303.4/301.5), no player choice at all
#: (`TapEffect`/`PumpEffect`'s ``"attached_permanent"`` mode) — the
#: activated-ability sibling of `effect_binder._subject_condition`'s
#: ``"attached_permanent"`` *trigger*-subject concept. The same five printed
#: subject phrases `static_handlers._ATTACHED_SUBJECTS` lists — "enchanted
#: permanent"/"enchanted land" appear on real Auras that enchant something
#: other than a creature (Flood the Engine's "When ~ enters, tap enchanted
#: permanent.", Animal Boneyard).
_ATTACHED_SUBJECT = (
    r"(?:enchanted creature|equipped creature|fortified land"
    r"|enchanted permanent|enchanted land)"
)


#: "{U}: Tap enchanted creature."/"{U}: Untap enchanted creature." (Freed
#: from the Real/Pemmin's Aura-shaped Aura activated abilities).
def _tap_attached(m: re.Match[str]) -> list[EffectSpec]:
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": "attached_permanent", "untap": untap})]


#: "Sacrifice ~."/"Sacrifice this enchantment." (Dress Down/Underworld
#: Breach-shaped standing end-step self-sac) — the self form, no player
#: choice or RULE 115 target (RULE 701.17).
def _sacrifice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("sacrifice_self", {})]


#: "Sacrifice ~ unless you pay `<cost>`." (RULE 701.17 + an "unless"
#: payment) — the single most common upkeep-trigger body on older cards
#: (Arcades Sabboth, Breeding Pit, Child of Gaea, Chromium, Kuro; Aura
#: Flux/Coral Net grant it onto another permanent). Unlike `_sacrifice_self`
#: this is a *choice*: `SacrificeUnlessPayEffect` opens the same
#: pay-or-lose-it `pending_choice` ward uses.
#:
#: The cost is a deliberately **closed** list of shapes rather than free
#: text handed to `costs.parse_activation_cost`, because that function
#: returns a *free* cost for anything it doesn't understand — which here
#: would silently read as "pay nothing to keep it". Every excluded variant
#: is one the engine genuinely can't honour and so stays unclaimed:
#:
#: * "pay its echo cost"/"pay its upkeep cost for each age counter on it" —
#:   Echo and Cumulative Upkeep's own reminder text, a self-referential cost
#:   (and those two keywords aren't modeled at all).
#: * "pay {G} **for each** wind counter on it" (Sandstorm Ambush) — a scaled
#:   cost; `parse_activation_cost` would quietly drop the multiplier.
#: * "discard a card **at random**" — the engine's `discard` auto-picks and
#:   has no random mode, so claiming it would misrepresent the card.
#: * "sacrifice **four** creatures" — `ActivationCost.sacrifice` is one
#:   permanent.
_UNLESS_COST = (
    r"(?:pay (?:\{[^{}]+\})+"
    r"|pay \d+ life"
    r"|discard a card"
    r"|sacrifice (?:a|another) (?:creature|permanent|artifact|enchantment|land))"
)
_SACRIFICE_UNLESS_PAY_RE = _c(
    rf"sacrifice {_SELF_SUBJECT} unless you (?P<cost>{_UNLESS_COST})"
)


def _sacrifice_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("sacrifice_unless_pay", {"cost": m.group("cost")})]


#: "Destroy ~ unless you pay `<cost>`." (RULE 701.16 + an "unless" payment)
#: — the real-destruction sibling of `_SACRIFICE_UNLESS_PAY_RE` above (The
#: Tabernacle at Pendrell Vale's mass granted upkeep trigger, "All creatures
#: have 'At the beginning of your upkeep, destroy this creature unless you
#: pay {1}.'"). Shares `_UNLESS_COST`'s closed cost vocabulary for the same
#: reason that handler does — see its own docstring.
_DESTROY_UNLESS_PAY_RE = _c(
    rf"destroy {_SELF_SUBJECT} unless you (?P<cost>{_UNLESS_COST})"
)


def _destroy_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("destroy_unless_pay", {"cost": m.group("cost")})]


#: "Exile ~."/"Exile this card." (Teferi's Protection/Mnemonic Betrayal's
#: trailing self-exile) — the self form, `ExileEffect`'s `target_kind=None`.
def _exile_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {"target_kind": None})]


#: "return target creature to its owner's hand" / "return a land you control
#: to its owner's hand" (RULE 701.3) — the bounce family. ``target_kind``
#: reuses the shared `TARGET` grammar, so this claims both a genuine RULE 115
#: target and the "a land you control" controller-restricted choice the same
#: way; restricted to the shapes real bounce cards actually use.
_RETURN_TO_HAND_KINDS: frozenset[str] = frozenset(
    {"creature", "permanent", "nonland_permanent", "any", "creature_you_control", "land_you_control"}
)


def _return_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in _RETURN_TO_HAND_KINDS:
        return None
    return [EffectSpec("return_to_hand", {"target_kind": kind, **_optional_param(m)})]


#: RULE 601.2c mass "return all nonland permanents with mana value X or less
#: to their owners' hands." (Displacement Wave) — `ReturnToHandEffect`'s own
#: sibling of `_destroy_all`'s board wipe, reusing the exact same
#: `_MASS_DESTROY_FILTER`/`_mass_destroy_filter_dict` vocabulary (including
#: the ``"x"`` sentinel, substituted at cast time by `RulesEngine.
#: _substitute_x`, which already walks any effect's ``filter`` attribute
#: generically).
_RETURN_ALL_NONLAND_RE = _c(
    rf"return all nonland permanents{_MASS_DESTROY_FILTER} to their owners'? hands?"
)


def _return_all_nonland(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"selector": "all_nonland_permanents"}
    filt = _mass_destroy_filter_dict(m)
    if filt:
        params["filter"] = filt
    return [EffectSpec("return_to_hand", params)]


#: "put target creature on top of its owner's library" (RULE 701.3 — Time
#: Ebb/Griptide/Roil Spout/Vedalken Dismisser-shaped tempo bounce, 10 SOLO
#: cards, `parser_probe.py blocked`) / "…on the bottom of its owner's
#: library" (rarer — same shape, ``position="bottom"``). `ReturnToLibraryEffect`
#: is `return_to_hand`'s library-destination sibling.
def _return_to_library(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in _RETURN_TO_HAND_KINDS:
        return None
    position = "bottom" if m.group("pos") == "bottom" else "top"
    return [
        EffectSpec(
            "return_to_library",
            {"target_kind": kind, "position": position, **_optional_param(m)},
        )
    ]


#: "Return ~ to its owner's hand." (RULE 701.3, self form — no RULE 115
#: target and no player choice, the bounce sibling of `_sacrifice_self`/
#: `_exile_self`). Two families of real cards, both Aura-heavy:
#: Rancor/Launch/Aspect of Mongoose's "When ~ dies, return it to its
#: owner's hand." trigger (`normalize` folds RULE 700.4's long "is put
#: into a graveyard from the battlefield" phrasing to "dies", and ``it``
#: to ``~``), and Flickering Ward/Fiery Mantle's "{W}: Return ~ to its
#: owner's hand." activated ability. Resolves against the effect's own
#: source wherever it currently is — battlefield *or* graveyard, since a
#: dies-trigger's source has already moved (RULE 400.7) by the time the
#: ability resolves and `RulesEngine.return_to_hand` moves an object from
#: whatever zone it's in.
def _return_self_to_hand(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"target_kind": None})]


#: "return two target creatures to their owners' hands" (RULE 115.1a
#: generalized to N>=2) — the plural sibling of `_return_to_hand`.
def _return_to_hand_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] not in _RETURN_TO_HAND_KINDS:
        return None
    return [EffectSpec("return_to_hand", params)]


#: "Return those creatures to their owners' hands." (PAR-1, Run Away
#: Together) — the indirect-referent sibling of `_return_to_hand_multi_
#: target`: the group was already announced (and, for "controlled by
#: different players", already constrained) by the preceding "choose N
#: target creatures …" clause (`_choose_targets_group`), so this clause
#: names no target of its own at all — only offered when that preceding
#: clause actually chose one (`EffectHandler.previous_subject_only`).
_RETURN_PREVIOUS_GROUP_RE = _c(
    r"(?:then )?return (?:those creatures|them) to their owners'? hands?"
)


def _return_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("return_to_hand", {"previous_subject": True})]


#: A graveyard clause's card-*type* word, right before "card" — "target
#: [instant or sorcery/sorcery/nonland permanent/creature/artifact/
#: enchantment/land/permanent] card", or no word at all for a bare "target
#: card" (longest-alternative-first so "nonland permanent" wins over
#: "permanent"; ``sorcery`` alone — MEC-24, Recoup's own "target **sorcery**
#: card" — doesn't need the same ordering care since it starts on a
#: different word than "instant or sorcery").
_GRAVEYARD_TYPE_WORD = (
    r"instant or sorcery|sorcery|nonland permanent|creature|artifact|enchantment|land|permanent"
)
#: A graveyard clause's *scope* — whose graveyard — "your"/"a" (any single
#: graveyard)/"an opponent's" (longest-alternative-first, same reason).
_GRAVEYARD_SCOPE_WORD = r"an opponent'?s|your|a"
#: Scope word → `targeting._GRAVEYARD_SCOPE_PREFIXES` key.
_GRAVEYARD_SCOPE_KIND: dict[str, str] = {
    "your": "graveyard", "a": "any_graveyard", "an opponents": "opponent_graveyard",
}


def _graveyard_target_kind(type_word: Optional[str], scope_word: str) -> Optional[str]:
    """A graveyard clause's ``(type_word, scope_word)`` → engine
    ``target_kind`` string (`game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`),
    or ``None`` if either half isn't one of the recognised shapes."""
    scope_key = _GRAVEYARD_SCOPE_KIND.get(re.sub(r"'", "", scope_word.strip().lower()))
    if scope_key is None:
        return None
    type_key = {
        "": "card", "instant or sorcery": "instant_or_sorcery",
        "nonland permanent": "nonland_permanent",
    }.get((type_word or "").strip().lower(), (type_word or "").strip().lower() or "card")
    return f"{scope_key}_{type_key}"


#: "return target [type] card [with mana value N or less] from [scope]
#: graveyard to the battlefield/your hand/its owner's hand" / "put target
#: [type] card from [scope] graveyard onto the battlefield under its
#: owner's control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
#: recursion family — see `game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS`
#: for the scope × type vocabulary this claims). Both verb shapes land the
#: object under its own *owner*'s control — the "steal it for yourself"
#: shape is `_reanimate_under_your_control` below, a genuinely different
#: effect. The optional mana-value cap (Auriok Salvagers-shaped) is the
#: same `TargetSpec.max_mana_value` offer-time filter `destroy_mv` already
#: uses, not a new one.
_RETURN_FROM_GRAVEYARD_RE = _c(
    rf"return (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card"
    rf"(?: with mana value (?P<mv>\d+) or less)? from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard to "
    r"(?P<dest>the battlefield|your hand|its owner'?s hand)"
)
_PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under its owner'?s control"
)


def _return_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    params: dict = {"target_kind": kind, "destination": destination}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    mv = m.groupdict().get("mv")
    if mv is not None:
        params["max_mana_value"] = int(mv)
    return [EffectSpec("return_from_graveyard", params)]


#: "return up to two target creature cards from your graveyard to your
#: hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2 — Back for
#: Seconds/Dead Revels/Death's Duet/Entreat the Dead-shaped, a large real
#: family) — the plural sibling of `_RETURN_FROM_GRAVEYARD_RE`. The type
#: word itself doesn't inflect ("creature cards", not "creatures cards").
_RETURN_FROM_GRAVEYARD_MULTI_RE = _c(
    rf"return {_MULTI_TARGET_QUANTIFIER}target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyards? to "
    r"(?P<dest>the battlefield|your hand|their owners'? hands)"
)


def _return_from_graveyard_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
    if m.groupdict().get("range_min") is not None:
        # ENG-30: "return 1 or 2 target creature cards from your graveyard
        # to your hand/the battlefield" (Infernal Rebirth/Leonardo's
        # Technique-shaped) — a genuine RULE 601.2c range, not "up to N".
        range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
        if range_min < 1 or range_max <= range_min:
            return None
        return [EffectSpec("return_from_graveyard", {
            "target_kind": kind, "destination": destination,
            "count": range_min, "count_max": range_max,
        })]
    count = int(m.group("count"))
    if count < 2:
        return None
    params: dict = {"target_kind": kind, "destination": destination, "count": count}
    if m.groupdict().get("up_to"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: "put target [type] card from [scope] graveyard onto the battlefield
#: under your control" (Reanimate/Rise from the Grave/Virtue of Persistence)
#: — unlike the two shapes above, this one *steals* the card for the
#: activating/casting player regardless of whose graveyard it came from.
_REANIMATE_UNDER_YOUR_CONTROL_RE = _c(
    rf"put (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard onto the battlefield under your control"
)


def _reanimate_under_your_control(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind, "destination": "battlefield", "under_your_control": True}
    if m.groupdict().get("up_to_one"):
        params["optional"] = True
    return [EffectSpec("return_from_graveyard", params)]


#: PAR-15's "any number of" siblings of the two shapes above — always "your
#: own graveyard" on every real card using either ("put ... on top of your
#: library": Bone Harvest/Footbottom Feast/Forever Young/Gravepurge; "shuffle
#: ... into your library": Piper's Melody/Renewing Touch/Perpetual Timepiece/
#: The Bath Song), so unlike `_RETURN_FROM_GRAVEYARD_RE` neither needs the
#: full opponent/any-graveyard scope vocabulary. The shuffle shape is
#: modeled as "put on the bottom, then shuffle" — see `ReturnFromGraveyard
#: Effect.shuffle_after` — since the position `library_bottom` gives it is
#: immediately randomized away by the shuffle, matching "shuffled into your
#: library" exactly.
_RETURN_FROM_GRAVEYARD_TOP_ANY_RE = _c(
    rf"put any number of target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard on top of your library"
)
_RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE = _c(
    rf"shuffle any number of target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?cards from "
    r"your graveyard into your library"
)


def _return_from_graveyard_top_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_top",
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


def _return_from_graveyard_shuffle_any(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), "your")
    if kind is None:
        return None
    return [EffectSpec("return_from_graveyard", {
        "target_kind": kind, "destination": "library_bottom", "shuffle_after": True,
        "count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    })]


#: "exile [up to one] target [type] card from [scope] graveyard" (RULE
#: 701.5a) — the Deathrite Shaman/Scavenging Ooze/Lion Sash graveyard-hate
#: family; almost always "a graveyard" in practice, but the same scope
#: vocabulary applies. The `UP_TO_ONE` prefix (RULE 115.1a — PAR-18's own
#: "exile up to 1 target creature card from a graveyard[. create a token
#: that's a copy of that card]" antecedent, Ardyn/Anikthea-shaped) reuses
#: `_optional_param`/`target_is_optional` the same way every other
#: `{TARGET}`-bearing handler does, even though this clause hand-rolls its
#: own "target" grammar instead of embedding `TARGET` (the graveyard scope/
#: type vocabulary predates that macro and has its own word lists).
#: The determiner is ``target`` for the RULE 115 form (Deathrite Shaman) or a
#: bare ``a``/``an`` for the untargeted reanimator-cycle antecedent ("you may
#: exile a creature card from your graveyard. Create a token that's a copy of
#: that card." — God-Pharaoh's Gift/Séance); both resolve to the same
#: `graveyard_*` `EffectSpec`, the "target" nuance (redirect/"can't be
#: targeted") being immaterial for a graveyard-card pick this grammar models.
_EXILE_FROM_GRAVEYARD_RE = _c(
    rf"exile (?P<up_to_one>{UP_TO_ONE})(?:target |an? )(?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard"
)


def _exile_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    return [EffectSpec("exile", {"target_kind": kind, **_optional_param(m)})]


#: "exile target player's graveyard." (Bojuka Bog) / "exile all cards from
#: target player's graveyard." (Tormod's Crypt) — a whole *graveyard*
#: targeted by player, not a single card from one (`_EXILE_FROM_GRAVEYARD_RE`
#: above) — the two phrasings are the same effect, so one builder claims both.
_EXILE_TARGET_GRAVEYARD_RE = _c(
    r"exile (?:all cards from )?target player'?s graveyard"
)


def _exile_target_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("exile_target_graveyard", {"target_kind": "player"})]


#: "search your library for a [<criteria>] card, [reveal it,] put it/that
#: card/them/those cards <destination>, then shuffle." (RULE 701.19, the
#: general tutor/ramp/fetch family — Demonic Tutor/Rampant Growth/Farseek/
#: Nature's Lore/Crop Rotation/Eladamri's Call/Buried Alive/Sylvan
#: Scrying-shaped) and its reordered sibling "..., [reveal it,] then shuffle
#: and put it/that card/the card on top." (Vampiric/Mystical/Enlightened/
#: Worldly Tutor-shaped). Both map onto the engine's existing `"search"`
#: `EffectSpec` (`game/effects.py`'s `SearchLibraryEffect`, already
#: parameterized on criteria/destination/count — `tests/
#: test_search_popular_tutors.py` proves it against 15 real popular tutors)
#: — no new effect type needed, just recognition. Three siblings below
#: extend the same `"search"` `EffectSpec` onto its ``zones``/
#: ``destinations``/``exile_rest`` params (`RulesEngine.request_search`):
#: "library and/or graveyard" combined search (`_search_zone_put`, ~50 real
#: cards — the backgrounds/planeswalker-tutor family), a split destination
#: per found card (`_search_split_destination` — Cultivate/Kodama's Reach),
#: and "search for N cards and exile the rest" (`_search_exile_rest` —
#: Doomsday). Deliberately still NOT attempted here (fail-closed, real cards
#: found but left unclaimed): any qualifier after the noun phrase such as
#: "with mana value X or less" (Green Sun's Zenith/Chord of Calling/Finale
#: of Devastation — X is a spell's own cast-time choice, not a static
#: criterion this grammar can express), a name criterion whose own name
#: contains a comma ("a card named Angrath, Minotaur Pirate" —
#: indistinguishable from the following put-clause's own comma without a
#: name dictionary), and a searched-for subtype not in `_SEARCH_TYPE_WORD`'s
#: vocabulary ("a Shrine card"/"an Ally creature card").
#:
#: The type-word vocabulary intentionally also carries the five basic land
#: names (a card can be searched for by name, "a Forest card"/"a Plains,
#: Island, Swamp, or Mountain card" — Nature's Lore/Farseek), separate from
#: "basic land" (Rampant Growth) which sets `criteria["basic"]` instead of a
#: `type` filter — the two are mutually exclusive alternatives tried in that
#: order (longest/most-specific first), never combined.
#: "Equipment" is a subtype, not a main card type, but `models.card_query.
#: _type_matches` does a plain substring check against the whole printed
#: type line ("Artifact — Equipment") rather than only the pre-em-dash main
#: types — the same reason "Forest"/"Island" already work as entries here
#: despite being land subtypes too. Adding it costs nothing engine-side,
#: purely a missing vocabulary word (Steelshaper's Gift/Stoneforge
#: Mystic-shaped).
_SEARCH_TYPE_WORD = (
    r"artifact|creature|enchantment|instant|planeswalker|sorcery|land|"
    r"plains|island|swamp|mountain|forest|equipment"
)
#: An "or"/comma-separated list of 1+ type words, same shape as
#: `subgrammars._SPELL_TYPE_LIST` (kept separate/local since this vocabulary
#: — land + basic land names — is specific to a library search, not a spell
#: target filter).
_SEARCH_TYPE_LIST = (
    rf"(?:{_SEARCH_TYPE_WORD})(?:,\s*(?:{_SEARCH_TYPE_WORD}))*"
    rf"(?:,?\s+or\s+(?:{_SEARCH_TYPE_WORD}))?"
)
#: A colour word ahead of the type list — "search your library for a
#: **blue** instant card" (Merchant Scroll), "a **green** creature card"
#: (Green Sun's Zenith/Magus of the Order/Natural Order/Shadow-Rite
#: Priest) — captured and mapped onto `models.card_query`'s own ``color``
#: key (matched against the card's colour identity), the same key/matcher
#: `_destroy_color_adj` already reuses via `resolve_color_word` — not
#: dropped, despite this module's older docstrings elsewhere describing it
#: that way (that was a real gap until `SearchLibraryEffect.criteria`
#: started reaching `card_query.matches`, not a documented permanent
#: choice). ``colorless`` (Eye of Ugin's "a colorless creature card") is
#: kept local to this search vocabulary rather than added to the shared
#: `subgrammars.COLOR_WORD_ALT`/`resolve_color_word` every other colour-word
#: consumer (target filters, "if it's `<color>`" suffixes, …) reuses — those
#: are genuinely WUBRG-only templates, "colorless" isn't a valid substitute
#: for any of them today, so widening that shared vocabulary would risk
#: silently claiming a clause it shouldn't. `_search_criteria_from_match`/
#: `_search_zone_criteria_from_match` handle it directly rather than through
#: `resolve_color_word`, which only maps WUBRG letters.
_SEARCH_COLOR_WORD = r"white|blue|black|red|green|colorless"
#: "…with mana value X or less" (Green Sun's Zenith/Chord of Calling) — X
#: is this spell's own announced {X}, so the captured magnitude is the
#: literal ``"x"``/``"-x"`` sentinel `RulesEngine._substitute_x` rewrites
#: once the spell actually resolves, exactly like every other X-scaled
#: one-shot effect; a literal digit bound ("…with mana value 3 or less")
#: is accepted the same way but has no known real card on this exact
#: search-noun-phrase shape yet.
_SEARCH_MV_QUALIFIER = (
    r"(?: with mana value (?P<mv>\d+|x) or (?P<mv_cmp>greater|less))?"
)
#: The noun phrase after "search your library for": a determiner ("a"/"an"/
#: "up to N"), an optional "basic" qualifier (sets `basic`), then either a
#: `_SEARCH_TYPE_LIST` (sets `types` — "land" is itself one of that list's
#: words, so bare "basic land" still resolves to ``{"basic": True}`` with no
#: separate case) or neither (a bare "a card"), then "card(s)", then an
#: optional trailing mana-value qualifier. "Basic" and a type list combine
#: freely — "a basic Forest, Plains, or Island card" (the Panorama/Landscape/
#: Monument tri-land fetch cycles, Bant Panorama-shaped: ~40 real cards on
#: this exact combined shape) narrows the search to *basic* lands of *those*
#: named types, not "basic land" (any basic) or a bare type list (any card of
#: that type, not necessarily basic) alone.
_SEARCH_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<color>{_SEARCH_COLOR_WORD})\s+)?"
    r"(?:(?P<basic>basic)\s+)?"
    rf"(?P<types>{_SEARCH_TYPE_LIST})?\s*"
    r"cards?"
    + _SEARCH_MV_QUALIFIER
)
#: Whichever pronoun/noun-phrase a card's "reveal ~"/"put ~ <dest>" clause
#: uses for the found card — every variant found in the popular-tutor cache
#: scan (Wishclaw Talisman's "it", most tutors' "that card", Buried Alive's
#: plural "them", Worldly Tutor's "the card").
_SEARCH_PRONOUN = r"(?:it|that card|them|those cards|the card)"
#: An optional "reveal <pronoun>," clause between the criteria and the
#: put/shuffle tail (Eladamri's Call/Mystical/Enlightened/Worldly Tutor) —
#: purely descriptive text at this engine's fidelity (no separate game-state
#: effect: the found card is already known to both players via the search
#: choice), so it's consumed and dropped, not modeled as its own effect.
_SEARCH_REVEAL = rf"(?:reveal {_SEARCH_PRONOUN},?\s*)?"
#: Where the found card goes — order matters ("battlefield tapped" must be
#: tried before the bare "battlefield" row so it isn't left partially
#: unconsumed).
_SEARCH_DESTINATION_ROWS: list[tuple[str, str]] = [
    (r"onto the battlefield tapped", "battlefield_tapped"),
    (r"onto the battlefield", "battlefield"),
    (r"into your hand", "hand"),
    (r"into your graveyard", "graveyard"),
]
_SEARCH_DESTINATION_ALT = "|".join(f"(?:{frag})" for frag, _ in _SEARCH_DESTINATION_ROWS)


def _search_destination_kind(phrase: str) -> Optional[str]:
    text = phrase.strip()
    for frag, kind in _SEARCH_DESTINATION_ROWS:
        if re.fullmatch(frag, text, re.IGNORECASE):
            return kind
    return None

#: "Its controller may search their library for a basic land card, put it
#: onto the battlefield, then shuffle." (Assassin's Trophy/Geomancer's
#: Gambit/Ghost Quarter-shaped — always the trailing sentence after a
#: "Destroy target land/permanent an opponent controls." clause the
#: ordinary `destroy` handler already claims on its own) — `SearchLibraryEffect`'s
#: ``player="previous_target_controller"`` sentinel (the same one
#: `PayCostThenEffect`'s own ``payer`` param already uses for Chain of
#: Vapor's "that permanent's controller may sacrifice a land"), since the
#: acting player here is whoever just lost the destroyed permanent, not
#: this spell's own caster.
_DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE = _c(
    r"its controller may search (?:its|their) library for a basic land card, "
    r"put it onto the battlefield, then shuffle"
)


def _destroy_controller_search_basic_land(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "search",
            {
                "criteria": {"basic": True},
                "destination": "battlefield",
                "optional": True,
                "player": "previous_target_controller",
            },
        )
    ]


#: "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." — the common put-then-shuffle order.
_SEARCH_PUT_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: "search your library for <criteria> that share a land type, [reveal
#: <pronoun>,] put <pronoun> <destination>, then shuffle." (Myriad
#: Landscape, MEC-43 round 3) — the same put-then-shuffle order as
#: `_SEARCH_PUT_THEN_SHUFFLE_RE` just above, plus the cross-pick "that share
#: a land type" qualifier (RULE 305.6) between the criteria and the
#: put-clause; a separate regex rather than an optional group spliced into
#: the shared one, since only this one shape maps onto `"search"`'s new
#: ``share_land_type`` param (`SearchLibraryEffect`/`RulesEngine.
#: request_search`).
_SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA} that share a land type,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)
#: "search your library for <criteria>, [reveal <pronoun>,] then shuffle and
#: put <pronoun> on top [of your library]." — the reordered shuffle-then-put
#: order, always to the top of the library (Vampiric/Mystical/Enlightened/
#: Worldly Tutor).
_SEARCH_SHUFFLE_THEN_PUT_TOP_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"then shuffle and put {_SEARCH_PRONOUN} on top(?: of your library)?"
)


def _search_mv_qualifier_from_match(m: re.Match[str]) -> dict:
    """The trailing "with mana value X or less/greater" qualifier, if
    present — shared by `_SEARCH_CRITERIA` and `_SEARCH_ZONE_CRITERIA`,
    both of which name their groups ``mv``/``mv_cmp`` identically."""
    mv = m.groupdict().get("mv")
    if not mv:
        return {}
    n: Any = int(mv) if mv != "x" else "x"
    key = "max_mana_value" if m.groupdict().get("mv_cmp") == "less" else "min_mana_value"
    return {key: n}


def _search_color_from_match(m: re.Match[str]) -> Optional[str]:
    """The captured ``color`` group → a WUBRG letter, ``"colorless"``
    (`_SEARCH_COLOR_WORD`'s own local addition — see its docstring for why
    this isn't `resolve_color_word`), or ``None``."""
    word = (m.groupdict().get("color") or "").strip().lower()
    if word == "colorless":
        return "colorless"
    return resolve_color_word(word)


def _search_criteria_from_match(m: re.Match[str]) -> dict:
    crit: dict = {}
    basic = bool(m.groupdict().get("basic"))
    if basic:
        crit["basic"] = True
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        # Bare "basic land" stays `{"basic": True}` alone (pre-existing
        # shape, Rampant Growth) — "land" is redundant once `basic` is set
        # (every basic card is a land), so it's only kept as a `type` filter
        # when it names something *besides* plain "land" ("a basic Forest,
        # Plains, or Island card" — the Panorama/Landscape/Monument tri-land
        # cycles, `_SEARCH_CRITERIA`'s combined basic+type-list shape).
        if not (basic and words == ["land"]):
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    return crit


def _search_count_from_match(m: re.Match[str]) -> Optional[int]:
    count = m.groupdict().get("count")
    return int(count) if count is not None else None


def _search_put_then_shuffle(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": destination}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


def _search_put_then_shuffle_share_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": destination,
        "share_land_type": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for a card with mana value less than or equal to the
#: number of lands you control, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." (Beseech the Queen, MEC-43 round 3) — a
#: board-count mana-value bound instead of `_SEARCH_CRITERIA`'s own literal
#: digit/``x`` (`_SEARCH_MV_QUALIFIER`), so it's its own regex rather than a
#: fourth `_SEARCH_MV_QUALIFIER` alternative; maps onto `"search"`'s
#: ``mana_value_from`` param with the new ``"count_selector"`` source
#: (`SearchLibraryEffect._resolved_criteria`, `continuous.count_selector`'s
#: existing ``"lands_you_control"`` entry).
_SEARCH_MV_LANDS_QUALIFIER_RE = _c(
    r"search your library for a card with mana value less than or equal to "
    r"the number of lands you control,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_mv_lands_qualifier(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "mana_value_from": {"source": "count_selector", "count_selector": "lands_you_control"},
                "destination": destination,
            },
        )
    ]


#: "search your library for a snow permanent card, a legendary card, or a
#: Saga card, [reveal <pronoun>,] put <pronoun> <destination>, then
#: shuffle." (Search for Glory, MEC-43 round 3) — a three-way OR across
#: disjoint criteria shapes (a "snow" supertype card that's also a
#: *permanent*, vs. two plain type-line substrings) `_SEARCH_CRITERIA`'s own
#: single type-list grammar can't express, so it's its own regex mapped
#: straight onto `models.card_query`'s already-general ``"or"`` combinator —
#: "snow permanent" is ``{"type": "Snow", "without_type": ["Instant",
#: "Sorcery"]}`` (RULE 205.4g's supertype, minus the two non-permanent card
#: types). This card's own trailing life-gain sentence is a wholly separate
#: clause (`_GAIN_LIFE_PER_SNOW_SPENT_RE` below), reached independently by
#: the segmenter's own period-connector split, not by this regex.
_SEARCH_SNOW_LEGENDARY_SAGA_RE = _c(
    r"search your library for a snow permanent card, a legendary card, or a saga card,?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_snow_legendary_saga(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    criteria = {
        "or": [
            {"type": "Snow", "without_type": ["Instant", "Sorcery"]},
            {"type": "Legendary"},
            {"type": "Saga"},
        ]
    }
    return [EffectSpec("search", {"criteria": criteria, "destination": destination})]


#: "You gain 1 life for each {S} spent to cast this spell." (Search for
#: Glory's own trailing sentence) — reads `GameObject.mana_spent_to_cast_
#: snow` (MEC-43 round 3, `ManaPool.snow_pool`) via the already-general
#: ``"gain_life"`` `count_selector` hook (`continuous.count_selector`'s new
#: ``"snow_mana_spent_to_cast"`` entry), the same self-referential idiom
#: `sacrificed_cost_mana_value`/`sacrificed_cost_power` already use. Scoped
#: to the literal "1 life" this card prints — no known card scales the
#: amount, so a multiplier is left unbuilt rather than guessed at.
_GAIN_LIFE_PER_SNOW_SPENT_RE = _c(r"you gain 1 life for each \{s\} spent to cast this spell")


def _gain_life_per_snow_spent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_life", {"count_selector": "snow_mana_spent_to_cast"})]


#: "search your library for <criteria>, put <pronoun> onto the battlefield,
#: attach it to a creature you control, then shuffle." (Stonehewer Giant/
#: Quest for the Holy Relic-shaped combined search-then-attach — MEC-12
#: sixth pass) — a strict superset of `_SEARCH_PUT_THEN_SHUFFLE_RE`'s own
#: "put <pronoun> onto the battlefield, then shuffle" shape with the attach
#: clause spliced in, mapped onto `"search"`'s new
#: ``attach_to_creature_you_control`` param (`SearchLibraryEffect`).
#: Destination is always the battlefield (the attach clause presupposes
#: it), so unlike the plain family this doesn't need a `dest` capture group.
_SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"put {_SEARCH_PRONOUN} onto the battlefield,?\s*"
    r"attach it to a creature you control,?\s*"
    r"then shuffle"
)


def _search_put_attach_then_shuffle(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": "battlefield",
        "attach_to_creature_you_control": True,
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


def _search_shuffle_then_put_top(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"criteria": _search_criteria_from_match(m), "destination": "library_top"}
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for up to N basic land cards, reveal those cards,
#: put one <destA> and the other <destB>, then shuffle." (Cultivate/Kodama's
#: Reach-shaped split destination — RULE 701.19 same as the plain family
#: above, just two different destinations for the two picks instead of one
#: shared `destination`; maps onto `"search"`'s `destinations` param,
#: positional against the picks).
_SEARCH_SPLIT_DESTINATION_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    # "one" is folded to "1" by `normalize`'s spelled-number pass (it can't
    # tell this "one" is a pronoun, not a count) — match the folded form.
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT}),?\s*"
    r"then shuffle"
)


def _search_split_destination(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    params: dict = {
        "criteria": _search_criteria_from_match(m),
        "destination": dest1,
        "destinations": [dest1, dest2],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library for N cards. Put 1 <destA> and the other <destB>.
#: Then shuffle." (Final Parting, MEC-43 round 3) — the same split
#: destination as `_SEARCH_SPLIT_DESTINATION_RE` just above, but printed as
#: three plain sentences (bare "N cards", no criteria/reveal clause) instead
#: of one comma-joined one, so it needs its own literal ``\.\s*`` sentence
#: boundaries rather than reusing `_SEARCH_CRITERIA`/`_SEARCH_REVEAL` (same
#: idiom `_SEARCH_EXILE_REST_RE` below already uses for its own two-sentence
#: Doomsday shape).
_SEARCH_TWO_CARDS_SPLIT_RE = _c(
    r"search your library for (?P<count>\d+) cards?\.\s*"
    rf"put 1 (?P<dest1>{_SEARCH_DESTINATION_ALT}) and the other "
    rf"(?P<dest2>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"then shuffle"
)


def _search_two_cards_split(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dest1 = _search_destination_kind(m.group("dest1"))
    dest2 = _search_destination_kind(m.group("dest2"))
    if dest1 is None or dest2 is None:
        return None
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": dest1,
                "destinations": [dest1, dest2],
                "count": int(m.group("count")),
            },
        )
    ]


#: The criteria noun phrase for a "library and/or graveyard" search — same
#: basic-land/type-list alternatives as `_SEARCH_CRITERIA`, plus a bare-name
#: alternative ("a card named <Name>") this family's real cards lean on
#: heavily (planeswalker/background tutors); restricted to a name with no
#: internal comma (see the module docstring above for why).
_SEARCH_ZONE_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<color>{_SEARCH_COLOR_WORD})\s+)?"
    r"(?:"
    r"(?P<basic>basic land) cards?"
    rf"|card named (?P<name>[a-z][a-z' -]*?)"
    rf"|(?P<types>{_SEARCH_TYPE_LIST}) cards?"
    r"|cards?"
    r")"
    + _SEARCH_MV_QUALIFIER
)
#: "search your library and/or graveyard for <criteria>, [reveal <pronoun>,]
#: [and] put <pronoun> <destination>. If you search[ed] your library this
#: way, shuffle." (RULE 701.19 "and/or" combined-zone search — the
#: backgrounds/planeswalker-tutor family: Delivery Moogle/Tale of Momo/
#: Elspeth Undaunted Hero/Tower Winder/…). Unlike the library-only family's
#: "then shuffle" tail, the shuffle here is conditional on *which* zone hit
#: — engine-side this maps onto `RulesEngine._finish_search` always
#: shuffling whenever ``"library"`` is among ``zones`` (a documented
#: simplification: it doesn't track which specific zone the chosen card(s)
#: actually came from).
_SEARCH_ZONE_PUT_RE = _c(
    rf"search your library and/or graveyard for {_SEARCH_ZONE_CRITERIA},?\s*"
    rf"{_SEARCH_REVEAL}"
    rf"(?:and\s+)?put {_SEARCH_PRONOUN} (?P<dest>{_SEARCH_DESTINATION_ALT})\.\s*"
    r"if you search(?:ed)? your library this way,?\s*shuffle"
)


def _search_zone_criteria_from_match(m: re.Match[str]) -> dict:
    if m.groupdict().get("basic"):
        crit: dict = {"basic": True}
    else:
        name = m.groupdict().get("name")
        if name:
            return {"name": name.strip()}  # a named-card search ignores colour/mv qualifiers
        crit = {}
        types = m.groupdict().get("types")
        if types:
            words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
            crit["type"] = words if len(words) > 1 else words[0]
    color = _search_color_from_match(m)
    if color:
        crit["color"] = color
    crit.update(_search_mv_qualifier_from_match(m))
    return crit


def _search_zone_put(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    destination = _search_destination_kind(m.group("dest"))
    if destination is None:
        return None
    params: dict = {
        "criteria": _search_zone_criteria_from_match(m),
        "destination": destination,
        "zones": ["library", "graveyard"],
    }
    count = _search_count_from_match(m)
    if count is not None:
        params["count"] = count
    return [EffectSpec("search", params)]


#: "search your library [and graveyard] for N cards and exile the rest. Put
#: the chosen cards on top of your library in any order." (Doomsday-shaped —
#: no "then shuffle" at all: RULE 701.19e's shuffle is for an *ordinary*
#: search, and this one's own text never calls for one). Maps onto
#: `"search"`'s ``exile_rest``/``count``/``destination="library_top"``.
_SEARCH_EXILE_REST_RE = _c(
    r"search your library(?P<gy> and (?:your )?graveyard)? for "
    r"(?P<count>\d+) cards? and exile the rest\.\s*"
    r"put the chosen cards? on top of your library in any order"
)


def _search_exile_rest(m: re.Match[str]) -> list[EffectSpec]:
    zones = ["library", "graveyard"] if m.group("gy") else ["library"]
    return [
        EffectSpec(
            "search",
            {
                "criteria": {},
                "destination": "library_top",
                "count": int(m.group("count")),
                "exile_rest": True,
                "zones": zones,
            },
        )
    ]


#: "An opponent gains control of ~." (Wishclaw Talisman-shaped — RULE
#: 701.10-adjacent; `game/effects.py`'s `GainControlBySourceEffect`).
_GAIN_CONTROL_BY_OPPONENT_RE = _c(
    rf"an opponent gains control of {_SELF_SUBJECT}"
)


def _gain_control_by_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_by_source", {"recipient": "opponent"})]


#: RULE 108.4-adjacent "threaten" effect — "Gain control of target creature
#: until end of turn." (Act of Treason/Act of Aggression/Claim the
#: Firstborn-shaped — the single most-repeated effect template in the whole
#: cache, ~90 real cards). `effects.GainControlUntilEndOfTurnEffect` already
#: bundles the control change, untap, and haste grant into one atomic effect
#: (built for the hand-authored Zealous Conscripts); this only teaches the
#: parser the oracle-text shape, including its optional "with mana value N
#: or less" cap (Claim the Firstborn, `TargetSpec.max_mana_value`, the same
#: param `destroy_mv` uses). The trailing "Untap that creature[.] It gains
#: haste until end of turn." pair is recognized separately, in `segmenter.
#: parse_effect_body` (`_GAIN_CONTROL_HASTE_TAIL_RE`) — it's not a second
#: effect, just the card restating in words what this one already does, so
#: it's absorbed there rather than re-parsed into a second (redundant, and
#: RULE-115-target-doubling-risky) untap/haste effect here.
_GAIN_CONTROL_EOT_RE = _c(
    rf"gain control of (?P<another>another )?{TARGET}"
    r"(?: with power (?P<pn>\d+) or (?P<pcmp>less|greater))?"
    r"(?: with mana value (?P<mv>\d+) or less)? until end of turn"
)


def _gain_control_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in (
        "creature", "creature_you_dont_control", "permanent", "artifact",
    ):
        return None
    params: dict = {"target_kind": kind, **_optional_param(m)}
    if m.group("mv"):
        params["max_mana_value"] = int(m.group("mv"))
    # "gain control of target creature an opponent controls **with power N
    # or less/greater**" (Enthralling Victor) — a target-offer-time filter,
    # RULE 115.1c. "another" (Akroan Conscriptor) is accepted but its RULE
    # 601.2c self-exclusion isn't enforced (documented simplification —
    # these are all trigger/ETB bodies with no reason to grab the source).
    if m.group("pn"):
        key = "max_power" if m.group("pcmp") == "less" else "min_power"
        params["creature_filter"] = {key: int(m.group("pn"))}
    return [EffectSpec("gain_control_until_eot", params)]


#: The untargeted mass sibling — "Untap all creatures and gain control of
#: them until end of turn. They gain haste until end of turn." (Insurrection)
#: — RULE 601.2c's "all creatures" over the same `GainControlUntilEndOfTurnEffect`,
#: `selector="all_creatures"` (`effects._mass_selector_objects`). A whole-body
#: match (both sentences, like `_DESTROY_ALL_NO_REGEN_RE`) rather than the
#: `_GAIN_CONTROL_HASTE_TAIL_RE` two-step above, since the only real card
#: printing this exact mass shape has nothing before or after it to split on.
_GAIN_CONTROL_ALL_RE = _c(
    r"untap all creatures and gain control of them until end of turn\."
    r"\s*they gain haste until end of turn"
)


def _gain_control_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_until_eot", {"selector": "all_creatures"})]


#: "For each opponent, gain control of up to 1 target creature that player
#: controls until end of turn. Untap those creatures. They gain haste until
#: end of turn." (Mass Mutiny / Molten Primordial / Mob Rule-shaped) — the
#: one-requirement-per-opponent RULE 601.2c count, the same `count_selector`
#: shape `_goad_per_opponent` uses, over the multi-target
#: `GainControlUntilEndOfTurnEffect` (its `apply` now iterates every chosen
#: target, not just the first). A whole-body match like `_GAIN_CONTROL_ALL_
#: RE` — the untap/haste restatement is the same "the effect already does
#: this" tail `_GAIN_CONTROL_HASTE_TAIL_RE` absorbs.
_GAIN_CONTROL_EOT_PER_OPPONENT_RE = _c(
    r"for each opponent, gain control of up to (?:one|1) target creature "
    r"that player controls until end of turn\.\s*"
    r"untap (?:those creatures|them)\.\s*they gain haste until end of turn"
)


def _gain_control_eot_per_opponent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("gain_control_until_eot", {
        "target_kind": "creature_you_dont_control",
        "optional": True,
        "count_selector": "opponents",
    })]


#: "Whenever a player casts an instant or sorcery spell, that player
#: copies it and may choose new targets for the copy [until end of turn]."
#: (Bonus Round) — RULE 603.1's "it"/"that player" both name the *firing
#: trigger event* rather than a RULE 601.2c target choice, unlike every
#: other `copy_spell` card in scope (Dualcaster Mage-shaped, which really
#: does target). `CopySpellEffect.spell_from_trigger_event`/
#: `controller_from_trigger_event` read the SPELL_CAST event's own
#: ``instance_id``/``player_id`` instead of a target list — the same
#: "resolve off the firing event" idiom `DestroyEffect.
#: target_from_trigger_event` already established (Mikaeus, the
#: Unhallowed). "may choose new targets" is the same accepted
#: simplification `CopySpellEffect`'s own docstring already documents for
#: every card in this family (the copy keeps the original's targets, no
#: retarget prompt) — not a new gap this card introduces.
_TRIGGER_COPY_SPELL_RE = _c(
    r"that player copies it and may choose new targets for the copy(?: until end of turn)?"
)


#: "Each instant and sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (Past in
#: Flames/Will of the Jeskai-shaped — the untargeted "each" sibling of
#: `_GRANT_FLASHBACK_TARGET_RE` below). `GrantGraveyardCastPermissionThisTurnEffect`
#: already exists (built for Backdraft Hellkite's identical wording) — this
#: is purely the missing oracle-text recognizer for a *second* card using
#: the same primitive, per the project's "sweep for what else a new
#: primitive closes" discipline.
_GRANT_FLASHBACK_EACH_RE = _c(
    r"each instant and sorcery card in your graveyard gains flashback until end of turn\.\s*"
    r"the flashback cost is equal to its mana cost"
)


def _grant_flashback_each(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_graveyard_cast_permission_this_turn", {})]


#: "Target instant or sorcery card in your graveyard gains flashback until
#: end of turn. The flashback cost is equal to its mana cost." (MEC-24 —
#: Recoup/Snapcaster Mage/Slickshot Lockpicker/Sphinx of Forgotten Lore/
#: Katilda and Lier-shaped) — the *targeted*, single-card sibling of
#: `_GRANT_FLASHBACK_EACH_RE` above, needing a genuinely different
#: primitive (`grant_flashback_to_target`/`GameState.temp_flashback_grants`
#: — see that effect's own docstring for why the untargeted marker doesn't
#: fit) rather than reusing `grant_graveyard_cast_permission_this_turn`.
#: Reuses the graveyard-recursion family's own `_GRAVEYARD_TYPE_WORD`/
#: `_GRAVEYARD_SCOPE_WORD`/`_graveyard_target_kind` vocabulary (word order
#: is "target ... card **in** ... graveyard", not "**from** ... graveyard"
#: like the recursion family, so this is its own regex rather than a shared
#: one). The trailing "the flashback cost is equal to [that card's/its]
#: mana cost" sentence is optional and dropped once matched — it's not a
#: second effect, just prose restating what "gains flashback" (with no
#: literal cost) already means; when a literal cost **is** given inline
#: instead (The Fugitive Doctor's "gains flashback {2}{R}{G} until end of
#: turn", no such sentence at all), ``cost`` carries it and overrides the
#: "equal to its mana cost" default `GrantFlashbackToTargetEffect` falls
#: back to.
_GRANT_FLASHBACK_TARGET_RE = _c(
    rf"target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card in "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard gains flashback"
    r"(?: (?P<cost>(?:\{[^}]+\})+))? until end of turn\.?"
    r"(?:\s*the flashback cost is equal to (?:that card'?s|its) mana cost\.?)?"
)


def _grant_flashback_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if m.groupdict().get("cost"):
        params["cost"] = m.group("cost")
    return [EffectSpec("grant_flashback_to_target", params)]


#: "The next spell you cast this turn can't be countered." (Mistrise
#: Village) — `arm_spell_watcher`'s existing "when you next cast a spell
#: this turn, `<effect>`" mechanism (built for Dual Strike's "…copy it"),
#: here with `MarkCantBeCounteredEffect` as the ``then_specs`` payload
#: instead — no card-type/mana-value filter, since the printed line has
#: neither.
_NEXT_SPELL_CANT_BE_COUNTERED_RE = _c(
    r"the next spell you cast this turn can'?t be countered"
)


#: "Look at the top card of target player's library." (Mishra's Bauble) /
#: "Look at a card at random in target player's hand." (Urza's Bauble) — a
#: genuine RULE 115 target with no other game-state consequence, see
#: `LookAtCardsEffect`'s own docstring for why. Two narrow, closed phrasings
#: (not "look at *any* card X") rather than a general "look at" grammar —
#: the only two real cards printing this in the cache.
_LOOK_AT_TARGET_RE = _c(
    r"look at (?:the top card of target player's library"
    r"|a card at random in target player's hand)"
)


def _look_at_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("look_at_cards", {"target_kind": "player"})]


def _next_spell_cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "arm_spell_watcher",
            {"then_specs": [{"type": "mark_cant_be_countered", "params": {}}]},
        )
    ]


def _trigger_copy_spell(m: re.Match[str]) -> list[EffectSpec]:
    return [
        EffectSpec(
            "copy_spell",
            {
                "spell_from_trigger_event": "instance_id",
                "controller_from_trigger_event": "player_id",
            },
        )
    ]


#: "Shuffle ~ into its owner's library." (RULE 701.20 — Green Sun's Zenith's
#: own trailing sentence, overriding the spell's default RULE 608.2m
#: "goes to the graveyard as it resolves" routing; `game/effects.py`'s
#: `ShuffleSelfIntoLibraryEffect`).
_SHUFFLE_SELF_INTO_LIBRARY_RE = _c(
    rf"shuffle {_SELF_SUBJECT} into its owner'?s library"
)
#: ENG-32 (Watery Grasp) — the Aura-host form: "Enchanted creature's owner
#: shuffles it into their library."
_SHUFFLE_ENCHANTED_INTO_LIBRARY_RE = _c(
    r"enchanted creature'?s owner shuffles it into (?:their|its owner'?s) library"
)


def _shuffle_self_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {})]


def _shuffle_enchanted_into_library(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_self_into_library", {"subject": "attached_permanent"})]


#: "attach it to target creature you control" / "attach ~ to target creature
#: you control" (an Equipment's own ETB self-attach, RULE 303.4f-adjacent —
#: `AttachEffect` already exists for Equip's activated ability, reused here).
def _attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("permanent", "creature", "creature_you_control"):
        return None
    return [EffectSpec("attach", {"target_kind": kind})]


# --- RULE 701.14 fight ------------------------------------------------------
# "Target creature you control fights target creature you don't control."
# (Prey Upon), "it fights up to one target creature you don't control."
# (Kogla's ETB), "when this Aura enters, enchanted creature fights …" — one
# `fight` effect (`game/effects.py`'s `FightEffect`) in all three, differing
# only in who the *fighter* is.

#: The target kinds a fight clause may name. Both fighters must be creatures
#: (RULE 701.14a), so a `TARGET` row resolving to anything else — "any
#: target", "target permanent" — leaves the clause unclaimed rather than
#: widening the fight to a non-creature.
_FIGHT_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)

#: The second requirement's `TARGET`, group-renamed so both fit one regex.
_TARGET_B = target_macro("_b")

#: RULE 109.5's "**another** target creature", which means one of two
#: different things depending on who the *other* fighter is:
#:
#: * against an **implicit** fighter (the source, an Aura's host) it excludes
#:   that permanent — already what the engine's plain ``creature`` kind means
#:   (`targeting.legal_targets` unconditionally drops the ability's own
#:   source), and `_another_kind` narrows a "…you control" phrase to the
#:   dedicated `other_creature_you_control` kind for the same reason;
#: * against a **chosen** fighter (the two-target form, or a pronoun pointing
#:   back at the previous clause's pick) it excludes *that target*, which is
#:   `TargetSpec.distinct_from_others` — an across-requirements constraint,
#:   enforced at offer time by the board and backstopped in `FightEffect`.
_ANOTHER = r"(?P<another>another )?"

#: The same phrase in the second slot of a two-target clause ("target
#: creature you control fights **another** target creature"), where the
#: group has to carry its own name.
_ANOTHER_B = r"(?P<another_b>another )?"


def _fight_kind(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if kind in _FIGHT_TARGET_KINDS else None


def _another_kind(kind: str) -> str:
    """RULE 109.5 against an implicit fighter: "another target creature you
    control" is the `other_creature_you_control` kind; a bare "another target
    creature" needs no narrowing (``creature`` already excludes the source)."""
    return "other_creature_you_control" if kind == "creature_you_control" else kind


def _fight(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    fighter = _fight_kind(m.group("target"))
    other = _fight_kind(m.group("target_b"))
    if fighter is None or other is None:
        return None
    params: dict = {"fighter_kind": fighter, "other_kind": other}
    if target_is_optional(m):
        params["fighter_optional"] = True
    if target_is_optional(m, "_b"):
        params["optional"] = True
    if m.groupdict().get("another_b"):
        params["distinct"] = True
    return [EffectSpec("fight", params)]


def _fight_implicit(fighter_kind: Optional[str]):
    """Builder for the three clauses whose fighter isn't chosen: the source
    (``None``), an Aura's host (``"attached_permanent"``), or the previous
    clause's target (``"previous_target"``). Only the *other* creature is a
    RULE 115 requirement, so the whole clause is one target wide."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        other = _fight_kind(m.group("target"))
        if other is None:
            return None
        params: dict = {"other_kind": other, **_optional_param(m)}
        if fighter_kind is not None:
            params["fighter_kind"] = fighter_kind
        if m.groupdict().get("another"):
            # "Another" than a *chosen* previous target is a cross-requirement
            # exclusion; than the source/host it's just the narrower kind.
            if fighter_kind == "previous_target":
                params["distinct"] = True
            else:
                params["other_kind"] = _another_kind(other)
        return [EffectSpec("fight", params)]

    return build


def _fight_previous_pair(m: re.Match[str]) -> list[EffectSpec]:
    """"Then those creatures fight each other." — both fighters come from the
    preceding "choose target … and target …" clause, so this clause announces
    no requirement of its own at all."""
    return [
        EffectSpec(
            "fight",
            {"fighter_kind": "previous_target", "other_kind": "previous_target_2"},
        )
    ]


def _choose_targets(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Choose target creature you control and target creature you don't
    control." (RULE 601.2c) — announces the pair the following clauses act on
    by pronoun; see `effects.ChooseTargetsEffect`."""
    first = _fight_kind(m.group("target"))
    second = _fight_kind(m.group("target_b"))
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
    params = _multi_target_params(m)
    if params is None:
        return None
    kind = params.pop("target_kind")
    return [EffectSpec("choose_targets", {"kinds": [kind], **params})]


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
     "permanent", "nonland_permanent", "artifact", "land",
     "land_you_control", "land_you_dont_control"}
)


def _exchange_control_self(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in _EXCHANGE_CONTROL_TARGET_KINDS:
        return None
    return [EffectSpec("exchange_control", {
        "target_kind": kind, **_optional_param(m),
    })]


def _exchange_control_two_explicit(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    first = resolve_target_kind(m.group("target"))
    second = resolve_target_kind(m.group("target_b"))
    if first not in _EXCHANGE_CONTROL_TARGET_KINDS or second not in _EXCHANGE_CONTROL_TARGET_KINDS:
        return None
    return [EffectSpec("exchange_control", {"first_target_kind": first, "target_kind": second})]


def _exchange_control_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("exchange_control", params)]


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


#: "you may **have** it fight …" — `_peel_optional` strips the "you may",
#: leaving the causative "have <subject> fight" (uninflected verb), so both
#: inflections are accepted in one row. A leading "then " survives the
#: segmenter's split on ". " (its own "then" connector only strips the
#: comma-less mid-sentence form), so every pronoun row tolerates it.
_THEN = r"(?:then )?"
#: The pronouns a later clause uses for the creature an earlier one chose.
_PREVIOUS_SUBJECT = r"(?:it|that creature|the chosen creature)"
_FIGHT_TWO_TARGETS_RE = _c(rf"{TARGET} fights {_ANOTHER_B}{_TARGET_B}")
_FIGHT_SELF_RE = _c(rf"(?:have )?{re.escape(SELF)} fights? {_ANOTHER}{TARGET}")
_FIGHT_PRONOUN_RE = _c(rf"(?:have )?it fights? {_ANOTHER}{TARGET}")
_FIGHT_ATTACHED_RE = _c(rf"(?:have )?{_ATTACHED_SUBJECT} fights? {_ANOTHER}{TARGET}")
_FIGHT_PREVIOUS_RE = _c(
    rf"{_THEN}(?:have )?{_PREVIOUS_SUBJECT} fights? {_ANOTHER}{TARGET}"
)

#: RULE 701.14 fight, in its four printed subjects: two chosen creatures
#: ("target creature you control fights target creature you don't
#: control"), the source itself written as ``~`` or as "it", and an Aura's
#: host ("enchanted creature fights …"), plus the fifth "pronoun pointing
#: back at an earlier clause" form ("… gets +1/+2 until end of turn. **It**
#: fights target creature you don't control.", offered only when the caller
#: says an earlier clause in this same body actually chose a creature —
#: `EffectHandler.previous_subject_only`). The "it" row is
#: `self_subject_only` — see `EffectHandler`. Grammar/builders differ enough
#: per row (the "have"/"another" wording, which kind-resolver applies) that
#: only the repetitive `EffectHandler(...)` registration itself is factored
#: into this row table, not the regexes/builders behind it.
_FIGHT_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    ("fight", _FIGHT_TWO_TARGETS_RE, _fight, {}),
    ("fight_self", _FIGHT_SELF_RE, _fight_implicit(None), {}),
    ("fight_pronoun", _FIGHT_PRONOUN_RE, _fight_implicit(None), {"self_subject_only": True}),
    ("fight_attached", _FIGHT_ATTACHED_RE, _fight_implicit("attached_permanent"), {}),
    (
        "fight_previous", _FIGHT_PREVIOUS_RE, _fight_implicit("previous_target"),
        {"previous_subject_only": True},
    ),
]

_FIGHT_PREVIOUS_PAIR_RE = _c(
    rf"{_THEN}(?:those|the chosen) creatures fight each other"
)
#: "Put a +1/+1 counter on target creature. **It** phases out." (Slip Out
#: the Back) — the same previous-clause pronoun `_FIGHT_PREVIOUS_RE` uses,
#: for `PhaseOutEffect.previous_subject` instead of a fight.
_PHASE_OUT_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} phases? out")


def _phase_out_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"previous_subject": True})]


#: RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn/Crystal Golem-
#: shaped — the source phasing out *itself*) — `PhaseOutEffect.self_target`,
#: distinct from the plain untargeted default below (Robe of Stars' own
#: Equipment-hosted "equipped creature phases out", reached by
#: `_phase_out_attached` instead).
_PHASE_OUT_SELF_RE = _c(r"~ phases? out")
#: "Enchanted/equipped creature phases out." (Vanishing) — the untargeted
#: default `PhaseOutEffect` already had (Robe of Stars' own hand-authored
#: shape, `EffectSpec("phase_out", {})`), just reached from oracle text now.
_PHASE_OUT_ATTACHED_RE = _c(rf"{_ATTACHED_SUBJECT} phases? out")
#: "Target creature phases out." / "Target artifact, creature, or land
#: phases out." / "Target creature you control phases out." / "Target
#: creature or planeswalker an opponent controls phases out." (Reality
#: Ripple/Vodalian Illusionist/Haystack/Divine Smite-shaped) — a genuine
#: RULE 115 target, so an opponent's own permanent is exactly as legal a
#: target as your own whenever the printed phrase says so (no engine
#: restriction ever scoped this to "your own permanents" — `PhaseOutEffect`
#: just forwards whatever `target_kind` `resolve_target_kind` resolves).
_PHASE_OUT_TARGET_RE = _c(rf"{TARGET} phases? out")


def _phase_out_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {"self_target": True})]


def _phase_out_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("phase_out", {})]


def _phase_out_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    params: dict = {"target_kind": kind}
    if target_is_optional(m):
        params["optional"] = True
    return [EffectSpec("phase_out", params)]


#: RULE 500.4-adjacent "after this phase, there is an additional combat
#: phase." (Combat Celebrant/Godo/Aurelia-shaped, `normalize` folds "this
#: combat phase" to the bare "this phase" self-reference every printing of
#: this clause uses) / World at War/Aggravated Assault's own longer
#: "after this main phase, there is an additional combat phase followed by
#: an additional main phase." — `ExtraCombatPhaseEffect`'s `main_phase_too`
#: flag is what tells the two apart. The subject-first word order ("there
#: is an additional combat phase after this phase.", A-Raiyuu, Storm's
#: Edge/Raiyuu-shaped, MEC-28) is the same clause with its two halves
#: swapped — real cache cards print both orderings.
_EXTRA_COMBAT_PHASE_RE = _c(
    r"after this phase, there is an additional combat phase"
    r"|there is an additional combat phase after this phase"
)
_EXTRA_COMBAT_AND_MAIN_PHASE_RE = _c(
    r"after this main phase, there is an additional combat phase followed by an additional main phase"
)


def _extra_combat_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {})]


def _extra_combat_and_main_phase(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_combat_phase", {"main_phase_too": True})]


_CHOOSE_TARGETS_RE = _c(rf"choose {TARGET} and {_TARGET_B}")
#: "choose two target creatures [controlled by different players]." (PAR-1)
#: — the `_MULTI_TARGET_QUANTIFIER`/`_MULTI_TARGET_ALT`/`_MULTI_TARGET_
#: DISTINCT_CONTROLLERS` grammar `destroy`/`exile`'s own multi-target rows
#: use, repurposed as a bare announcement (see `_choose_targets_group`).
_CHOOSE_TARGETS_GROUP_RE = _c(
    rf"choose {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"
    rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
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
    {"any", "creature", "creature_you_control", "creature_you_dont_control", "player"}
)
_DEALS_POWER = r"deals? damage equal to its power to"


def _power_recipient(phrase: str) -> Optional[str]:
    kind = resolve_target_kind(phrase)
    return kind if kind in _DAMAGE_RECIPIENT_KINDS else None


def _damage_equal_to_power(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dealer = _fight_kind(m.group("target"))
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
        params: dict = {"target_kind": recipient, **_optional_param(m)}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


def _damage_equal_to_power_selector(dealer_kind: Optional[str]):
    """"… to each opponent." — an untargeted recipient group (RULE 601.2c),
    the same closed vocabulary `_damage_selector` uses."""

    def build(m: re.Match[str]) -> Optional[list[EffectSpec]]:
        selector = _SELECTOR_WORD_MAP.get(m.group("selector").lower())
        if selector is None:
            return None
        params: dict = {"selector": selector, "target_kind": None}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


#: The subset of `_SELECTOR_WORD_MAP` a *damage* clause can legally match —
#: "each other player" is a lose_life/rad-counter-only phrasing (no card
#: prints "deals damage to each other player"), so these selector rows must
#: not inherit it just because the lookup dict is shared with lose_life's.
_DAMAGE_SELECTOR_KEYS = ("each creature", "each player", "each opponent", "that player")
_DAMAGE_SELECTOR_ALT = "|".join(_DAMAGE_SELECTOR_KEYS)
_POWER_DAMAGE_TWO_TARGETS_RE = _c(rf"{TARGET} {_DEALS_POWER} {_TARGET_B}")
_POWER_DAMAGE_SELF_RE = _c(rf"{re.escape(SELF)} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PRONOUN_RE = _c(rf"it {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_ATTACHED_RE = _c(rf"{_ATTACHED_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_PREVIOUS_RE = _c(rf"{_THEN}{_PREVIOUS_SUBJECT} {_DEALS_POWER} {TARGET}")
_POWER_DAMAGE_SELF_SELECTOR_RE = _c(
    rf"{re.escape(SELF)} {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)
_POWER_DAMAGE_PRONOUN_SELECTOR_RE = _c(
    rf"it {_DEALS_POWER} (?P<selector>{_DAMAGE_SELECTOR_ALT})"
)

#: The one-sided fight's own registration table (see `_FIGHT_ROW_SPECS`'s
#: matching note) — two rows wider than fight's, since a creature can deal
#: damage to a mass selector ("… to each opponent") but can't "fight" one,
#: so `damage_equal_to_power` alone gets the `_self_selector`/
#: `_pronoun_selector` rows.
_POWER_DAMAGE_ROW_SPECS: list[tuple[str, "re.Pattern[str]", Any, dict]] = [
    ("damage_equal_to_power", _POWER_DAMAGE_TWO_TARGETS_RE, _damage_equal_to_power, {}),
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
        _damage_equal_to_power_implicit(None), {"self_subject_only": True},
    ),
    (
        "damage_equal_to_power_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector(None), {"self_subject_only": True},
    ),
    (
        "damage_equal_to_power_attached", _POWER_DAMAGE_ATTACHED_RE,
        _damage_equal_to_power_implicit("attached_permanent"), {},
    ),
    (
        "damage_equal_to_power_previous", _POWER_DAMAGE_PREVIOUS_RE,
        _damage_equal_to_power_implicit("previous_target"), {"previous_subject_only": True},
    ),
]


#: A single mana symbol run — "add {b}{b}{b}." (Dark Ritual-shaped). Only a
#: *pure* run of colour/colourless symbols claims (fail-closed): "add 1 mana
#: of any color" has no ``{…}`` symbols to capture, so it's left unclaimed
#: rather than guessed at (that's a player choice, not modeled yet).
_MANA_SYMBOL = r"\{[wubrgc]\}"
_ADD_MANA_RE = _c(rf"add (?P<syms>(?:{_MANA_SYMBOL}){{1,20}})")
#: "add 1 mana of any color" (number words already folded to digits by
#: `normalize`) — a genuine resolve-time player choice (RULE 106.4), unlike
#: the fixed pip run above. Deliberately narrow: real cards only print this
#: singular form (a multi-mana "any color" clause is always templated "any
#: *one* color" instead, a different, not-yet-modeled shape — guessing it
#: means the same thing here would be wrong).
_ADD_MANA_ANY_COLOR_RE = _c(r"add 1 mana of any colou?r")


def _add_mana(m: re.Match[str]) -> list[EffectSpec]:
    colors = [s.upper() for s in re.findall(r"\{([wubrgc])\}", m.group("syms"))]
    return [EffectSpec("add_mana", {"colors": colors})]


def _add_mana_any_color(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_mana", {"colors": ["any"]})]


#: "you may pay {E}{E}. If/When you do, <effect>." (RULE 122, Aether Chaser/
#: Herder/Inspector/Swooper) — a resolve-time optional energy payment gating
#: a follow-up. The follow-up is recursively parsed; a follow-up the parser
#: can't model (e.g. a *targeted* one — Guide of Souls) leaves the whole
#: clause unclaimed (fail-closed).
_PAY_ENERGY_THEN_RE = _c(
    r"you may pay (?P<pips>(?:\{e\})+)\.\s*(?:if|when) you do,?\s*(?P<effect>.+)"
)


def _pay_energy_then(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    amount = m.group("pips").count("{e}")
    sub = parse_effect_body(m.group("effect").strip())
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if any(s.params.get("target_kind") for s in sub):
        # A *targeted* follow-up (Guide of Souls' "put counters on target
        # attacking creature") isn't resolvable through `PayEnergyThen
        # Effect`'s no-target resolution — fail-closed rather than model it
        # half-way (the resolve handler runs each sub-effect untargeted).
        return None
    return [EffectSpec("pay_energy_then", {"amount": amount, "effects": [s.to_dict() for s in sub]})]


#: MEC-18/RULE 603.5's general "You may `<cost-shaped action>`. When/If you
#: do, `<effect>`." — generalizes `_pay_cost_then_draw`/`_pay_energy_then`
#: from one hardcoded antecedent (a bare mana cost / `{E}` pips) and, for
#: the first, one hardcoded consequence (draw a card) to the *whole*
#: `ActivationCost` vocabulary `pay_cost_then`/`RulesEngine.
#: request_pay_cost_then` already supports server-side (mana, sacrifice,
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
#: silently make an energy antecedent free. A *targeted* follow-up is
#: rejected for the same reason `_pay_energy_then` rejects one:
#: `PayCostThenEffect`'s branch effects resolve off-stack with no
#: target-gathering step of their own (RULE 601.2c targets are announced
#: with the spell/ability, and this clause isn't one).
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
#: payment — but it also rejects a targeted follow-up outright, which the
#: self-sacrifice cases don't need to risk.
_MAY_COST_THEN_CLAUSE = (
    r"pay (?:\{[wubrgcx0-9/]+\})+"
    r"|sacrifice an? \w+"
    r"|sacrifice another \w+"
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
)
_PAY_COST_THEN_GENERAL_RE = _c(
    r"you may (?P<cost>" + _MAY_COST_THEN_CLAUSE + r")\.\s*(?:if|when) you do,?\s*(?P<effect>.+)"
)
#: RULE 603.5's *negative* antecedent: "you may `<cost>`. If you don't,
#: `<effect>`." (Chaos Spewer, Gutsplitter Gang, Scuzzback Scrounger — the
#: PAR-29 Blight batch's "if you don't" shape). The mirror of
#: `_PAY_COST_THEN_GENERAL_RE`: the effect goes in `pay_cost_then`'s
#: ``else_effects`` branch (`game/effects.py`'s `PayCostThenEffect`), which
#: fires only when the optional cost is *declined* or unpayable.
_PAY_COST_THEN_OR_ELSE_RE = _c(
    r"you may (?P<cost>" + _MAY_COST_THEN_CLAUSE + r")\.\s*if you don't,?\s*(?P<effect>.+)"
)


def _pay_cost_then_general(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    # PAR-29: "it endures N" (Descendant of Storms) needs `self_subject=True`
    # to unlock `self_subject_only` rows — safe here because a target-bearing
    # follow-up is rejected below anyway (the only pronoun shape left is the
    # ability's own source), and RULE 603.5's "if you do, <effect>" always
    # continues the *same* triggered ability's subject, never introduces one.
    sub = parse_effect_body(m.group("effect").strip(), self_subject=True)
    if not sub:
        return None  # follow-up not modeled → whole clause unclaimed
    if any(s.params.get("target_kind") for s in sub):
        return None  # a targeted follow-up can't resolve off-stack — see docstring above
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [s.to_dict() for s in sub],
    })]


def _pay_cost_then_or_else(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"you may `<cost>`. If you don't, `<effect>`." — the else-branch
    sibling of `_pay_cost_then_general` (PAR-29 Blight batch)."""
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

    sub = parse_effect_body(m.group("effect").strip(), self_subject=True)
    if not sub:
        return None
    if any(s.params.get("target_kind") for s in sub):
        return None  # a targeted else-branch can't resolve off-stack either
    return [EffectSpec("pay_cost_then", {
        "cost": m.group("cost"),
        "effects": [],
        "else_effects": [s.to_dict() for s in sub],
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
_COUNTER_UNLESS_PAY_RE = _c(
    r"counter (?:it|that spell or ability|that spell|that ability) unless "
    r"(?:that player|its controller) (?P<verb>pays|discards) "
    r"(?P<amount>(?:\{[wubrgcx0-9/]+\})+|\d+ life|a card)"
)


def _counter_unless_pay(m: re.Match[str]) -> list[EffectSpec]:
    verb = "pay" if m.group("verb") == "pays" else "discard"
    return [EffectSpec("counter_unless_pay", {"cost": f"{verb} {m.group('amount')}"})]


#: "you get {E}{E}" (RULE 122 energy production, the reminder-text
#: parenthetical already stripped by `normalize`) — N energy counters to the
#: effect's controller, the resolve-time sibling of the "Pay {E}" cost. Uses
#: the same generic `add_player_counters` primitive `rad`/`poison` do.
_GET_ENERGY_RE = _c(r"you get (?P<pips>(?:\{e\})+)")


def _get_energy(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_player_counters", {"amount": m.group("pips").count("{e}"), "kind": "energy"})]


def _transform(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("transform", {})]


#: "exile ~/this saga, then return it/him/her to the battlefield transformed
#: under your/its/his/her owner's control" (RULE 400.7 + RULE 712.8 combined)
#: — distinct from a plain in-place `transform`: this is a Batch 9 shape
#: where the permanent actually leaves and re-enters the battlefield already
#: on its back face (a transforming Saga's own final chapter, Fable of the
#: Mirror-Breaker-shaped; or a transform-flip permanent's activated ability
#: that phrases its own flip this way instead of a bare "transform ~",
#: Ayara/Clive/Jin-Gitaxias-shaped). "this saga" is matched literally since
#: `normalize._SELF_REFERENCE_RE` deliberately excludes it (Saga gets its own
#: dedicated grammar, `catalogue/saga.py`); every other self-reference
#: (including "this equipment") already folds to ``~`` before this runs.
_EXILE_RETURN_TRANSFORMED_RE = _c(
    rf"exile (?:{re.escape(SELF)}|this saga),? then return (?:it|him|her) to "
    r"the battlefield transformed under (?:your control|(?:its|his|her) owner's control)"
)


def _exile_return_transformed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile_return_transformed", {})]


#: The O-Ring / Banisher Priest / Fiend Hunter family — modern one-sentence
#: templating: "exile `<TARGET>` [an opponent controls] until ~ leaves the
#: battlefield." (~47 SOLO cache cards). `ExileEffect(remember=True)` stamps
#: the exiled card's id onto `GameObject.linked_exile_id`; the companion
#: `LEAVES_BATTLEFIELD` → `return_linked_exile` ability is synthesized by
#: the segmenter (`_EXILE_UNTIL_LEAVES_LTB`), since a body handler emits
#: one ability's effects and the return is a *second* ability. The
#: ``until_source_leaves`` param is that signal. Old two-sentence O-Ring
#: templating ("…exile another target nonland permanent." + a separate
#: "When ~ leaves the battlefield, return the exiled card…") is a
#: different, still-unmodeled shape.
_EXILE_UNTIL_LEAVES_RE = _c(
    rf"exile {TARGET}(?P<opp_ctrl> an opponent controls| defending player controls)? "
    r"until ~ leaves the battlefield"
)
_EXILE_UNTIL_LEAVES_OPP_KINDS: dict[str, str] = {
    "creature": "creature_you_dont_control",
    "permanent": "permanent_you_dont_control",
    "artifact": "artifact_you_dont_control",
    "nonland_permanent": "nonland_permanent_you_dont_control",
}


def _exile_until_leaves(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    if (m.group("opp_ctrl") or "").strip() == "an opponent controls":
        kind = _EXILE_UNTIL_LEAVES_OPP_KINDS.get(kind, kind)
    return [EffectSpec("exile", {
        "target_kind": kind,
        "remember": True,
        "until_source_leaves": True,
        **_optional_param(m),
    })]


#: "return it/~ to the battlefield transformed under its owner's control"
#: (RULE 400.7 + RULE 712.8, Bruce Banner-shaped) — the graveyard-sourced
#: sibling of `_EXILE_RETURN_TRANSFORMED_RE` above: a dies trigger's own
#: "return it..." (no "exile ~, then" prefix — dying already put it in the
#: graveyard, so this clause returns straight from there) rather than an
#: exile-and-blink. Always self/untargeted, same as that sibling.
_RETURN_FROM_GRAVEYARD_TRANSFORMED_RE = _c(
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
_RETURN_SELF_FROM_GRAVEYARD_RE = _c(
    r"return this card from your graveyard to "
    r"(?:the battlefield(?P<tapped> tapped)?|(?P<hand>your hand))"
)


def _return_self_from_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    if m.group("hand"):
        return [EffectSpec("return_self_from_graveyard_to_hand", {})]
    return [EffectSpec("return_self_from_graveyard", {"tapped": bool(m.group("tapped"))})]


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


#: RULE 602.1-adjacent per-instance activation cap: "Activate only once each
#: turn." (Quirion Ranger/Scryb Ranger-shaped) — a plain trailing sentence in
#: an activated ability's own body (after the cost's colon), sitting
#: alongside its real effect ("Untap target creature. Activate only once
#: each turn." — two sentences `parse_effect_body`'s connector-splitting
#: already tries independently). Not a real one-shot effect: this handler
#: claims the clause but emits a *marker* `EffectSpec` `effect_binder.
#: bind_ability`'s "activated" branch recognizes and strips before binding,
#: turning it into `ActivatedAbility.once_per_turn` instead of a `GameEffect`
#: (mirroring `TriggeredAbility.once_per_turn`'s own RULE 603.2 stamp).
ONCE_PER_TURN_MARKER = "once_per_turn_marker"
_ONCE_PER_TURN_RE = _c(r"activate (?:this ability )?only once each turn")


def _once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONCE_PER_TURN_MARKER, {})]


#: RULE 603.2's own once-per-turn limiter, PAR-14 — "This ability triggers
#: only once each turn." (Chance-Met Elves/Prudent Fateseer-shaped) — a
#: trailing sentence in a *triggered* ability's own body, the exact same
#: "claim the clause, emit a marker, let the binder fold it into a flag"
#: shape `ONCE_PER_TURN_MARKER` above uses for an *activated* ability, but
#: textually distinct ("this ability triggers", not "activate"), so its own
#: row rather than widening that one. `segmenter.segment_line`'s "triggered"
#: dispatch strips this marker from the parsed body and folds it into
#: `AbilitySpec.trigger["limit"]`, consumed by `effect_binder.bind_ability`
#: as `TriggeredAbility.once_per_turn` — a primitive that already existed
#: (built for Dionus, Elvish Archdruid's *granted* ability) but no
#: oracle-text recognizer had ever reached from an ordinary printed card.
TRIGGER_ONCE_PER_TURN_MARKER = "trigger_once_per_turn_marker"
_TRIGGER_ONCE_PER_TURN_RE = _c(r"this ability triggers only once each turn")


def _trigger_once_per_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(TRIGGER_ONCE_PER_TURN_MARKER, {})]


#: RULE 602.5d timing restriction: "Activate only as a sorcery." (older
#: template) / "Activate this ability only any time you could cast a sorcery."
#: (current) — like `ONCE_PER_TURN_MARKER`, a trailing sentence in the
#: activated ability's own body, not a real one-shot effect. Claimed as a
#: marker `EffectSpec` that `effect_binder.bind_ability`'s "activated" branch
#: strips and folds into `ActivationCost.sorcery_speed_only` (already enforced
#: by `game_engine.can_activate` via `_sorcery_speed_ok`), the same lever the
#: engine already uses for level-up / Class-level sorcery-speed abilities.
#: Only the two canonical *sorcery-speed* phrasings (RULE 605.3b / "any time
#: you could cast a sorcery"). Deliberately not "only during your turn"
#: (its own, wider `ONLY_DURING_YOUR_TURN_MARKER` below — folding it in
#: here would be *wrong*, since a non-empty stack is still legal for that
#: one) or "before attackers are declared" (still unclaimed, fail-closed,
#: until modeled precisely).
SORCERY_SPEED_MARKER = "sorcery_speed_marker"
_SORCERY_SPEED_RE = _c(
    r"activate (?:this ability )?only "
    r"(?:as a sorcery|any time you could cast a sorcery)"
)


def _sorcery_speed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(SORCERY_SPEED_MARKER, {})]


#: RULE 602.5d's *other* timing restriction: "Activate only during your
#: turn." (Wishclaw Talisman-shaped) — deliberately left unclaimed above
#: (see `SORCERY_SPEED_MARKER`'s own docstring) since it's a genuinely
#: different, wider window than sorcery-speed (still legal at instant
#: speed with a non-empty stack — just not outside the controller's own
#: turn). Same marker-then-strip shape, folded by `effect_binder.
#: bind_ability` into `ActivationCost.only_during_your_turn`
#: (`GameEngine._only_during_your_turn_ok`) instead of `sorcery_speed_only`.
ONLY_DURING_YOUR_TURN_MARKER = "only_during_your_turn_marker"
_ONLY_DURING_YOUR_TURN_RE = _c(r"activate (?:this ability )?only during your turn")


def _only_during_your_turn(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(ONLY_DURING_YOUR_TURN_MARKER, {})]


# PAR-28: marker `EffectSpec`s synthesized by `segmenter._segment_keyword_
# labeled_ability` for the "Keyword — [ability]" families (Boast/Exhaust/
# Power-up/Forecast — RULE 702.142/702.177/702.57). They carry no oracle
# text of their own (there is no regex row here — the keyword name *is* the
# recognition), and `effect_binder.bind_ability`'s "activated" branch strips
# and folds each into an `ActivatedAbility`/`ActivationCost` flag exactly
# like `ONCE_PER_TURN_MARKER` above.
#: RULE 702.177a / Power-up — "Activate only once." (per game, per ability).
ACTIVATE_ONLY_ONCE_MARKER = "activate_only_once_marker"
#: Power-up — "Reduce the cost by its mana cost if it entered this turn."
POWERUP_COST_REDUCTION_MARKER = "powerup_cost_reduction_marker"
#: RULE 702.57a — a forecast ability is activated from the card's hand.
FROM_HAND_MARKER = "from_hand_marker"


# PAR-10: "Activate only as a sorcery and only if `<condition>`." (Cabal
# Inquisitor/Dread Wanderer/Hall of Oracles/Jin-Gitaxias // The Great
# Synthesis) and its bare sibling "Activate only if `<condition>`."
# (Potioner's Trove) — RULE 602.5d timing stacked with (or standing in for)
# an activation-legality board condition, a second marker `effect_binder.
# bind_ability`'s "activated" branch folds into `ActivationCost.
# activation_condition`, checked by `GameEngine.can_activate` via
# `game/static_conditions.condition_holds` — the same RULE 613.6 whitelist a
# permanent's own "as long as `<condition>`" static already uses, so a
# condition recognized for one is recognized (and evaluated identically) for
# both.
#
# `game/static_conditions.py`'s full vocabulary lives behind
# `catalogue.static_handlers.static_condition` — which this module can't
# import (`static_handlers` already imports `SORCERY_SPEED_MARKER` from
# *here*, so the reverse import would cycle). This is deliberately a small,
# independent subset covering only the phrasings real cards actually pair
# with an activation condition today: hand/graveyard card counts and "cast
# an instant or sorcery spell this turn" (`cast_instant_or_sorcery_this_
# turn` is new — see `static_conditions.py` and `static_handlers.py`'s own
# `_STATIC_CONDITION_RES` row, which picks up the same phrase for free for
# the "created" ~250-clause "as long as" family: Haunting Figment/Leapfrog/
# Piston-Fist Cyclops). Every one of the ~150 *other* "Activate only if …"
# phrasings in the cache (`you control a Plains`, `this creature is
# attacking`, `a creature died this turn`, …) is real, standing PAR-12 tail
# work, not part of this ticket — fail-closed here, same as everywhere else.
ACTIVATION_CONDITION_MARKER = "activation_condition_marker"
_ACTIVATION_CONDITION_RES: list[tuple[re.Pattern[str], Callable[[re.Match[str]], dict]]] = [
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
]


def _activation_condition_dict(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _ACTIVATION_CONDITION_RES:
        match = pattern.fullmatch(stripped)
        if match is not None:
            return build(match)
    return None


_SORCERY_SPEED_AND_CONDITION_RE = _c(
    r"activate (?:this ability )?only as a sorcery and only if (?P<cond>.+)"
)


def _sorcery_speed_and_condition(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = _activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [
        EffectSpec(SORCERY_SPEED_MARKER, {}),
        EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition}),
    ]


_ACTIVATE_ONLY_IF_RE = _c(r"activate (?:this ability )?only if (?P<cond>.+)")


def _activate_only_if(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    condition = _activation_condition_dict(m.group("cond"))
    if condition is None:
        return None
    return [EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": condition})]


def _token_keywords(text: str) -> Optional[list[str]]:
    """Validate a token's "with <keywords>" clause → flag-keyword slugs, or None.

    Fail-closed: if any listed ability isn't a parameterless (flag) keyword, the
    whole token clause is left unclaimed rather than dropping the ability
    (a token that silently lacks "flying" would be a wrong game state). The
    one parametric exception is a *bare* "hexproof" — RULE 702.11b's
    QUALITY shape (PAR-5) exists for the scoped "hexproof from <colour>"
    variant, but plain "hexproof" with no "from" is still its own complete,
    unscoped keyword (the shape it had before PAR-5), so it's granted here
    exactly like a FLAG keyword. A scoped "hexproof from black" never
    reaches this branch: `keyword_slug` only resolves the bare "hexproof"/
    "hexproof from" spellings, so a real quality suffix keeps `kdef` ``None``
    and still fails closed below.
    """
    slugs: list[str] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        kdef = KEYWORDS.get(keyword_slug(part))
        if kdef is None or (kdef.shape is not KeywordShape.FLAG and kdef.slug != "hexproof"):
            return None
        slugs.append(kdef.slug)
    return slugs


#: ENG-31: the parametric keywords a *grant* ("gains firebending N until end
#: of turn", "has firebending N as long as …", a token "with firebending N")
#: can model — exactly the ones whose RULE 702 text is a triggered ability
#: `effect_binder._KEYWORD_TRIGGERED_BUILDERS` re-synthesizes off the granted
#: N. Every other NUMBER-shape keyword (renown, toxic, …) stays fail-closed
#: for a grant.
_GRANTABLE_PARAMETRIC_KEYWORDS: frozenset[str] = frozenset(
    {"firebending", "annihilator", "afflict", "bushido"}
)


def _split_keywords_with_parametric(
    text: str,
) -> Optional[tuple[list[str], list[dict[str, object]]]]:
    """A "<kw>[, <kw> and firebending N …]" list → ``(flag_slugs,
    [{"name", "n"}, ...])``, or ``None`` if any entry is neither a FLAG
    keyword nor a grantable parametric one (fail-closed, like
    `_token_keywords`). ``"firebending 2"`` / ``"annihilator 1"`` entries go
    to the parametric list; everything else must be a plain flag."""
    flags: list[str] = []
    parametric: list[dict[str, object]] = []
    for part in re.split(r",|\band\b", text):
        part = part.strip()
        if not part:
            continue
        pm = re.fullmatch(r"([a-z]+)\s+(\d+)", part)
        if pm and pm.group(1) in _GRANTABLE_PARAMETRIC_KEYWORDS:
            parametric.append({"name": pm.group(1), "n": int(pm.group(2))})
            continue
        kdef = KEYWORDS.get(keyword_slug(part))
        if kdef is None or (kdef.shape is not KeywordShape.FLAG and kdef.slug != "hexproof"):
            return None
        flags.append(kdef.slug)
    return flags, parametric


def _inline_create_token_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``create_token`` params for the inline-stats creature-token
    grammar (``p``/``t``/``mid``/``kw``/``n``/``tapped``/``legendary``/``who``
    groups) — factored out of `_create_token` so `_create_token_and_attach`
    can build the same params for its own, differently-wrapped clause."""
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    parametric_keywords: list[dict[str, object]] = []
    if m.groupdict().get("kw"):
        split = _split_keywords_with_parametric(m.group("kw"))
        if split is None:
            return None  # unrecognised "with …" ability → fail-closed
        keywords, parametric_keywords = split
    params: dict = {
        "count": count_of(m.group("n")),
        "power": int(m.group("p")),
        "toughness": int(m.group("t")),
        "colors": colors,
        "subtypes": subtypes,
        "keywords": keywords,
    }
    if parametric_keywords:  # ENG-31: "… token with firebending N"
        params["parametric_keywords"] = parametric_keywords
    if is_artifact:
        params["is_artifact"] = True
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    # "**Each player** creates …" / "**each opponent** creates …" — everyone
    # gets their own ``count`` tokens under their own control, rather than
    # the effect's controller getting them all.
    who = (m.groupdict().get("who") or "").strip().lower()
    if "each" in who:
        # "**Each player** / **each opponent** creates …" — only the "each …"
        # phrasings mean everyone; a captured "you" is the ordinary
        # controller-scoped default, not a `creators` override.
        params["creators"] = "each_opponent" if "opponent" in who else "each_player"
    if m.groupdict().get("tapped"):  # RULE 110.5a — enters tapped, not tapped after
        params["tapped"] = True
    return params


def _create_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params)]


#: "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
#: Blade of the Elves-shaped "whenever ~ deals combat damage to a player"
#: payoff, ~38 real cards) — "that many" always refers back to the firing
#: event's own ``amount`` (RULE 603.1), read fresh at resolve time
#: (`CreateTokenEffect.count_from_trigger_event`) rather than a literal
#: count. Reuses `_xx_token_mid_params` for the "<mid> token[s][ with
#: <kw>]" tail (a fixed literal count needs none of `_inline_create_token_
#: params`'s ``n``/``who`` groups).
_CREATE_TOKEN_THAT_MANY_RE = _c(
    r"creates? that many "
    r"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
)


def _create_token_that_many(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    params.update({
        "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_from_trigger_event": "amount",
    })
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", params)]


#: A dynamic token *count* (RULE 601.2c, `CreateTokenEffect.count_selector`
#: — `continuous.count_selector`'s own vocabulary), for the two real
#: phrasings found so far: "…for each `<subtype>` you control" (Elvish
#: Promenade-shaped) and "…for each attacking creature" (Embercleave's own
#: cost-reduction wording, reused here for a token count). A count-selector
#: word not in this table stays unclaimed rather than guessed at.
def _count_selector_for_phrase(subtype: Optional[str], attacking: Optional[str]) -> Optional[str]:
    if attacking:
        return "attacking_creatures"
    if subtype:
        return f"creatures_you_control_of_type_{subtype}"
    return None


#: "Create a 1/1 green Elf Warrior creature token for each Elf you control."
#: (Elvish Promenade-shaped) — the trailing-count-selector sibling of the
#: plain `create_token` row above.
_CREATE_TOKEN_FOR_EACH_RE = _c(
    rf"(?:(?P<who>you|each player|each opponent) )?creates? {COUNT} "
    rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    rf"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))?"
    r" for each (?:(?P<subtype>[a-z]+) you control|(?P<attacking>attacking creature))"
)


def _create_token_for_each(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    selector = _count_selector_for_phrase(m.groupdict().get("subtype"), m.groupdict().get("attacking"))
    if selector is None:
        return None
    params.pop("count", None)
    params["count_selector"] = selector
    return [EffectSpec("create_token", params)]


#: "Create X 1/1 green Elf Warrior creature tokens, where X is the number
#: of attacking creatures." (Galadhrim Ambush-shaped) — the "announce X,
#: then explain it" sibling of the "for each" row above. MEC-27: widened
#: from its own narrow subtype/attacking-only tail to the full
#: `subgrammars.DEVOTION` vocabulary (bare "creatures/permanents/artifacts/
#: lands/enchantments/planeswalkers you control", the two-word compounds,
#: devotion-to-colour) — the same reading `_CREATE_TOKEN_NUMBER_EQUAL_
#: DEVOTION_RE` already uses for the "equal to" phrasing, just for this
#: row's "where x is" surface wording instead.
_CREATE_TOKEN_XX_WHERE_RE = _c(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))?, where x is {DEVOTION}"
)


def _create_token_xx_where(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if selector is None:
        return None
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature tokens
#: equal to your devotion to white." (Evangel of Heliod/Master of Waves-
#: shaped) — a third surface wording for the same dynamic-count shape
#: `_CREATE_TOKEN_FOR_EACH_RE`/`_CREATE_TOKEN_XX_WHERE_RE` already cover,
#: this time keyed to `DEVOTION` instead of a `count_selector` subtype word.
_CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE = _c(
    r"creates? a number of (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    rf"(?: with (?P<kw>[a-z, ]+))? equal to {DEVOTION}"
)


def _create_token_number_equal_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = devotion_selector(m)
    if not selector:
        return None
    if m.groupdict().get("tapped"):
        params["tapped"] = True
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    return [EffectSpec("create_token", {
        **params, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "count_selector": selector,
    })]


#: The inline-stats creature-token grammar `_create_token`'s own `EffectHandler`
#: row wraps, reused bare here (no leading "creates?") so it can be embedded
#: inside a bigger clause — "create **a 1/1 white Halfling creature token**
#: and attach ~ to it." (Auxiliary Boosters/Field-Tested Frying Pan's own
#: second sentence) needs the token description without also consuming the
#: "and attach …" tail the way the top-level row's fullmatch would demand.
_CREATE_TOKEN_INLINE = (
    rf"{COUNT} (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    # ``0-9`` in the keyword capture is ENG-31's "… token with firebending
    # N" — `_inline_create_token_params` splits a "<name> <N>" entry into
    # ``parametric_keywords`` and fail-closes on any other numbered ability.
    rf"(?P<mid>[a-z ]*?)creature tokens?(?: with (?P<kw>[a-z0-9, ]+))?"
)

#: "create a 1/1 white Halfling creature token and attach ~ to it." (Living
#: Weapon-adjacent, but printed as ordinary oracle text rather than the
#: keyword — Auxiliary Boosters) / "…**then** attach **this** to it." (the
#: "For Mirrodin!" ability word's own reminder-text wording, MEC-28 — see
#: `gate.py`'s ``_FOR_MIRRODIN_RE`` for why this specific card's real rules
#: text lives in reminder text at all) — one clause, two effects: the
#: token, then `AttachEffect`'s ``target_kind="created"`` mode onto
#: whatever that just made (RULE 608.2's "it").
_CREATE_TOKEN_AND_ATTACH_RE = _c(
    rf"creates? {_CREATE_TOKEN_INLINE}(?:,)? (?:and|then) attach (?:~|this) to it"
)


def _create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    return [EffectSpec("create_token", params), EffectSpec("attach", {"target_kind": "created"})]


#: "Create <Name>, a legendary N/N ... creature token [with <keywords>]."
#: (PAR-13, Dungeon of the Mad Mage's "Cradle of the Death God" — "Create
#: The Atropal, a legendary 4/4 black God Horror creature token with
#: deathtouch.") — the named-legendary sibling of `_create_token`'s bare
#: inline-stats grammar: a real proper name up front (unlike `_create_
#: named_token`'s closed Treasure/Clue/Food vocabulary, this name is
#: whatever the clause prints, always legendary, always with inline stats)
#: rather than a curated `TokenDatabase` lookup, since a card's own unique
#: token needs no shared ability the database would otherwise supply.
_CREATE_NAMED_LEGENDARY_TOKEN_RE = _c(
    r"create (?P<name>[a-z][a-z' ]*), a legendary (?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?"
)


def _create_named_legendary_token(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    colors, subtypes, is_artifact = _split_token_mid_words(m.group("mid") or "")
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = _token_keywords(m.group("kw"))
        if parsed is None:
            return None
        keywords = parsed
    return [EffectSpec("create_token", {
        "count": 1, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes, "keywords": keywords,
        **({"is_artifact": True} if is_artifact else {}),
        "token_name": m.group("name").strip().title(), "legendary": True,
    })]


#: A closed vocabulary of the popular colourless "named" artifact tokens
#: (no inline P/T, no "creature" word — Treasure/Clue/Food-shaped) that
#: `services/token_database.py`'s `data/tokens.json` actually defines with
#: their own real abilities (a Treasure's mana ability, a Clue's sacrifice-
#: to-draw, a Food's sacrifice-to-gain-life). Deliberately **not** every
#: name real cards print (Blood/Map/Gold/Incubator/Powerstone aren't in
#: that JSON yet) — claiming one of those here would silently synthesize a
#: blank token missing its real ability (`CreateTokenEffect.apply`'s
#: fallback), the exact half-resolved outcome docs/09's fail-closed
#: discipline forbids. Keep this dict in sync with `data/tokens.json`
#: whenever a new named token is added there.
_NAMED_TOKEN_WORDS: dict[str, str] = {"treasure": "Treasure", "clue": "Clue", "food": "Food"}


#: "create a Treasure token" / "create two Clue tokens" — the named-token
#: sibling of `_create_token`'s inline-stats creature grammar: no P/T, no
#: "creature" word, just a bare recognised token name. Looked up in the
#: curated `TokenDatabase` at resolve time (`CreateTokenEffect.apply`), so
#: the created object keeps its real activated ability, not a blank card.
def _create_named_token(m: re.Match[str]) -> list[EffectSpec]:
    name = _NAMED_TOKEN_WORDS[m.group("name")]
    return [EffectSpec("create_token", {"count": count_of(m.group("n")), "token_name": name})]


#: The compound sibling of `_create_token_and_attach` — "create a Food
#: token, then create a 1/1 white Halfling creature token and attach ~ to
#: it." (Field-Tested Frying Pan): a named artifact token
#: (`_NAMED_TOKEN_WORDS`) first, *then* the create+attach shape onto the
#: second, inline-stats token — `AttachEffect`'s ``created_objects[-1]``
#: read picks the Halfling, not the Food, since it's whichever effect ran
#: last. Deliberately hard-codes the singular "a `<named>` token" (rather
#: than reusing `COUNT`) — the real card this closes only ever prints one,
#: and `COUNT`'s own capture group is named ``n``, the same name
#: `_CREATE_TOKEN_INLINE` already binds for the *second* token's count, so a
#: shared `COUNT` here would collide.
_CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE = _c(
    rf"creates? an? (?P<named>{'|'.join(_NAMED_TOKEN_WORDS)}) token, then "
    rf"creates? {_CREATE_TOKEN_INLINE} and attach ~ to it"
)


def _create_named_then_create_token_and_attach(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _inline_create_token_params(m)
    if params is None:
        return None
    named_name = _NAMED_TOKEN_WORDS[m.group("named")]
    return [
        EffectSpec("create_token", {"count": 1, "token_name": named_name}),
        EffectSpec("create_token", params),
        EffectSpec("attach", {"target_kind": "created"}),
    ]


#: RULE 701.19a's keyword action — "Investigate" (Shadows over Innistrad-
#: introduced, but reused across many later sets — the widest single
#: template found in this batch's ranking, 87 SOLO cache-wide). Purely "the
#: player creates a Clue token" (`"Clue"` is already in `_NAMED_TOKEN_WORDS`,
#: so the *token* itself needed no new work — only this keyword-action
#: recognition), so it's modeled as a direct alias onto the same
#: `create_token` shape `_create_named_token` already emits rather than a
#: dedicated `investigate` effect type. "Investigate twice" is `normalize`'s
#: one gap in its own spelled-number folding (it rewrites "three times" to
#: "3 times" but "twice" isn't a `_NUMBER_WORDS` entry — it's a distinct
#: word, not "two times") — handled here as its own literal alternative
#: rather than widening `normalize` for a single irregular word no other
#: family needs. "Investigate X times"/"...for each `<count>`" (a dynamic
#: count) stays unclaimed — `COUNT` only ever resolves a literal int.
_INVESTIGATE_RE = _c(r"investigate(?: (?P<times>twice|\d+ times?))?")


def _investigate(m: re.Match[str]) -> list[EffectSpec]:
    times = m.group("times")
    count = 2 if times == "twice" else (int(times.split()[0]) if times else 1)
    return [EffectSpec("create_token", {"count": count, "token_name": "Clue"})]


#: RULE 701.51a's keyword action — "The Ring tempts you." (Tales of
#: Middle-earth-shaped, "Lord of the Rings" set-specific — see
#: PARSER_LONG_TAIL.md's set-specific-mechanics table). The engine
#: primitive and the `"the_ring_tempts_you"` `EffectSpec` type already
#: existed (`RulesEngine.the_ring_tempts_you`, `effects.
#: TheRingTemptsYouEffect`, both built for one hand-authored card,
#: `game/ability_catalogue.py`'s "One Ring to Rule Them All") — only this
#: general oracle-text recognition was missing, the single widest gap this
#: set's own precon deck has (36 SOLO cache-wide).
_RING_TEMPTS_YOU_RE = _c(r"the ring tempts you")


def _ring_tempts_you(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("the_ring_tempts_you", {})]


def _signed_int(token: str) -> int:
    """A signed integer literal, tolerating the unicode minus ``−`` (U+2212)."""
    return int(token.replace("−", "-"))


def _counter_sign(token: str) -> str:
    """"+1/+1" (default) or "-1/-1" from a captured counter-kind sign, tolerating
    the unicode minus ``−`` (U+2212) — both shift net P/T through the same
    machinery (RULE 122)."""
    return "-1/-1" if token.lstrip()[0] in "-−" else "+1/+1"


def _add_counters_target_params(
    m: re.Match[str], params: dict, include_optional: bool = True
) -> Optional[list[EffectSpec]]:
    """The shared selfref-or-target tail every ``add_counters`` builder below
    shares: "on ~" buffs the source untargeted; otherwise the target phrase
    must resolve to a permanent-ish kind (RULE 122.1a — +1/+1 counters can sit
    on *any* permanent, incl. the controller-restricted "target creature you
    control" pick, Archdruid's Charm-shaped) or the clause is unclaimed.
    ``include_optional`` is ``False`` for the one caller
    (`_add_counters_from_trigger_amount`) whose regex has no "up to" group to
    read."""
    if m.groupdict().get("selfref"):
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent", "creature_you_control", *_SINGLE_TYPE_PERMANENT_KINDS):
        return None
    params["target_kind"] = kind
    if include_optional:
        params.update(_optional_param(m))
    return [EffectSpec("add_counters", params)]


def _add_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"count": count_of(m.group("n")), "kind": _counter_sign(m.group("ckind"))}
    return _add_counters_target_params(m, params)


# "put a +1/+1 counter on target suspected creature you control" (RULE
# 701.60, PAR-29 — Deadly Complication) — the one adjective-qualified TARGET
# phrase `subgrammars.TARGET`'s own alternation doesn't carry (unlike
# "target attacking/tapped creature", it isn't worth widening that shared
# macro for a single-card phrase), so its own small row feeding
# `combat.matches_object_filter`'s new ``is_suspected`` key.
def _add_counters_suspected_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": _counter_sign(m.group("ckind")),
        "target_kind": "creature_you_control", "creature_filter": {"is_suspected": True},
    })]


#: MEC-27: "put x +1/+1 counters on ~/target creature, where x is the number
#: of `<noun phrase>` you control." (Domain-shaped triggers, "the number of
#: Elves you control", etc.) — `subgrammars.DEVOTION`'s wider RULE 613.7c
#: reading, previously wired into `damage`/`lose_life` only
#: (`_damage_selector_devotion`/`_lose_life_selector_devotion`); this is
#: that same reading applied to the counter family via `AddCountersEffect`'s
#: new `amount_from_count_selector`. Requires the literal "x" (not `{COUNT}`
#: — a plain digit/"a"/"an" amount has no "where x is" tail to resolve
#: against), so it's a genuinely separate row from `_add_counters` above,
#: not a widening of its ``{COUNT}`` group.
_ADD_COUNTERS_DEVOTION_RE = _c(
    rf"put x (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT})), where x is {DEVOTION}"
)


def _add_counters_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    dsel = devotion_selector(m)
    if not dsel:
        return None
    params: dict = {"amount_from_count_selector": dsel, "kind": _counter_sign(m.group("ckind"))}
    return _add_counters_target_params(m, params, include_optional=False)


#: RULE 122.1's *named* (non-P/T) counter kinds this grammar recognizes for
#: the plain "put a `<kind>` counter on X" shape — deliberately small,
#: extended as a real card needs one (fail-closed for anything else via the
#: alternation below, same discipline `_CREATURE_FILTER_KEYWORD_WORDS`
#: uses). Kept as a wholly separate row from `_add_counters`'s own
#: `[+\-−]1/[+\-−]1` `ckind` group rather than widening that regex's
#: alternation — `_add_counters`'s builder maps *any* non-`-`-prefixed
#: match to `"+1/+1"`, so a shared group would have silently mis-typed
#: "spore" as a P/T counter. `AddCountersEffect.kind` is already a free
#: string (RULE 122.1a — any permanent, any named counter type), so no
#: engine change is needed, only this narrower parser recognition.
_NAMED_COUNTER_KINDS: frozenset[str] = frozenset({"spore", "burden", "quest"})
_ADD_NAMED_COUNTER_RE = _c(
    rf"put {COUNT} (?P<ckind>{'|'.join(_NAMED_COUNTER_KINDS)}) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
)


def _add_named_counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"count": count_of(m.group("n")), "kind": m.group("ckind")}
    return _add_counters_target_params(m, params)


#: RULE 603.1's "Whenever you gain life, …" lifegain-payoff family (RULE
#: 119.3, Ajani's Pridemate-shaped — `_PLAYER_TRIGGER_CONDITIONS`'s
#: ``"you gain life"`` row already claims the *condition*; this is the
#: matching *body* grammar for the two forms real cards actually print:
#: "target opponent loses that much life" (Sanguine Bond/Defiant Bloodlord)
#: and "put that many +1/+1 counters on ~/target creature" (Ageless
#: Entity/Karlov-adjacent). ``amount_from_trigger_event`` reads the firing
#: LIFE_GAINED event's own ``amount`` (`GameContext.trigger_event`,
#: `LoseLifeEffect`/`AddCountersEffect`'s new param) rather than a literal
#: int — the same "that much"/"that many" idiom `AddManaEffect.
#: amount_from_trigger_event` already models for Raphael, Ninja Destroyer's
#: "add that much {R}". Not wired into every trigger family generally
#: (only this one prints "that much"/"that many" this way), so it's a
#: narrow pair of rows rather than a generic COUNT alternative.
def _lose_life_from_trigger_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind != "player":
        return None
    return [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "amount"})]


def _add_counters_from_trigger_amount(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"kind": _counter_sign(m.group("ckind")), "amount_from_trigger_event": "amount"}
    return _add_counters_target_params(m, params, include_optional=False)


#: "~ gets +X/+X until end of turn, where X is the amount of life you
#: gained." (Field-Tested Frying Pan's granted Equipment ability) — the
#: dynamic-magnitude sibling of `_pump`'s literal-int "+N/+N until end of
#: turn"; only ever seen self-referential (a granted quoted ability's own
#: "~" resolves to whatever object received the grant — the equipped
#: creature — at bind time, see `continuous._apply_layer_6_ability`'s
#: ``source=obj``), so no target form is needed.
_PUMP_SELF_FROM_LIFE_GAINED_RE = _c(
    rf"{_SELF_SUBJECT} gets \+x/\+x until end of turn, "
    r"where x is the amount of life you gained"
)


def _pump_self_from_life_gained(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {"amount_from_trigger_event": "amount"})]


#: ENG-32 (Flexible Waterbender / Katara, Water Tribe's Hope) — "~ / creatures
#: you control ha[s|ve] base power and toughness N/M until end of turn"
#: (a resolve-time layer-7b `pt_set`, parked in `GameState.floating_statics`
#: via `grant_until` so it ends at cleanup like any RULE 611 duration).
#: Literal digits or the `{X}` form (Katara — "X can't be 0", a documented
#: simplification: X is announced, and 0 is already meaningless for it).
_BASE_PT_UNTIL_EOT_RE = _c(
    rf"(?:{_SELF_SUBJECT}|(?P<group>creatures you control)) "
    rf"(?:has|have) base power and toughness (?P<p>\d+|x)/(?P<t>\d+|x) until end of turn"
    rf"(?:\. x can'?t be 0)?(?:\. activate only during your turn)?"
)


def _base_pt_until_eot(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    def _v(g: str) -> "int | str":
        return "x" if g.lower() == "x" else int(g)

    params: dict = {
        "power": _v(m.group("p")), "toughness": _v(m.group("t")),
        "affects": "creatures_you_control" if m.groupdict().get("group") else "self",
    }
    return [EffectSpec("grant_until", {
        "static": {"type": "pt_set", "params": params},
        "duration": "end_of_turn",
        "target_kind": None,
    })]


#: "put a +1/+1 counter on each of up to two target creatures" (RULE 115.1a
#: generalized to N>=2 — the Support-keyword-shaped family; a live query
#: against the cached Oracle DB found 100+ real cards spelling this out,
#: e.g. Ajani, Adversary of Tyrants/Arcade Cabinet/Basri's Aegis/Bretagard
#: Stronghold). Two numbers in one clause (counter amount vs. target count,
#: the same shape `_damage_each_multi_target` already handles for damage) —
#: ``target_count`` is a deliberately distinct `EffectSpec` key from
#: ``count``/``amount`` (both already mean the *counter* amount here).
def _add_counters_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mt = _multi_target_params(m)
    if mt is None or mt["target_kind"] not in ("creature", "permanent", *_SINGLE_TYPE_PERMANENT_KINDS):
        return None
    params: dict = {
        "count": count_of(m.group("n")),
        "kind": _counter_sign(m.group("ckind")),
        "target_kind": mt["target_kind"],
        "target_count": mt["count"],
    }
    if mt.get("optional"):
        params["optional"] = True
    if mt.get("count_max") is not None:
        # ENG-30: "put a +1/+1 counter on each of 1 or 2 target creatures" —
        # `target_count`/`target_count_max` is the *target* range, distinct
        # from `count`/`amount` (both already the counter amount per card).
        params["target_count_max"] = mt["count_max"]
    return [EffectSpec("add_counters", params)]


#: PAR-15's "distribute N +1/+1 counters among any number of target
#: creatures[ you control]" (Blessings of Nature/Jugan, the Rising Star/
#: Verdurous Gearhulk) — the *divided pool* sibling of `_add_counters_
#: multi_target`'s "each of up to N" full-amount-per-target shape, mirroring
#: `_divided_damage`'s relationship to `_damage_each_multi_target`
#: (`AddCountersEffect.divided`).
_DISTRIBUTE_COUNTERS_RE = _c(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among any number "
    r"of target creatures(?P<yc> you control)?"
)


def _distribute_counters(m: re.Match[str]) -> list[EffectSpec]:
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": _counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures[ you
#: control]" (Armament Corps/Contagion/Elven Rite/Splendid Agony-shaped) —
#: the *fixed range* sibling of `_DISTRIBUTE_COUNTERS_RE`'s "any number of":
#: a genuine RULE 601.2c minimum of one, not 0..cap.
_DISTRIBUTE_COUNTERS_RANGE_RE = _c(
    r"distribute (?P<n>\d+) (?P<ckind>\+1/\+1|-1/-1|−1/−1) counters among "
    r"(?P<range_min>\d+) or (?P<range_max>\d+) target creatures(?P<yc> you control)?"
)


def _distribute_counters_range(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    range_min, range_max = int(m.group("range_min")), int(m.group("range_max"))
    if range_min < 1 or range_max <= range_min:
        return None
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": _counter_sign(m.group("ckind")), "target_kind": kind,
        "target_count": range_min, "target_count_max": range_max, "divided": True,
    })]


#: "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
#: effect, Vastwood Surge-shaped) — a genuinely different shape from
#: `_add_counters`'s RULE 115 target/self forms, so its own handler row
#: rather than folding "each creature you control" into `TARGET` (that
#: grammar deliberately keeps "each ..." selectors out, see
#: `subgrammars._TARGET_ROWS`'s note).
def _add_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": _counter_sign(m.group("ckind")),
        "selector": "each_creature_you_control",
    })]


def _pump_target(m: re.Match[str]) -> Optional[tuple[Optional[str], Optional[str]]]:
    """The pump's ``(target_kind, selector)`` — or ``None`` to signal fail-closed.

    Exactly one of the pair is set for a targeted or group subject; both are
    ``None`` for a self-pump ("~ gets …", untargeted single object) so the
    caller can tell it apart from an unrecognised target (real ``None``
    overall).
    """
    groupdict = m.groupdict()
    if groupdict.get("selfref"):
        return (None, None)  # untargeted self-pump (an activated "~ gets +1/+0 …")
    if groupdict.get("group"):
        return (None, _GROUP_SELECTORS[re.sub(r"'", "", groupdict["group"])])
    if groupdict.get("attached"):
        return ("attached_permanent", None)  # "enchanted creature gains …" (Aura activated ability)
    kind = resolve_target_kind(m.group("target"))
    # The controller-scoped creature kinds are as pumpable as a bare
    # "target creature" — `targeting.legal_targets` resolves all four, and a
    # pump doesn't care *whose* creature it lands on. Anything else (a
    # player, a spell) has no P/T to modify, so it stays fail-closed.
    if kind not in (
        "creature", "permanent", "creature_you_control", "creature_you_dont_control"
    ):
        return None
    return (kind, None)


def _pump(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    params: dict = {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


def _pump_keywords(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    split = _split_keywords_with_parametric(m.group("kw"))
    if split is None:
        return None
    flags, parametric = split
    if not flags and not parametric:
        return None
    params: dict = {}
    if flags:
        params["keywords"] = flags
    if parametric:  # ENG-31: "gains firebending N until end of turn"
        params["parametric_keywords"] = parametric
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


# RULE 701.10/11 "double"/"triple `<creature>`'s power and toughness [until
# end of turn]" — a `PumpEffect.self_multiplier` recipient-relative pump
# (each recipient's own current power/toughness, not a flat/shared amount),
# PAR-29. Three surface shapes on real cards, each its own row: "double the
# power and toughness of `<TARGET>`/each creature you control" (Dragonclaw
# Strike/Roar of Endless Song), the possessive "double `<TARGET>`'s/~'s
# power and toughness" (Nylea's Colossus/Reckless Amplimancer/Tifa's Limit
# Break's own "triple"), and the bare pronoun "double its power and
# toughness" — offered both `self_subject_only` (Grunn's "whenever ~
# attacks alone, double its power and toughness") and `previous_subject_
# only` (World War Hulk's "choose target creature you control. … double its
# power and toughness.").
_DOUBLE_PT_MULTIPLIERS: dict[str, int] = {"double": 2, "triple": 3}
_DOUBLE_PT_TARGET_KINDS = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control"}
)


def _double_pt_of(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    if m.groupdict().get("each_group"):
        return [EffectSpec("pump", {"selector": "creatures_you_control", "self_multiplier": mult})]
    kind = resolve_target_kind(m.group("target"))
    if kind not in _DOUBLE_PT_TARGET_KINDS:
        return None
    return [EffectSpec("pump", {
        "target_kind": kind, "self_multiplier": mult, **_optional_param(m),
    })]


def _double_pt_possessive(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    if m.groupdict().get("selfposs"):
        return [EffectSpec("pump", {"self_multiplier": mult})]
    kind = resolve_target_kind(m.group("target"))
    if kind not in _DOUBLE_PT_TARGET_KINDS:
        return None
    return [EffectSpec("pump", {
        "target_kind": kind, "self_multiplier": mult, **_optional_param(m),
    })]


def _double_pt_pronoun(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    return [EffectSpec("pump", {"self_multiplier": mult})]


def _double_pt_previous(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    mult = _DOUBLE_PT_MULTIPLIERS.get(m.group("mult"))
    if mult is None:
        return None
    return [EffectSpec("pump", {"self_multiplier": mult, "previous_subject": True})]


#: "Target attacking Elf you control gains deathtouch until end of turn."
#: (Gnarlroot Trapper-shaped) — RULE 506.4's attacker status composed with
#: a creature-subtype filter (`combat.matches_object_filter`'s new
#: ``"attacking"`` key), a target phrase the shared `TARGET` macro has no
#: row for.
_PUMP_ATTACKING_SUBTYPE_TARGET_RE = _c(
    r"target attacking (?P<subtype>[a-z]+) you control gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_attacking_subtype_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "target_kind": "creature_you_control",
        "creature_filter": {"attacking": True, "subtype": m.group("subtype").capitalize()},
    })]


#: "Up to two target creatures each get +N/+N [and gain `<keywords>`] until
#: end of turn." (Dauntless Onslaught-shaped — the single biggest pump
#: template found in the cache, 19 SOLO cards, `parser_probe.py blocked`) /
#: "One or two target creatures…" (Opera Love Song/Heroic Teamwork-shaped) —
#: ENG-30: these are no longer the same shape. "Up to two" is RULE 115.1a's
#: 0..2 `optional` idiom; "one or two" is a genuine RULE 601.2c *range*
#: (`TargetSpec.count_max`, at least one) — previously both were folded to
#: `count=2, optional=True` as a documented simplification (declining below
#: the "one or two" minimum was never a choice a real player would make
#: differently); now that the engine has a real range primitive, the two
#: wordings get their real, distinct shapes instead.
_PUMP_UP_TO_TWO_RE = _c(
    r"up to 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_ONE_OR_TWO_RE = _c(
    r"1 or 2 target creatures each gets? "
    r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)


def _pump_up_to_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        # `EffectRegistry`'s "pump" factory reads the *target* count as
        # "target_count" (distinct from a magnitude key also spelled
        # "count" elsewhere in this file) — a bare "count" here was a
        # dormant bug: every "up to two target creatures" pump spell (19
        # SOLO cards, Dauntless Onslaught-shaped) silently only ever
        # offered *one* target, since `PumpEffect`'s own `count` defaulted
        # to 1 and this key was never read. Found while building ENG-30's
        # neighboring "one or two" range shape just below.
        "target_kind": "creature", "target_count": 2, "optional": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


def _pump_one_or_two(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": "creature", "target_count": 1, "target_count_max": 2,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: ENG-30: "1 or 2 target creatures gain `<kw>` until end of turn." (Wind
#: Sail) — the keyword-only sibling of `_PUMP_ONE_OR_TWO_RE` (no P/T delta
#: at all, unlike every other row in this family).
_PUMP_ONE_OR_TWO_KW_RE = _c(
    r"1 or 2 target creatures gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_one_or_two_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "target_kind": "creature", "target_count": 1, "target_count_max": 2, "keywords": keywords,
    })]


#: "Each creature your opponents control gets -1/-1 until end of turn for
#: each poison counter its controller has." (Phyresis Outbreak-shaped) —
#: `PumpEffect.per_recipient_controller_counter`'s own dedicated grammar:
#: unlike every other group-pump row, each recipient's boost scales
#: independently by *its own controller's* count of a player counter kind,
#: not one shared magnitude. Deliberately narrow to "poison" (a direct
#: `Player.poison` attribute) — a "rad"/"energy" variant would read
#: `Player.counters` instead, unneeded by any real card yet.
_PUMP_PER_CONTROLLER_COUNTER_RE = _c(
    r"each creature your opponents control "
    r"gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+) until end of turn "
    r"for each (?P<kind>poison) counter its controller has"
)


def _pump_per_controller_counter(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "selector": "creatures_opponents_control",
        "per_recipient_controller_counter": m.group("kind"),
    })]


#: "Creatures you control gain trample and get +X/+X until end of turn,
#: where X is the number of creatures you control." (Craterhoof Behemoth-
#: shaped) — `PumpEffect.amount_from_count_selector`'s own dedicated
#: grammar: one shared magnitude for the whole "creatures you control"
#: group, computed live from the board rather than a fixed int. The
#: keyword-list-*then*-P/T word order ("gain `<kw>` and get +X/+X") is the
#: opposite of `_pump`'s own "+N/+N and gain `<kw>`", so this needs its
#: own row rather than widening that one.
_GROUP_PUMP_COUNT_SELECTOR_RE = _c(
    r"creatures you control gain (?P<kw>[a-z, ]+?) and get \+x/\+x until end of turn, "
    r"where x is the number of creatures you control"
)


def _group_pump_count_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {
        "keywords": keywords, "selector": "creatures_you_control",
        "amount_from_count_selector": "creatures_you_control",
    })]


#: RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where X
#: is your devotion to `<colour(s)/wedge>`." (Aspect of Hydra/Devoted Temur-
#: shaped) — the `DEVOTION` fragment feeding `PumpEffect.amount_from_count_
#: selector` via `continuous.count_selector`'s existing `devotion_to_<key>`
#: vocabulary, same shape `_GROUP_PUMP_COUNT_SELECTOR_RE` uses for a board
#: count instead of a mana-symbol one.
_PUMP_DEVOTION_TARGET_RE = _c(rf"{TARGET} gets? \+x/\+x until end of turn, where x is {DEVOTION}")
#: The mass sibling — "creatures you control get +X/+X …" (Klothys's
#: Design) — same amount grammar, group subject instead of a RULE 115
#: target.
_GROUP_PUMP_DEVOTION_RE = _c(
    rf"creatures you control gets? \+x/\+x until end of turn, where x is {DEVOTION}"
)
#: The debuff sibling — "target creature [an opponent controls] gets -X/-X
#: until end of turn, where X is your devotion to `<colour>`." (Blight-
#: Breath Catoblepas) — `PumpEffect.amount_from_count_selector_negative`
#: flips the always-nonnegative devotion count into the printed "-X/-X".
_PUMP_DEVOTION_NEGATIVE_TARGET_RE = _c(
    rf"{TARGET} gets? -x/-x until end of turn, where x is {DEVOTION}"
)


def _pump_devotion_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    return [EffectSpec("pump", params)]


def _pump_devotion_negative_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector_subject = subject
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector, "amount_from_count_selector_negative": True}
    if target_kind:
        params["target_kind"] = target_kind
    if selector_subject:
        params["selector"] = selector_subject
    return [EffectSpec("pump", params)]


def _group_pump_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    return [EffectSpec("pump", {"selector": "creatures_you_control", "amount_from_count_selector": selector})]

#: The devotion/count-scaled sibling of `_pump_self_subject`'s fixed-int
#: form — "it gets +X/+X until end of turn, where X is `{DEVOTION}`"
#: (Angelic Exaltation/Akroan Hoplite-adjacent self-buff-on-attack — see
#: `{DEVOTION}`'s own docstring for the wider "the number of `<noun
#: phrase>` you control" reading this also picks up). Symmetric only
#: (``+x/+x``/``-x/-x``): `PumpEffect.amount_from_count_selector` always
#: sets power and toughness to the *same* resolved amount, so an
#: asymmetric "+X/+0" (Akroan Hoplite's own real printing) has no way to
#: express "only power scales" yet and stays unclaimed — a smaller,
#: separate gap from the amount-resolver this row closes.
_PUMP_SELF_SUBJECT_DEVOTION_RE = _c(
    rf"it gets? (?P<sign>\+|-)x/(?P=sign)x until end of turn, where x is {DEVOTION}"
)


def _pump_self_subject_devotion(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = devotion_selector(m)
    if not selector:
        return None
    params: dict = {"amount_from_count_selector": selector}
    if m.group("sign") == "-":
        params["amount_from_count_selector_negative"] = True
    return [EffectSpec("pump", params)]


def _pump_self_subject(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """The bare-pronoun sibling of `_pump`'s untargeted self form —
    "it gets +N/+N [and gains <keyword>] until end of turn" (Akroan Hoplite/
    Aurochs-shaped: an attack/enters trigger whose own body refers back to
    the source as "it" rather than "~", `self_subject_only`-gated)."""
    params: dict = {
        "power": _signed_int(m.group("p")),
        "toughness": _signed_int(m.group("t")),
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: The durations a grant may carry beyond "until end of turn", as printed →
#: `game/durations.py`'s vocabulary. "Until end of turn" is deliberately
#: absent: that is exactly what the `pump` family's ``temp_*`` fields already
#: are (cleared at RULE 514.2 cleanup), and routing it here too would give one
#: phrasing two implementations. These are the ones ``temp_*`` *cannot*
#: express, because it has nowhere to record any other ending.
_GRANT_DURATIONS: dict[str, str] = {
    "until your next turn": "your_next_turn",
    "until end of combat": "end_of_combat",
    "until the end of combat": "end_of_combat",
    "until the beginning of the next end step": "next_end_step",
}


def _grant_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"Target creature gains flying until your next turn." (RULE 611)

    The keyword-pump handler's sibling for every duration other than end of
    turn — same subjects, same keyword vocabulary, but the grant becomes a
    real continuous effect on `GameState.floating_statics` rather than a
    turn-scoped ``temp_*`` stamp.
    """
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {"type": "grant_keyword", "params": {"keywords": keywords}}
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        # A group grant ("creatures you control gain flying until your next
        # turn") has no target: the static keeps the selector as its own
        # ``affects``, so the floating effect covers whatever matches it at
        # each recompute (RULE 611.2c).
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: PAR-13's P/T sibling of `_grant_until` — "target creature gets -4/-0
#: until your next turn" (Fungi Cavern/A-Binding Geist/Hag of Inner
#: Weakness/Wasp, Shrinking Savior-shaped; "creatures your opponents
#: control get -3/-0 until your next turn" — Mouth of the Storm — via the
#: same widened `_GROUP`). The `anthem` static (layer 7c) is already the
#: general P/T-delta static every plain pump uses; this is the first
#: oracle-text route to it with a non-end-of-turn duration.
def _pump_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subject = _pump_target(m)
    if subject is None:
        return None
    target_kind, selector = subject
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    static: dict = {
        "type": "anthem",
        "params": {"power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t"))},
    }
    params: dict = {"static": static, "duration": duration}
    if target_kind:
        params["target_kind"] = target_kind
    else:
        params["target_kind"] = None
        static["params"]["affects"] = selector
    return [EffectSpec("grant_until", params)]


#: PAR-13's "can't attack"/"can't block" sibling — "target creature can't
#: attack until your next turn" (Dungeon of the Mad Mage's own Twisted
#: Caverns). The plain, unqualified restriction rides the same synthetic
#: `grant_keyword` flag (`cant_attack`/`cant_block`) its permanent-static
#: cousin uses (`combat_restriction`'s own docstring) — not `_token_
#: keywords`, since these verbs aren't real RULE 702 keyword names.
_CANT_ATTACK_OR_BLOCK_UNTIL_RE = _c(
    rf"{TARGET} can'?t (?P<verb>attack|block) "
    r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
    r"the beginning of the next end step))"
)


def _cant_attack_or_block_until(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent"):
        return None
    duration = _GRANT_DURATIONS.get(m.group("dur").strip().lower())
    if duration is None:
        return None
    flag = "cant_attack" if m.group("verb") == "attack" else "cant_block"
    return [EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": [flag]}},
        "duration": duration, "target_kind": kind,
    })]


#: The lock-down family's own "for as long as <cond>" durations (PAR-11),
#: matched against `game/static_conditions.py`'s vocabulary.
_LOCKDOWN_CONDITIONS: list[tuple[re.Pattern[str], dict]] = [
    (re.compile(r"~ remains tapped", re.I), {"kind": "source_tapped"}),
    (re.compile(r"you control ~", re.I), {"kind": "source_on_battlefield"}),
    (re.compile(r"~ remains on the battlefield", re.I), {"kind": "source_on_battlefield"}),
]


def _lockdown(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    """"It doesn't untap during its controller's untap step for as long as ~
    remains tapped." (RULE 502.1 + RULE 611.2b — Sand Squid/Ice Floe-shaped.)

    The second sentence of a tap-then-lock ability, so its subject is the
    *previous* clause's target. Composes three pieces that already existed
    separately and had never met: the `previous_subject_only` pronoun, the
    ``no_untap`` static, and this batch's condition-bounded duration — which
    is what made this family unreachable until now (PAR-11).
    """
    condition = next(
        (cond for pattern, cond in _LOCKDOWN_CONDITIONS if pattern.fullmatch(m.group("cond").strip())),
        None,
    )
    if condition is None:
        return None
    return [
        EffectSpec(
            "grant_until",
            {
                "static": {"type": "no_untap", "params": {}},
                "duration": "for_as_long_as",
                "condition": dict(condition),
                "previous_subject": True,
                "target_kind": None,
            },
        )
    ]


def _scry_or_surveil(m: re.Match[str]) -> list[EffectSpec]:
    # "scry N" (RULE 701.18) / "surveil N" (RULE 701.31) — identical grammar
    # and params, differing only in which verb was matched; the matched word
    # is itself the EffectSpec type string.
    return [EffectSpec(m.group("verb"), {"count": int(m.group("n"))})]


#: "Look at the top N cards of your library, then put them back in any
#: order." (Sensei's Divining Top/Sylvan Library-shaped, RULE 701.18's own
#: unabbreviated old-templating spelling — ~27 cache-wide cards) — this
#: engine's non-interactive `scry(N)` resolution already covers every
#: legal outcome of "put them back in any order" (Ponder's own existing
#: entry documents why), so it's the same `"scry"` EffectSpec, just a
#: different printed phrasing reaching it.
_LOOK_TOP_REORDER_RE = _c(
    rf"look at the top {NUMBER} cards? of your library, then put (?:it|them) back in any order"
)


def _look_top_reorder(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("scry", {"count": int(m.group("n"))})]


def _proliferate(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("proliferate", {})]


#: "proliferate twice" (Contagion Engine/Agent Frank Horrigan/Ezuri, Stalker
#: of Spheres) / "proliferate N times" (War of the Spark's Saga chapter —
#: normalize.py folds spelled-out numbers to digits, but not "twice", so
#: that's matched as its own literal word). A bare "proliferate x times"
#: (Expansion Algorithm's spell-announced-X, Tromell's dynamic
#: count-selector) stays unclaimed — a different shape (`ProliferateEffect`
#: has no "x"/count-selector support), not this literal-count one.
def _proliferate_n_times(m: re.Match[str]) -> list[EffectSpec]:
    times = 2 if m.group("n") is None else int(m.group("n"))
    return [EffectSpec("proliferate", {"times": times})]


#: "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
#: Aether Snap/Thief of Blood-shaped, untargeted board wipe of counters).
def _remove_counters_all_permanents(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {})]


#: "remove all counters from target permanent" (Vampire Hexmage-shaped).
def _remove_counters_target(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_counters", {"target_kind": "permanent"})]


#: "remove up to N counters from target permanent/creature/…" (Glissa
#: Sunslayer/Heartless Act/Render Inert-shaped) — a genuinely different,
#: interactive chosen-*amount* shape from the bare "remove all counters"
#: above (`RemoveCountersEffect`'s ``max_count``). Digits only —
#: `normalize.py` already folds spelled-out numbers ("up to three" → "up to
#: 3"). Embeds the shared `TARGET` sub-grammar (PAR-2) rather than a
#: hand-rolled "permanent|creature" alternation, so Price of Betrayal's
#: "target artifact, creature, planeswalker, or opponent" — a player
#: alongside three permanent types, `targeting.
#: artifact_creature_planeswalker_or_opponent` — is claimed the same way
#: any other TARGET-shaped clause is.
_REMOVE_COUNTERS_CHOICE_RE = _c(
    rf"remove up to (?P<n>\d+) counters? from {TARGET}"
)


def _remove_counters_choice(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec(
        "remove_counters", {"target_kind": kind, "max_count": int(m.group("n"))},
    )]


# "You may play [up to] N additional land(s) this turn."  (RULE 305.2
# one-turn permission, Explore/Escape to the Wilds/Kiora's -1-shaped) — the
# resolve-time, single-turn sibling of the standing `extra_land_drop` static
# `catalogue.static_handlers` recognises for a permanent's own printed
# ability ("…on each of your turns"); this shape only ever appears as a
# clause in a spell/ability's effect body, never a permanent's standing text.
# "You may " is optional here: when this is the *only* clause in the body,
# `segmenter.segment_line`'s `_peel_optional` already stripped a leading
# "you may " before this ever runs (Summer Bloom-shaped); when it trails an
# earlier clause ("Draw a card. You may play …", Explore/Urban Evolution-
# shaped) it's still there in the text this handler sees.
_EXTRA_LAND_PLAY_RE = _c(rf"(?:you may )?play (?:up to )?{COUNT} additional lands? this turn")


def _extra_land_play(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("extra_land_play", {"count": count_of(m.group("n"))})]


# RULE 701.40a manifest / RULE 701.58a cloak — "manifest the top card of your
# library" and its "the top N cards" plural, plus cloak's identical shape
# (the only difference is ward {2} on the resulting permanent, carried as the
# effect's ``kind``). "Manifest dread" (RULE 701.40a plus a look-at-two
# chooser) is a separate handler since it isn't a count at all.
def _manifest(m: re.Match[str]) -> list[EffectSpec]:
    kind = "cloak" if m.group("verb").lower() == "cloak" else "manifest"
    return [EffectSpec("manifest", {"count": count_of(m.group("n") or "a"), "kind": kind})]


def _manifest_dread(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("manifest_dread", {})]


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
    if kind not in _CONNIVE_TARGET_KINDS:
        return None
    return [EffectSpec("connive", {
        "target_kind": kind, **_optional_param(m), **_connive_amount_params(m),
    })]


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
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None  # only a creature explores on a real card (RULE 701.44)
    return [EffectSpec("explore", {"target_kind": kind, **_optional_param(m)})]


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
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("endure", {
        "amount": int(m.group("n")), "target_kind": kind, **_optional_param(m),
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


# "Incubate N." (RULE 701.53, PAR-29) — create an Incubator token (a
# power/toughness-less colourless artifact token) with N +1/+1 counters on
# it. No new engine primitive: the `Incubator` catalogue entry
# (`ability_catalogue/entries_008.py`) already binds "{2}: Transform this
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
#: "…where X is its power" (Bloated Processor/Furnace Gremlin — a dying
#: creature's own last-known power) and "…that many times" (Phyrexian
#: Incubator — a search count) stay UNMODELED, fail-closed.
_INCUBATE_X_SELECTORS: dict[str, str] = {
    "the number of lands you control": "lands_you_control",
    "the number of creature cards in your graveyard": "creature_cards_in_your_graveyard",
}
_INCUBATE_X_ALT = "|".join(re.escape(p) for p in _INCUBATE_X_SELECTORS)
_INCUBATE_X_RE = _c(
    r"(?:you )?incubate x(?: (?P<twice>twice))?, where x is "
    r"(?:(?P<selector>" + _INCUBATE_X_ALT + r")|(?P<spell_mv>that spell'?s mana value))"
)


def _incubate_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    extra: dict[str, Any] = {"kind": "+1/+1"}
    if m.group("spell_mv"):
        extra["count_from_trigger_event"] = "mana_value"
    else:
        selector = _INCUBATE_X_SELECTORS.get(m.group("selector"))
        if selector is None:
            return None  # fail closed — an X phrasing we don't model
        extra["count_from_count_selector"] = selector
    return [EffectSpec("create_token", {
        "count": 2 if m.group("twice") else 1,
        "token_name": "Incubator",
        "extra_counters": extra,
    })]


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


# "Starting with you, each player votes for `<A>` or `<B>`. If `<A>` gets
# more votes, `<X>`. If `<B>` gets more votes or the vote is tied, `<Y>`."
# (RULE 701.38, PAR-29). `RulesEngine.request_vote` / `effects.VoteEffect`
# own the APNAP sweep and outcome. Two shapes: a majority branch (this
# handler) and per-vote scaling ("… for each `<A>` vote", `_vote_per_vote`
# below). Only the 2-option majority form here — 3+-option votes
# (Council Guardian) and "vote for a permanent/card" (Council's Judgment)
# stay UNMODELED, fail-closed.
_VOTE_HEADER_RE = _c(
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
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

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
    if any(s.params.get("target_kind") for s in (*x_specs, *y_specs)):
        return None  # a targeted branch can't resolve off-stack — see `_pay_cost_then_general`
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
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

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
    per_vote: list[dict] = []
    for i, seg in enumerate(segments):
        opt = seg.group("opt").lower()
        if opt not in lowered:
            return None
        body = seg.group("body").strip()
        # A later segment split on a bare "and" can silently lose a subject
        # carried from the first ("each opponent sacrifices … *and* discards
        # a card for each taxes vote" — the "discards" clause is still each
        # opponent's). Only the first segment may name a per-player subject;
        # fail-closed otherwise rather than mis-scoping it to the caster.
        if i > 0 and re.match(r"^(?:each (?:player|opponent)|target|that player)\b", body):
            return None
        if i == 0 and len(segments) > 1 and re.match(
            r"^(?:each (?:player|opponent)|target|that player)\b", body
        ):
            return None
        body_specs = parse_effect_body(body)
        if not body_specs:
            return None
        if any(s.params.get("target_kind") for s in body_specs):
            return None
        per_vote.append({
            "option": lowered.index(opt),
            "effects": [s.to_dict() for s in body_specs],
            "scale": 1,
        })
    return [EffectSpec("vote", {"options": options, "per_vote_specs": per_vote})]


# "`<player>` faces a villainous choice — `<A>`, or `<B>`." (RULE 701.55,
# PAR-29). `RulesEngine.request_villainous_choice` / `effects.FaceVillainous
# ChoiceEffect` own the APNAP sweep (each facing player applies their own
# pick). Each option is mini-parsed with the facing player as the target:
# "they/that player `<verb>`" → a player-targeted `sacrifice`/`discard`/
# `lose_life`, "you `<verb>`" stays controller-scoped. Only the options
# both parse — cards whose option is "cast a spell without paying", "put a
# permanent from hand", "create a copy of that card", "exile until …" &c.
# stay UNMODELED (tracked in PAR-30).
_VILLAINOUS_HEADER_RE = _c(
    r"(?P<subj>each opponent|that player|that opponent|target opponent|target player|defending player) "
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
    player is the effect's target — `request_villainous_choice` applies
    each option with ``targets=[facing]``); a bare edict ("they sacrifice
    a creature of their choice") maps straight to a player-less
    `sacrifice` spec.
    """
    from ..segmenter import parse_effect_body  # lazy: segmenter imports this module

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
            return [EffectSpec("face_villainous_choice", {
                "subject": subject,
                "option_a": a_specs,
                "option_b": b_specs,
            })]
    return None


# "Bolster N." (RULE 701.39a) — put N +1/+1 counters on a least-toughness
# creature you control (your choice on a tie). `RulesEngine.bolster` /
# `effects.BolsterEffect` (registered as ``bolster``) own the procedure and
# the tie-break choice.
def _bolster(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("bolster", {"amount": int(m.group("n"))})]


# "Bolster X, where X is `<board count>`." (PAR-29) — the three phrases real
# cards print, each onto `continuous.count_selector`'s matching entry.
# A dedicated small map rather than routing through the shared `DEVOTION`
# macro: only one of the three ("tapped creatures you control") overlaps
# its vocabulary at all, and the other two ("cards in your hand", the
# distinct-name artifact-token count) are single-card phrasings not worth
# widening a general grammar for.
_BOLSTER_AMOUNT_SELECTORS: dict[str, str] = {
    "the number of tapped creatures you control": "tapped_creatures_you_control",
    "the number of cards in your hand": "cards_in_your_hand",
    "the number of differently named artifact tokens you control":
        "distinct_named_artifact_tokens_you_control",
}
_BOLSTER_AMOUNT_ALT = "|".join(re.escape(phrase) for phrase in _BOLSTER_AMOUNT_SELECTORS)


def _bolster_x(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector = _BOLSTER_AMOUNT_SELECTORS.get(m.group("selector"))
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
_AIRBEND_RE = _c(
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
#: (`_peel_optional`), so this only claims the bare verb.
_AIRBEND_TRIGGER_SUBJECT_RE = _c(
    r"airbend (?:that creature|that permanent|it)"
)


def _airbend_trigger_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("exile", {
        "target_kind": "trigger_subject",
        "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}",
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
_EARTHBEND_THAT_CREATURES_POWER_RE = _c(
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
_EARTHBEND_X_RE = _c(
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


# "Suspect <creature>." (RULE 701.60a — Murders at Karlov Manor): the
# creature gains the suspected designation (menace + can't block, 701.60b).
# `RulesEngine.suspect` / `effects.SuspectEffect` (registered as
# ``suspect``). Same subject shapes as `_goad`/`_explore`:
#   • "suspect it" — the ability's own source ("when ~ enters, suspect it");
#   • "suspect it"/"suspect that creature" after a targeting clause — the
#     previous target (`previous_subject_only`, Caught Red-Handed);
#   • "suspect enchanted creature" — this Aura's host (`attached`);
#   • "suspect [up to N] target creature[ an opponent controls / other
#     target creature you control]" — off the shared TARGET rows.
_SUSPECT_TARGET_KINDS = (
    "creature", "creature_you_control", "creature_you_dont_control",
    "other_creature_you_control",
)


def _suspect_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {})]


def _suspect_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"previous_subject": True})]


def _suspect_attached(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("suspect", {"attached": True})]


def _suspect_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in _SUSPECT_TARGET_KINDS:
        return None  # only a creature can be suspected (RULE 701.60a)
    return [EffectSpec("suspect", {"target_kind": kind, **_optional_param(m)})]


# "All suspected creatures are no longer suspected." (RULE 701.60a's
# reverse — Absolving Lammasu). Only the mass standalone shape; the
# conditional single-creature "if it's suspected, it's no longer suspected"
# stays unclaimed, fail-closed.
def _remove_suspected_all(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("remove_suspected", {})]


# "Detain [up to N] target <permanent> an opponent controls." (RULE 701.35a
# — Return to Ravnica). `RulesEngine.detain` / `effects.DetainEffect`
# (registered as ``detain``). Only an opponent-controlled creature or
# nonland permanent (every real detain card); a plain "target creature"
# with no controller qualifier isn't a real printing, so leave it
# unclaimed. "detain each nonland permanent … with mana value N or less"
# (Lavinia) and a "with backup or vehicle" filter (Azorius Traffic
# Enforcement) stay UNMODELED — a selector + filter this doesn't build yet.
_DETAIN_TARGET_KINDS = (
    "creature_you_dont_control", "nonland_permanent_you_dont_control",
    "permanent_you_dont_control",
)
_DETAIN_MULTI_RE = _c(
    r"detain up to (?P<n>2|3|two|three) target "
    r"(?P<what>creatures|nonland permanents) "
    r"(?:your opponents control|an opponent controls)"
)
_DETAIN_WORD_N = {"two": 2, "three": 3, "2": 2, "3": 3}


def _detain(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in _DETAIN_TARGET_KINDS:
        return None
    return [EffectSpec("detain", {"target_kind": kind, **_optional_param(m)})]


def _detain_multi(m: re.Match[str]) -> list[EffectSpec]:
    kind = ("nonland_permanent_you_dont_control"
            if m.group("what") == "nonland permanents" else "creature_you_dont_control")
    return [EffectSpec("detain", {
        "target_kind": kind, "count": _DETAIN_WORD_N[m.group("n")], "optional": True,
    })]


# "Goad target creature." (RULE 701.15a) and its controller-scoped variants
# ("…target creature an opponent controls"), off the shared `TARGET` rows.
def _goad(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        # Goaded is only ever a creature designation (RULE 701.15b) — a
        # non-creature target row here means the clause isn't what it looks
        # like, so leave it unclaimed.
        return None
    return [EffectSpec("goad", {"target_kind": kind, **_optional_param(m)})]


# "Goad it." / "Goad that creature." — the pronoun form, pointing at whatever
# the *previous* clause of this same ability targeted ("~ deals 2 damage to
# target creature. Goad that creature.", Hellrider-shaped). Offered only when
# such a clause really preceded it (`EffectHandler.previous_subject_only`),
# never as a blind claim.
def _goad_previous(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None})]


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


# "The tokens are goaded for the rest of the game." (Rendmaw, The War Games,
# Life of the Party) — the subject is what an *earlier clause of this same
# ability* just created, which is `GameContext.created_objects`; "for the
# rest of the game" is the no-expiry variant of RULE 701.15a's default
# "until your next turn".
def _goad_created(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None, "referent": "created", "permanent": True})]


# "It's goaded for the rest of the game." (Jon Irenicus) — the same no-expiry
# designation aimed at the previous clause's *target* instead.
def _goad_previous_permanent(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("goad", {"target_kind": None, "permanent": True})]


# "You become the monarch." / "Target player becomes the monarch." (RULE
# 725.1) and "You take the initiative." / "Target player takes the
# initiative." (RULE 726.1) — plain designation grants, the same untargeted-
# vs-targeted "who" split `_gain_life`/`_lose_life` use.
def _become_monarch(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("become_monarch", params)]


def _take_initiative(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("take_initiative", params)]


# "[You/Target player] get[s] an emblem with '<ability>'." (RULE 114.2) —
# the quoted ability is itself an ordinary ability line, recursively parsed
# the same way `static_handlers._quoted_ability_grant_effects` parses an
# Aura/Equipment's quoted grant (`segmenter.segment_line`, imported lazily in
# `_emblem_ability_spec` below — `segmenter` imports *this* module, so a
# module-level import would cycle). Unlike that grant (which flattens to a
# `grant_triggered_ability`'s bare effects list), the *whole* nested
# `AbilitySpec` is kept, since `game/rules_engine.py`'s `create_emblem` binds
# it fresh at resolve time against a synthetic `Emblem` source (RULE 114.4) —
# there's no host permanent to flatten onto in the first place.
_EMBLEM_RE = re.compile(
    r'(?P<who>you |target player )?gets? an emblem with "(?P<inner>.+)"',
    re.IGNORECASE | re.DOTALL,
)

#: Subject/selector shapes that only mean something relative to a *source
#: permanent* ("this creature", "equipped/enchanted creature", "other
#: creatures you control") — meaningless for an emblem's synthetic source,
#: so a nested spec using one is rejected (fail-closed) rather than silently
#: binding an ability that can never fire, or that resolves a selector that
#: always comes back empty.
_EMBLEM_UNSUPPORTED_SUBJECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "self_or_attached_permanent"}
)
_EMBLEM_UNSUPPORTED_AFFECTS: frozenset[str] = frozenset(
    {"self", "attached_permanent", "other_creatures_you_control"}
)


def _emblem_ability_spec(inner: str) -> Optional[dict]:
    from ..segmenter import segment_line  # lazy: segmenter imports this module

    segment = segment_line(
        inner.strip(),
        allow_spell_effect=False,
        provenance=ParserProvenance(version="nested", source="rule:oracle"),
    )
    spec = segment.spec
    if spec is None or spec.modes:
        return None
    if spec.ability_kind == "triggered":
        condition = (spec.trigger or {}).get("condition") or {}
        if condition.get("subject") in _EMBLEM_UNSUPPORTED_SUBJECTS:
            return None
        if condition.get("subject") == "group" and condition.get("other"):
            return None
    elif spec.ability_kind == "static":
        if any(e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS for e in spec.effects):
            return None
    elif spec.ability_kind == "activated":
        # RULE 114.4 also permits an emblem's own activated ability (MEC-8) —
        # `RulesEngine.create_emblem` binds it fresh against the synthetic
        # `Emblem` source exactly like the triggered/static cases, so the
        # same fail-closed self-referential guard applies: no real emblem
        # prints one yet, but "sacrifice this"/"equipped creature…"-shaped
        # effects would be meaningless with no host permanent.
        if any(
            e.params.get("target_kind") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("selector") in _EMBLEM_UNSUPPORTED_SUBJECTS
            or e.params.get("affects") in _EMBLEM_UNSUPPORTED_AFFECTS
            for e in spec.effects
        ):
            return None
    else:
        return None  # only a static/triggered/activated ability can live in an emblem
    try:
        spec.validate()
    except Exception:
        return None
    return spec.to_dict()


def _create_emblem(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    ability = _emblem_ability_spec(m.group("inner"))
    if ability is None:
        return None
    params: dict = {"ability": ability}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("create_emblem", params)]


# A pump's subject: a targeted creature/permanent, the self-reference ``~``
# (a creature's own activated "~ gets +1/+0 …"), or an untargeted *group*
# ("creatures you control get +2/+1 …" — RULE 601.2c, not a target at all;
# the common Saga-chapter/anthem-spell shape, or the board-wide "all
# creatures get -N/-N until end of turn" mass-removal shape, Infest/Blight
# Grenade-shaped). Shared by the pump handlers.
#: PAR-13's own two additions — "creatures your opponents control"/
#: "creatures you don't control" (Mouth of the Storm/Behold the
#: Unspeakable-shaped mass debuffs) — both the same `continuous.
#: group_selector_objects` selector as each other (every creature not
#: yours, the plain-English reading of either phrasing).
_GROUP = (
    r"(?P<group>other creatures you control"
    # "Each creature you control with a counter on it gains firebending N …"
    # (Iroh, Dragon of the West) — a counter-presence filter on the
    # controller-scoped creature set; tried before the bare
    # "each creature you control" alternative below.
    r"|each creature you control with a counter on it"
    r"|each creature you control"
    r"|creatures you control|all creatures"
    r"|creatures your opponents control|creatures you don'?t control"
    r"|permanents you control|elves you control|elf creatures you control"
    # PAR-19: "Attacking creatures get -3/-0 until end of turn." (Lethargy
    # Trap-shaped) — unscoped by controller, the same `group_selector_
    # objects` "attacking_creatures" branch Motivated Pony's anthem and
    # `TapEffect.selector` (MEC-28) already reuse.
    r"|attacking creatures)"
)
_SUBJECT = (
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP}|(?P<attached>{_ATTACHED_SUBJECT}))"
)
#: A matched ``group`` phrase → its `continuous.group_selector_objects` selector.
_GROUP_SELECTORS: dict[str, str] = {
    "creatures you control": "creatures_you_control",
    # The distributive-singular phrasing ("Each creature you control gains
    # indestructible until end of turn." — Avacyn and Griselbrand) is the
    # same group, just worded per-creature.
    "each creature you control": "creatures_you_control",
    "each creature you control with a counter on it":
        "creatures_you_control_with_a_counter",
    "other creatures you control": "other_creatures_you_control",
    "all creatures": "all_creatures",
    "creatures your opponents control": "creatures_opponents_control",
    "creatures you dont control": "creatures_opponents_control",
    # "Permanents you control gain hexproof and indestructible until end of
    # turn." (Heroic Intervention-shaped) — the non-creature-scoped sibling;
    # `continuous.group_selector_objects`'s own "permanents_you_control"
    # branch already existed for the layer-6 static grant family, just
    # never reachable from a one-shot `PumpEffect`'s ``selector`` before.
    "permanents you control": "permanents_you_control",
    # "Elves you control get +2/+2 and gain deathtouch until end of turn."
    # (Elvish Warmaster) / "Elf creatures you control get +3/+3 and gain
    # trample until end of turn." (Ezuri, Renegade Leader) — the same
    # subtype-scoped selector under both real phrasings.
    "elves you control": "creatures_you_control_of_type_elf",
    "elf creatures you control": "creatures_you_control_of_type_elf",
    "attacking creatures": "attacking_creatures",
}
#: A signed P/T delta, "+3/+3" / "-2/-2" / "+0/-1" (ASCII or unicode minus).
_PT_DELTA = r"(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"

#: PAR-15's "any number of target creatures each get +N/+N [and gain
#: `<keyword>`] until end of turn" (Aerial Formation/Ajani's Presence/Cruel
#: Feeding/Desperate Stand/Rouse the Mob-shaped) — the pump-family sibling of
#: `_add_counters_multi_target`'s "each of up to N" shape: every chosen
#: creature gets the *full* stated boost (`PumpEffect`'s ``target_count``,
#: not a divided pool).
_PUMP_MULTI_TARGET_RE = _c(
    rf"any number of target creatures each get {_PT_DELTA}"
    rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
)


def _pump_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": "creature", "target_count": _ANY_NUMBER_TARGET_CAP, "optional": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None  # unmodeled granted ability → fail-closed
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


#: "Untap those creatures." (Colossal Heroics' own trailing sentence,
#: following "Any number of target creatures each get +2/+2 until end of
#: turn.") — the tap-family sibling of `_return_previous_group`: no target
#: of its own, only offered when a preceding multi-target clause actually
#: chose a group (`EffectHandler.previous_subject_only`).
_UNTAP_PREVIOUS_GROUP_RE = _c(r"(?:then )?untap (?:those creatures|them)")


def _untap_previous_group(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": True})]


#: "…, then untap **that land**." (Avatar Kyoshi — PAR-30, following
#: "earthbend N") / "…, then tap **that permanent**." — the singular
#: `previous_subject` sibling of `_UNTAP_PREVIOUS_GROUP_RE`: "that
#: `<permanent-word>`" names the single object the preceding clause chose
#: (`EffectHandler.previous_subject_only`, `GameContext.previous_targets`).
#: Distinct from `_TAP_GROUP_SUBJECT_RE` ("that creature", `group_subject_
#: only`) and `_tap_self` ("it"/"this ~", the ability's own source).
_TAP_PREVIOUS_SUBJECT_RE = _c(
    r"(?:then )?(?P<verb>tap|untap) that (?:land|permanent|artifact|creature)"
)


def _tap_previous_subject(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("tap", {"previous_subject": True, "untap": m.group("verb").lower() == "untap"})]


#: "[That / target / ~] `<permanent>` doesn't untap during
#: [its controller's / your / the player's] next untap step." — Barl's Cage
#: and the ~95-card "Tap X. It doesn't untap …" tempo family (Chillbringer,
#: Berg Strider, the Frost Lynx cycle, Entangling Trap / Pollen Lullaby
#: clash payoffs, …). `SkipNextUntapEffect` sets `GameObject.
#: skip_next_untap`, RULE 702.19b's own one-time flag. Three subject shapes,
#: routed by the same `_PERMANENT_NOUN`/`~`/pronoun split every other
#: family here uses.
_DONT_UNTAP_SUFFIX = (
    r" doesn'?t untap during (?:its controller'?s|your|the player'?s) next untap step"
)
_SKIP_UNTAP_TARGET_RE = _c(rf"target (?P<what>creature|artifact|land|permanent){_DONT_UNTAP_SUFFIX}")
_SKIP_UNTAP_PREV_RE = _c(rf"(?:it|that (?:creature|artifact|land|permanent)){_DONT_UNTAP_SUFFIX}")
_SKIP_UNTAP_SELF_RE = _c(rf"(?:~|this (?:creature|artifact|permanent)){_DONT_UNTAP_SUFFIX}")


def _skip_untap_target(m: re.Match[str]) -> list[EffectSpec]:
    what = m.group("what")
    kind = "creature" if what == "creature" else what
    return [EffectSpec("skip_next_untap", {"target_kind": kind})]


def _skip_untap_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"previous_subject": True})]


def _skip_untap_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("skip_next_untap", {"target_kind": None})]


#: "[`<TARGET>` / ~ / it] gains protection from the color of your choice
#: until end of turn." (Gods Willing / Emerge Unscathed / Jareth / Feat of
#: Resistance — RULE 702.16, ~27 SOLO). The engine primitive
#: (`effects.GrantProtectionEffect` / `RulesEngine.grant_protection_choice`
#: — the interactive `grant_protection_color` pick, `temp_protections`,
#: cleared at cleanup) is Mother of Runes'; only the parser recognition of
#: this exact phrasing was missing.
_PROT_CHOICE_SUFFIX = r" gains? protection from the colou?r of your choice until end of turn"
_GRANT_PROT_CHOICE_TARGET_RE = _c(rf"{TARGET}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_SELF_RE = _c(rf"{_SELF_SUBJECT}{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_PREV_RE = _c(rf"it{_PROT_CHOICE_SUFFIX}")
_GRANT_PROT_CHOICE_KINDS = frozenset({"creature", "creature_you_control", "permanent_you_control"})


def _grant_prot_choice_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in _GRANT_PROT_CHOICE_KINDS:
        return None
    return [EffectSpec("grant_protection", {"target_kind": kind})]


def _grant_prot_choice_self(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"target_kind": None})]


def _grant_prot_choice_prev(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("grant_protection", {"previous_subject": True})]


#: "Reveal cards from the top of your library until you reveal a `<land /
#: creature / artifact / enchantment / nonland / basic land>` card. Put that
#: card `<onto the battlefield / into your hand>` and the rest `<on the
#: bottom of your library in a random order / into your graveyard / shuffle
#: into your library>`." (Recross the Paths, Clifftop Lookout, Atla Palani,
#: Bloodline Pretender-cycle, ~40 real cards.) `RulesEngine.dig_until` /
#: `effects.DigUntilEffect` — the generalized cascade dig — is the engine
#: primitive; this is its "reveal until a *type* predicate" recognition.
#: **Documented simplification**: "in any order" is modeled as the engine's
#: only bottoming mode, a *random* order — the player doesn't get to choose
#: the sequence of the bottomed cards.
_DIG_UNTIL_PRED = {
    "a land": {"type": "land"},
    "a basic land": {"type": "land", "basic": True},
    "a creature": {"type": "creature"},
    "an artifact": {"type": "artifact"},
    "an enchantment": {"type": "enchantment"},
    "a nonland": {"without_type": "land"},
    "a nonartifact, nonland": {"without_type": ["artifact", "land"]},
}
_DIG_UNTIL_HIT = {
    "onto the battlefield": "battlefield",
    "into your hand": "hand",
}
#: The "…and the rest `<somewhere>`" tail — matched as a whole phrase
#: (`re.search` inside the leftover) so the many "put all other cards
#: revealed this way" / "the rest" / ", then shuffle" connector spellings
#: don't each need a row.
_DIG_UNTIL_REST_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"bottom of your library in (?:a random|any) order", re.I), "library_bottom_random"),
    (re.compile(r"shuffle .*?into your library", re.I), "library_shuffled"),
    (re.compile(r"(?:cards? .*?)?into your graveyard", re.I), "graveyard"),
]
_REVEAL_UNTIL_TYPE_RE = _c(
    r"reveal cards from the top of your library until you reveal "
    rf"(?P<pred>{'|'.join(map(re.escape, _DIG_UNTIL_PRED))}) card\. "
    rf"put that card (?P<hit>{'|'.join(map(re.escape, _DIG_UNTIL_HIT))})"
    r"(?P<rest>.+)"
)


def _reveal_until_type(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    tail = m.group("rest")
    # "put that card onto the battlefield **tapped**" (Clifftop Lookout) —
    # `dig_until`'s `_place_dig_hit` has no tapped-entry mode, and a land
    # entering tapped vs untapped is a real difference; fail closed.
    if re.match(r"(?i)^\s*tapped\b", tail):
        return None
    rest_dest = next((d for rx, d in _DIG_UNTIL_REST_RES if rx.search(tail)), None)
    if rest_dest is None:
        return None
    return [EffectSpec("dig_until", {
        "criteria": dict(_DIG_UNTIL_PRED[m.group("pred")]),
        "hit_destination": _DIG_UNTIL_HIT[m.group("hit")],
        "rest_destination": rest_dest,
    })]


#: PAR-30 — the single biggest RULE 701-trail sub-cluster (~100 SOLO cache
#: cards): a trailing "[Then] sacrifice / exile <it / that creature / that
#: token / them / those tokens> at the beginning of [the/your] next end
#: step." (Kiki-Jiki / Twinflame / every "create a token …, exile it" and
#: "reanimate …, sacrifice it" card). RULE 603.7 delayed trigger over
#: `create_delayed_trigger` — the same primitive the hand-authored
#: Kiki-Jiki/Twinflame entries use, with a new ``capture="previous_or_
#: self"`` that bakes in whatever the *earlier clause of this same
#: resolution* chose (RULE 115 target — `GameContext.previous_targets`) or
#: created (RULE 608.2 — `created_objects`), falling back to the ability's
#: own source for a bare self-subject "sacrifice it" (Brackwater Elemental /
#: Deathknell Kami). Deliberately **not** `previous_subject_only`: the
#: capture no-ops cleanly on an empty referent chain (same safety the
#: exile→copy connector relies on), and a create-token antecedent never
#: sets the segmenter's `previous_subject` flag, so gating would miss the
#: majority of the cluster.
_DELAYED_SAC_EXILE_TAIL_RE = _c(
    r"(?:then )?(?P<verb>sacrifice|exile|destroy) "
    r"(?:it|that creature|that token|that permanent|that artifact|those tokens|them) "
    r"at the beginning of (?:the|your) next end step"
)
_DELAYED_TAIL_INNER = {
    "sacrifice": "sacrifice_specific",
    "exile": "exile_specific",
    "destroy": "destroy_specific",  # Old Hob, Alleycat Blues
}


def _delayed_sac_exile_tail(m: re.Match[str]) -> list[EffectSpec]:
    inner = _DELAYED_TAIL_INNER[m.group("verb").lower()]
    return [EffectSpec("create_delayed_trigger", {
        "step": "end",
        "scope": "any",
        "capture": "previous_or_self",
        "effects": [{"type": inner, "params": {}}],
    })]


#: ENG-30: "They [each] get +N/+N [and gain `<kw>`]/gain `<kw>` until end of
#: turn." (A-Bretagard Stronghold/Fancy Footwork-shaped, following "…1 or 2
#: target creatures…") — the pump-family sibling of `_UNTAP_PREVIOUS_GROUP_
#: RE` just above: "they" is the RULE 115 target *group* the preceding
#: clause chose (`PumpEffect.previous_subject`/`GameContext.
#: previous_targets`), not a mass selector — that's `_PUMP_PREVIOUS_
#: SELECTOR_RE`'s own, separately-gated (`previous_selector_only`) row,
#: which this can't collide with since `match_clause` only ever tries the
#: one whose gate the actual preceding clause satisfied. Two rows (P/T vs.
#: keyword-only) rather than one combined regex, mirroring `_pump`/`_pump_
#: keyword`'s own split for the ordinary targeted form.
#: "they"/"those creatures"/"each of those creatures" — all name the RULE
#: 115 target group the preceding clause chose (`GameContext.
#: previous_targets`); the wordier forms are what most real cards actually
#: print ("Arm the Cathars", "Cauldron Haze", …).
_PREV_GROUP_SUBJECT = r"(?:they|those creatures|each of those creatures)"
_PUMP_PREVIOUS_TARGETS_PT_RE = _c(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gets? (?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREVIOUS_TARGETS_KW_RE = _c(
    rf"{_PREV_GROUP_SUBJECT}(?: each)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


def _pump_previous_targets_pt(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "previous_subject": True,
    }
    if m.groupdict().get("kw"):
        keywords = _token_keywords(m.group("kw"))
        if keywords is None:
            return None
        params["keywords"] = keywords
    return [EffectSpec("pump", params)]


def _pump_previous_targets_kw(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {"keywords": keywords, "previous_subject": True})]


#: PAR-30: the singular-pronoun sibling of `_PUMP_PREVIOUS_TARGETS_*_RE` —
#: "it [also] gets +N/+N [and gains `<kw>`] until end of turn" / "it [also]
#: gains `<kw>` until end of turn", where "it"/"that creature"/"that
#: permanent" is the single RULE 115 target the preceding split clause chose
#: (`GameContext.previous_targets`, `PumpEffect.previous_subject`). Real
#: cards run this off a threaten clause's own restatement tail ("gain
#: control of target creature until end of turn. untap that creature. **it**
#: gains haste …") when a further sentence keeps `segmenter.
#: _GAIN_CONTROL_HASTE_TAIL_RE` from absorbing the pair whole, and off clash
#: "if you win, **that creature** gets +2/+2 …" payoffs (RULE 701.30d).
#: Gated `previous_subject_only`, so it only competes once the preceding
#: clause actually bound the pronoun.
_PREV_SUBJECT_SINGULAR = r"(?:it|that creature|that permanent|that artifact|that token)"
_PUMP_PREV_SINGULAR_PT_RE = _c(
    rf"{_PREV_SUBJECT_SINGULAR}(?: also)? gets? (?:an additional )?(?P<p>[+\-−]\d+)/(?P<t>[+\-−]\d+)"
    r"(?: and gains? (?P<kw>[a-z][a-z, ]*?))? until end of turn"
)
_PUMP_PREV_SINGULAR_KW_RE = _c(
    rf"{_PREV_SUBJECT_SINGULAR}(?: also)? gains? (?P<kw>[a-z][a-z, ]*?) until end of turn"
)


#: MEC-28: "They gain first strike until end of turn." (Karlach, Fury of
#: Avernus's own trailing sentence, following "untap all attacking
#: creatures.") — the *mass-selector* sibling of the row above: "they" isn't
#: a RULE 115 targeted group at all (`_UNTAP_PREVIOUS_GROUP_RE`'s own
#: `previous_subject`/`GameContext.previous_targets` idiom), it's whichever
#: group the *previous clause's own selector* (RULE 601.2c, untargeted) just
#: acted on — `PumpEffect`'s new ``selector="previous_selector"`` sentinel,
#: resolved at apply time off the new `GameContext.previous_selector` field
#: `_apply_effects_partitioned` now tracks alongside `previous_targets`.
#: Only offered when the preceding split clause's own spec really used a
#: recognised group selector (`segmenter._announces_group_selector`,
#: `EffectHandler.previous_selector_only`) — never reused for
#: `previous_subject_only`'s existing meaning, a deliberately separate gate.
_PUMP_PREVIOUS_SELECTOR_RE = _c(
    rf"{_PREV_GROUP_SUBJECT} gains? (?P<kw>[a-z, ]+?) until end of turn"
)


def _pump_previous_selector(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    return [EffectSpec("pump", {"keywords": keywords, "selector": "previous_selector"})]


#: "target creature gets +1/+0 until end of turn and can't be blocked this
#: turn" (You Come to a River-shaped) — the P/T-then-unblockable ordering
#: (unlike `_pump`'s "and gains <kw> until end of turn", the keyword clause
#: sits *before* "until end of turn"; here "can't be blocked this turn"
#: trails it instead) — a targeted-only shape (real cards always name a
#: single "target creature", never a self/group subject for this combo), so
#: it uses `TARGET` directly rather than the broader `_SUBJECT`.
_PUMP_UNBLOCKABLE_RE = _c(
    rf"{TARGET} gets? {_PT_DELTA} until end of turn and can'?t be blocked this turn"
)


def _pump_unblockable(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("pump", {
        "power": _signed_int(m.group("p")), "toughness": _signed_int(m.group("t")),
        "target_kind": kind, "unblockable": True,
    })]


#: ENG-32: a bare "~ / target creature can't be blocked this turn" (Giant
#: Koi's own activated ability / Waterbender Ascension) — the standalone
#: `UnblockableEffect`, no P/T delta (that's `_PUMP_UNBLOCKABLE_RE` above).
_CANT_BE_BLOCKED_TURN_RE = _c(
    rf"(?:(?P<selfref>{_SELF_SUBJECT})|{TARGET}) can'?t be blocked this turn"
)


def _cant_be_blocked_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    if m.groupdict().get("selfref"):
        return [EffectSpec("unblockable", {"target_kind": None})]
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("unblockable", {"target_kind": kind})]


#: "Target creature can't block this turn" (Falter/Ahn-Crop Crasher/Abandon
#: the Post) — the *resolve-time* half of the combat-restriction family, and
#: by far its largest: an ordinary one-shot effect (`game/effects.py`'s
#: `CantBlockEffect` → `GameObject.temp_cant_block`, cleared at cleanup),
#: not the standing `combat_restriction` static that
#: `catalogue/static_handlers.py` binds. Three shapes, in the order tried
#: below: N targets ("up to two target creatures"), one target, and the
#: untargeted mass form.
_CANT_BLOCK_TURN_MULTI_RE = _c(
    rf"{_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT}) can'?t block this turn"
)
_CANT_BLOCK_TURN_RE = _c(rf"{TARGET} can'?t block this turn")

#: The untargeted mass form's own subject vocabulary (RULE 601.2c) — a
#: `continuous.group_selector_objects` selector plus an optional
#: characteristic narrowing (`combat.matches_object_filter`), since
#: "creatures **without flying**" is a real printed scope no selector name
#: covers. Bare "creatures" is every creature on the battlefield.
_CANT_BLOCK_TURN_GROUPS: dict[str, tuple[str, dict]] = {
    "creatures": ("all_creatures", {}),
    "all creatures": ("all_creatures", {}),
    "creatures without flying": ("all_creatures", {"without_keyword": "flying"}),
    "creatures with flying": ("all_creatures", {"keyword": "flying"}),
    "creatures your opponents control": ("opponents_permanents", {}),
    "creatures you control": ("creatures_you_control", {}),
    "creatures you don't control": ("opponents_permanents", {}),
}
_CANT_BLOCK_TURN_GROUP_RE = _c(
    r"(?P<group>" + "|".join(re.escape(g) for g in _CANT_BLOCK_TURN_GROUPS)
    + r") can'?t block this turn"
)


def _cant_block_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("cant_block_this_turn", {"target_kind": kind, **_optional_param(m)})]


def _cant_block_turn_multi(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] != "creature":
        return None
    return [EffectSpec("cant_block_this_turn", params)]


#: "~ can't be blocked by creatures with power 2 or less this turn" (Cavern
#: Stomper) / "target creature can't be blocked by Walls this turn" (Tower of
#: Coireall) — the resolve-time sibling of the standing static that
#: `catalogue/static_handlers.py` claims. Reuses that module's own
#: `_object_filter` so the blocker vocabulary is literally the same one, and
#: only the two subjects real cards print here (``~`` and a single target).
_CANT_BE_BLOCKED_BY_TURN_RE = _c(
    rf"(?:(?P<selfref>~)|{TARGET}) can'?t be blocked by (?P<filter>.+) this turn"
)


def _cant_be_blocked_by_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    from .static_handlers import object_filter

    filt = object_filter(m.group("filter"))
    if filt is None:
        return None
    params: dict = {"restriction": {"kind": "cant_be_blocked_by", "filter": filt}}
    if not m.group("selfref"):
        kind = resolve_target_kind(m.group("target"))
        if kind not in ("creature", "creature_you_control"):
            return None
        params["target_kind"] = kind
    return [EffectSpec("combat_restriction_this_turn", params)]


def _cant_block_turn_group(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    selector, filt = _CANT_BLOCK_TURN_GROUPS[m.group("group").lower()]
    params: dict = {"selector": selector}
    if filt:
        params["filter"] = dict(filt)
    return [EffectSpec("cant_block_this_turn", params)]


#: "Target creature can't block ~ this turn." (RULE 509.1a, Provoke-adjacent
#: but without the untap half) — the *pairwise* sibling of `_cant_block_turn`
#: above: that one bars the target from blocking anything, this one bars it
#: from blocking only this ability's own source. Can't be told apart from a
#: standing static's own filter at parse time (the source's instance id
#: doesn't exist yet), so it rides `GrantCombatRestrictionEffect`'s
#: ``restrict_to_source`` instead — see its docstring.
_CANT_BLOCK_SOURCE_TURN_RE = _c(rf"{TARGET} can'?t block (?:~|it|this creature) this turn")

#: "Target creature blocks ~ this turn if able." — the resolve-time,
#: targeted sibling of the standing "~ must be blocked if able." static:
#: forces one specific (usually opposing) creature to block this ability's
#: own source, checked by `GameEngine._enforce_block_requirements` via the
#: `must_block_target` restriction kind.
_BLOCKS_SOURCE_TURN_IF_ABLE_RE = _c(rf"{TARGET} blocks (?:~|it|this creature) this turn if able")


def _cant_block_source_turn(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "cant_block_filtered"},
        "restrict_to_source": True,
    })]


def _blocks_source_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("combat_restriction_this_turn", {
        "target_kind": kind,
        "restriction": {"kind": "must_block_target"},
        "restrict_to_source": True,
    })]


#: "Target creature attacks this turn if able." — the resolve-time, targeted
#: sibling of the standing "~ attacks each combat if able." static (RULE
#: 508.1a): a plain temporary keyword grant (`PumpEffect`'s ``keywords``),
#: since `GameEngine._enforce_attacks_if_able` already reads `combat.has()`,
#: which unions in a `temp_keywords` grant the same as a printed one — no new
#: engine code needed, unlike the pairwise "blocks ~"/"can't block ~" shapes
#: above (which name a *specific* attacker no bare flag can carry).
_ATTACKS_TURN_IF_ABLE_RE = _c(rf"{TARGET} attacks this turn if able")


def _attacks_turn_if_able(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "creature_you_control", "creature_you_dont_control"):
        return None
    return [EffectSpec("pump", {"keywords": ["attacks_if_able"], "target_kind": kind})]


#: RULE 701.47/48 Amass "<Type> N" ("amass Orcs 1"/"amass Zombies 2" — this
#: repo's existing `game/effects.py` `AmassEffect` and its one proven
#: consumer, Orcish Bowmasters (`ability_catalogue/entries_013.py`), both
#: cite it as 701.48; the current `docs/Reference/rules_wiki` text has it
#: renumbered to 701.47 since Learn moved to take 701.48 — same mechanic
#: either way). The printed type word is always a regular "+s" plural in
#: real Oracle text (confirmed against every cached Amass card via
#: `parser_probe.py blocked "amass"` — Orcs/Zombies/Goblins/Birds/Slivers),
#: so it's singularized (`_singularize_amass_subtype`, the same bare
#: trailing-"s" strip `subgrammars._singularize` already uses for the
#: unrelated "N `<type>` you control" count phrase) and capitalized to
#: match `AmassEffect`'s own singular `subtype` param convention ("Orc",
#: not "Orcs" — the exact shape Orcish Bowmasters' hand-authored
#: ``EffectSpec("amass", {"subtype": "Orc", "count": 1})`` uses).
#:
#: Deliberately digit-only counts (`NUMBER`, not `COUNT_X`):
#: `EffectRegistry.register("amass", ...)` forces ``int(p.get("count", 1))``
#: on bind, so a literal "x" sentinel (RULE 107.3c's announced {X} — "amass
#: Orcs X", Assault on Osgiliath/Barad-dûr) would raise at bind time rather
#: than resolve through the ordinary `_substitute_x` machinery every other
#: count-bearing effect gets for free — `AmassEffect`/its registry factory
#: were never actually built to accept the sentinel. Left unclaimed rather
#: than risk that crash; teaching them the "x" sentinel is separate engine
#: work, out of this parser-only change's scope.
def _singularize_amass_subtype(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 1 else word


def _amass(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    subtype = _singularize_amass_subtype(m.group("subtype")).capitalize()
    return [EffectSpec("amass", {"subtype": subtype, "count": int(m.group("n"))})]


_AMASS_RE = _c(rf"amass (?P<subtype>[a-z]+) {NUMBER}")


#: RULE 701.47d: pre-errata "amass N" with no subtype at all — Oracle text
#: has since been errata'd to always spell out "amass Zombies N" instead, so
#: no card in today's cache reaches this row (confirmed: none of the 73
#: cached Amass-mentioning cards omit a type word) — kept for a
#: differently-worded future import rather than as a real current unlock.
#: Defaults to Zombie (matching the errata'd wording and `AmassEffect`'s own
#: default subtype), spelled out explicitly and singular here rather than
#: relying on that default, which is itself stored plural ("Zombies") and
#: would otherwise produce a grammatically-wrong "Army Zombies" token type
#: line if this row were ever actually hit.
def _amass_untyped(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    return [EffectSpec("amass", {"subtype": "Zombie", "count": int(m.group("n"))})]


_AMASS_UNTYPED_RE = _c(rf"amass {NUMBER}")


# --- The table --------------------------------------------------------------
# Order matters only for reporting; a clause is claimed by the first handler
# whose full-clause regex matches. Every pattern is anchored to the whole
# clause by `EffectHandler.match`'s `fullmatch`, so no partial claims.

HANDLERS: list[EffectHandler] = [
    # RULE 701.47/48 Amass "<Type> N" — "amass Orcs 1"/"amass Zombies 2".
    # Tried before the untyped row below since a real type word always
    # parses here first (the untyped row's bare NUMBER can never see it —
    # a type word isn't a digit — so the ordering is purely cosmetic).
    EffectHandler("amass", _AMASS_RE, _amass),
    # RULE 701.47d's pre-errata bare "amass N" (no subtype) — see the
    # builder's own docstring; not expected to match any card in today's
    # already-errata'd cache.
    EffectHandler("amass_untyped", _AMASS_UNTYPED_RE, _amass_untyped),
    # "~ deals 2 damage to any target. If this spell was kicked, it deals 4
    # damage instead." — the two-sentence override form, tried before the
    # single-sentence `_damage` row below since only this one's regex spans
    # the whole clause.
    EffectHandler(
        "damage_kicked_override",
        _DAMAGE_KICKED_OVERRIDE_RE,
        _damage_kicked_override,
    ),
    # "Create a token that's a copy of target creature. If this spell was
    # kicked, create five of those tokens instead." (Rite of Replication) —
    # tried before the bare `copy_permanent` row for the same two-sentence-
    # spans-the-whole-clause reason as the damage row above.
    EffectHandler(
        "copy_permanent_kicked_override",
        _COPY_PERMANENT_KICKED_OVERRIDE_RE,
        _copy_permanent_kicked_override,
    ),
    # "Create a token that's a copy of target creature[, except <modifier(s)>]."
    # (RULE 707/706.2, Cackling Counterpart/Multiversal Recruitment/Impostor
    # Syndrome-shaped) — the bare form and every safely-generalizable
    # compound "except" tail in one row (`_parse_copy_except_tail`).
    EffectHandler(
        "copy_permanent",
        _COPY_PERMANENT_RE,
        _copy_permanent,
    ),
    # PAR-18: "exile up to 1 target creature card from a graveyard. Create a
    # token that's a copy of it/that card[, except <modifier(s)>]." — the
    # pronoun sibling of the row above, offered only once an earlier clause
    # of the same ability actually chose something (`GameContext.
    # previous_targets`).
    EffectHandler(
        "copy_permanent_previous",
        _COPY_PERMANENT_PREVIOUS_RE,
        _copy_permanent_previous,
        previous_subject_only=True,
    ),
    # Tried before the plain `damage` row below, whose `TARGET` alternation
    # has no two-colour-OR creature filter of its own.
    EffectHandler(
        "damage_target_two_color",
        _DAMAGE_TARGET_TWO_COLOR_RE,
        _damage_target_two_color,
    ),
    # "~ deals 3 damage to any target" / "deal 2 damage to target creature" /
    # "it deals 2 damage to target opponent" (a triggered-ability body's own
    # "it"/"this creature"/"this land"/"this permanent" subject — cosmetic,
    # since the source is already bound at bind time regardless of wording).
    EffectHandler(
        "damage",
        _c(rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to {TARGET}"),
        _damage,
    ),
    # "~ deals X damage to any target." (Blaze/Devil's Play/Fanning the
    # Flames, and every "{X}{R}, {T}, Sacrifice ~: it deals X damage …"
    # activated ability) — the {X}-scaled sibling, emitting the ``"x"``
    # sentinel `RulesEngine._substitute_x` rewrites off the spell/ability's
    # announced {X}. Digit-free, so no overlap with the `NUMBER` row above.
    EffectHandler(
        "damage_x",
        _c(rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? x damage to {TARGET}"),
        _damage_x,
    ),
    # "~ deals 6 damage to each of up to two target creatures and/or
    # planeswalkers" (RULE 115.1a generalized to N>=2) — the full amount
    # applies to *every* chosen target, not divided among them.
    EffectHandler(
        "damage_each_multi_target",
        _c(
            rf"(?:(?:~|it|this creature|this land|this permanent) )?"
            rf"deals? (?P<amount>\d+) damage to each of {_MULTI_TARGET_QUANTIFIER}"
            rf"(?P<target>{_MULTI_TARGET_ALT})"
        ),
        _damage_each_multi_target,
    ),
    # ENG-30: "deals N damage to each of 1 or 2 targets" (Storm of Steel) —
    # tried before the row above since that row's `_MULTI_TARGET_ALT` has no
    # bare "targets" option (RULE 115.4 "any target" is specific to
    # damage/prevention, unlike destroy/exile/tap's typed object phrasing —
    # see `_DAMAGE_EACH_RANGE_RE`'s own comment for why this stays a local
    # alternation instead of widening the shared table).
    EffectHandler(
        "damage_each_range",
        _DAMAGE_EACH_RANGE_RE,
        _damage_each_range,
    ),
    # RULE 601.2d "divided as you choose among any number of target(s)"
    # (PAR-15) — a split total, not the "each of N" full-amount shape above.
    EffectHandler(
        "divided_damage",
        _DIVIDED_DAMAGE_RE,
        _divided_damage,
    ),
    # ENG-30: "deals N damage divided as you choose among 1 or 2 targets"
    # (Arc Mage/Chandra's Pyrohelix/Electrolyze/Fire // Ice/Forked Bolt/
    # Skarrgan Hellkite) — tried before the row above for the same reason.
    EffectHandler(
        "divided_damage_range",
        _DIVIDED_DAMAGE_RANGE_RE,
        _divided_damage_range,
    ),
    # RULE 615's divided-prevention sibling (PAR-15) — Embolden/Remedy/
    # Angel of Salvation.
    EffectHandler(
        "prevent_divided_damage",
        _PREVENT_DIVIDED_DAMAGE_RE,
        _prevent_divided_damage,
    ),
    # RULE 615's plain single-target sibling — Alabaster Wall/Amulet of
    # Kroog/Aven Redeemer-shaped.
    EffectHandler(
        "prevent_damage_single_target",
        _PREVENT_DAMAGE_SINGLE_TARGET_RE,
        _prevent_damage_single_target,
    ),
    # RULE 615's unscoped Fog-shaped form — no recipient at all.
    EffectHandler(
        "prevent_all_combat_damage",
        _PREVENT_ALL_COMBAT_DAMAGE_RE,
        _prevent_all_combat_damage,
    ),
    EffectHandler(
        "damage_per_noncreature_spell_cast_this_turn",
        _DAMAGE_PER_NONCREATURE_SPELL_CAST_THIS_TURN_RE,
        _damage_per_noncreature_spell_cast_this_turn,
    ),
    # Tried before the single-sentence row below (a strict superset of its
    # own opening clause, so it must win the race or never get a turn).
    EffectHandler(
        "damage_each_opponent_and_creatures_exile",
        _DAMAGE_EACH_OPPONENT_AND_CREATURES_EXILE_RE,
        _damage_each_opponent_and_creatures_exile,
    ),
    # Tried before the plain `damage_selector` row below (its own "each
    # opponent" alternative would otherwise match first and leave "and each
    # creature they control" unconsumed, failing the clause closed).
    EffectHandler(
        "damage_each_opponent_and_creatures",
        _DAMAGE_EACH_OPPONENT_AND_CREATURES_RE,
        _damage_each_opponent_and_creatures,
    ),
    # "~ deals 2 damage to each creature" / "… to each player" / "… to each
    # opponent" — a mass effect (RULE 601.2c), not RULE 115 targeting.
    EffectHandler(
        "damage_selector",
        _c(
            rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to "
            rf"(?P<selector>each creature|each player|each opponent|that player|them)"
        ),
        _damage_selector,
    ),
    # RULE 202.2f/700.6 "it deals damage to each opponent equal to your
    # devotion to <colour>." (Fanatic of Mogis) — tried before the plain
    # `damage_selector` row above since "equal to …" has no digit `NUMBER`
    # for that row to match.
    EffectHandler("damage_selector_devotion", _DAMAGE_SELECTOR_DEVOTION_RE, _damage_selector_devotion),
    # MEC-27: the draw/gain-life/lose-life verb families `{DEVOTION}` had
    # never reached — always the ability's own controller, unlike the mass
    # "each player/opponent loses life" row below.
    EffectHandler("draw_devotion", _DRAW_DEVOTION_RE, _draw_devotion),
    EffectHandler("gain_life_devotion", _GAIN_LIFE_DEVOTION_RE, _gain_life_devotion),
    EffectHandler("lose_life_self_devotion", _LOSE_LIFE_SELF_DEVOTION_RE, _lose_life_self_devotion),
    EffectHandler(
        "draw_and_lose_life_devotion", _DRAW_AND_LOSE_LIFE_DEVOTION_RE, _draw_and_lose_life_devotion
    ),
    EffectHandler(
        "gain_life_and_draw_devotion", _GAIN_LIFE_AND_DRAW_DEVOTION_RE, _gain_life_and_draw_devotion
    ),
    EffectHandler(
        "draw_and_gain_life_devotion", _DRAW_AND_GAIN_LIFE_DEVOTION_RE, _draw_and_gain_life_devotion
    ),
    EffectHandler(
        "lose_life_and_gain_life_devotion",
        _LOSE_LIFE_AND_GAIN_LIFE_DEVOTION_RE,
        _lose_life_and_gain_life_devotion,
    ),
    # "Each creature deals 1 damage to its controller." (Rakdos Charm).
    EffectHandler(
        "damage_each_creature_to_controller",
        _DAMAGE_EACH_CREATURE_TO_CONTROLLER_RE,
        _damage_each_creature_to_controller,
    ),
    # "You may pay <cost>. If you do, draw a card." (RULE 118.3).
    EffectHandler(
        "pay_cost_then_draw",
        _PAY_COST_THEN_DRAW_RE,
        _pay_cost_then_draw,
    ),
    # "draw that many cards" (Vilis, Broker of Blood-shaped "that many"
    # trigger-event payoff) — tried before the plain row below since it's a
    # strict superset match on that specific phrase.
    EffectHandler(
        "draw_that_many",
        _DRAW_THAT_MANY_RE,
        _draw_that_many,
    ),
    # "draw a card" / "draw 3 cards" / "you draw two cards" / "draw X cards" /
    # "target player draws a card" / "each opponent draws a card"
    EffectHandler(
        "draw",
        _c(
            r"(?P<who>you|target player|target opponent|each player|each opponent)?\s*"
            rf"draws? {COUNT_X} cards?"
        ),
        _draw,
    ),
    # "draw a card at the beginning of the next turn's upkeep" (RULE 603.7
    # delayed trigger) — Clairvoyance/Balduvian Rage/Carrier Pigeons-shaped.
    EffectHandler(
        "draw_next_upkeep",
        _c(rf"(?:you )?draws? {COUNT} cards? at the beginning of the next turn's upkeep"),
        _draw_next_upkeep,
    ),
    # PAR-13: "exile the top N cards of your library. you may play them
    # [this turn/until the end of your next turn]." — RULE 601.3b impulsive
    # draw (Runestone Caverns/Bonehoard Dracosaur/Painter's Studio-shaped).
    EffectHandler(
        "exile_top_play",
        _EXILE_TOP_PLAY_RE,
        _exile_top_play,
    ),
    # PAR-13: "draw N cards and reveal them. you may cast one of them
    # without paying its mana cost." — Mad Wizard's Lair's own room.
    EffectHandler(
        "draw_reveal_cast_free",
        _DRAW_REVEAL_CAST_FREE_RE,
        _draw_reveal_cast_free,
    ),
    # MEC-20: RULE 601.2f "Expertise" cycle — "you may cast a spell with
    # mana value N/X or less from your hand without paying its mana cost
    # [, where x is the number of attacking creatures]".
    EffectHandler(
        "free_cast_from_hand",
        _FREE_CAST_FROM_HAND_RE,
        _free_cast_from_hand,
    ),
    # ENG-33: "you may put a <type> card from your hand onto the
    # battlefield" (Dr. Eggman — a villainous-choice option body).
    EffectHandler(
        "put_from_hand",
        _PUT_FROM_HAND_RE,
        _put_from_hand,
    ),
    # "Target opponent reveals their hand. You choose a nonland card from
    # it. That player discards that card." (Duress/Thoughtseize-shaped) —
    # tried before the plain `discard` row below (unrelated shapes, but
    # this one's much longer clause should never partially match that
    # row's short one anyway).
    EffectHandler(
        "hand_disruption_discard",
        _HAND_DISRUPTION_RE,
        _hand_disruption_discard,
    ),
    # "exile target non-Angel creature you control, then return that card
    # to the battlefield under your control." (Restoration Angel-shaped).
    EffectHandler(
        "blink_non_subtype",
        _BLINK_NON_SUBTYPE_RE,
        _blink_non_subtype,
    ),
    # "exile [up to N] [another] target creature/[nonland] permanent you
    # control, then return that card/it to the battlefield under your/its
    # owner's control." (Felidar Guardian/Emiel the Blessed/Displacer
    # Kitten-shaped) — tried after the subtype-exclusion row above so a
    # Restoration Angel-shaped clause still matches that narrower row first.
    EffectHandler(
        "blink_plain",
        _BLINK_PLAIN_RE,
        _blink_plain,
    ),
    # "defending player reveals the top card of their library. If it's a
    # land card, that player puts it into their hand." (Goblin Guide-shaped).
    EffectHandler(
        "reveal_top_conditional",
        _REVEAL_TOP_CONDITIONAL_RE,
        _reveal_top_conditional,
    ),
    # "create an X/X blue Shark creature token with flying, where X is that
    # spell's mana value." (Shark Typhoon-shaped spell-cast payoff). Note
    # `_cycling_xx_token`/`_CYCLING_XX_TOKEN_RE` (this row's sibling for
    # RULE 702.28c's Cycling-cost X) is deliberately NOT registered here —
    # a bare "create an X/X ... token." with no trailing explanation is
    # ambiguous outside a "when you cycle this card" wrapper (Wurmcalling/
    # Slime Molding's X is their own {X} mana cost, not a Cycling cost) —
    # `segmenter.py`'s cycle-trigger dispatch calls it directly instead,
    # scoped to exactly that context.
    EffectHandler(
        "mana_value_xx_token",
        _MANA_VALUE_XX_TOKEN_RE,
        _mana_value_xx_token,
    ),
    # "you discard a card" / "discard 2 cards" / "target player discards a card"
    EffectHandler(
        "discard",
        _c(
            r"(?P<who>you|target player|target opponent|each player|each opponent)?\s*"
            rf"discards? {COUNT} cards?"
        ),
        _discard,
    ),
    # PAR-13: "each player loses N life unless they discard a card/sacrifice
    # a creature, artifact, or land of their choice." — Veils of Fear/
    # Sandfall Cell's own APNAP mass "unless".
    EffectHandler(
        "each_player_lose_life_unless",
        _EACH_PLAYER_LOSE_LIFE_UNLESS_RE,
        _each_player_lose_life_unless,
    ),
    # "each player/opponent sacrifices a[n] [nontoken] creature/artifact/
    # land/permanent of their choice" (Accursed Marauder/Liliana, Dreadhorde
    # General's -4 mass edict).
    EffectHandler(
        "sacrifice_edict",
        _SACRIFICE_EDICT_RE,
        _sacrifice_edict,
    ),
    # ENG-33: "target player/opponent sacrifices a <what> of their choice"
    # (Diabolic Edict-shaped, and villainous/vote's *other* option).
    EffectHandler(
        "target_player_edict",
        _TARGET_PLAYER_EDICT_RE,
        _target_player_edict,
    ),
    # PAR-13: "discard a card and sacrifice a creature, an artifact, and a
    # land." — Oubliette's own compound mandatory punishment.
    EffectHandler(
        "discard_and_sacrifice_triple",
        _DISCARD_AND_SACRIFICE_TRIPLE_RE,
        _discard_and_sacrifice_triple,
    ),
    # "you gain 3 life" / "gain 5 life" / "target player gains 3 life"
    EffectHandler(
        "gain_life",
        _c(rf"(?P<who>you |target player )?gains? {NUMBER} life"),
        _gain_life,
    ),
    # RULE 119's "drain" idiom trailing sentence — "You gain life equal to
    # the life lost this way." (Gray Merchant of Asphodel-shaped).
    EffectHandler("gain_life_lost_this_way", _GAIN_LIFE_LOST_THIS_WAY_RE, _gain_life_lost_this_way),
    # Tried before the plain `lose_life` row below (its own bare
    # `{NUMBER} life` would otherwise stop right after the digit, leaving
    # "for each spell they've cast this turn" unconsumed).
    EffectHandler(
        "lose_life_per_spell_cast_this_turn",
        _LOSE_LIFE_PER_SPELL_CAST_THIS_TURN_RE,
        _lose_life_per_spell_cast_this_turn,
    ),
    # "you lose 2 life" / "target player loses 2 life" / "they lose 2 life"
    # (the group-subject event's own player — see `_lose_life`'s docstring).
    EffectHandler(
        "lose_life",
        _c(rf"(?P<who>you |target player |they )?loses? {NUMBER} life"),
        _lose_life,
    ),
    # RULE 202.2f/700.6 "each opponent loses X life, where X is your
    # devotion to <colour>." (Gray Merchant of Asphodel) — tried before the
    # plain digit-amount row below since "x" never matches its `NUMBER`.
    EffectHandler(
        "lose_life_selector_devotion", _LOSE_LIFE_SELECTOR_DEVOTION_RE, _lose_life_selector_devotion
    ),
    # "Each opponent loses life equal to the number of Vampires you
    # control." (Malakir Bloodwitch) — tried before the plain digit-amount
    # row below.
    EffectHandler(
        "lose_life_selector_subtype", _LOSE_LIFE_SELECTOR_SUBTYPE_RE, _lose_life_selector_subtype
    ),
    # "each opponent loses 2 life" / "each player loses 2 life" (RULE
    # 601.2c mass effect, Deathrite Shaman-shaped).
    EffectHandler(
        "lose_life_selector",
        _c(rf"(?P<selector>each other player|each player|each opponent) loses? {COUNT_X} life"),
        _lose_life_selector,
    ),
    # "whenever you gain life, target opponent loses that much life."
    # (Sanguine Bond/Defiant Bloodlord-shaped) — tried before the plain
    # `lose_life` row above so "that much" wins over that row's literal
    # `NUMBER`.
    EffectHandler(
        "lose_life_from_trigger_amount",
        _c(rf"{TARGET} loses that much life"),
        _lose_life_from_trigger_amount,
    ),
    # "you get half X rad counters, rounded up/down" (Contaminated Drink) —
    # tried before the plain shape below since its own ``n`` group would
    # otherwise never match "half x" anyway (no overlap risk either way).
    EffectHandler(
        "add_player_counters_half_x",
        _c(rf"(?P<who>you |target player |defending player )?gets? half x rad counters?, "
           rf"rounded (?P<round>up|down)"),
        _add_rad_counters_half_x,
    ),
    # "you get two rad counters" / "target player gets four rad counters" /
    # "defending player gets two rad counters" / bare "get two rad
    # counters" (a "you may" prefix already peeled) — RULE 728 player
    # counters.
    EffectHandler(
        "add_player_counters",
        _c(rf"(?P<who>you |target player |defending player )?gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison) counters?"),
        _add_rad_counters,
    ),
    # "each player gets three rad counters" / "each opponent gets a poison
    # counter" (RULE 601.2c mass effect).
    EffectHandler(
        "add_player_counters_selector",
        _c(rf"(?P<selector>each player|each opponent) gets? (?P<n>a|an|x|\d+) (?P<kind>rad|poison) counters?"),
        _add_rad_counters_selector,
    ),
    # "target player loses all rad counters" (Survivor's Med Kit).
    EffectHandler(
        "lose_all_player_counters",
        _c(r"target player loses all rad counters"),
        _lose_all_rad_counters,
    ),
    # "each opponent gets a number of rad counters equal to its power"
    # (Feral Ghoul's dies trigger).
    EffectHandler(
        "dies_grants_rad_counters_equal_power",
        _c(r"each opponent gets a number of rad counters equal to its power"),
        _dies_rad_counters_equal_power,
    ),
    # "destroy target [color] creature/permanent/artifact/enchantment/land"
    # (RULE 105 colour-hoser adjective, Red Elemental Blast-shaped) — tried
    # before the plain `destroy` handler below (see `_DESTROY_COLOR_ADJ_RE`'s
    # docstring for why it's safe to try first).
    EffectHandler(
        "destroy_color_adj",
        _DESTROY_COLOR_ADJ_RE,
        _destroy_color_adj,
    ),
    # "destroy target nonland permanent with mana value 3 or less"
    # (Abrupt Decay-shaped) — tried before the plain `destroy` handler
    # below (see `_destroy_mv`'s docstring for why it's safe to try first).
    EffectHandler(
        "destroy_mv",
        _c(rf"destroy {TARGET} with mana value (?P<mv>\d+) or less"),
        _destroy_mv,
    ),
    # "destroy target creature with power 4 or greater" / "…with flying"
    # (RULE 115/601.2c power/toughness/keyword quality filter) — tried
    # before the plain `destroy` handler below for the same reason as
    # `destroy_mv` (a strict superset of the bare "target creature" shape).
    EffectHandler(
        "destroy_creature_filter",
        _c(rf"destroy target creature {_CREATURE_FILTER_SUFFIX}"),
        _destroy_creature_filter,
    ),
    # "destroy target nonblack creature[. It can't be regenerated.]"
    # (Doom Blade-shaped) — tried before the plain `destroy` handler for
    # the same "strict superset" reason as `destroy_mv`/
    # `destroy_creature_filter` just above.
    EffectHandler(
        "destroy_non_creature",
        _DESTROY_NON_CREATURE_RE,
        _destroy_non_creature,
    ),
    # "destroy target creature" / "destroy target artifact" / "destroy
    # target permanent if it's blue" (the trailing-clause old-templating
    # colour variant, Pyroblast-shaped — see `IF_COLOR_SUFFIX`).
    EffectHandler(
        "destroy",
        _c(rf"destroy {TARGET}" + IF_COLOR_SUFFIX),
        _destroy,
    ),
    # "destroy two target creatures" / "destroy up to two target artifacts
    # and/or enchantments" (RULE 115.1a generalized to N>=2 — Curtains'
    # Call/Force of Vigor-shaped), optionally "… controlled by different
    # players" (Cloud's Limit Break-adjacent cross-target constraint —
    # `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "destroy_multi_target",
        _c(
            rf"destroy {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"
            rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _destroy_multi_target,
    ),
    # "destroy all creatures. they can't be regenerated." (Wrath of God-
    # shaped) — tried before the plain `destroy_all` below since it's a
    # strict superset (see `_DESTROY_ALL_NO_REGEN_RE`'s docstring).
    EffectHandler(
        "destroy_all_no_regen",
        _DESTROY_ALL_NO_REGEN_RE,
        _destroy_all_no_regen,
    ),
    # "destroy all creatures[.]" / "destroy all artifacts with mana value 3
    # or less." (RULE 601.2c untargeted mass board wipe — Damnation/Citywide
    # Bust-shaped; Wrath of God itself is hand-authored in
    # `ability_catalogue.py`, this is the general oracle-text form).
    EffectHandler(
        "destroy_all",
        _DESTROY_ALL_RE,
        _destroy_all,
    ),
    # "Regenerate another target Elf." (Ezuri, Renegade Leader/Mad Auntie/
    # Baron Sengir-shaped) — tried before the plain `regenerate` row below
    # since it's a strict superset of that shape.
    EffectHandler(
        "regenerate_another_target",
        _REGENERATE_ANOTHER_TARGET_RE,
        _regenerate_another_target,
    ),
    # "regenerate target creature" (RULE 701.16).
    EffectHandler(
        "regenerate",
        _c(rf"regenerate {TARGET}"),
        _regenerate,
    ),
    # "regenerate ~" / "regenerate it" / "regenerate this creature" — the
    # *self* form (Broodhatch Nantuko/Thorn Elemental-shaped "{cost}:
    # Regenerate ~."), mirroring `tap_self`'s no-RULE-115-target shape.
    EffectHandler(
        "regenerate_self",
        _c(rf"regenerate {_SELF_SUBJECT}"),
        _regenerate_self,
    ),
    # "counter target spell" / "counter target noncreature spell" / "counter
    # target instant or sorcery spell" / "counter target spell with mana
    # value N" / "counter target blue spell" (RULE 105 colour-hoser
    # adjective, inline via `SPELL_TARGET`'s own ``color`` group) / any of
    # those "… unless its controller pays {N}" (the "Mana Leak" unless-pay
    # template) and/or "… if it's blue" (the trailing-clause old-templating
    # colour variant, Red Elemental Blast/Pyroblast-shaped).
    EffectHandler(
        "counter",
        _c(
            rf"counter {SPELL_TARGET}"
            + r"(?: unless its controller pays (?P<cost>\{[^}]+\}))?"
            + IF_COLOR_SUFFIX
        ),
        _counter,
    ),
    # "this spell can't be countered." / "~ can't be countered." (RULE
    # 118-area) — a spell's own property, docked as a marker the counter
    # effect refuses to act on (`RulesEngine._is_cant_be_countered`).
    EffectHandler(
        "cant_be_countered",
        CANT_BE_COUNTERED_RE,
        _cant_be_countered,
    ),
    EffectHandler(
        "grant_quoted_ability_until_eot",
        _GRANT_QUOTED_ABILITY_UNTIL_EOT_RE,
        _grant_quoted_ability_until_eot,
    ),
    # RULE 119.3: "Your opponents can't gain life this turn." (Roiling
    # Vortex's activated-ability rider).
    EffectHandler(
        "cant_gain_life",
        _CANT_GAIN_LIFE_RE,
        _cant_gain_life,
    ),
    # "Change the target of target spell with a single target." (Deflection/
    # Shunt/Swerve-shaped) / "…target spell or ability with a single
    # target." (Bolt Bend/Redirect Lightning/Untimely Malfunction/
    # Willbender-shaped) — RULE 115.4/601.2c, the oracle-text front-end for
    # `ChangeTargetEffect`, previously only reachable by hand-authoring
    # (Misdirection/Deflecting Swat, `ability_catalogue.py`) since no
    # generic handler had claimed the phrase.
    EffectHandler(
        "change_target",
        _c(r"change the target of target (?P<kind>spell or ability|spell) with a single target"),
        _change_target,
    ),
    # "mill 3 cards" / "you mill 3 cards" / "target player mills 3 cards"
    EffectHandler(
        "mill",
        _c(rf"(?:(?P<who>you|target player|target opponent) )?mills? {NUMBER} cards?"),
        _mill,
    ),
    # "exile target creature with power 4 or greater" / "…with flying" —
    # tried before the plain `exile` handler below, same reasoning as
    # `destroy_creature_filter`.
    EffectHandler(
        "exile_creature_filter",
        _c(rf"exile target creature {_CREATURE_FILTER_SUFFIX}"),
        _exile_creature_filter,
    ),
    # "exile target creature" / "exile target artifact"
    EffectHandler(
        "exile",
        _c(rf"exile {TARGET}"),
        _exile,
    ),
    # "exile two target creatures" / "exile up to two target artifacts" /
    # "exile any number of target spells" (Mindbreak Trap — the one row
    # `_MULTI_TARGET_ALT_WITH_SPELL` adds on top of the shared alternation)
    # (RULE 115.1a generalized to N>=2), optionally "… controlled by
    # different players" (Protector of the Wastes-shaped cross-target
    # constraint — `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "exile_multi_target",
        _c(
            rf"exile {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT_WITH_SPELL})"
            rf"{_MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _exile_multi_target,
    ),
    # "exile all creatures[.]" / "exile all lands." (RULE 601.2c untargeted
    # mass form, Farewell-shaped) — the `exile` sibling of `destroy_all`.
    EffectHandler(
        "exile_all",
        _EXILE_ALL_RE,
        _exile_all,
    ),
    # "exile ~" / "exile this card" — the self form (Teferi's Protection/
    # Mnemonic Betrayal's trailing self-exile).
    EffectHandler(
        "exile_self",
        _c(rf"exile {_SELF_SUBJECT}"),
        _exile_self,
    ),
    # "sacrifice ~ unless you pay <cost>" — before the plain self-sac
    # below, whose regex is a prefix of this one (an unanchored
    # `EffectHandler` match would otherwise claim the clause and silently
    # drop the "unless you pay" half, sacrificing unconditionally).
    EffectHandler(
        "sacrifice_unless_pay",
        _SACRIFICE_UNLESS_PAY_RE,
        _sacrifice_unless_pay,
    ),
    # "destroy ~ unless you pay <cost>" — the real-destruction sibling
    # (RULE 701.16) of `sacrifice_unless_pay` above (The Tabernacle at
    # Pendrell Vale's granted upkeep trigger).
    EffectHandler(
        "destroy_unless_pay",
        _DESTROY_UNLESS_PAY_RE,
        _destroy_unless_pay,
    ),
    # "sacrifice ~" / "sacrifice this enchantment" — the self form (Dress
    # Down/Underworld Breach's standing end-step self-sac).
    EffectHandler(
        "sacrifice_self",
        _c(rf"sacrifice {_SELF_SUBJECT}"),
        _sacrifice_self,
    ),
    # "tap target creature" / "untap target permanent"
    EffectHandler(
        "tap",
        _c(rf"(?P<verb>tap|untap) {TARGET}"),
        _tap,
    ),
    # "tap two target creatures" / "untap up to two target lands" (RULE
    # 115.1a generalized to N>=2, Snap-shaped).
    EffectHandler(
        "tap_multi_target",
        _c(rf"(?P<verb>tap|untap) {_MULTI_TARGET_QUANTIFIER}(?:other )?(?P<target>{_MULTI_TARGET_ALT})"),
        _tap_multi_target,
    ),
    # "untap all creatures you control" (Village Bell-Ringer) / "untap all
    # other creatures you control" (Ahn-Crop Champion/Combat Celebrant's
    # own exert rider) / "untap each other creature you control" (Copperhorn
    # Scout) — must sit above `tap_self`/the bare `_SELF_SUBJECT` row so
    # "all [other] creatures you control" (not a self-reference) is
    # recognised on its own.
    EffectHandler(
        "tap_selector",
        _c(
            r"(?P<verb>tap|untap) (?:all (?P<other_all>other )?creatures you control"
            r"|each (?P<other_each>other) creature you control)"
        ),
        _tap_selector,
    ),
    # "untap all attacking creatures" / "untap each attacking creature"
    # (Karlach, Fury of Avernus/Hexplate Wallbreaker) — tried above `tap_self`
    # too, same "specific mass phrase before the bare pronoun row" ordering.
    EffectHandler(
        "tap_attacking_creatures",
        _c(r"(?P<verb>tap|untap) (?:all attacking creatures|each attacking creature)"),
        _tap_attacking_creatures,
    ),
    # "Untap it and all Samurai you control." (Godo, Bandit Warlord) — tried
    # before `tap_self` since that row's bare `_SELF_SUBJECT` would consume
    # only "it" and leave "and all Samurai you control" unclaimed.
    EffectHandler("tap_self_and_subtype", _TAP_SELF_AND_SUBTYPE_RE, _tap_self_and_subtype),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        _c(rf"(?P<verb>tap|untap) {_SELF_SUBJECT}"),
        _tap_self,
    ),
    # "untap that creature" (Finest Hour, MEC-28) — only offered from a
    # group-subject trigger body, where "that creature" unambiguously means
    # whichever creature matched the trigger.
    EffectHandler(
        "tap_group_subject",
        _TAP_GROUP_SUBJECT_RE,
        _tap_self,
        group_subject_only=True,
    ),
    # "tap enchanted creature" / "untap enchanted creature" (Freed from the
    # Real/Pemmin's Aura-shaped Aura activated abilities).
    EffectHandler(
        "tap_attached",
        _c(rf"(?P<verb>tap|untap) {_ATTACHED_SUBJECT}"),
        _tap_attached,
    ),
    # "Return ~ to its owner's hand." (RULE 701.3, self form) — before the
    # targeted sibling below, whose `TARGET` grammar has no ``~``
    # alternative to compete with but would otherwise have first claim on
    # the surrounding phrase.
    EffectHandler(
        # "return **this card** to its owner's hand" (Ringskipper — a
        # "when ~ dies" clash-win body, so the source is in the graveyard;
        # `RulesEngine.return_to_hand` moves it from whatever zone it's in).
        # Scoped here rather than widening the shared `_SELF_SUBJECT` macro.
        "return_self_to_hand",
        _c(rf"return (?:{_SELF_SUBJECT}|this card) to its owner's hand"),
        _return_self_to_hand,
    ),
    # "return target creature to its owner's hand" / "return a land you
    # control to its owner's hand" (RULE 701.3 — the bounce family).
    EffectHandler(
        "return_to_hand",
        _c(rf"return {TARGET} to its owner's hand"),
        _return_to_hand,
    ),
    # "put target creature on top/the bottom of its owner's library" (RULE
    # 701.3 — Time Ebb/Griptide-shaped tempo bounce).
    EffectHandler(
        "return_to_library",
        _c(rf"put {TARGET} on (?:top|the (?P<pos>bottom)) of its owner's library"),
        _return_to_library,
    ),
    # "return all nonland permanents with mana value X or less to their
    # owners' hands." (Displacement Wave).
    EffectHandler(
        "return_all_nonland",
        _RETURN_ALL_NONLAND_RE,
        _return_all_nonland,
    ),
    # "return two target creatures to their owners' hands" (RULE 115.1a
    # generalized to N>=2) — the plural sibling of `return_to_hand`.
    EffectHandler(
        "return_to_hand_multi_target",
        _c(rf"return {_MULTI_TARGET_QUANTIFIER}(?:other )?(?P<target>{_MULTI_TARGET_ALT}) to their owners'? hands?"),
        _return_to_hand_multi_target,
    ),
    # "Return those creatures to their owners' hands." (PAR-1, Run Away
    # Together) — the indirect-referent sibling of `return_to_hand_multi_
    # target`; only offered when a preceding "choose N target creatures …"
    # clause actually announced the group (`EffectHandler.
    # previous_subject_only`, `_choose_targets_group`).
    EffectHandler(
        "return_previous_group", _RETURN_PREVIOUS_GROUP_RE, _return_previous_group,
        previous_subject_only=True,
    ),
    # "return target [type] card from [scope] graveyard to the
    # battlefield/your hand/its owner's hand" / "put target [type] card
    # from [scope] graveyard onto the battlefield under its owner's
    # control" (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent
    # recursion family — own/any/opponent graveyard scope).
    EffectHandler(
        "return_from_graveyard",
        _RETURN_FROM_GRAVEYARD_RE,
        _return_from_graveyard,
    ),
    EffectHandler(
        "return_from_graveyard_owner_control",
        _PUT_FROM_GRAVEYARD_OWNER_CONTROL_RE,
        _return_from_graveyard,
    ),
    # "return up to two target creature cards from your graveyard to your
    # hand"/"...to the battlefield" (RULE 115.1a generalized to N>=2) — the
    # plural sibling of `return_from_graveyard`.
    EffectHandler(
        "return_from_graveyard_multi_target",
        _RETURN_FROM_GRAVEYARD_MULTI_RE,
        _return_from_graveyard_multi_target,
    ),
    # "put target [type] card from [scope] graveyard onto the battlefield
    # under your control" (Reanimate/Rise from the Grave/Virtue of
    # Persistence) — a genuinely different effect from the two above: the
    # activating player takes control, not the card's owner.
    EffectHandler(
        "reanimate_under_your_control",
        _REANIMATE_UNDER_YOUR_CONTROL_RE,
        _reanimate_under_your_control,
    ),
    # PAR-15's "any number of" graveyard-recursion siblings — new
    # destinations (library top / shuffle into library) rather than a new
    # targeting primitive.
    EffectHandler(
        "return_from_graveyard_top_any",
        _RETURN_FROM_GRAVEYARD_TOP_ANY_RE,
        _return_from_graveyard_top_any,
    ),
    EffectHandler(
        "return_from_graveyard_shuffle_any",
        _RETURN_FROM_GRAVEYARD_SHUFFLE_ANY_RE,
        _return_from_graveyard_shuffle_any,
    ),
    # "exile target [type] card from [scope] graveyard" (RULE 701.5a,
    # Deathrite Shaman/Scavenging Ooze/Lion Sash-shaped graveyard hate).
    EffectHandler(
        "exile_from_graveyard",
        _EXILE_FROM_GRAVEYARD_RE,
        _exile_from_graveyard,
    ),
    # "exile target player's graveyard."/"exile all cards from target
    # player's graveyard." (Bojuka Bog/Tormod's Crypt-shaped whole-graveyard
    # hate, as opposed to a single card from one above).
    EffectHandler(
        "exile_target_graveyard",
        _EXILE_TARGET_GRAVEYARD_RE,
        _exile_target_graveyard,
    ),
    # "Its controller may search their library for a basic land card, put
    # it onto the battlefield, then shuffle." (Assassin's Trophy/
    # Geomancer's Gambit/Ghost Quarter — the destroyed permanent's
    # controller, not the caster, gets the ramp).
    EffectHandler(
        "destroy_controller_search_basic_land",
        _DESTROY_CONTROLLER_SEARCH_BASIC_LAND_RE,
        _destroy_controller_search_basic_land,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
    # <destination>, then shuffle." (RULE 701.19 — the general tutor/ramp/
    # fetch family: unrestricted tutors, basic-land fetches, criteria-
    # filtered tutors, "reveal" variants).
    # "search your library for <criteria> that share a land type, ... then
    # shuffle." (Myriad Landscape-shaped cross-pick constraint) — tried
    # before the plain row below since it's a strict superset of it.
    EffectHandler(
        "search_put_then_shuffle_share_type",
        _SEARCH_PUT_THEN_SHUFFLE_SHARE_TYPE_RE,
        _search_put_then_shuffle_share_type,
    ),
    EffectHandler(
        "search_put_then_shuffle",
        _SEARCH_PUT_THEN_SHUFFLE_RE,
        _search_put_then_shuffle,
    ),
    # "search your library for <criteria>, put it onto the battlefield,
    # attach it to a creature you control, then shuffle." (Stonehewer
    # Giant/Quest for the Holy Relic-shaped combined search-then-attach) —
    # tried before the plain row above since it's a strict superset of it.
    EffectHandler(
        "search_put_attach_then_shuffle",
        _SEARCH_PUT_ATTACH_THEN_SHUFFLE_RE,
        _search_put_attach_then_shuffle,
    ),
    # "search your library for a card with mana value less than or equal to
    # the number of lands you control, ... then shuffle." (Beseech the
    # Queen-shaped board-count mana-value bound).
    EffectHandler(
        "search_mv_lands_qualifier",
        _SEARCH_MV_LANDS_QUALIFIER_RE,
        _search_mv_lands_qualifier,
    ),
    # "search your library for a snow permanent card, a legendary card, or
    # a Saga card, ... then shuffle." (Search for Glory's own three-way OR
    # criteria).
    EffectHandler(
        "search_snow_legendary_saga",
        _SEARCH_SNOW_LEGENDARY_SAGA_RE,
        _search_snow_legendary_saga,
    ),
    # "You gain 1 life for each {S} spent to cast this spell." (Search for
    # Glory's own trailing sentence).
    EffectHandler(
        "gain_life_per_snow_spent",
        _GAIN_LIFE_PER_SNOW_SPENT_RE,
        _gain_life_per_snow_spent,
    ),
    # "search your library for <criteria>, [reveal <pronoun>,] then shuffle
    # and put <pronoun> on top." (the reordered shuffle-then-put-on-top
    # tutors — Vampiric/Mystical/Enlightened/Worldly Tutor).
    EffectHandler(
        "search_shuffle_then_put_top",
        _SEARCH_SHUFFLE_THEN_PUT_TOP_RE,
        _search_shuffle_then_put_top,
    ),
    # "search your library for up to N basic land cards, reveal those cards,
    # put one <destA> and the other <destB>, then shuffle." (Cultivate/
    # Kodama's Reach-shaped split destination).
    EffectHandler(
        "search_split_destination",
        _SEARCH_SPLIT_DESTINATION_RE,
        _search_split_destination,
    ),
    # "search your library for N cards. Put 1 <destA> and the other
    # <destB>. Then shuffle." (Final Parting-shaped three-sentence split
    # destination, no criteria).
    EffectHandler(
        "search_two_cards_split",
        _SEARCH_TWO_CARDS_SPLIT_RE,
        _search_two_cards_split,
    ),
    # "search your library and/or graveyard for <criteria>, [reveal
    # <pronoun>,] put <pronoun> <destination>. If you search[ed] your
    # library this way, shuffle." (the backgrounds/planeswalker-tutor
    # combined-zone family).
    EffectHandler(
        "search_zone_put",
        _SEARCH_ZONE_PUT_RE,
        _search_zone_put,
    ),
    # "search your library [and graveyard] for N cards and exile the rest.
    # Put the chosen cards on top of your library in any order."
    # (Doomsday-shaped).
    EffectHandler(
        "search_exile_rest",
        _SEARCH_EXILE_REST_RE,
        _search_exile_rest,
    ),
    # "Shuffle ~ into its owner's library." (Green Sun's Zenith's own
    # trailing sentence, overriding the spell's default graveyard routing).
    EffectHandler(
        "shuffle_self_into_library",
        _SHUFFLE_SELF_INTO_LIBRARY_RE,
        _shuffle_self_into_library,
    ),
    # ENG-32 (Watery Grasp): "Enchanted creature's owner shuffles it into
    # their library."
    EffectHandler(
        "shuffle_enchanted_into_library",
        _SHUFFLE_ENCHANTED_INTO_LIBRARY_RE,
        _shuffle_enchanted_into_library,
    ),
    # "An opponent gains control of ~." (Wishclaw Talisman's own drawback
    # clause).
    EffectHandler(
        "gain_control_by_opponent",
        _GAIN_CONTROL_BY_OPPONENT_RE,
        _gain_control_by_opponent,
    ),
    # "gain control of target creature [with mana value N or less] until
    # end of turn" (Act of Treason/Claim the Firstborn-shaped threaten
    # effect).
    EffectHandler(
        "gain_control_eot",
        _GAIN_CONTROL_EOT_RE,
        _gain_control_eot,
    ),
    # "Untap all creatures and gain control of them until end of turn. They
    # gain haste until end of turn." (Insurrection's own mass threaten).
    EffectHandler(
        "gain_control_all",
        _GAIN_CONTROL_ALL_RE,
        _gain_control_all,
    ),
    # "For each opponent, gain control of up to 1 target creature that player
    # controls until end of turn. Untap those creatures. They gain haste …"
    # (Mass Mutiny / Molten Primordial) — one requirement per opponent.
    EffectHandler(
        "gain_control_eot_per_opponent",
        _GAIN_CONTROL_EOT_PER_OPPONENT_RE,
        _gain_control_eot_per_opponent,
    ),
    # "that player copies it and may choose new targets for the copy [until
    # end of turn]" (Bonus Round's own trigger body).
    EffectHandler(
        "trigger_copy_spell",
        _TRIGGER_COPY_SPELL_RE,
        _trigger_copy_spell,
    ),
    # "Each instant and sorcery card in your graveyard gains flashback until
    # end of turn. The flashback cost is equal to its mana cost." (Past in
    # Flames-shaped).
    EffectHandler(
        "grant_flashback_each",
        _GRANT_FLASHBACK_EACH_RE,
        _grant_flashback_each,
    ),
    # "Target instant or sorcery card in your graveyard gains flashback
    # [<cost>] until end of turn[. The flashback cost is equal to its mana
    # cost.]" (MEC-24, Recoup/Snapcaster Mage-shaped).
    EffectHandler(
        "grant_flashback_target",
        _GRANT_FLASHBACK_TARGET_RE,
        _grant_flashback_target,
    ),
    # "The next spell you cast this turn can't be countered." (Mistrise
    # Village's own activated ability body).
    EffectHandler(
        "next_spell_cant_be_countered",
        _NEXT_SPELL_CANT_BE_COUNTERED_RE,
        _next_spell_cant_be_countered,
    ),
    # "Look at the top card of target player's library."/"Look at a card at
    # random in target player's hand." (Mishra's/Urza's Bauble).
    EffectHandler(
        "look_at_target",
        _LOOK_AT_TARGET_RE,
        _look_at_target,
    ),
    # "attach it to target creature you control" / "attach ~ to target
    # creature you control" (an Equipment's own ETB self-attach).
    EffectHandler(
        "attach",
        _c(rf"attach (?:it|{re.escape(SELF)}) to {TARGET}"),
        _attach,
    ),
    # RULE 701.14 fight, in its four printed subjects: two chosen creatures
    # ("target creature you control fights target creature you don't
    # control"), the source itself written as ``~`` or as "it", and an Aura's
    # host ("enchanted creature fights …"). The "it" row is
    # `self_subject_only` — see `EffectHandler`.
    # (grammar/builder logic unchanged — only the repetitive EffectHandler(...)
    # calls below were collapsed into one row table, see `_FIGHT_ROW_SPECS`).
    *(
        EffectHandler(name, regex, build, **flags)
        for name, regex, build, flags in _FIGHT_ROW_SPECS
    ),
    EffectHandler(
        "fight_previous_pair", _FIGHT_PREVIOUS_PAIR_RE, _fight_previous_pair,
        previous_subject_only=True,
    ),
    # "Put a +1/+1 counter on target creature. It phases out." (Slip Out
    # the Back) — the same previous-clause pronoun idiom as the fight
    # family just above, for a phase-out instead.
    EffectHandler(
        "phase_out_previous", _PHASE_OUT_PREVIOUS_RE, _phase_out_previous,
        previous_subject_only=True,
    ),
    # RULE 702.26 "~ phases out." (Blink Dog/Vaporous Djinn-shaped) / the
    # attached-permanent sibling "enchanted/equipped creature phases out."
    # (Vanishing) / a genuine RULE 115 target (Reality Ripple/Divine Smite,
    # including an opponent-controlled one) — tried in "most specific
    # subject first" order like every other family here.
    EffectHandler("phase_out_self", _PHASE_OUT_SELF_RE, _phase_out_self),
    EffectHandler("phase_out_attached", _PHASE_OUT_ATTACHED_RE, _phase_out_attached),
    EffectHandler("phase_out_target", _PHASE_OUT_TARGET_RE, _phase_out_target),
    # RULE 500.4-adjacent "after this [main] phase, there is an additional
    # combat phase[ followed by an additional main phase]." (Combat
    # Celebrant/Godo/Aurelia-shaped; World at War/Aggravated Assault's own
    # longer form) — tried longer-form-first, same "most specific first"
    # convention as everywhere else in this table.
    EffectHandler(
        "extra_combat_and_main_phase", _EXTRA_COMBAT_AND_MAIN_PHASE_RE, _extra_combat_and_main_phase
    ),
    EffectHandler("extra_combat_phase", _EXTRA_COMBAT_PHASE_RE, _extra_combat_phase),
    # "Choose target creature you control and target creature you don't
    # control." — the target announcement those pair clauses read back.
    EffectHandler("choose_targets", _CHOOSE_TARGETS_RE, _choose_targets),
    # "Choose two target creatures controlled by different players." (PAR-1)
    # — the quantified-group announcement `_return_previous_group` (below)
    # reads back via "those creatures".
    EffectHandler("choose_targets_group", _CHOOSE_TARGETS_GROUP_RE, _choose_targets_group),
    # RULE 701.10 "exchange control of `<X>` and `<Y>`" (PAR-29) — three
    # printed shapes, longest/most-specific first (the file's usual
    # convention): two fully-named independent targets, then "N target
    # `<kind>`[ controlled by different players]", then this permanent plus
    # one target.
    EffectHandler(
        "exchange_control_two_explicit",
        _c(rf"exchange control of {TARGET} and {_TARGET_B}"),
        _exchange_control_two_explicit,
    ),
    EffectHandler(
        "exchange_control_multi",
        _c(
            rf"exchange control of {_MULTI_TARGET_QUANTIFIER}(?:other )?"
            rf"(?P<target>{_MULTI_TARGET_ALT}){_MULTI_TARGET_DISTINCT_CONTROLLERS}"
        ),
        _exchange_control_multi,
    ),
    EffectHandler(
        "exchange_control_self",
        _c(rf"exchange control of ~ and {TARGET}"),
        _exchange_control_self,
    ),
    # RULE 701.10's life-total half.
    EffectHandler(
        "exchange_life_totals_self",
        _c(r"exchange life totals with (?:target opponent|target player)"),
        _exchange_life_totals_self,
    ),
    EffectHandler(
        "exchange_life_totals_two_target",
        _c(r"(?:have )?2 target players exchange life totals"),
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
    ),
    # MEC-18: "you may <sacrifice/discard/pay-mana/pay-life>. when/if you
    # do, <effect>." — the general RULE 603.5 optional-antecedent family.
    # Tried after `pay_energy_then`/`pay_cost_then_draw` (both narrower,
    # both correct) so first-match-wins never lets this one preempt them.
    EffectHandler(
        "pay_cost_then_general",
        _PAY_COST_THEN_GENERAL_RE,
        _pay_cost_then_general,
    ),
    # PAR-29 (Blight batch): the "If you don't, <effect>." else-branch
    # sibling — same clause shape, opposite antecedent, into
    # `pay_cost_then`'s `else_effects`.
    EffectHandler(
        "pay_cost_then_or_else",
        _PAY_COST_THEN_OR_ELSE_RE,
        _pay_cost_then_or_else,
    ),
    # MEC-19: "counter it unless that player pays <cost>" — the
    # un-keyworded-Ward-shaped `BECOMES_TARGET` trigger's own resolution.
    EffectHandler(
        "counter_unless_pay",
        _COUNTER_UNLESS_PAY_RE,
        _counter_unless_pay,
    ),
    # "you get {E}{E}" — energy-counter production (RULE 122).
    EffectHandler(
        "get_energy",
        _GET_ENERGY_RE,
        _get_energy,
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
    # "transform ~" / "transform it" / "transform this permanent"/"creature"
    # (RULE 712.8) — the self-transform shape a loyalty "[0]: Transform ~."
    # or a "whenever ~ attacks, transform it" trigger uses.
    EffectHandler(
        "transform",
        _c(rf"transform (?:{re.escape(SELF)}|it|this permanent|this creature)"),
        _transform,
    ),
    # "exile ~/this saga, then return it/him/her to the battlefield
    # transformed under your/its/his/her owner's control" (RULE 400.7 +
    # RULE 712.8) — a transforming Saga's chapter III, or an activated
    # ability's own flip phrased this way instead of a bare "transform ~".
    EffectHandler(
        "exile_return_transformed",
        _EXILE_RETURN_TRANSFORMED_RE,
        _exile_return_transformed,
    ),
    # "exile <TARGET> [an opponent controls] until ~ leaves the
    # battlefield." (O-Ring / Banisher Priest / Fiend Hunter) — the
    # companion LEAVES_BATTLEFIELD return ability is synthesized by the
    # segmenter off the ``until_source_leaves`` param.
    EffectHandler(
        "exile_until_leaves",
        _EXILE_UNTIL_LEAVES_RE,
        _exile_until_leaves,
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
    # "~ becomes prepared" / "it becomes prepared" / "this permanent"/
    # "this creature becomes prepared" (RULE 722.3a) — a preparation card's
    # own "whenever X, ~ becomes prepared" trigger; the self-only shape
    # mirrors "transform" above (RULE 722.3a has no targeted form).
    EffectHandler(
        "become_prepared",
        _c(rf"(?:{re.escape(SELF)}|it|this permanent|this creature) becomes prepared"),
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
    # "Activate only as a sorcery." / "… only any time you could cast a
    # sorcery." — a RULE 602.5d timing restriction, not a real effect; see
    # `SORCERY_SPEED_MARKER`'s docstring for how the binder folds it into the
    # cost's `sorcery_speed_only` flag.
    EffectHandler(
        "sorcery_speed",
        _SORCERY_SPEED_RE,
        _sorcery_speed,
    ),
    # "Activate only during your turn." — RULE 602.5d's wider sibling
    # (Wishclaw Talisman); see `ONLY_DURING_YOUR_TURN_MARKER`'s docstring.
    EffectHandler(
        "only_during_your_turn",
        _ONLY_DURING_YOUR_TURN_RE,
        _only_during_your_turn,
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
        "activate_only_if",
        _ACTIVATE_ONLY_IF_RE,
        _activate_only_if,
    ),
    # "if your library has no cards in it, you win the game" (Jace, Wielder
    # of Mysteries' -8 tail).
    EffectHandler(
        "win_if_empty_library",
        _c(r"(?:then )?if your library has no cards? in it, you win the game"),
        _win_if_empty_library,
    ),
    # MEC-27: "put x +1/+1 counters on target creature, where x is the
    # number of Elves you control." — tried before the plain `add_counters`
    # row below since "x" never matches that row's `{COUNT}` (digit/"a"/"an"
    # only).
    EffectHandler("add_counters_devotion", _ADD_COUNTERS_DEVOTION_RE, _add_counters_devotion),
    # "put a +1/+1 counter on target suspected creature you control" (PAR-29)
    # — tried before the plain `add_counters` row below, whose `TARGET`
    # alternation has no "suspected" adjective row.
    EffectHandler(
        "add_counters_suspected_target",
        _c(rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on target suspected creature you control"),
        _add_counters_suspected_target,
    ),
    # "put a +1/+1 counter on target creature" / "put a -1/-1 counter on …" /
    # "… on ~"/"this creature" (Walking Ballista's "{4}: Put a +1/+1 counter
    # on this creature." — `_SELF_SUBJECT`, the same self-reference
    # vocabulary `_tap_self` already uses, not just the literal ``~`` a
    # card's own name folds to).
    EffectHandler(
        "add_counters",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
        ),
        _add_counters,
    ),
    # "put a spore counter on ~" (Deathspore Thallid/Elvish Farmer-shaped)
    # / "…on target fungus" (Fungal Bloom) — the named-counter sibling of
    # the P/T-only row just above.
    EffectHandler(
        "add_named_counter",
        _ADD_NAMED_COUNTER_RE,
        _add_named_counter,
    ),
    # "whenever you gain life, put that many +1/+1 counters on ~/target
    # creature" (Ageless Entity/Karlov-adjacent lifegain payoffs) — tried
    # before the plain `add_counters` row above so its "that many" wins
    # over that row's literal-`COUNT` alternation. `self_subject_only`:
    # its ``(?P<selfref>{_SELF_SUBJECT})`` branch includes the bare pronoun
    # "it", which under a *group*-subject trigger ("whenever a creature you
    # control deals combat damage to a player, put that many +1/+1 counters
    # on it" — Necropolis Regent) means whichever group member fired it,
    # not this ability's own source — claiming it blind would silently
    # buff the wrong object. A player-subject trigger ("whenever you gain
    # life") introduces no such group, so `segmenter.segment_line`'s player-
    # event branch passes ``self_subject=True`` and this row is offered.
    EffectHandler(
        "add_counters_from_trigger_amount",
        _c(
            rf"put that many (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
        ),
        _add_counters_from_trigger_amount,
        self_subject_only=True,
    ),
    # "~ gets +x/+x until end of turn, where x is the amount of life you
    # gained." (Field-Tested Frying Pan's granted ability) — same pronoun-
    # ambiguity gate as the row above.
    EffectHandler(
        "pump_self_from_life_gained",
        _PUMP_SELF_FROM_LIFE_GAINED_RE,
        _pump_self_from_life_gained,
        self_subject_only=True,
    ),
    # ENG-32: "~ / creatures you control ha[s|ve] base power and toughness
    # N/M until end of turn" (Flexible Waterbender / Katara, Water Tribe's
    # Hope) — a resolve-time layer-7b `pt_set` via `grant_until`.
    EffectHandler(
        "base_pt_until_eot",
        _BASE_PT_UNTIL_EOT_RE,
        _base_pt_until_eot,
    ),
    # "put a +1/+1 counter on each of up to two target creatures" (RULE
    # 115.1a generalized to N>=2 — the Support-keyword-shaped family).
    EffectHandler(
        "add_counters_multi_target",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on each of "
            rf"{_MULTI_TARGET_QUANTIFIER}(?:other )?(?P<target>{_MULTI_TARGET_ALT})"
        ),
        _add_counters_multi_target,
    ),
    # PAR-15: "distribute N +1/+1 counters among any number of target
    # creatures[ you control]" — a divided pool, not "each of N" full-amount.
    EffectHandler(
        "distribute_counters",
        _DISTRIBUTE_COUNTERS_RE,
        _distribute_counters,
    ),
    # ENG-30: "distribute N +1/+1 counters among 1 or 2 target creatures
    # [you control]" — a genuine RULE 601.2c range, tried before the plain
    # `distribute_counters` row since "1 or 2" would otherwise also satisfy
    # that row's own `\d+` (it doesn't — that row requires "any number of"
    # literally — but keeping the more specific row first matches this
    # file's usual ordering convention for overlapping shapes).
    EffectHandler(
        "distribute_counters_range",
        _DISTRIBUTE_COUNTERS_RANGE_RE,
        _distribute_counters_range,
    ),
    # "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
    # effect, Vastwood Surge-shaped).
    EffectHandler(
        "add_counters_selector",
        _c(
            rf"put {COUNT} (?P<ckind>[+\-−]1/[+\-−]1) counters? on "
            r"each creature you control"
        ),
        _add_counters_selector,
    ),
    # "target creature gets +1/+0 until end of turn and can't be blocked
    # this turn" (You Come to a River-shaped) — tried before the plain
    # `pump` handler below since it's a strict superset of that shape (a
    # trailing unblockable clause `_pump`'s own grammar doesn't recognise).
    EffectHandler(
        "pump_unblockable",
        _PUMP_UNBLOCKABLE_RE,
        _pump_unblockable,
    ),
    # ENG-32: bare "~ / target creature can't be blocked this turn" (Giant
    # Koi / Waterbender Ascension) — no P/T delta.
    EffectHandler(
        "cant_be_blocked_this_turn",
        _CANT_BE_BLOCKED_TURN_RE,
        _cant_be_blocked_turn,
    ),
    # "Up to two target creatures can't block this turn" / "target creature
    # can't block this turn" / "creatures without flying can't block this
    # turn" — the multi form first, since its "up to two target creatures"
    # phrase is not something the singular `TARGET` alternation can claim.
    EffectHandler(
        "cant_block_this_turn_multi",
        _CANT_BLOCK_TURN_MULTI_RE,
        _cant_block_turn_multi,
    ),
    EffectHandler(
        "cant_block_this_turn",
        _CANT_BLOCK_TURN_RE,
        _cant_block_turn,
    ),
    EffectHandler(
        "cant_block_this_turn_group",
        _CANT_BLOCK_TURN_GROUP_RE,
        _cant_block_turn_group,
    ),
    # "~ can't be blocked by creatures with power 2 or less this turn" — the
    # resolve-time sibling of the standing combat-restriction static.
    EffectHandler(
        "cant_be_blocked_by_this_turn",
        _CANT_BE_BLOCKED_BY_TURN_RE,
        _cant_be_blocked_by_turn,
    ),
    # "Target creature can't block ~ this turn." — the pairwise sibling of
    # `cant_block_this_turn` above (bars blocking *this* source specifically,
    # not every attacker).
    EffectHandler(
        "cant_block_source_this_turn",
        _CANT_BLOCK_SOURCE_TURN_RE,
        _cant_block_source_turn,
    ),
    # "Target creature blocks ~ this turn if able." (RULE 509.1c, resolve-time)
    EffectHandler(
        "blocks_source_this_turn_if_able",
        _BLOCKS_SOURCE_TURN_IF_ABLE_RE,
        _blocks_source_turn_if_able,
    ),
    # "Target creature attacks this turn if able." (RULE 508.1a, resolve-time)
    EffectHandler(
        "attacks_this_turn_if_able",
        _ATTACKS_TURN_IF_ABLE_RE,
        _attacks_turn_if_able,
    ),
    # "target creature gets +3/+3 until end of turn" / "gets -2/-2 …" /
    # "gets +1/+1 and gains trample until end of turn" / "~ gets +1/+0 …" /
    # "creatures you control get +2/+1 until end of turn" (plural "get").
    EffectHandler(
        "pump",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump,
    ),
    # RULE 701.10/11 "double"/"triple the power and toughness of <target
    # creature[ you control]>/each creature you control until end of turn"
    # (Dragonclaw Strike/Roar of Endless Song).
    EffectHandler(
        "double_pt_of",
        _c(
            rf"(?P<mult>double|triple) the power and toughness of "
            rf"(?:{TARGET}|(?P<each_group>each creature you control)) until end of turn"
        ),
        _double_pt_of,
    ),
    # The possessive phrasing — "double/triple <target creature>'s/~'s
    # power and toughness until end of turn" (Nylea's Colossus/Reckless
    # Amplimancer/Tifa's Limit Break's own "triple").
    EffectHandler(
        "double_pt_possessive",
        _c(
            rf"(?P<mult>double|triple) (?:(?P<selfposs>~)|{TARGET})'s "
            rf"power and toughness until end of turn"
        ),
        _double_pt_possessive,
    ),
    # The bare pronoun — "double its power and toughness until end of
    # turn." Self-subject (Grunn's "whenever ~ attacks alone, double its
    # power and toughness") and the previous-clause pronoun (World War
    # Hulk's "choose target creature you control. … double its power and
    # toughness.") are genuinely different referents, so two rows.
    EffectHandler(
        "double_pt_self_pronoun",
        _c(r"(?P<mult>double|triple) its power and toughness until end of turn"),
        _double_pt_pronoun,
        self_subject_only=True,
    ),
    EffectHandler(
        "double_pt_previous",
        _c(r"(?P<mult>double|triple) its power and toughness until end of turn"),
        _double_pt_previous,
        previous_subject_only=True,
    ),
    # PAR-15: "any number of target creatures each get +N/+N [and gain
    # `<keyword>`] until end of turn" — every chosen creature gets the full
    # boost, not a divided pool.
    EffectHandler(
        "pump_multi_target",
        _PUMP_MULTI_TARGET_RE,
        _pump_multi_target,
    ),
    # "Untap those creatures." (Colossal Heroics) — the previous clause's own
    # multi-target group, read back the same way `return_previous_group` does.
    EffectHandler(
        "untap_previous_group",
        _UNTAP_PREVIOUS_GROUP_RE,
        _untap_previous_group,
        previous_subject_only=True,
    ),
    # "…, then untap that land." (Avatar Kyoshi, following "earthbend N") —
    # the singular previous-subject sibling of the row just above.
    EffectHandler(
        "tap_previous_subject",
        _TAP_PREVIOUS_SUBJECT_RE,
        _tap_previous_subject,
        previous_subject_only=True,
    ),
    # "target/that/~ <permanent> doesn't untap during … next untap step"
    # (Barl's Cage + the ~95-card "Tap X. It doesn't untap …" family).
    EffectHandler("skip_next_untap_target", _SKIP_UNTAP_TARGET_RE, _skip_untap_target),
    EffectHandler(
        "skip_next_untap_prev", _SKIP_UNTAP_PREV_RE, _skip_untap_prev,
        previous_subject_only=True,
    ),
    EffectHandler(
        "skip_next_untap_self", _SKIP_UNTAP_SELF_RE, _skip_untap_self,
        self_subject_only=True,
    ),
    # "[TARGET / ~ / it] gains protection from the color of your choice
    # until end of turn" (RULE 702.16 — Gods Willing, Jareth, Feat of
    # Resistance &c.; the engine primitive is Mother of Runes').
    EffectHandler(
        "grant_prot_choice_target", _GRANT_PROT_CHOICE_TARGET_RE, _grant_prot_choice_target,
    ),
    EffectHandler(
        "grant_prot_choice_self", _GRANT_PROT_CHOICE_SELF_RE, _grant_prot_choice_self,
        self_subject_only=True,
    ),
    EffectHandler(
        "grant_prot_choice_prev", _GRANT_PROT_CHOICE_PREV_RE, _grant_prot_choice_prev,
        previous_subject_only=True,
    ),
    # "Reveal cards from the top of your library until you reveal a <type>
    # card. Put that card <onto the battlefield / into your hand> and the
    # rest <bottom / graveyard / shuffle>." (Recross the Paths, Clifftop
    # Lookout, Atla Palani, … — `RulesEngine.dig_until`).
    EffectHandler("reveal_until_type", _REVEAL_UNTIL_TYPE_RE, _reveal_until_type),
    # PAR-30: "[Then] sacrifice/exile <it/that creature/that token/them/
    # those tokens> at the beginning of [the/your] next end step." — the
    # RULE 603.7 delayed-trigger tail on every "create a token …, exile it"
    # / "reanimate …, sacrifice it" card (~100 SOLO). Ungated: `capture=
    # "previous_or_self"` resolves the referent (prev target → created
    # object → the source) at arm time and no-ops on an empty chain.
    EffectHandler(
        "delayed_sac_exile_tail",
        _DELAYED_SAC_EXILE_TAIL_RE,
        _delayed_sac_exile_tail,
    ),
    # ENG-30: "They [each] get +N/+N [and gain <kw>] until end of turn."
    # (A-Bretagard Stronghold/Fancy Footwork) — the pump-family sibling of
    # `untap_previous_group`, same previous-target-group gate.
    EffectHandler(
        "pump_previous_targets_pt",
        _PUMP_PREVIOUS_TARGETS_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    # ENG-30: "They [each] gain <kw> until end of turn." — the keyword-only
    # sibling of the row above (tried after it since a P/T delta present
    # would otherwise be swallowed by this row's own bare-keyword capture).
    EffectHandler(
        "pump_previous_targets_kw",
        _PUMP_PREVIOUS_TARGETS_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    # PAR-30: the singular-pronoun siblings — "it [also] gets +N/+N …" /
    # "it [also] gains <kw> until end of turn" (threaten restatement tails,
    # clash "if you win, that creature …" payoffs). P/T row first so a
    # delta isn't swallowed by the keyword row's bare capture.
    EffectHandler(
        "pump_prev_singular_pt",
        _PUMP_PREV_SINGULAR_PT_RE,
        _pump_previous_targets_pt,
        previous_subject_only=True,
    ),
    EffectHandler(
        "pump_prev_singular_kw",
        _PUMP_PREV_SINGULAR_KW_RE,
        _pump_previous_targets_kw,
        previous_subject_only=True,
    ),
    # "They gain first strike until end of turn." (Karlach, Fury of
    # Avernus, MEC-28) — the mass-selector sibling: only offered when the
    # preceding clause's own spec used a real group selector.
    EffectHandler(
        "pump_previous_selector",
        _PUMP_PREVIOUS_SELECTOR_RE,
        _pump_previous_selector,
        previous_selector_only=True,
    ),
    # "Target attacking Elf you control gains deathtouch until end of
    # turn." (Gnarlroot Trapper-shaped) — tried before the plain
    # `pump_keyword` row below since the shared `TARGET` macro has no
    # "attacking `<subtype>` you control" row for that one to match.
    EffectHandler(
        "pump_attacking_subtype_target",
        _PUMP_ATTACKING_SUBTYPE_TARGET_RE,
        _pump_attacking_subtype_target,
    ),
    # "target creature gains flying until end of turn" (keyword-only pump) /
    # "creatures you control gain flying until end of turn".
    EffectHandler(
        "pump_keyword",
        # ``0-9`` in the keyword capture is ENG-31's parametric grant
        # ("gains firebending 4 until end of turn"); `_pump_keywords` splits
        # a "<name> <N>" entry off into ``parametric_keywords`` and
        # fail-closes on anything that isn't a FLAG or a grantable
        # parametric keyword.
        _c(rf"{_SUBJECT} gains? (?P<kw>[a-z0-9, ]+?) until end of turn"),
        _pump_keywords,
    ),
    # "Each creature your opponents control gets -1/-1 until end of turn
    # for each poison counter its controller has." (Phyresis Outbreak).
    EffectHandler(
        "pump_per_controller_counter",
        _PUMP_PER_CONTROLLER_COUNTER_RE,
        _pump_per_controller_counter,
    ),
    # "Up to two target creatures each get +N/+N [and gain <keywords>]
    # until end of turn." (Dauntless Onslaught-shaped).
    EffectHandler(
        "pump_up_to_two",
        _PUMP_UP_TO_TWO_RE,
        _pump_up_to_two,
    ),
    # ENG-30: "One or two target creatures…" (Opera Love Song/Heroic
    # Teamwork-shaped) — a genuine RULE 601.2c range, not "up to two"; see
    # `_PUMP_ONE_OR_TWO_RE`'s own comment for why this is now split out.
    EffectHandler(
        "pump_one_or_two",
        _PUMP_ONE_OR_TWO_RE,
        _pump_one_or_two,
    ),
    # ENG-30: "1 or 2 target creatures gain <kw> until end of turn." (Wind
    # Sail) — the keyword-only sibling of the row above.
    EffectHandler(
        "pump_one_or_two_kw",
        _PUMP_ONE_OR_TWO_KW_RE,
        _pump_one_or_two_kw,
    ),
    # "Creatures you control gain trample and get +X/+X until end of turn,
    # where X is the number of creatures you control." (Craterhoof
    # Behemoth-shaped) — tried before the plain `pump_keyword` row above
    # since it's a strict superset of that shape.
    EffectHandler(
        "group_pump_count_selector",
        _GROUP_PUMP_COUNT_SELECTOR_RE,
        _group_pump_count_selector,
    ),
    # RULE 202.2f/700.6 "target creature gets +X/+X until end of turn, where
    # X is your devotion to <colour(s)/wedge>." (Aspect of Hydra/Devoted
    # Temur-shaped) and its "-X/-X" debuff sibling (Blight-Breath
    # Catoblepas) / mass "creatures you control get +X/+X …" sibling
    # (Klothys's Design) — tried before the plain digit-amount `pump` row
    # below since "x" would otherwise never match that row's `\d+`.
    EffectHandler("pump_devotion_target", _PUMP_DEVOTION_TARGET_RE, _pump_devotion_target),
    EffectHandler(
        "pump_devotion_negative_target", _PUMP_DEVOTION_NEGATIVE_TARGET_RE, _pump_devotion_negative_target
    ),
    EffectHandler("group_pump_devotion", _GROUP_PUMP_DEVOTION_RE, _group_pump_devotion),
    # "Whenever ~ attacks, it gets +X/+X until end of turn, where X is …"
    # (Angelic Exaltation-adjacent self-buff-on-attack) — tried before the
    # flat-amount row below, whose `\d+` would never match a bare "x".
    EffectHandler(
        "pump_self_subject_devotion",
        _PUMP_SELF_SUBJECT_DEVOTION_RE,
        _pump_self_subject_devotion,
        self_subject_only=True,
    ),
    # "Whenever ~ attacks, it gets +1/+0 until end of turn." (Akroan Hoplite-
    # adjacent self-buff-on-attack, `it` bound to the ability's own source —
    # `self_subject_only`, only ever offered from a self-subject trigger
    # body).
    EffectHandler(
        "pump_self_subject",
        _c(
            rf"it gets? {_PT_DELTA}"
            rf"(?: and gains? (?P<kw>[a-z, ]+?))? until end of turn"
        ),
        _pump_self_subject,
        self_subject_only=True,
    ),
    # "It doesn't untap during its controller's untap step for as long as ~
    # remains tapped." — the tap-then-lock family (PAR-11), whose subject is
    # the previous clause's target.
    EffectHandler(
        "lockdown_no_untap",
        _c(
            r"(?:it|that creature|that permanent|that land|that artifact) doesn'?t untap "
            r"during its controller'?s untap step for as long as (?P<cond>.+)"
        ),
        _lockdown,
        previous_subject_only=True,
    ),
    # The same grant with any *other* duration (RULE 611) — "…until your next
    # turn", "…until end of combat". Ordered after the end-of-turn row above,
    # which it can't collide with (that duration isn't in `_GRANT_DURATIONS`).
    EffectHandler(
        "grant_until",
        _c(
            rf"{_SUBJECT} gains? (?P<kw>[a-z, ]+?) "
            r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _grant_until,
    ),
    # PAR-13: the P/T sibling of the row above — "target creature gets
    # -4/-0 until your next turn"/"creatures your opponents control get
    # -3/-0 until your next turn".
    EffectHandler(
        "pump_until",
        _c(
            rf"{_SUBJECT} gets? {_PT_DELTA} "
            r"(?P<dur>until (?:your next turn|the end of combat|end of combat|"
            r"the beginning of the next end step))"
        ),
        _pump_until,
    ),
    # PAR-13: "target creature can't attack/block until <duration>" — the
    # resolve-time-grant sibling of the permanent-static "~ can't attack."
    EffectHandler(
        "cant_attack_or_block_until",
        _CANT_ATTACK_OR_BLOCK_UNTIL_RE,
        _cant_attack_or_block_until,
    ),
    # "scry 2" (RULE 701.18) / "surveil 2" (RULE 701.31) — both a self effect
    # (the controller scries/surveils), same grammar, one handler.
    EffectHandler(
        "scry_or_surveil",
        _c(rf"(?P<verb>scry|surveil) {NUMBER}"),
        _scry_or_surveil,
    ),
    EffectHandler(
        "look_top_reorder",
        _LOOK_TOP_REORDER_RE,
        _look_top_reorder,
    ),
    # "venture into the dungeon" (RULE 701.49) / "venture into Undercity"
    # (RULE 701.49d).
    EffectHandler(
        "venture",
        _c(r"venture into (?P<dungeon>the dungeon|undercity)"),
        _venture,
    ),
    # "monstrosity 3" / "monstrosity x" (RULE 701.37a).
    EffectHandler(
        "monstrosity",
        _c(r"monstrosity (?P<n>x|\d+)"),
        _monstrosity,
    ),
    # "adapt 2" (RULE 701.46a).
    EffectHandler(
        "adapt",
        _c(rf"adapt {NUMBER}"),
        _adapt,
    ),
    # "~ connives[ X]" (RULE 701.50a/d) — explicit self reference
    # (activated-ability body / self-subject trigger with the name kept).
    EffectHandler(
        "connive_self_named",
        _c(rf"~ connives?{_CONNIVE_AMOUNT}"),
        _connive,
    ),
    # "it connives[ X]" / "he connives" / "she connives" — the self-subject
    # trigger pronoun; only offered when the body's "it" really is the source
    # (`self_subject_only`), never an earlier clause's pick.
    EffectHandler(
        "connive_self_pronoun",
        _c(rf"(?:it|he|she) connives?{_CONNIVE_AMOUNT}"),
        _connive,
        self_subject_only=True,
    ),
    # "that creature connives" — the previous-clause pronoun ("target
    # creature you control gains menace. That creature connives.").
    EffectHandler(
        "connive_previous",
        _c(rf"(?:it|that creature) connives?{_CONNIVE_AMOUNT}"),
        _connive_previous,
        previous_subject_only=True,
    ),
    # "each of x target creatures you control connive" (Change of Plans).
    EffectHandler(
        "connive_each_x",
        _c(r"each of x target creatures you control connive"),
        _connive_each_x,
    ),
    # "target creature [you control/an opponent controls] connives[ X]"
    # (RULE 601.2c targeting on 701.50a/d).
    EffectHandler(
        "connive_target",
        _c(rf"{TARGET} connives?{_CONNIVE_AMOUNT}"),
        _connive_target,
    ),
    # "recruit" (RULE 701.70a) — bare word (an ETB/attack trigger's whole body).
    EffectHandler(
        "recruit",
        _c(r"recruit"),
        _recruit,
    ),
    # "learn" (RULE 701.48a) — bare word (spell effect / ETB / dies / cost body).
    EffectHandler(
        "learn",
        _c(r"learn"),
        _learn,
    ),
    # "you may collect evidence N" (RULE 701.59a) — bare, no "if you do" rider.
    EffectHandler(
        "collect_evidence_bare",
        _c(r"you may collect evidence (?P<n>\d+)"),
        _collect_evidence_bare,
    ),
    # bare "collect evidence N" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "collect_evidence",
        _c(r"collect evidence (?P<n>\d+)"),
        _collect_evidence,
    ),
    # "you may forage" (RULE 701.61a) — bare, no "if you do" rider.
    EffectHandler(
        "forage_bare",
        _c(r"you may forage"),
        _forage_bare,
    ),
    # bare "forage" — the segmenter-peeled triggered-ability body.
    EffectHandler(
        "forage",
        _c(r"forage"),
        _forage,
    ),
    # "discover 3" (RULE 701.57a) — literal mana value only.
    EffectHandler(
        "discover",
        _c(r"discover (?P<n>\d+)"),
        _discover,
    ),
    # "target creature [you control] explores" (RULE 701.44) — before the
    # bare/pronoun rows so its TARGET isn't stolen by a looser match.
    EffectHandler(
        "explore_target",
        _c(rf"{TARGET} explores"),
        _explore_target,
    ),
    # "~ explores" — explicit self (activated body / self-subject trigger
    # with the name kept, "when ~ enters, ~ explores").
    EffectHandler(
        "explore_self_named",
        _c(r"~ explores"),
        _explore_self,
    ),
    # "it explores" / "he explores" / "she explores" — self-subject trigger
    # pronoun ("when ~ enters, it explores").
    EffectHandler(
        "explore_self_pronoun",
        _c(r"(?:it|he|she) explores"),
        _explore_self,
        self_subject_only=True,
    ),
    # "that creature explores" — a creature an earlier clause of this same
    # resolution chose ("return target creature card … that creature
    # explores", Defossilize's first half).
    EffectHandler(
        "explore_previous",
        _c(r"(?:it|that creature) explores"),
        _explore_previous,
        previous_subject_only=True,
    ),
    # "target creature you control endures N" (RULE 701.63a) — before the
    # bare/pronoun rows so its TARGET isn't stolen.
    EffectHandler(
        "endure_target",
        _c(rf"{TARGET} endures (?P<n>\d+)"),
        _endure_target,
    ),
    # "~ endures N" — explicit self ("when ~ enters, ~ endures 3").
    EffectHandler(
        "endure_self_named",
        _c(r"~ endures (?P<n>\d+)"),
        _endure_self,
    ),
    # "~ endures x" (PAR-29, Krumar Initiate) — X is this activated
    # ability's own announced {X}.
    EffectHandler(
        "endure_self_named_x",
        _c(r"~ endures x"),
        _endure_self_x,
    ),
    # "it endures N" / "he/she endures N" — self-subject trigger pronoun.
    EffectHandler(
        "endure_self_pronoun",
        _c(r"(?:it|he|she) endures (?P<n>\d+)"),
        _endure_self,
        self_subject_only=True,
    ),
    # "it endures N" / "that creature endures N" — a previous clause's pick.
    EffectHandler(
        "endure_previous",
        _c(r"(?:it|that creature) endures (?P<n>\d+)"),
        _endure_previous,
        previous_subject_only=True,
    ),
    # "populate" (RULE 701.36a) — copy a creature token you control.
    EffectHandler(
        "populate",
        _c(r"populate"),
        _populate,
    ),
    # "populate x times" (RULE 701.36a, Full Flowering).
    EffectHandler(
        "populate_x_times",
        _c(r"populate x times"),
        _populate_x_times,
    ),
    # "clash with an opponent" / "clash with defending player" (RULE 701.30).
    EffectHandler(
        "clash",
        _c(r"clash with (?:an opponent|defending player)"),
        _clash,
    ),
    # "starting with you, each player votes for A or B. if A gets more
    # votes, X. if B gets more votes or the vote is tied, Y." (RULE 701.38,
    # PAR-29) — the 2-option majority form. Tried before the per-vote form
    # below since its "if … gets more votes" tail is more specific.
    EffectHandler(
        "vote_majority",
        _VOTE_HEADER_RE,
        _vote_majority,
    ),
    # "starting with you, each player votes for A or B. <body1> for each A
    # vote[ and <body2> for each B vote]." (RULE 701.38, PAR-29) — the
    # per-vote scaling form.
    EffectHandler(
        "vote_per_vote",
        _VOTE_HEADER_RE,
        _vote_per_vote,
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
        _c(r"(?:you )?incubate (?P<n>\d+)"),
        _incubate,
    ),
    # "time travel" (RULE 701.56, Doctor Who) — remove a time counter from
    # each suspended card you own / add one to each Vanishing-style
    # permanent you control. "time travel, then time travel" is two of
    # these from `parse_effect_body`'s ", then" split.
    EffectHandler(
        "time_travel",
        _c(r"(?:you )?time travel"),
        lambda _m: [EffectSpec("time_travel", {})],
    ),
    # "bolster N" (RULE 701.39a) — N +1/+1 counters on a least-toughness
    # creature you control.
    EffectHandler(
        "bolster",
        _c(r"bolster (?P<n>\d+)"),
        _bolster,
    ),
    # "bolster x, where x is <board count>" (PAR-29).
    EffectHandler(
        "bolster_x",
        _c(rf"bolster x, where x is (?P<selector>{_BOLSTER_AMOUNT_ALT})"),
        _bolster_x,
    ),
    # "blight N" (Bloomburrow) — N -1/-1 counters on a creature you control.
    EffectHandler(
        "blight",
        _c(r"blight (?P<n>\d+)"),
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
        _c(r"earthbend (?P<n>\d+)"),
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
        _c(r"support (?P<n>\d+)"),
        _support,
    ),
    # "support x" (PAR-29) — X is the spell/ability's own announced {X}.
    EffectHandler(
        "support_x",
        _c(r"support x"),
        _support_x,
    ),
    # "goad all creatures your opponents control" (RULE 701.15a) — the mass
    # form first: the targeted row below can't match it (no "target"), but
    # the mass one is the more specific phrase and reads better up here.
    EffectHandler(
        "goad_selector",
        _c(r"goad all creatures (?:your opponents control|you don't control)"),
        _goad_selector,
    ),
    # "for each opponent, goad up to one target creature that player
    # controls" — a per-opponent requirement (RULE 601.2c). Before the plain
    # `goad` row, whose `TARGET` would otherwise claim the tail and silently
    # goad exactly one creature.
    EffectHandler(
        "goad_per_opponent",
        _c(
            r"for each opponent, goad up to 1 target creature "
            r"that (?:player|opponent) controls"
        ),
        _goad_per_opponent,
    ),
    # "goad up to X target creatures your opponents control" (Death Kiss).
    EffectHandler(
        "goad_up_to_x",
        _c(r"goad up to x target creatures (?:your opponents control|you don't control)"),
        _goad_up_to_x,
    ),
    # "goad target creature [an opponent controls]" (RULE 701.15a).
    EffectHandler(
        "goad",
        _c(rf"goad {TARGET}"),
        _goad,
    ),
    # "the tokens are goaded for the rest of the game" — the tokens an
    # earlier clause of this same ability created (`created_objects`).
    EffectHandler(
        "goad_created",
        _c(r"the tokens? (?:is|are) goaded for the rest of the game"),
        _goad_created,
    ),
    # "it's goaded for the rest of the game" — same duration, previous target.
    EffectHandler(
        "goad_previous_permanent",
        _c(r"(?:it's|that creature is) goaded for the rest of the game"),
        _goad_previous_permanent,
        previous_subject_only=True,
    ),
    # "goad it" / "goad that creature" — the previous clause's target.
    EffectHandler(
        "goad_previous",
        _c(r"goad (?:it|that creature)"),
        _goad_previous,
        previous_subject_only=True,
    ),
    # "all suspected creatures are no longer suspected" (RULE 701.60a's
    # reverse) — before the `suspect {TARGET}` row, which can't match it
    # (no "target") but reads better kept together.
    EffectHandler(
        "remove_suspected_all",
        _c(r"all suspected creatures are no longer suspected"),
        _remove_suspected_all,
    ),
    # "suspect enchanted creature" (RULE 701.60a) — an Aura's host.
    EffectHandler(
        "suspect_attached",
        _c(r"suspect enchanted creature"),
        _suspect_attached,
    ),
    # "suspect [up to N] target creature [an opponent controls]" (RULE 701.60a).
    EffectHandler(
        "suspect_target",
        _c(rf"suspect {TARGET}"),
        _suspect_target,
    ),
    # "suspect it" — explicit self ("when ~ enters, suspect it").
    EffectHandler(
        "suspect_self",
        _c(r"suspect (?:it|~)"),
        _suspect_self,
        self_subject_only=True,
    ),
    # "suspect it" / "suspect that creature" — the previous clause's target
    # ("gain control of target creature … suspect it", Caught Red-Handed).
    EffectHandler(
        "suspect_previous",
        _c(r"suspect (?:it|that creature)"),
        _suspect_previous,
        previous_subject_only=True,
    ),
    # "detain up to two target creatures your opponents control" (RULE
    # 701.35a) — before the singular row, which its `TARGET` can't match
    # (plural) but reads better kept together.
    EffectHandler(
        "detain_multi",
        _DETAIN_MULTI_RE,
        _detain_multi,
    ),
    # "detain [up to one] target creature/nonland permanent an opponent
    # controls" (RULE 701.35a).
    EffectHandler(
        "detain",
        _c(rf"detain {TARGET}"),
        _detain,
    ),
    # "manifest dread" (RULE 701.40a) — tried before the plain manifest row
    # below, which would otherwise not match it at all but reads more
    # naturally kept in this order alongside its sibling.
    EffectHandler(
        "manifest_dread",
        _c(r"manifest dread"),
        _manifest_dread,
    ),
    # "manifest the top card of your library" / "…the top two cards…" and
    # cloak's identical shape (RULE 701.40a/701.58a).
    EffectHandler(
        "manifest",
        _c(rf"(?P<verb>manifest|cloak) the top (?:{COUNT} )?cards? of your library"),
        _manifest,
    ),
    # "proliferate twice" / "proliferate N times" (RULE 701.30) — tried
    # before the bare `proliferate` row below since it's a strict superset.
    EffectHandler(
        "proliferate_n_times",
        _c(r"proliferate (?:(?P<twice>twice)|(?P<n>\d+) times)"),
        _proliferate_n_times,
    ),
    # "proliferate" (RULE 701.30) — bare.
    EffectHandler(
        "proliferate",
        _c(r"proliferate"),
        _proliferate,
    ),
    # "remove all counters from all permanents" (RULE 122 — Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped).
    EffectHandler(
        "remove_counters_all_permanents",
        _c(r"remove all counters from all permanents"),
        _remove_counters_all_permanents,
    ),
    # "remove all counters from target permanent" (Vampire Hexmage-shaped).
    EffectHandler(
        "remove_counters_target",
        _c(r"remove all counters from target permanent"),
        _remove_counters_target,
    ),
    # "remove up to N counters from target permanent/creature" (Glissa
    # Sunslayer/Heartless Act/Render Inert-shaped) — see
    # `_REMOVE_COUNTERS_CHOICE_RE`.
    EffectHandler(
        "remove_counters_choice",
        _REMOVE_COUNTERS_CHOICE_RE,
        _remove_counters_choice,
    ),
    # "You may play an additional land this turn." / "You may play up to
    # two additional lands this turn." (RULE 305.2 one-turn permission) —
    # see `_EXTRA_LAND_PLAY_RE` above; the standing per-turn static sibling
    # is `catalogue.static_handlers`' `extra_land_drop`.
    EffectHandler(
        "extra_land_play",
        _EXTRA_LAND_PLAY_RE,
        _extra_land_play,
    ),
    # "You become the monarch." / "Target player becomes the monarch."
    # (RULE 725.1).
    EffectHandler(
        "become_monarch",
        _c(r"(?P<who>you |target player )?becomes? the monarch"),
        _become_monarch,
    ),
    # "You take the initiative." / "Target player takes the initiative."
    # (RULE 726.1) — RULE 726.2's "venture into the dungeon" companion isn't
    # modeled (dungeons/RULE 309 aren't built yet); see
    # `game/effects.py`'s `TakeInitiativeEffect`.
    EffectHandler(
        "take_initiative",
        _c(r"(?P<who>you |target player )?takes? the initiative"),
        _take_initiative,
    ),
    # "You get an emblem with '<ability>'." (RULE 114.2) — see
    # `_emblem_ability_spec` above.
    EffectHandler(
        "create_emblem",
        _EMBLEM_RE,
        _create_emblem,
    ),
    # "Create that many 1/1 green Elf Warrior creature tokens." (Lathril,
    # Blade of the Elves-shaped) — tried before the plain `create_token`
    # row below, same "strict superset" reasoning.
    EffectHandler(
        "create_token_that_many",
        _CREATE_TOKEN_THAT_MANY_RE,
        _create_token_that_many,
    ),
    # "Create a 1/1 green Elf Warrior creature token for each Elf you
    # control." (Elvish Promenade-shaped) — tried before the plain
    # `create_token` row below since it's a strict superset of that shape.
    EffectHandler(
        "create_token_for_each",
        _CREATE_TOKEN_FOR_EACH_RE,
        _create_token_for_each,
    ),
    # "Create X 1/1 green Elf Warrior creature tokens, where X is the
    # number of attacking creatures." (Galadhrim Ambush-shaped).
    EffectHandler(
        "create_token_xx_where",
        _CREATE_TOKEN_XX_WHERE_RE,
        _create_token_xx_where,
    ),
    # RULE 202.2f/700.6 "create a number of 1/1 white Soldier creature
    # tokens equal to your devotion to white." (Evangel of Heliod/Master of
    # Waves-shaped) — tried before the plain `create_token` row below, same
    # "strict superset" reasoning as the two rows above.
    EffectHandler(
        "create_token_number_equal_devotion",
        _CREATE_TOKEN_NUMBER_EQUAL_DEVOTION_RE,
        _create_token_number_equal_devotion,
    ),
    # "create a 1/1 white Soldier creature token" / "create two 2/2 green Bear
    # creature tokens with trample" — inline creature tokens (fully modeled).
    EffectHandler(
        "create_token",
        _c(
            rf"(?:(?P<who>you|each player|each opponent) )?creates? {COUNT} "
            rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
            rf"(?P<mid>[a-z ]*?)creature tokens?"
            # ``0-9`` in the keyword capture is ENG-31's "… token with
            # firebending N" (Fire Nation Attacks/Occupation).
            rf"(?: with (?P<kw>[a-z0-9, ]+))?"
        ),
        _create_token,
    ),
    # PAR-13: "Create <Name>, a legendary N/N ... creature token [with
    # <keywords>]." — Cradle of the Death God's own unique Atropal token.
    EffectHandler(
        "create_named_legendary_token",
        _CREATE_NAMED_LEGENDARY_TOKEN_RE,
        _create_named_legendary_token,
    ),
    # "create a Food token, then create a 1/1 white Halfling creature token
    # and attach ~ to it." (Field-Tested Frying Pan) — tried before the
    # plain create-and-attach row below since it's a strict superset (a
    # leading named-token sentence that row's grammar doesn't expect).
    EffectHandler(
        "create_named_then_create_token_and_attach",
        _CREATE_NAMED_THEN_CREATE_TOKEN_AND_ATTACH_RE,
        _create_named_then_create_token_and_attach,
    ),
    # "create a 1/1 white Halfling creature token and attach ~ to it."
    # (Auxiliary Boosters, Living Weapon-adjacent) — the token, then attach
    # the ability's own source onto whatever that just made.
    EffectHandler(
        "create_token_and_attach",
        _CREATE_TOKEN_AND_ATTACH_RE,
        _create_token_and_attach,
    ),
    # "create a Treasure token" / "create two Clue tokens" — named,
    # non-creature artifact tokens (`_NAMED_TOKEN_WORDS`, kept in sync with
    # `data/tokens.json`).
    EffectHandler(
        "create_named_token",
        _c(rf"(?:you )?creates? {COUNT} (?P<name>{'|'.join(_NAMED_TOKEN_WORDS)}) tokens?"),
        _create_named_token,
    ),
    # "Investigate." / "Investigate twice." / "Investigate 3 times." (RULE
    # 701.19a) — a Clue-token-creation alias.
    EffectHandler(
        "investigate",
        _INVESTIGATE_RE,
        _investigate,
    ),
    # "The Ring tempts you." (RULE 701.51a) — Tales of Middle-earth.
    EffectHandler(
        "ring_tempts_you",
        _RING_TEMPTS_YOU_RE,
        _ring_tempts_you,
    ),
    # "[You may c]ast spells this turn as though they had flash." (Emergence
    # Zone-shaped, MEC-12; the leading "you may" is already peeled off by
    # `segmenter._peel_optional` before a clause ever reaches this table) —
    # the unrestricted, "this turn" one-shot grant already shipped as
    # `effects.GrantFlashUntilEndOfTurnEffect` (Borne Upon a Wind,
    # hand-authored only until now). No type filter exists on that effect,
    # so this row deliberately claims only the unqualified "spells"
    # wording, not a "sorcery spells"/"creature spells" narrowed variant (a
    # different, still-unmodeled shape — see PARSER_LONG_TAIL.md).
    EffectHandler(
        "grant_flash_until_eot",
        _c(r"cast spells this turn as though they had flash"),
        lambda m: [EffectSpec("grant_flash_until_eot", {})],
    ),
]


def match_clause(
    clause: str, *, self_subject: bool = False, previous_subject: bool = False,
    group_subject: bool = False, previous_selector: bool = False,
) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for one normalised effect ``clause``, or ``None``.

    Runs the handler table; the first handler to claim the whole clause wins.
    ``None`` means no handler modeled it — the clause is unclaimed and its card
    will fail the coverage gate (docs/09 fail-closed).

    ``self_subject`` says the clause's bare "it" is the ability's own source;
    ``previous_subject`` says it is the creature the *preceding* clause of
    the same body chose; ``group_subject`` says it is whichever object
    matched this ability's own RULE 603.1 group-subject trigger condition;
    ``previous_selector`` says "they" is the group a mass selector in the
    preceding clause acted on. Each unlocks its own gated rows (see
    `EffectHandler.self_subject_only`/``previous_subject_only``/
    ``group_subject_only``/``previous_selector_only``); with none set — the
    default, and the only reading available to a clause standing alone — a
    pronoun claims nothing at all.
    """
    for handler in HANDLERS:
        if handler.self_subject_only and not self_subject:
            continue
        if handler.previous_subject_only and not previous_subject:
            continue
        if handler.group_subject_only and not group_subject:
            continue
        if handler.previous_selector_only and not previous_selector:
            continue
        effects = handler.match(clause)
        if effects is not None:
            return effects
    return None
