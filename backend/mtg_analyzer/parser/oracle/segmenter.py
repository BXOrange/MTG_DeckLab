"""Step 2 of the front-end pipeline: segment abilities (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE FRONT-END PIPELINE", step 2
SEGMENT). Splits *normalised* card text into individual abilities and peels
the wrapper off each one — the trigger phrase of a triggered ability, the
"you may" optionality — leaving a bare **effect body** for the handler table
(step 3) to claim. Keyword lines are recognised so the coverage gate can
account for them (their actual specs come from the keyword catalogue, which
anchors on Scryfall's `keywords` array).

Pure text/data — **no `game/` imports** (front-end security boundary). The
`EventType` strings a trigger maps to are hard-coded here with a comment and
kept in sync with `models/events.py` by `tests/test_oracle_segmenter.py`,
so the front-end stays import-pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from .catalogue.handlers import match_clause
from .catalogue.keywords import KEYWORDS
from .catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from .catalogue.static_handlers import static_effect_specs
from .spec import AbilitySpec, EffectSpec, ParserProvenance

#: Trigger phrase → `EventType` value (mirrors `models/events.py`). Conservative
#: on purpose: only the events the engine actually fires and the binder can wire.
#: Anything not here leaves the ability unclaimed → its card stays `UNMODELED`
#: (docs/09 fail-closed), never a wrong trigger.
_TRIGGER_EVENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\benters\b"), "ENTERS_BATTLEFIELD"),
    (re.compile(r"\bdies\b"), "DIES"),
    (re.compile(r"\battacks\b"), "ATTACKS"),
    (re.compile(r"\bblocks\b"), "BLOCKS"),
]

#: A triggered-ability wrapper: "When/Whenever/At <condition>, <body>".
_TRIGGER_RE = re.compile(r"^(?:when|whenever|at)\b(?P<cond>[^,]*),\s*(?P<body>.+)$", re.S)

#: RULE 603.1's condition *subject* — "self" ("~"/"this creature" itself) —
#: scoped so e.g. "when ~ enters the battlefield, draw a card" only fires for
#: its own source, never any other permanent entering (the over-firing bug
#: this grammar exists to close). The verb itself is still resolved by
#: `_trigger_event` above; this only decides *whose* enters/dies/attacks/
#: blocks the ability cares about.
_SELF_SUBJECT_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|land|permanent|equipment))\s+"
    r"(?:enters|dies|attacks|blocks)(?:\s+the\s+battlefield)?$"
)

#: The card-type words a "group" trigger condition can scope to (RULE 613.6-
#: adjacent vocabulary shared with `catalogue.static_handlers`'s anthem
#: selectors) — deliberately small: only what `models/game_object.py`'s
#: `type_words` can check without a subtype grammar.
_GROUP_TYPE_WORDS = ("creature", "artifact", "enchantment", "land", "permanent")

#: RULE 603.1's condition subject — a *group* of objects, not just the
#: source itself: "a"/"another" <type> [you control], then the trigger verb,
#: optionally "the battlefield" (enters) and/or "under your control" (the
#: older enters-battlefield templating). Examples this claims: "a creature
#: enters the battlefield under your control", "another creature you control
#: enters", "a creature dies", "another creature you control dies", "a
#: creature you control attacks".
_GROUP_SUBJECT_RE = re.compile(
    r"^(?P<article>a|another)\s+(?P<type>" + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<you_a> you control)?"
    r"\s+(?:enters|dies|attacks|blocks)"
    r"(?:\s+the\s+battlefield)?"
    r"(?P<you_b> under your control)?$"
)

#: An activated-ability wrapper: "<cost>: <effect>" (RULE 602.1). The cost is
#: everything before the first colon.
_ACTIVATED_RE = re.compile(r"^(?P<cost>[^:]+):\s*(?P<effect>.+)$", re.S)

#: A cost is only trusted as one if it actually *looks* like a cost — a mana/
#: {T} symbol, or one of the non-mana cost words. This keeps a stray sentence
#: colon (and loyalty "[+1]:" costs, not modeled yet — RULE 606) from being
#: mis-read as an activation cost (fail-closed). "put a counter on this/~"
#: is Devoted Druid's "Put a -1/-1 counter on this creature: Untap this
#: creature." cost; "tap ... untapped ... you control" is Birchlore Rangers'/
#: Heritage Druid's bulk-tap cost (RULE 602.1, `costs.tap_others`).
_COST_LOOKS_REAL = re.compile(
    r"\{[^}]+\}|sacrifice|pay \d+ life|discard|put an? .+ counter on|"
    r"tap .+ untapped .+ you control",
    re.I,
)

#: A planeswalker loyalty ability: "[+N]:", "[-N]:", "[0]:" then the effect
#: (RULE 606.5c). The bracket is the whole cost; the sign says add/remove.
_LOYALTY_LINE_RE = re.compile(r"^\s*\[\s*([+\-−]?)\s*(\d+)\s*\]\s*:\s*(?P<effect>.+)$", re.S)

#: A mana ability's effect ("add {g}", "add 1 mana of any color"): the engine
#: models these in `game/mana_abilities.py`, not through effect specs, so such a
#: line is *claimed* here (covered) but contributes no spec.
_MANA_EFFECT_RE = re.compile(r"^add\b", re.I)

#: Connectors that chain two effect clauses in one ability body, tried in this
#: order when the whole body isn't a single handled clause.
_CONNECTORS: tuple[str, ...] = (r"\.\s+", r";\s+", r",?\s+then\s+", r"\s+and\s+")

#: RULE 601.2b/604.3's additional-cost line: "As an additional cost to cast
#: this spell, <cost>." — instants/sorceries only (gated by
#: ``allow_spell_effect`` at the call site below, same as a bare imperative).
#: The wrapper is recognised here; the "<cost>" clause itself is a small
#: closed vocabulary (`_additional_cost_dict`) — anything outside it leaves
#: the whole line unclaimed (fail-closed), never a guessed/partial cost.
_ADDITIONAL_COST_LINE_RE = re.compile(
    r"^as an additional cost to cast this spell,\s*(?P<cost>.+?)\.?\s*$", re.IGNORECASE
)
_ADDITIONAL_COST_SACRIFICE_RE = re.compile(
    r"^sacrifice an?\s+(creature|artifact|land)$", re.IGNORECASE
)
_ADDITIONAL_COST_DISCARD_RE = re.compile(r"^discard an?\s+card$", re.IGNORECASE)
_ADDITIONAL_COST_PAY_LIFE_RE = re.compile(r"^pay\s+(x|\d+)\s+life$", re.IGNORECASE)


def _additional_cost_dict(text: str) -> Optional[dict[str, Any]]:
    """One additional-cost clause's closed vocabulary → its dict, or ``None``.

    Matches `AbilitySpec.additional_cost`'s shape exactly: ``{"sacrifice":
    "creature"|"artifact"|"land"}``, ``{"discard": 1}`` ("discard a card" is
    the only printed count in the pool), or ``{"pay_life": N|"x"}``.
    """
    text = text.strip().lower()
    sac = _ADDITIONAL_COST_SACRIFICE_RE.match(text)
    if sac is not None:
        return {"sacrifice": sac.group(1)}
    if _ADDITIONAL_COST_DISCARD_RE.match(text):
        return {"discard": 1}
    life = _ADDITIONAL_COST_PAY_LIFE_RE.match(text)
    if life is not None:
        amount = life.group(1)
        return {"pay_life": "x" if amount.lower() == "x" else int(amount)}
    return None


#: All keyword display names, lowercased, longest first — so a keyword-only
#: line can be recognised for the coverage gate ("flying, vigilance").
_KEYWORD_DISPLAYS: list[str] = sorted(
    (kdef.display.lower() for kdef in KEYWORDS.values()), key=len, reverse=True
)
_KEYWORD_TOKEN_RE = re.compile(
    r"^(?:" + "|".join(re.escape(d) for d in _KEYWORD_DISPLAYS) + r")\b.*$"
)


@dataclass
class Segment:
    """One ability's parse: either a spec (claimed) or the unclaimed raw text."""

    raw: str
    spec: Optional[AbilitySpec] = None
    claimed: bool = False
    #: True when the line is a pure keyword line (claimed elsewhere, by the
    #: keyword catalogue) — it contributes no effect spec here but *is* covered.
    keyword_line: bool = False


def _trigger_event(condition: str) -> Optional[str]:
    """Map a trigger condition phrase to an `EventType`, or ``None`` (fail-closed)."""
    for pattern, event in _TRIGGER_EVENTS:
        if pattern.search(condition):
            return event
    return None


def _trigger_condition(condition: str) -> Optional[dict[str, Any]]:
    """RULE 603.1's condition *subject* → the `AbilitySpec.trigger["condition"]` dict.

    Either ``{"subject": "self"}`` (this ability's own source only) or
    ``{"subject": "group", "type": ..., "controller": "you"|"any", "other":
    bool}`` (any matching battlefield object, e.g. a Soul-Warden-shaped
    "another creature you control enters"). ``None`` — fail-closed — for a
    condition phrase that isn't one of these two recognised shapes (e.g. "you
    cast a spell", a multi-event "enters or attacks", or anything RULE 603.1
    covers that this grammar doesn't yet model): the caller leaves the whole
    trigger unclaimed rather than binding a wrongly-scoped (or unscoped, i.e.
    over-firing) ability.
    """
    cond = condition.strip()
    if _SELF_SUBJECT_RE.match(cond):
        return {"subject": "self"}
    m = _GROUP_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "group",
            "type": m.group("type"),
            "controller": "you" if (m.group("you_a") or m.group("you_b")) else "any",
            "other": m.group("article") == "another",
        }
    return None


def parse_effect_body(body: str) -> Optional[list[EffectSpec]]:
    """A normalised effect ``body`` → its `EffectSpec`s, or ``None`` if unclaimed.

    Tries the whole body as one clause first (so a target phrase containing
    "or"/"and" isn't split), then falls back to splitting on effect connectors
    and parsing each part. Any unclaimed part fails the whole body (fail-closed:
    a partially-modeled ability is never emitted).
    """
    body = body.strip().rstrip(".").strip()
    if not body:
        return []

    direct = match_clause(body)
    if direct is not None:
        return direct

    for sep in _CONNECTORS:
        parts = [p for p in re.split(sep, body) if p.strip()]
        if len(parts) > 1:
            collected: list[EffectSpec] = []
            ok = True
            for part in parts:
                sub = parse_effect_body(part)
                if sub is None:
                    ok = False
                    break
                collected.extend(sub)
            if ok:
                return collected
    return None


def is_keyword_line(line: str) -> bool:
    """Whether ``line`` is only keyword abilities (comma-separated), for the gate."""
    tokens = [t.strip() for t in line.split(",") if t.strip()]
    if not tokens:
        return False
    return all(
        _KEYWORD_TOKEN_RE.match(tok) or re.match(r"^[a-z]+walk\b", tok)
        for tok in tokens
    )


def segment_line(
    line: str,
    *,
    allow_spell_effect: bool,
    provenance: ParserProvenance,
    is_saga: bool = False,
) -> Segment:
    """Parse one normalised ability ``line`` into a `Segment`.

    ``allow_spell_effect`` gates bare imperative clauses (no trigger wrapper)
    to instants/sorceries — a permanent's non-triggered imperative would be
    mis-modeled as a resolve-time effect, so for permanents it's left unclaimed
    (fail-closed) rather than turned into a `spell_effect`. ``is_saga`` gates
    the RULE 714 chapter-line grammar ("i, ii — <effect>") to actual Sagas, so
    the numeral-dash shape can't misfire on an unrelated card.
    """
    raw = line.strip()
    if not raw:
        return Segment(raw=raw, claimed=True)  # blank lines are trivially covered

    if is_keyword_line(raw):
        return Segment(raw=raw, claimed=True, keyword_line=True)

    # RULE 601.2b/604.3 additional cost — instants/sorceries only, and
    # checked before every other wrapper since it has neither a trigger word
    # nor a colon (so it can't be mistaken for one of those shapes below).
    if allow_spell_effect:
        add_cost = _ADDITIONAL_COST_LINE_RE.match(raw)
        if add_cost is not None:
            cost = _additional_cost_dict(add_cost.group("cost"))
            if cost is None:
                return Segment(raw=raw)  # unrecognised cost shape → unclaimed
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                additional_cost=cost,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

    # Saga chapter ability "i, ii — <effect>" (RULE 714.2d) — checked before
    # every other wrapper since it has neither a trigger word nor a colon.
    if is_saga:
        chap = CHAPTER_LINE_RE.match(raw)
        if chap is not None:
            chapters = parse_chapter_token(chap.group("chapters"))
            if chapters is None:
                return Segment(raw=raw)  # unrecognised numeral → unclaimed
            body, optional = _peel_optional(chap.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={"event": "SAGA_CHAPTER", "chapter": chapters},
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

    # Planeswalker loyalty ability "[±N]: <effect>" (RULE 606.5c) — its cost is
    # the bracket, so it's recognised before the generic activated case (whose
    # cost sniff wouldn't accept a bare "[+1]").
    loy = _LOYALTY_LINE_RE.match(raw)
    if loy is not None:
        magnitude = int(loy.group(2))
        delta = -magnitude if loy.group(1) in ("-", "−") else magnitude
        body, optional = _peel_optional(loy.group("effect").strip())
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)  # unrecognised loyalty effect → unclaimed
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost={"loyalty": delta},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    # Activated ability "<cost>: <effect>" — checked before the trigger/spell
    # cases since a colon unambiguously marks it (RULE 602.1). A trigger has no
    # colon, so this never steals one.
    act = _ACTIVATED_RE.match(raw)
    if act is not None and _COST_LOOKS_REAL.search(act.group("cost")):
        effect_text = act.group("effect").strip()
        if _MANA_EFFECT_RE.match(effect_text):
            # Mana ability — covered by the engine's mana model, no spec here.
            return Segment(raw=raw, claimed=True)
        body, optional = _peel_optional(effect_text)
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost={"text": act.group("cost").strip()},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    trig = _TRIGGER_RE.match(raw)
    if trig is not None:
        cond_text = trig.group("cond")
        event = _trigger_event(cond_text)
        if event is None:
            return Segment(raw=raw)  # unrecognised trigger → unclaimed
        condition = _trigger_condition(cond_text)
        if condition is None:
            return Segment(raw=raw)  # unrecognised subject scope → unclaimed (fail-closed)
        body, optional = _peel_optional(trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": event, "condition": condition},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    # No trigger wrapper. On a *permanent*, a standing "Creatures you control
    # get +1/+1" / "Goblins you control have haste" is a static continuous
    # ability (RULE 613), not a resolve-time effect — try that before giving up.
    if not allow_spell_effect:
        static = static_effect_specs(raw)
        if static is not None:
            spec = AbilitySpec(
                "static", effects=static, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        return Segment(raw=raw)  # permanent bare imperative → unclaimed

    # A resolve-time effect (instant/sorcery only).
    body, optional = _peel_optional(raw)
    effects = parse_effect_body(body)
    if effects is None:
        return Segment(raw=raw)
    spec = AbilitySpec(
        "spell_effect",
        effects=effects,
        optional=optional,
        raw_text=raw,
        parser=provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def _peel_optional(body: str) -> tuple[str, bool]:
    """Strip a leading "you may " and report whether it was present (RULE 601.2)."""
    m = re.match(r"^you may\s+(?P<rest>.+)$", body.strip(), re.S)
    if m is not None:
        return m.group("rest"), True
    return body.strip(), False
