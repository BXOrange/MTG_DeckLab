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
    IF_COLOR_SUFFIX,
    NUMBER,
    SPELL_TARGET,
    TARGET,
    UP_TO_ONE,
    count_of,
    count_or_x_of,
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
    (r"target permanents", "permanent"),
    (r"target artifacts", "permanent"),
    (r"target enchantments", "permanent"),
    (r"target lands", "permanent"),
    (r"target players", "player"),
]
_MULTI_TARGET_ALT = "|".join(f"(?:{frag})" for frag, _ in _MULTI_TARGET_ROWS)


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
_MULTI_TARGET_QUANTIFIER = (
    r"(?:(?P<any_number>any number of )|(?P<up_to>up to )?(?P<count>\d+) )"
)


#: An optional trailing "controlled by different players/controllers"
#: clause (Run Away Together/Protector of the Wastes-shaped, RULE 115.1a's
#: N>=2 generalized with a cross-target constraint — `targeting.TargetSpec.
#: distinct_controllers`) — appended right after `_MULTI_TARGET_ALT`'s
#: target phrase in whichever multi-target handler regex opts in.
_MULTI_TARGET_DISTINCT_CONTROLLERS = r"(?P<dc> controlled by different (?:players|controllers))?"


def _multi_target_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``{target_kind, count, optional?, distinct_controllers?}``
    params for a `_MULTI_TARGET_QUANTIFIER` + `_MULTI_TARGET_ALT` match, or
    ``None`` if the target phrase isn't recognized or the count is < 2 (the
    N=1 "up to one"/bare-target case is the existing singular handler's
    job, not this one's — a count of exactly 1 here would just be a
    confusing duplicate route to the same effect). PAR-15's "any number of"
    always carries ``optional=True`` (RULE 115.1a — 0 is always a legal
    choice) and a capped ``count`` (`_ANY_NUMBER_TARGET_CAP`)."""
    kind = _multi_target_kind(m.group("target"))
    if kind is None:
        return None
    if m.groupdict().get("any_number"):
        params: dict = {"target_kind": kind, "count": _ANY_NUMBER_TARGET_CAP, "optional": True}
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
_DAMAGE_KICKED_OVERRIDE_RE = _c(
    rf"(?:~|it) deals? {NUMBER} damage to {TARGET}\. "
    r"if this spell was kicked, it deals (?P<n2>\d+) damage"
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


#: RULE 707/706.2's "create a token that's a copy of target X" (Cackling
#: Counterpart/Rite of Replication-shaped) — deliberately narrow: only a
#: bare `{TARGET}` phrase with no trailing "except it's/has/isn't …"
#: modification clause, since that clause's shapes are too varied (a static
#: characteristic swap, a granted ability, a P/T override, …) to safely fold
#: into one grammar row without risking a wrong copy — fail-closed (no
#: match) rather than silently dropping the modification, same as every
#: other "can't safely represent this clause" case in this file.
_COPY_PERMANENT_RE = _c(rf"create a token that'?s a copy of {TARGET}")


def _copy_permanent(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("copy_permanent", {"target_kind": kind, **_optional_param(m)})]


#: The RULE 702.33b kicked-override sibling — "Create a token that's a copy
#: of target creature. If this spell was kicked, create five of those
#: tokens instead." (Rite of Replication) — same override shape as
#: `_damage_kicked_override`, just replacing ``count`` instead of ``amount``
#: (`CopyPermanentEffect.count_if_kicked`).
_COPY_PERMANENT_KICKED_OVERRIDE_RE = _c(
    rf"create a token that'?s a copy of {TARGET}\. "
    r"if this spell was kicked, create (?P<n2>\d+) of those tokens instead"
)


def _copy_permanent_kicked_override(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None:
        return None
    return [EffectSpec("copy_permanent", {
        "target_kind": kind, "count_if_kicked": int(m.group("n2")), **_optional_param(m),
    })]


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
    r"(?:\. if this spell was kicked, prevent the next (?P<n2>\d+) damage this way instead)?"
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


#: "~ deals N damage to each creature/player/opponent" — a *mass* effect
#: (RULE 601.2c), not RULE 115 targeting, so it's a dedicated regex rather
#: than a `TARGET` row (see `subgrammars._TARGET_ROWS`'s note on why "each
#: opponent"/"each player" were deliberately kept out of that grammar).
_DAMAGE_SELECTOR_WORDS: dict[str, str] = {
    "each creature": "each_creature",
    "each player": "each_player",
    "each opponent": "each_opponent",
}


def _damage_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _DAMAGE_SELECTOR_WORDS[m.group("selector")]
    return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": selector})]


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
_EXILE_TOP_PLAY_RE = _c(
    r"exile the top (?P<n>\d+) cards? of your library\. you may play (?:them|it)"
    r"(?: (?P<dur>this turn|until the end of your next turn))?"
)


def _exile_top_play(m: re.Match[str]) -> list[EffectSpec]:
    same_turn_only = (m.groupdict().get("dur") or "").strip() == "this turn"
    return [EffectSpec("impulsive_draw", {
        "count": int(m.group("n")), "same_turn_only": same_turn_only,
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


#: RULE 119/701.8's "Target opponent/player reveals their hand. You choose
#: a `<filter>` card from it. That player discards that card." (Duress/
#: Thoughtseize/Coercion/Distress-shaped — one of the most repeated hand-
#: disruption templates in the cache). Deliberately just the five real
#: filter phrasings found so far (bare/nonland/noncreature+nonland/
#: creature-or-planeswalker/artifact-or-creature) rather than a fully
#: general card-type grammar — a filter word not in this table (mana-value
#: thresholds, "or a card from their graveyard", a trailing "you lose N
#: life") stays unclaimed rather than guessed at.
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
    r"from it\. that player discards that card"
)


def _hand_disruption_discard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind != "player":
        return None
    params: dict = {"target_kind": kind, **_HAND_DISRUPTION_FILTERS[m.group("filter")]}
    return [EffectSpec("reveal_hand_choose_discard", params)]


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


def _xx_token_mid_params(mid: str, kw: Optional[str]) -> Optional[dict]:
    """The shared ``colors``/``subtypes``/``keywords`` params for an X/X
    token clause's "<mid> token[ with <kw>]" tail — the same word-splitting
    `_inline_create_token_params` uses for a literal-stats token, factored
    out since neither of the two X/X handlers below share that function's
    other (count/tapped/legendary) groups."""
    colors: list[str] = []
    subtypes: list[str] = []
    for word in mid.split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    keywords: list[str] = []
    if kw:
        parsed = _token_keywords(kw)
        if parsed is None:
            return None
        keywords = parsed
    params: dict = {"colors": colors, "subtypes": subtypes, "keywords": keywords}
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


def _lose_life(m: re.Match[str]) -> list[EffectSpec]:
    # "you lose N life" / "target player loses N life" — same targeting
    # split as `_gain_life`.
    params: dict = {"amount": int(m.group("n"))}
    if (m.groupdict().get("who") or "").strip() == "target player":
        params["target_kind"] = "player"
    return [EffectSpec("lose_life", params)]


#: "each opponent loses N life" / "each player loses N life" — the same
#: mass/untargeted-selector shape `_DAMAGE_SELECTOR_WORDS` uses (RULE
#: 601.2c, not RULE 115 targeting — see that constant's note on why "each
#: opponent"/"each player" stay out of the `TARGET` grammar).
_LOSE_LIFE_SELECTOR_WORDS: dict[str, str] = {
    "each player": "each_player", "each opponent": "each_opponent",
}


def _lose_life_selector(m: re.Match[str]) -> list[EffectSpec]:
    selector = _LOSE_LIFE_SELECTOR_WORDS[m.group("selector")]
    return [EffectSpec("lose_life", {"amount": int(m.group("n")), "selector": selector})]


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
    selector = _LOSE_LIFE_SELECTOR_WORDS[m.group("selector")]
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


def _destroy(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
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
    # doesn't recognise).
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
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


def _destroy_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = _creature_quality_filter(m)
    if filt is None:
        return None
    return [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": filt})]


def _exile_creature_filter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    filt = _creature_quality_filter(m)
    if filt is None:
        return None
    return [EffectSpec("exile", {"target_kind": "creature", "creature_filter": filt})]


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


def _destroy_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("destroy", params)]


#: RULE 601.2c mass "destroy/exile all X [with a numeric filter]" board wipe
#: (Wrath of God/Damnation/Citywide Bust-shaped) — untargeted, the same
#: `selector` vocabulary `game/effects.py`'s `DestroyEffect`/`ExileEffect`
#: already support (previously only reachable via hand-authoring individual
#: cards in `ability_catalogue.py`; this is the general oracle-text form).
#: Only the two numeric filter kinds `_mass_selector_objects` actually
#: implements are recognized here — "power N or greater" has no mass-form
#: engine support, so it's deliberately left unmatched (fail-closed) rather
#: than silently dropped.
_MASS_DESTROY_NOUNS: dict[str, str] = {
    "creatures": "all_creatures",
    "artifacts": "all_artifacts",
    "enchantments": "all_enchantments",
    "planeswalkers": "all_planeswalkers",
    "permanents": "all_permanents",
    "lands": "all_lands",
}
_MASS_DESTROY_FILTER = (
    r"(?: with (?:mana value (?P<mv>\d+) or (?P<mv_cmp>greater|less)"
    r"|toughness (?P<tough>\d+) or greater"
    r"|power (?P<power>\d+) or (?P<power_cmp>greater|less)))?"
)


def _mass_destroy_filter_dict(m: re.Match[str]) -> Optional[dict]:
    groups = m.groupdict()
    filt: dict = {}
    if groups.get("mv"):
        n = int(groups["mv"])
        filt["max_mana_value" if groups["mv_cmp"] == "less" else "min_mana_value"] = n
    if groups.get("tough"):
        filt["min_toughness"] = int(groups["tough"])
    if groups.get("power"):
        n = int(groups["power"])
        filt["max_power" if groups["power_cmp"] == "less" else "min_power"] = n
    return filt or None


_DESTROY_ALL_RE = _c(
    rf"destroy all (?P<noun>{'|'.join(_MASS_DESTROY_NOUNS)}){_MASS_DESTROY_FILTER}"
)


def _destroy_all(m: re.Match[str]) -> list[EffectSpec]:
    params: dict = {"selector": _MASS_DESTROY_NOUNS[m.group("noun")]}
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


def _cant_be_countered(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("cant_be_countered", {})]


def _mill(m: re.Match[str]) -> list[EffectSpec]:
    # "you mill N" / bare "mill N" → self; "target player/opponent mills N" → targeted.
    who = (m.groupdict().get("who") or "").strip()
    params: dict = {"count": int(m.group("n"))}
    if who in ("target player", "target opponent"):
        params["target_kind"] = "player"
    return [EffectSpec("mill", params)]


def _exile(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent"):
        return None
    return [EffectSpec("exile", {"target_kind": kind, **_optional_param(m)})]


def _exile_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None:
        return None
    return [EffectSpec("exile", params)]


def _tap(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in ("creature", "permanent", "legendary_permanent", "forest"):
        return None
    untap = m.group("verb").lower() == "untap"
    return [EffectSpec("tap", {"target_kind": kind, "untap": untap, **_optional_param(m)})]


#: "tap N target creatures" / "untap up to two target lands" (RULE 115.1a
#: generalized to N>=2, Snap-shaped — `TapEffect.count` already supported
#: this; only the grammar was missing). Restricted to the same
#: creature/permanent kinds the singular `_tap` handler allows.
def _tap_multi_target(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _multi_target_params(m)
    if params is None or params["target_kind"] not in ("creature", "permanent"):
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
    selector = "other_creatures_you_control" if m.groupdict().get("other") else "creatures_you_control"
    return [EffectSpec("tap", {"selector": selector, "untap": untap})]


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
    {"creature", "permanent", "any", "creature_you_control", "land_you_control"}
)


def _return_to_hand(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = resolve_target_kind(m.group("target"))
    if kind is None or kind not in _RETURN_TO_HAND_KINDS:
        return None
    return [EffectSpec("return_to_hand", {"target_kind": kind, **_optional_param(m)})]


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
#: [instant or sorcery/nonland permanent/creature/artifact/enchantment/
#: land/permanent] card", or no word at all for a bare "target card"
#: (longest-alternative-first so "nonland permanent" wins over "permanent").
_GRAVEYARD_TYPE_WORD = (
    r"instant or sorcery|nonland permanent|creature|artifact|enchantment|land|permanent"
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


#: "return target [type] card from [scope] graveyard to the battlefield/
#: your hand/its owner's hand" / "put target [type] card from [scope]
#: graveyard onto the battlefield under its owner's control" (RULE 701.3,
#: the Regrowth/Reanimate/Deathrite-adjacent recursion family — see
#: `game/targeting.py`'s `_GRAVEYARD_TARGET_KINDS` for the scope × type
#: vocabulary this claims). Both verb shapes land the object under its own
#: *owner*'s control — the "steal it for yourself" shape is
#: `_reanimate_under_your_control` below, a genuinely different effect.
_RETURN_FROM_GRAVEYARD_RE = _c(
    rf"return (?P<up_to_one>{UP_TO_ONE})target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
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
    count = int(m.group("count"))
    if count < 2:
        return None
    dest = m.groupdict().get("dest")
    destination = "battlefield" if dest is None or dest == "the battlefield" else "hand"
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


#: "exile target [type] card from [scope] graveyard" (RULE 701.5a) — the
#: Deathrite Shaman/Scavenging Ooze/Lion Sash graveyard-hate family; almost
#: always "a graveyard" in practice, but the same scope vocabulary applies.
_EXILE_FROM_GRAVEYARD_RE = _c(
    rf"exile target (?:(?P<type>{_GRAVEYARD_TYPE_WORD}) )?card from "
    rf"(?P<scope>{_GRAVEYARD_SCOPE_WORD}) graveyard"
)


def _exile_from_graveyard(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    kind = _graveyard_target_kind(m.groupdict().get("type"), m.group("scope"))
    if kind is None:
        return None
    return [EffectSpec("exile", {"target_kind": kind})]


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
_SEARCH_TYPE_WORD = (
    r"artifact|creature|enchantment|instant|planeswalker|sorcery|land|"
    r"plains|island|swamp|mountain|forest"
)
#: An "or"/comma-separated list of 1+ type words, same shape as
#: `subgrammars._SPELL_TYPE_LIST` (kept separate/local since this vocabulary
#: — land + basic land names — is specific to a library search, not a spell
#: target filter).
_SEARCH_TYPE_LIST = (
    rf"(?:{_SEARCH_TYPE_WORD})(?:,\s*(?:{_SEARCH_TYPE_WORD}))*"
    rf"(?:,?\s+or\s+(?:{_SEARCH_TYPE_WORD}))?"
)
#: The noun phrase after "search your library for": a determiner ("a"/"an"/
#: "up to N"), then either "basic land" (sets `basic`) or a `_SEARCH_TYPE_
#: LIST` (sets `types`) or neither (a bare "a card"), then "card(s)".
_SEARCH_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    rf"(?:(?P<basic>basic land)|(?P<types>{_SEARCH_TYPE_LIST}))?\s*"
    r"cards?"
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

#: "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
#: <destination>, then shuffle." — the common put-then-shuffle order.
_SEARCH_PUT_THEN_SHUFFLE_RE = _c(
    rf"search your library for {_SEARCH_CRITERIA},?\s*"
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


def _search_criteria_from_match(m: re.Match[str]) -> dict:
    if m.groupdict().get("basic"):
        return {"basic": True}
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        return {"type": words if len(words) > 1 else words[0]}
    return {}


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


#: The criteria noun phrase for a "library and/or graveyard" search — same
#: basic-land/type-list alternatives as `_SEARCH_CRITERIA`, plus a bare-name
#: alternative ("a card named <Name>") this family's real cards lean on
#: heavily (planeswalker/background tutors); restricted to a name with no
#: internal comma (see the module docstring above for why).
_SEARCH_ZONE_CRITERIA = (
    r"(?:up to (?P<count>\d+)|an?)\s+"
    r"(?:"
    r"(?P<basic>basic land) cards?"
    rf"|card named (?P<name>[a-z][a-z' -]*?)"
    rf"|(?P<types>{_SEARCH_TYPE_LIST}) cards?"
    r"|cards?"
    r")"
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
        return {"basic": True}
    name = m.groupdict().get("name")
    if name:
        return {"name": name.strip()}
    types = m.groupdict().get("types")
    if types:
        words = [t.strip() for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", types) if t.strip()]
        return {"type": words if len(words) > 1 else words[0]}
    return {}


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
_FIGHT_PREVIOUS_PAIR_RE = _c(
    rf"{_THEN}(?:those|the chosen) creatures fight each other"
)
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
        selector = _DAMAGE_SELECTOR_WORDS.get(m.group("selector").lower())
        if selector is None:
            return None
        params: dict = {"selector": selector, "target_kind": None}
        if dealer_kind is not None:
            params["dealer_kind"] = dealer_kind
        return [EffectSpec("damage_equal_to_power", params)]

    return build


_DAMAGE_SELECTOR_ALT = "|".join(_DAMAGE_SELECTOR_WORDS)
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
#: you could cast a sorcery"). Deliberately not "only during your turn" /
#: "before attackers are declared" — those are subtly different timing
#: windows (a non-empty stack / instant-speed-within-your-turn is still
#: allowed), so folding them to sorcery-speed would be *wrong*; left unclaimed
#: (fail-closed) until modeled precisely.
SORCERY_SPEED_MARKER = "sorcery_speed_marker"
_SORCERY_SPEED_RE = _c(
    r"activate (?:this ability )?only "
    r"(?:as a sorcery|any time you could cast a sorcery)"
)


def _sorcery_speed(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec(SORCERY_SPEED_MARKER, {})]


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


def _inline_create_token_params(m: re.Match[str]) -> Optional[dict]:
    """The shared ``create_token`` params for the inline-stats creature-token
    grammar (``p``/``t``/``mid``/``kw``/``n``/``tapped``/``legendary``/``who``
    groups) — factored out of `_create_token` so `_create_token_and_attach`
    can build the same params for its own, differently-wrapped clause."""
    colors: list[str] = []
    subtypes: list[str] = []
    for word in (m.group("mid") or "").split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = _token_keywords(m.group("kw"))
        if parsed is None:
            return None  # unrecognised "with …" ability → fail-closed
        keywords = parsed
    params: dict = {
        "count": count_of(m.group("n")),
        "power": int(m.group("p")),
        "toughness": int(m.group("t")),
        "colors": colors,
        "subtypes": subtypes,
        "keywords": keywords,
    }
    if subtypes:
        params["token_name"] = " ".join(subtypes)
    if m.groupdict().get("legendary"):
        params["legendary"] = True
    # "**Each player** creates …" / "**each opponent** creates …" — everyone
    # gets their own ``count`` tokens under their own control, rather than
    # the effect's controller getting them all.
    who = (m.groupdict().get("who") or "").strip()
    if who:
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
#: then explain it" sibling of the "for each" row above; same count-
#: selector vocabulary, different surface wording.
_CREATE_TOKEN_XX_WHERE_RE = _c(
    r"create x (?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
    r"(?P<mid>[a-z ]*?)creature tokens?"
    r"(?: with (?P<kw>[a-z, ]+))?, "
    r"where x is the number of (?:(?P<subtype>[a-z]+) you control|(?P<attacking>attacking creatures))"
)


def _create_token_xx_where(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params = _xx_token_mid_params(m.group("mid"), m.groupdict().get("kw"))
    if params is None:
        return None
    selector = _count_selector_for_phrase(m.groupdict().get("subtype"), m.groupdict().get("attacking"))
    if selector is None:
        return None
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
    rf"(?P<mid>[a-z ]*?)creature tokens?(?: with (?P<kw>[a-z, ]+))?"
)

#: "create a 1/1 white Halfling creature token and attach ~ to it." (Living
#: Weapon-adjacent, but printed as ordinary oracle text rather than the
#: keyword — Auxiliary Boosters) — one clause, two effects: the token, then
#: `AttachEffect`'s ``target_kind="created"`` mode onto whatever that just
#: made (RULE 608.2's "it").
_CREATE_TOKEN_AND_ATTACH_RE = _c(rf"creates? {_CREATE_TOKEN_INLINE} and attach ~ to it")


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
    colors: list[str] = []
    subtypes: list[str] = []
    for word in (m.group("mid") or "").split():
        if word in _COLOR_WORDS:
            colors.append(_COLOR_WORDS[word])
        elif word in _TOKEN_NOISE_WORDS:
            continue
        else:
            subtypes.append(word.capitalize())
    keywords: list[str] = []
    if m.groupdict().get("kw"):
        parsed = _token_keywords(m.group("kw"))
        if parsed is None:
            return None
        keywords = parsed
    return [EffectSpec("create_token", {
        "count": 1, "power": int(m.group("p")), "toughness": int(m.group("t")),
        "colors": colors, "subtypes": subtypes, "keywords": keywords,
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


def _add_counters(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    # "+1/+1" (default) or "-1/-1" — the sign of the captured counter kind picks
    # which; both shift net P/T through the same machinery (RULE 122).
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    params: dict = {"count": count_of(m.group("n")), "kind": ckind}
    if m.groupdict().get("selfref"):  # "on ~" — buffs the source, untargeted
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    # +1/+1 counters can sit on *any* permanent (RULE 122.1a) — a land that
    # enters with counters and later becomes a creature uses them. So we honour
    # whatever the text targets (creature or permanent, incl. the
    # controller-restricted "target creature you control" pick, Archdruid's
    # Charm-shaped); only the target phrase constrains it, not the counter itself.
    if kind not in ("creature", "permanent", "creature_you_control"):
        return None
    params["target_kind"] = kind
    params.update(_optional_param(m))
    return [EffectSpec("add_counters", params)]


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
_NAMED_COUNTER_KINDS: frozenset[str] = frozenset({"spore", "burden"})
_ADD_NAMED_COUNTER_RE = _c(
    rf"put {COUNT} (?P<ckind>{'|'.join(_NAMED_COUNTER_KINDS)}) counters? on "
    rf"(?:{TARGET}|(?P<selfref>{_SELF_SUBJECT}))"
)


def _add_named_counter(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    params: dict = {"count": count_of(m.group("n")), "kind": m.group("ckind")}
    if m.groupdict().get("selfref"):
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent", "creature_you_control"):
        return None
    params["target_kind"] = kind
    params.update(_optional_param(m))
    return [EffectSpec("add_counters", params)]


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
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    params: dict = {"kind": ckind, "amount_from_trigger_event": "amount"}
    if m.groupdict().get("selfref"):
        return [EffectSpec("add_counters", params)]
    kind = resolve_target_kind(m.group("target"))
    if kind not in ("creature", "permanent", "creature_you_control"):
        return None
    params["target_kind"] = kind
    return [EffectSpec("add_counters", params)]


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
    if mt is None or mt["target_kind"] not in ("creature", "permanent"):
        return None
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    params: dict = {
        "count": count_of(m.group("n")),
        "kind": ckind,
        "target_kind": mt["target_kind"],
        "target_count": mt["count"],
    }
    if mt.get("optional"):
        params["optional"] = True
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
    ckind = "-1/-1" if m.group("ckind")[0] in "-−" else "+1/+1"
    kind = "creature_you_control" if m.groupdict().get("yc") else "creature"
    return [EffectSpec("add_counters", {
        "count": int(m.group("n")), "kind": ckind, "target_kind": kind,
        "target_count": _ANY_NUMBER_TARGET_CAP, "optional": True, "divided": True,
    })]


#: "put N +1/+1 counters on each creature you control" (RULE 601.2c mass
#: effect, Vastwood Surge-shaped) — a genuinely different shape from
#: `_add_counters`'s RULE 115 target/self forms, so its own handler row
#: rather than folding "each creature you control" into `TARGET` (that
#: grammar deliberately keeps "each ..." selectors out, see
#: `subgrammars._TARGET_ROWS`'s note).
def _add_counters_selector(m: re.Match[str]) -> list[EffectSpec]:
    ckind = "-1/-1" if m.group("ckind").lstrip()[0] in "-−" else "+1/+1"
    return [EffectSpec("add_counters", {
        "count": count_of(m.group("n")), "kind": ckind, "selector": "each_creature_you_control",
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
    keywords = _token_keywords(m.group("kw"))
    if keywords is None:
        return None
    params: dict = {"keywords": keywords}
    if target_kind:
        params["target_kind"] = target_kind
    if selector:
        params["selector"] = selector
    return [EffectSpec("pump", params)]


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


def _scry(m: re.Match[str]) -> list[EffectSpec]:
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


def _surveil(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("surveil", {"count": int(m.group("n"))})]


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
    r"(?P<group>other creatures you control|creatures you control|all creatures"
    r"|creatures your opponents control|creatures you don'?t control"
    r"|permanents you control|elves you control|elf creatures you control)"
)
_SUBJECT = (
    rf"(?:{TARGET}|(?P<selfref>{re.escape(SELF)})|{_GROUP}|(?P<attached>{_ATTACHED_SUBJECT}))"
)
#: A matched ``group`` phrase → its `continuous.group_selector_objects` selector.
_GROUP_SELECTORS: dict[str, str] = {
    "creatures you control": "creatures_you_control",
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


# --- The table --------------------------------------------------------------
# Order matters only for reporting; a clause is claimed by the first handler
# whose full-clause regex matches. Every pattern is anchored to the whole
# clause by `EffectHandler.match`'s `fullmatch`, so no partial claims.

HANDLERS: list[EffectHandler] = [
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
    # "Create a token that's a copy of target creature." (RULE 707/706.2,
    # Cackling Counterpart-shaped) — the bare form, no kicker.
    EffectHandler(
        "copy_permanent",
        _COPY_PERMANENT_RE,
        _copy_permanent,
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
    # RULE 601.2d "divided as you choose among any number of target(s)"
    # (PAR-15) — a split total, not the "each of N" full-amount shape above.
    EffectHandler(
        "divided_damage",
        _DIVIDED_DAMAGE_RE,
        _divided_damage,
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
    # "~ deals 2 damage to each creature" / "… to each player" / "… to each
    # opponent" — a mass effect (RULE 601.2c), not RULE 115 targeting.
    EffectHandler(
        "damage_selector",
        _c(
            rf"(?:(?:~|it|this creature|this land|this permanent) )?deals? {NUMBER} damage to "
            rf"(?P<selector>each creature|each player|each opponent)"
        ),
        _damage_selector,
    ),
    # "You may pay <cost>. If you do, draw a card." (RULE 118.3).
    EffectHandler(
        "pay_cost_then_draw",
        _PAY_COST_THEN_DRAW_RE,
        _pay_cost_then_draw,
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
    # "you lose 2 life" / "target player loses 2 life"
    EffectHandler(
        "lose_life",
        _c(rf"(?P<who>you |target player )?loses? {NUMBER} life"),
        _lose_life,
    ),
    # "each opponent loses 2 life" / "each player loses 2 life" (RULE
    # 601.2c mass effect, Deathrite Shaman-shaped).
    EffectHandler(
        "lose_life_selector",
        _c(rf"(?P<selector>each player|each opponent) loses? {NUMBER} life"),
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
    # "exile two target creatures" / "exile up to two target artifacts"
    # (RULE 115.1a generalized to N>=2), optionally "… controlled by
    # different players" (Protector of the Wastes-shaped cross-target
    # constraint — `_MULTI_TARGET_DISTINCT_CONTROLLERS`).
    EffectHandler(
        "exile_multi_target",
        _c(
            rf"exile {_MULTI_TARGET_QUANTIFIER}(?P<target>{_MULTI_TARGET_ALT})"
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
    # "untap all creatures you control" (Village Bell-Ringer) — must sit
    # above `tap_self`/the bare `_SELF_SUBJECT` row so "all creatures you
    # control" (not a self-reference) is recognised on its own.
    EffectHandler(
        "tap_selector",
        _c(r"(?P<verb>tap|untap) (?:all creatures you control|each (?P<other>other) creature you control)"),
        _tap_selector,
    ),
    # "untap this creature" / "untap ~" / "tap it" — the self form (Devoted
    # Druid's "Put a -1/-1 counter on this creature: Untap this creature.").
    EffectHandler(
        "tap_self",
        _c(rf"(?P<verb>tap|untap) {_SELF_SUBJECT}"),
        _tap_self,
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
        "return_self_to_hand",
        _c(rf"return {_SELF_SUBJECT} to its owner's hand"),
        _return_self_to_hand,
    ),
    # "return target creature to its owner's hand" / "return a land you
    # control to its owner's hand" (RULE 701.3 — the bounce family).
    EffectHandler(
        "return_to_hand",
        _c(rf"return {TARGET} to its owner's hand"),
        _return_to_hand,
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
    # "search your library for <criteria>, [reveal <pronoun>,] put <pronoun>
    # <destination>, then shuffle." (RULE 701.19 — the general tutor/ramp/
    # fetch family: unrestricted tutors, basic-land fetches, criteria-
    # filtered tutors, "reveal" variants).
    EffectHandler(
        "search_put_then_shuffle",
        _SEARCH_PUT_THEN_SHUFFLE_RE,
        _search_put_then_shuffle,
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
    EffectHandler("fight", _FIGHT_TWO_TARGETS_RE, _fight),
    EffectHandler("fight_self", _FIGHT_SELF_RE, _fight_implicit(None)),
    EffectHandler(
        "fight_pronoun", _FIGHT_PRONOUN_RE, _fight_implicit(None), self_subject_only=True,
    ),
    EffectHandler("fight_attached", _FIGHT_ATTACHED_RE, _fight_implicit("attached_permanent")),
    # The same fight, with the fighter named by a pronoun pointing back at
    # the clause before it ("… gets +1/+2 until end of turn. **It** fights
    # target creature you don't control.") — only offered when the caller
    # says an earlier clause in this same body actually chose a creature
    # (`EffectHandler.previous_subject_only`).
    EffectHandler(
        "fight_previous", _FIGHT_PREVIOUS_RE, _fight_implicit("previous_target"),
        previous_subject_only=True,
    ),
    EffectHandler(
        "fight_previous_pair", _FIGHT_PREVIOUS_PAIR_RE, _fight_previous_pair,
        previous_subject_only=True,
    ),
    # "Choose target creature you control and target creature you don't
    # control." — the target announcement those pair clauses read back.
    EffectHandler("choose_targets", _CHOOSE_TARGETS_RE, _choose_targets),
    # "Choose two target creatures controlled by different players." (PAR-1)
    # — the quantified-group announcement `_return_previous_group` (below)
    # reads back via "those creatures".
    EffectHandler("choose_targets_group", _CHOOSE_TARGETS_GROUP_RE, _choose_targets_group),
    # The one-sided fight (RULE 701.14's shape minus the damage back):
    # "target creature you control deals damage equal to its power to target
    # creature you don't control" and its four implicit-dealer siblings.
    EffectHandler("damage_equal_to_power", _POWER_DAMAGE_TWO_TARGETS_RE, _damage_equal_to_power),
    EffectHandler(
        "damage_equal_to_power_self", _POWER_DAMAGE_SELF_RE,
        _damage_equal_to_power_implicit(None),
    ),
    EffectHandler(
        "damage_equal_to_power_self_selector", _POWER_DAMAGE_SELF_SELECTOR_RE,
        _damage_equal_to_power_selector(None),
    ),
    EffectHandler(
        "damage_equal_to_power_pronoun", _POWER_DAMAGE_PRONOUN_RE,
        _damage_equal_to_power_implicit(None), self_subject_only=True,
    ),
    EffectHandler(
        "damage_equal_to_power_pronoun_selector", _POWER_DAMAGE_PRONOUN_SELECTOR_RE,
        _damage_equal_to_power_selector(None), self_subject_only=True,
    ),
    EffectHandler(
        "damage_equal_to_power_attached", _POWER_DAMAGE_ATTACHED_RE,
        _damage_equal_to_power_implicit("attached_permanent"),
    ),
    EffectHandler(
        "damage_equal_to_power_previous", _POWER_DAMAGE_PREVIOUS_RE,
        _damage_equal_to_power_implicit("previous_target"), previous_subject_only=True,
    ),
    # "you may pay {E}{E}. If you do, <effect>." (Aether Chaser) — tried
    # before the bare mana/effect handlers since it wraps a whole clause.
    EffectHandler(
        "pay_energy_then",
        _PAY_ENERGY_THEN_RE,
        _pay_energy_then,
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
        _c(rf"{_SUBJECT} gains? (?P<kw>[a-z, ]+?) until end of turn"),
        _pump_keywords,
    ),
    # "Each creature your opponents control gets -1/-1 until end of turn
    # for each poison counter its controller has." (Phyresis Outbreak).
    EffectHandler(
        "pump_per_controller_counter",
        _PUMP_PER_CONTROLLER_COUNTER_RE,
        _pump_per_controller_counter,
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
    # "Whenever ~ attacks, it gets +1/+0 until end of turn." (Akroan Hoplite-
    # adjacent self-buff-on-attack, `it` bound to the ability's own source —
    # `self_subject_only`, only ever offered from a self-subject trigger
    # body). The "for each <count>" scaling variant (Akroan Hoplite's own
    # actual text, "…where x is the number of attacking creatures you
    # control") is a separate, still-open widening — this row only claims
    # the flat-amount form.
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
    # "scry 2" (a self effect — the controller scries; RULE 701.18).
    EffectHandler(
        "scry",
        _c(rf"scry {NUMBER}"),
        _scry,
    ),
    # "surveil 2" (a self effect — the controller surveils; RULE 701.31).
    EffectHandler(
        "surveil",
        _c(rf"surveil {NUMBER}"),
        _surveil,
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
    # "create a 1/1 white Soldier creature token" / "create two 2/2 green Bear
    # creature tokens with trample" — inline creature tokens (fully modeled).
    EffectHandler(
        "create_token",
        _c(
            rf"(?:(?P<who>you|each player|each opponent) )?creates? {COUNT} "
            rf"(?P<tapped>tapped )?(?P<legendary>legendary )?(?P<p>\d+)/(?P<t>\d+) "
            rf"(?P<mid>[a-z ]*?)creature tokens?"
            rf"(?: with (?P<kw>[a-z, ]+))?"
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
]


def match_clause(
    clause: str, *, self_subject: bool = False, previous_subject: bool = False
) -> Optional[list[EffectSpec]]:
    """The `EffectSpec`s for one normalised effect ``clause``, or ``None``.

    Runs the handler table; the first handler to claim the whole clause wins.
    ``None`` means no handler modeled it — the clause is unclaimed and its card
    will fail the coverage gate (docs/09 fail-closed).

    ``self_subject`` says the clause's bare "it" is the ability's own source;
    ``previous_subject`` says it is the creature the *preceding* clause of
    the same body chose. Each unlocks its own gated rows (see
    `EffectHandler.self_subject_only`/``previous_subject_only``); with
    neither set — the default, and the only reading available to a clause
    standing alone — a pronoun claims nothing at all.
    """
    for handler in HANDLERS:
        if handler.self_subject_only and not self_subject:
            continue
        if handler.previous_subject_only and not previous_subject:
            continue
        effects = handler.match(clause)
        if effects is not None:
            return effects
    return None
