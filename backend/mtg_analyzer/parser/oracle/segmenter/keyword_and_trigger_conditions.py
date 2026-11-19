"""Segmenter: keyword and trigger conditions (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional
from ..catalogue.object_trigger_head import legacy_group_condition, parse_object_trigger_head
from ..catalogue.spell_phrase import parse_spell_phrase
from ..catalogue.keywords import (
    ALIAS_DISPLAYS,
    CUMULATIVE_UPKEEP_DASH_RE,
    GIFT_QUALITIES,
    KEYWORDS,
    KeywordShape,
    cumulative_upkeep_dash_payable,
)
from ..catalogue.subgrammars import COLOR_WORD_ALT
from ..spec import AbilitySpec, EffectSpec, ParserProvenance
from .segment_types import Segment
from .trigger_heads import (
    ATTACHED_SUBJECT_RE,
    DAMAGED_BY_SOURCE_SUBJECT_RE,
    GOADED_SUBJECT_RE,
    OWN_GRAVEYARD_DIES_SUBJECT_RE,
    SELF_SUBJECT_RE,
    TRIGGER_EVENTS,
    VARIANT_TRIGGER_CONDITIONS,
    cast_spell_trigger_condition,
)
from .late import segment_line_unsplit


#: All keyword display names, lowercased, longest first — so a keyword-only
#: line can be recognised for the coverage gate ("flying, vigilance"). Also
#: includes alias spellings (`ALIAS_DISPLAYS` — "Multikicker", "Megamorph",
#: "Basic landcycling", "Partner with", …): `KEYWORDS` only holds the
#: canonical `_TABLE` row names, but a real oracle line may print the alias
#: spelling instead, and this check is a raw-text scan, not the
#: alias-resolving `keyword_slug`/`_resolve` lookup `parse_keywords` uses.
_KEYWORD_DISPLAYS: list[str] = sorted(
    [kdef.display.lower() for kdef in KEYWORDS.values()] + list(ALIAS_DISPLAYS),
    key=len,
    reverse=True,
)
_KEYWORD_TOKEN_RE = re.compile(
    # `(?![a-z0-9])` rather than `\b`: a display name ending in punctuation
    # ("Start Your Engines!", "For Mirrodin!") has no `\b` after its final
    # `!`, so `\b` wrongly rejected those whole keyword lines. The lookahead
    # still stops "fly" from matching inside "flyer".
    r"^(?:" + "|".join(re.escape(d) for d in _KEYWORD_DISPLAYS) + r")(?![a-z0-9]).*$"
)
#: Cycling's type-restricted variants ("Plainscycling", "Wizardcycling",
#: "Slivercycling", an unbounded land/creature-type family Scryfall mints one
#: name per type for) can't be listed exhaustively like `ALIAS_DISPLAYS`
#: above — matched the same way ``<type>walk`` is below instead.
_CYCLING_TOKEN_RE = re.compile(r"^(?:[a-z]+\s+)?[a-z]*cycling\b")

#: The closed set of keywords whose own parameter is itself comma-shaped —
#: Escape's "{cost}, Exile N other cards from your graveyard", Ward/Kicker's
#: non-mana fallback cost ("Pay 2 life", "Discard a creature card"), Partner
#: with's "<Name>, <Epithet>". Deliberately narrow (unlike the general
#: `_KEYWORD_TOKEN_RE`/`_CYCLING_TOKEN_RE` checks): a comma after *any*
#: keyword can't be assumed to continue that keyword's own clause (a
#: two-keyword line like "Flying, then draw a card" must still fail), so
#: only these known compound-parameter keywords get to swallow past a comma.
COMPOUND_PARAM_START_RE = re.compile(
    r"^(?:escape|ward|kicker|multikicker|partner with|friends forever)\b", re.IGNORECASE
)

# --- PAR-27: whole-line recognisers for keyword-only lines the comma-split
# token walk in `is_keyword_line` can't see -----------------------------------
# These match the *entire* line before it is ever split on commas, so a
# keyword ability whose own parameter contains commas ("Flashback—{1}{U},
# Pay 3 life.", "Protection from blue, from black, and from red", "Enchant
# creature, land, or planeswalker") is recognised as covered instead of
# dropping its card to UNMODELED over a formatting detail. Each pattern is
# anchored `^…$` and rejects `:` / a mid-line sentence period so it can never
# swallow a real ability body ("Boast — {1}{B}, Sacrifice a creature: …",
# "Flashback {8}{G}{G}. This spell costs {X} less …").

#: COST / NUMBER_COST keyword display words — the shapes whose parameter is a
#: cost and can therefore be a comma-joined "{mana}, <extra cost>" run.
_COST_KEYWORD_ALT = "|".join(
    re.escape(kdef.display.lower())
    for kdef in sorted(KEYWORDS.values(), key=lambda k: len(k.display), reverse=True)
    if kdef.shape in (KeywordShape.COST, KeywordShape.NUMBER_COST)
)
#: One component of a compound keyword cost. `:` and `.` are excluded from
#: every negated class so a match can never run past a cost into an ability
#: body or the next sentence.
_KW_COST_FRAG = (
    r"(?:\{[^}]+\}(?:\s*\{[^}]+\})*"          # a mana run
    r"|pay\s+[^,.:]*?(?:life|mana)"           # "pay 3 life", "pay half your life"
    r"|rounded\s+(?:up|down)"                 # tail of "pay half your life, rounded up"
    r"|discard\s+[^,.:]*?cards?(?:\s+at\s+random)?"
    r"|sacrifice\s+[^,.:]+"
    r"|exile\s+[^,.:]*?(?:cards?|creatures?|permanents?|lands?)[^,.:]*"
    r"|remove\s+[^,.:]*?counters?[^,.:]*"
    r"|collect\s+evidence\s+\d+"
    r"|behold\s+\d+\s+[a-z]+"
    r"|\{t\})"
)
_COMPOUND_COST_LINE_RE = re.compile(
    rf"^(?:{_COST_KEYWORD_ALT})\s*(?:[—-]\s*)?{_KW_COST_FRAG}"
    rf"(?:\s*,\s*{_KW_COST_FRAG})*\.?$",
    re.IGNORECASE,
)

#: "Protection from X, from Y, and from Z" / "Hexproof from A, B, and C"
#: (RULE 702.16 / 702.11b) — one keyword ability, comma-listed quality.
_MULTI_QUALITY_LINE_RE = re.compile(
    r"^(?:protection|hexproof)\s+from\s+[a-z][a-z ]*?"
    r"(?:,\s*(?:and\s+)?(?:from\s+)?[a-z][a-z ]*?)+\.?$",
    re.IGNORECASE,
)

#: "Enchant creature, land, or planeswalker" (RULE 702.5) — comma-listed
#: attachment restriction.
_ENCHANT_MULTI_LINE_RE = re.compile(
    r"^enchant\s+[a-z][a-z ]*?(?:,\s*(?:or\s+)?[a-z][a-z ]*?)+\.?$",
    re.IGNORECASE,
)

#: NUMBER-shape keywords printed with a variable "X" plus its defining clause
#: ("Firebending X, where X is the number of creatures you control.",
#: "Mobilize X, where X is …", "Devour X, where X is …"). The keyword stays
#: engine-inert either way (no binder reads a variable N), so recognising the
#: line only stops the card being UNMODELED for a formatting reason — exactly
#: as a plain "Firebending 2" is already claimed and inert.
_NUMBER_KEYWORD_ALT = "|".join(
    re.escape(kdef.display.lower())
    for kdef in sorted(KEYWORDS.values(), key=lambda k: len(k.display), reverse=True)
    if kdef.shape is KeywordShape.NUMBER
)
_VARIABLE_N_LINE_RE = re.compile(
    rf"^(?:{_NUMBER_KEYWORD_ALT})\s+x(?:,\s*where\s+x\s+is\s+[^.:]*)?\.?$",
    re.IGNORECASE,
)

#: "Companion — <deckbuilding restriction>" (RULE 702.139). Companion is a
#: pre-game action with no in-game rules effect (like Partner / Choose a
#: Background — see `catalogue/keywords.py`), so the labelled restriction is
#: claimed as an inert keyword line rather than left UNMODELED.
_COMPANION_LABEL_LINE_RE = re.compile(r"^companion\s*[—-]\s*\S.*$", re.IGNORECASE)

_COMPOUND_KEYWORD_LINE_RES: tuple[re.Pattern[str], ...] = (
    _COMPOUND_COST_LINE_RE,
    _MULTI_QUALITY_LINE_RE,
    _ENCHANT_MULTI_LINE_RE,
    _VARIABLE_N_LINE_RE,
    _COMPANION_LABEL_LINE_RE,
)


def is_compound_keyword_line(stripped: str) -> bool:
    """A keyword-only line whose own parameter contains commas (PAR-27)."""
    return any(rx.match(stripped) for rx in _COMPOUND_KEYWORD_LINE_RES)


#: RULE 702.174: "Gift a/an `<quality>`" — only the gifts the CR defines are a keyword line.
_GIFT_TOKEN_RE = re.compile(r"^gift an? (?P<quality>[a-z][a-z ]*?)\s*$", re.IGNORECASE)


#: PAR-245: "<keyword> abilities ..." / "<keyword> costs ..." opens a sentence about the keyword ("Exhaust abilities of other
#: permanents you control cost {2} less to activate.", "Flashback costs you pay cost {2} less."), never a keyword line itself.
#: `_KEYWORD_TOKEN_RE` only anchors the keyword word, so without this guard such a static was claimed as a bare keyword and
#: its cost change silently dropped.
_KEYWORD_SENTENCE_RE = re.compile(r"^[a-z-]+ (?:abilities|costs)\b")


#: BUG-62: a keyword line claims the keyword, its cost and its reminder text (stripped by `normalize`) and nothing else. A further
#: sentence ("Disguise {5}{R}. This cost is reduced by ...", Un-card joke text opening on the word "Sneak") is a rider that
#: `_KEYWORD_TOKEN_RE`'s greedy `.*$` would swallow while the card counted as MODELED.
_KEYWORD_LINE_SENTENCE_BREAK_RE = re.compile(r"\.\s+\S")

#: The riders a keyword line really carries, each read by `catalogue.keywords.parse_keywords` into the keyword's own parameter
#: (RULE 602.5b "Activate only once each turn" -> `once_per_turn` on equip/crew; RULE 702.62a "X can't be 0" -> suspend `min_x`).
#: Any other second sentence leaves the line unclaimed.
_CARRIED_KEYWORD_RIDER_RE = re.compile(
    r"^(?:(?:equip|crew)\b[^.]*\.\s*activate only once each turn\.?|suspend x\b[^.]*\.\s*x can(?:not|'t) be 0\.?)$",
    re.IGNORECASE,
)

#: RULE 702.74a Evoke's cost is a mana cost, or the Incarnation cycle's "Exile a <color> card from your hand" (RULE 702.74b),
#: the only non-mana evoke cost `catalogue.keywords` records. Any other dash cost (Cheer's "Celebrate an opponent") is a cost the
#: engine cannot pay, so the line stays unclaimed rather than becoming a free evoke.
_EVOKE_DASH_COST_RE = re.compile(
    rf"^evoke\s*[—-]\s*(?:exile an? (?:{COLOR_WORD_ALT}) card from your hand|\{{[^}}]+\}}(?:\s*\{{[^}}]+\}})*)\.?$",
    re.IGNORECASE,
)


def keyword_line_has_unmodeled_rider(stripped: str) -> bool:
    """BUG-62: whether ``stripped`` carries a sentence after the keyword that no keyword parameter represents."""
    if _KEYWORD_LINE_SENTENCE_BREAK_RE.search(stripped) is None:
        return False
    return _CARRIED_KEYWORD_RIDER_RE.match(stripped) is None


def is_keyword_token(tok: str) -> bool:
    # MEC-109: a cost-adjustment sentence is an ability, not a keyword line.
    if tok.startswith("blitz costs ") or _KEYWORD_SENTENCE_RE.match(tok):
        return False
    # BUG-62: an evoke cost the engine cannot pay is not a keyword line.
    if tok.startswith("evoke") and "—" in tok and _EVOKE_DASH_COST_RE.match(tok) is None:
        return False
    # BUG-64: a cumulative upkeep dash cost the engine cannot pay per age counter is not a keyword line.
    if tok.startswith("cumulative upkeep"):
        dash = CUMULATIVE_UPKEEP_DASH_RE.match(tok)
        if dash is not None and not cumulative_upkeep_dash_payable(dash.group("cost")):
            return False
    gift = _GIFT_TOKEN_RE.match(tok)
    if gift is not None and gift.group("quality").lower() not in GIFT_QUALITIES:
        # An un-card's "Gift a Rhystic Study": recognising the keyword would claim a gift the
        # engine cannot give, so the line stays unclaimed and the card UNMODELED.
        return False
    return bool(
        _KEYWORD_TOKEN_RE.match(tok)
        or _CYCLING_TOKEN_RE.match(tok)
        # RULE 702.14 landwalk, incl. the multi-word variants Scryfall names
        # ("legendary landwalk", "nonbasic landwalk", "snow forestwalk",
        # "snow-covered plainswalk") — the base rule was `^[a-z]+walk\b`.
        or re.match(r"^(?:[a-z-]+\s+)?[a-z-]*walk\b", tok)
        # RULE 702.48 "<type> offering" (Patron cycle) — the whole token is
        # "<Type> offering" and nothing else.
        or re.match(r"^[a-z]+\s+offering\s*$", tok)
    )


#: RULE 700.2's compact inline modal, in the one printed shape that is
#: genuinely ambiguous to the bulleted modal-block grammar: "<subject> gets
#: <P/T> **or** <P/T> [until end of turn]" (Pemmin's Aura, Freed from the
#: Real's family). Two full pump clauses sharing a subject and a duration,
#: written as one sentence — as opposed to every *other* " or " in an
#: effect body ("target artifact or enchantment", "Add {W} or {U}"), which
#: joins two nouns rather than two effects.
_INLINE_PT_MODAL_RE = re.compile(
    r"^(?P<prefix>.*?\bgets\s+)"
    r"(?P<a>[+-]\d+/[+-]\d+)\s+or\s+(?P<b>[+-]\d+/[+-]\d+)"
    r"(?P<suffix>.*)$",
    re.IGNORECASE,
)


def inline_pt_modal_bodies(body: str) -> Optional[list[str]]:
    """Split a compact "gets A or B" pump body into its two full clauses,
    or ``None`` when the body isn't that shape.

    Each half is rebuilt as a complete sentence (subject + one P/T +
    duration) so the ordinary pump handler reads it with no idea a modal
    was ever involved.
    """
    m = _INLINE_PT_MODAL_RE.match(body.strip())
    if m is None:
        return None
    prefix, suffix = m.group("prefix"), m.group("suffix")
    return [f"{prefix}{m.group('a')}{suffix}", f"{prefix}{m.group('b')}{suffix}"]


def trigger_event(condition: str) -> Optional[str]:
    """Map a trigger condition phrase to an `EventType`, or ``None`` (fail-closed)."""
    for pattern, event in TRIGGER_EVENTS:
        if pattern.search(condition):
            return event
    return None


def variant_trigger_event(condition: str) -> Any:
    """A RULE 9 variant trigger condition (a plane's planeswalk/chaos, a
    scheme's set-in-motion) → its `EventType`, a *list* of two for the
    compound plane template, or ``None`` for anything else."""
    cond = condition.strip()
    for pattern, event in VARIANT_TRIGGER_CONDITIONS:
        if pattern.match(cond):
            return list(event) if isinstance(event, list) else event
    return None


def trigger_condition(condition: str) -> Optional[dict[str, Any]]:
    """RULE 603.1's condition *subject* → the `AbilitySpec.trigger["condition"]` dict.

    Either ``{"subject": "self"}`` (this ability's own source only),
    ``{"subject": "attached_permanent"}`` (RULE 303.4/301.5's "enchanted/
    equipped creature", Acquired Mutation-shaped), ``{"subject": "group",
    "type": ..., "controller": "you"|"any", "other": bool}`` (any matching
    battlefield object, e.g. a Soul-Warden-shaped "another creature you
    control enters" — or, with ``"subtypes"``/``"nontoken"`` instead of
    ``"type"``, a tribal filter, The Ghoul Gunslinger-shaped "another
    nontoken Zombie or Mutant you control dies"), or ``{"subject":
    "self_or_group", ...}`` (the same group filter, but the ability's own
    source *also* qualifies — "~ or another <group> ..."). ``None`` —
    fail-closed — for a
    condition phrase that isn't one of these recognised shapes (e.g. "you
    cast a spell", a multi-event "enters or attacks", or anything RULE 603.1
    covers that this grammar doesn't yet model): the caller leaves the whole
    trigger unclaimed rather than binding a wrongly-scoped (or unscoped, i.e.
    over-firing) ability.
    """
    cond = condition.strip()
    if SELF_SUBJECT_RE.match(cond):
        return {"subject": "self"}
    if ATTACHED_SUBJECT_RE.match(cond):
        return {"subject": "attached_permanent"}
    m = OWN_GRAVEYARD_DIES_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "group", "type": m.group("type"), "nontoken": bool(m.group("nontoken")),
            "controller": "any", "owner": "you", "other": False,
        }
    # MEC-49 — "a creature dealt damage by ~ / enchanted creature this turn
    # dies" (before the composed group head below, which has no "dealt damage
    # by …" tail).
    dbs = DAMAGED_BY_SOURCE_SUBJECT_RE.match(cond)
    if dbs is not None:
        out = {
            "subject": "group",
            "type": "creature",
            "controller": "any",
            "other": False,
            "damaged_by_source_this_turn": True,
        }
        if dbs.group("by") == "enchanted creature":
            out["via_attached"] = True
        return out
    # Before the composed group head below: its "goaded" filter reads the live
    # object, where this row's keys read the DIES snapshot (RULE 400.7).
    m = GOADED_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "group",
            "type": m.group("type"),
            "controller": "any",
            "other": False,
            "goaded": True,
            "in_combat": bool(m.group("combat")),
        }
    # PAR-119: the four per-adjective group rows (`_GROUP_SUBJECT_RE`,
    # `_GROUP_SUBTYPE_SUBJECT_RE`, `_SELF_OR_GROUP_SUBJECT_RE`, `_SELF_OR_GROUP_SUBTYPE_RE`)
    # are the composed object head now, translated back into the flat keys they printed
    # (`object_trigger_head.legacy_condition`), so every spec they claimed is unchanged.
    # Its event must agree with `trigger_event`'s, which the caller pairs with it.
    composed = legacy_group_condition(cond)
    if composed is not None and composed[0] == trigger_event(cond):
        return composed[1]
    return None


def trigger_condition_dict(cond_text: str) -> Optional[dict[str, Any]]:
    """A finite trigger *condition* phrase (no body) → the `AbilitySpec.trigger`-shaped
    dict it would produce (``event``, ``condition``, extra keys), or ``None``.

    For a caller that needs the condition on its own — a trigger doubler's cause
    ("a creature you control attacks") — through the same three recognisers
    `segment_line` uses for an ordinary trigger: the per-adjective object
    subjects, then the composed object head (which owns the player events).
    """
    cond = cond_text.strip()
    event = trigger_event(cond)
    if event is not None:
        condition = trigger_condition(cond)
        if condition is not None:
            return {"event": event, "condition": condition}
    head = parse_object_trigger_head(cond)
    if head is not None:
        return {"event": head.event, "condition": head.condition, **head.trigger}
    cast = _CAST_HEAD_ONLY_RE.match(cond)
    if cast is not None:
        # PAR-236: a cast head inside a coordinated trigger ("a land you control enters from anywhere other than your
        # hand or you cast a spell from anywhere other than your hand"); re-segmented as its own line afterwards.
        keys = parse_spell_phrase(cast.group("phrase"))
        if keys is not None:
            return {"event": "SPELL_CAST", "condition": cast_spell_trigger_condition(cast.group("subj")), **keys}
    return None


_CAST_HEAD_ONLY_RE = re.compile(
    r"^(?P<subj>you|an opponent|a player|enchanted player) casts? (?P<phrase>(?:an?|another) .*\bspell\b.*)$"
)

#: RULE 603.2 events that one occurrence fires *together*: a dying permanent is also
#: put into a graveyard and also leaves the battlefield. Two compound heads on such a
#: pair would both trigger unless a zone tells them apart (`_compound_heads_disjoint`).
_CO_FIRING_EVENTS = frozenset({
    frozenset({"DIES", "PUT_INTO_GRAVEYARD"}), frozenset({"DIES", "LEAVES_BATTLEFIELD"}),
})


def _compound_heads_disjoint(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Whether no single event can satisfy both heads (so "A or B" triggers once)."""
    a, b = first.get("event"), second.get("event")
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if a != b:
        if frozenset({a, b}) not in _CO_FIRING_EVENTS:
            return True
        other = first if a != "DIES" else second
        if other.get("event") == "PUT_INTO_GRAVEYARD":
            origin = (other.get("filter") or {}).get("from_zone")
            # RULE 603.6c: "from anywhere other than the battlefield" (`from_zone_not`) excludes the dying permanent's
            # own arrival just as a named non-battlefield origin does -- "A is put into a graveyard from the
            # battlefield or B card is put into a graveyard from anywhere other than the battlefield" fires once.
            return (origin is not None and origin != "battlefield") or other.get("from_zone_not") == "battlefield"
        return other.get("to_zone") not in (None, "graveyard")
    # The same event: only "~ … or another … " names two disjoint objects.
    if a == "BECOMES_TARGET" and any((t.get("filter") or {}).get("is_player") for t in (first, second)):
        # RULE 115.1: a player target and an object target are different `BECOMES_TARGET` events (PAR-236).
        return not all((t.get("filter") or {}).get("is_player") for t in (first, second))
    subjects = {(first.get("condition") or {}).get("subject"),
                (second.get("condition") or {}).get("subject")}
    if subjects == {"self", "attached_permanent"}:
        # PAR-207: "~ or equipped creature deals combat damage" -- a permanent is never attached to itself
        # (RULE 301.5c / 303.4c), so the source and its host are two different objects and one event cannot
        # satisfy both heads.
        return True
    if subjects != {"self", "group"}:
        return False
    group = first if (first.get("condition") or {}).get("subject") == "group" else second
    return bool(group["condition"].get("other"))


#: The subjects a shared predicate may coordinate: the source and the permanent it is attached to.
_SHARED_PREDICATE_SUBJECTS_RE = re.compile(
    r"^(?P<a>~|equipped creature|enchanted creature) or (?P<b>equipped creature|enchanted creature|~) "
    r"(?P<predicate>(?:deals|attacks|blocks|dies|becomes|is) .+|attacks|blocks|dies)$"
)


#: PAR-236, RULE 115.1: "you or a permanent you control becomes the target of ..." names two kinds of target, a player
#: and a permanent. Each `BECOMES_TARGET` event is one target, so the two heads cannot both match one event and the
#: ability triggers once per target, as the rulings (Leovold, Rayne) say.
_COORDINATED_TARGET_SUBJECTS_RE = re.compile(
    r"^you or (?P<other>(?:a|an|another) .+?) becomes (?P<predicate>the target of .+)$"
)


_COORDINATED_VERB_HEADS: tuple[tuple["re.Pattern[str]", tuple[str, str]], ...] = (
    (re.compile(r"^you play a land or cast a spell from anywhere other than your hand$"),
     ("you play a land from anywhere other than your hand", "you cast a spell from anywhere other than your hand")),
    (re.compile(r"^you cast a spell from your graveyard or activate an ability of a card in your graveyard$"),
     ("you cast a spell from your graveyard", "you activate an ability of a card in your graveyard")),
)


def _compound_trigger_heads(cond: str) -> Optional[list[str]]:
    """RULE 603.1's coordinated trigger condition → its independent heads, or ``None``.

    Either two whole heads ("a creature dies or a creature card is put into a graveyard
    from a library" — Dreadhound; "~ dies or another artifact you control dies") or one
    subject with a second verb ("~ or another nontoken artifact you control dies or is
    put into exile from the battlefield" — Psychomancer). After "dies", a bare "is put
    into exile" is the battlefield departure it pairs with (Syr Vondam).
    """
    cond = cond.strip()
    # PAR-207: two subjects sharing one predicate -- "~ or equipped creature deals combat damage to a player" is
    # "~ deals ..." plus "equipped creature deals ...". Each half is validated as a head of its own below.
    # PAR-236: one origin tail over two verbs. "Play a land" and "cast a spell" are different events (RULE 305.1,
    # 601.2), so each half gets the tail and the ability triggers once per play or cast.
    for pattern, halves in _COORDINATED_VERB_HEADS:
        if pattern.match(cond):
            return list(halves)
    coordinated = _COORDINATED_TARGET_SUBJECTS_RE.match(cond)
    if coordinated is not None:
        halves = [f"you become {coordinated.group('predicate')}",
                  f"{coordinated.group('other')} becomes {coordinated.group('predicate')}"]
        triggers = [trigger_condition_dict(half) for half in halves]
        if all(t is not None for t in triggers) and _compound_heads_disjoint(*triggers):
            return halves
    shared = _SHARED_PREDICATE_SUBJECTS_RE.match(cond)
    if shared is not None:
        halves = [f"{shared.group('a')} {shared.group('predicate')}", f"{shared.group('b')} {shared.group('predicate')}"]
        triggers = [trigger_condition_dict(half) for half in halves]
        if all(t is not None and isinstance(t.get("event"), str) for t in triggers) and _compound_heads_disjoint(*triggers):
            return halves
    for sep in re.finditer(r",\s*(?:or\s+)?|\s+or\s+", cond):
        left, right = cond[:sep.start()], cond[sep.end():]
        first = trigger_condition_dict(left)
        if first is None or not isinstance(first.get("event"), str):
            continue
        candidates = [right]
        # RULE 603.1: coordinated verbs inherit the same object subject.
        # Validate each expansion with the ordinary head grammar rather than
        # enumerating attack/block/target phrase combinations. Internal "or"
        # in a subtype or "spell or ability" remains part of its own head.
        shared_tail = _SHARED_TAIL_RE.search(right)
        # A trailing phase/origin qualifier can qualify the entire verb list.
        # Do not broaden earlier verbs by attaching it to the final verb alone.
        # The established dies/exile union instead has an event-specific zone.
        inherit_subject = shared_tail is None or right.startswith("is put into exile")
        for boundary in reversed(list(re.finditer(r"\s+", left))) if inherit_subject else []:
            subject = left[:boundary.start()]
            verb = "is put into exile from the battlefield" if right == "is put into exile" else right
            candidates.append(f"{subject} {verb}")
        for second_text in candidates:
            second = trigger_condition_dict(second_text)
            # Recursion consumes at least one separator; subject restoration
            # cannot recurse on an equally large coordination expression.
            heads = [second_text] if second is not None and isinstance(second.get("event"), str) else (
                _compound_trigger_heads(second_text)
                if len(re.findall(r",|\s+or\s+", second_text))
                < len(re.findall(r",|\s+or\s+", cond)) else None
            )
            if heads is None:
                continue
            triggers = [first, *[trigger_condition_dict(head) for head in heads]]
            if any(trigger is None for trigger in triggers):
                continue
            if all(_compound_heads_disjoint(a, b)
                   for index, a in enumerate(triggers) for b in triggers[index + 1:]):
                return [left, *heads]
    return None


def compound_trigger_segment(
    raw: str, cond: str, body: str, *, allow_spell_effect: bool, provenance: ParserProvenance
) -> Optional[Segment]:
    """One ability per head of a compound "`<A>` or `<B>`" trigger, sharing its body —
    each re-segmented as its own line, so every head gets its own body reading."""
    heads = _compound_trigger_heads(cond)
    keyword = re.match(r"^(?:when|whenever)\b", raw)
    if heads is None or keyword is None:
        return None
    specs: list[AbilitySpec] = []
    for head in heads:
        part = segment_line_unsplit(
            f"{keyword.group(0)} {head}, {body}",
            allow_spell_effect=allow_spell_effect, provenance=provenance,
        )
        if not part.claimed or part.spec is None or part.keyword_line:
            return None
        part_specs = [part.spec, *part.extra_specs]
        # A trigger cap belongs to the one printed ability, not independently
        # to each event binding. No shared trigger-limit identity exists yet.
        if any((spec.trigger or {}).get("limit") for spec in part_specs):
            return None
        specs.extend(replace(spec, raw_text=raw) for spec in part_specs)
    return Segment(raw=raw, spec=specs[0], extra_specs=specs[1:], claimed=True)


#: A RULE 603.4 intervening-if / RULE 601.2b cost gate, as data (ENG-36).
#:
#: Fifteen of these were written out as fifteen near-identical ten-line
#: blocks in `parse_effect_body`: match a regex, recursively parse the
#: ``rest`` group, fail the whole body if that came back unclaimed, and
#: otherwise stamp one condition onto every spec it produced. The variable
#: part was always just *which condition* — so that is all a row carries.
#:
#: ``build`` returns a structured `game/effect_conditions.py` condition. The
#: engine still accepts the flat legacy spellings every shipped catalogue
#: entry uses, but nothing new needs to add a key to that flat vocabulary:
#: a new gate is a threshold or a referent on a predicate that already
#: exists, which is exactly what the structured form can say and the flat
#: one could not.
@dataclass(frozen=True)
class ConditionPrefix:
    #: Must expose a ``rest`` group — the effect text the gate applies to.
    #: An optional ``trailing`` group is a *second*, independently-gated
    #: sentence the same match swallowed (see
    #: `LIFE_GAINED_THIS_TURN_CONDITION_RE`), parsed separately and appended.
    pattern: "re.Pattern[str]"
    #: ``None`` means "this row matched but its condition phrase is outside
    #: the whitelisted vocabulary" — `peel_condition` then fails the body
    #: closed rather than emitting an ungated effect.
    build: "Callable[[re.Match[str]], Optional[dict[str, Any]]]"
    #: Rewrites the parsed params of each gated spec. Only Kicker needs it:
    #: an "X" inside a "was kicked" wrapper means Kicker's own announced {X}
    #: (`GameObject.kicker_x_paid`), a different sentinel from the spell's.
    rewrite_params: "Optional[Callable[[dict[str, Any], re.Match[str]], None]]" = None
    #: An alternative reading of the gated effect text, tried before the ordinary grammar; ``None`` from
    #: it means "no special reading". Called as ``parse_rest(rest, **parse_effect_body flags)``.
    parse_rest: "Optional[Callable[..., Optional[list[EffectSpec]]]]" = None


def rewrite_kicker_x(params: dict[str, Any], match: "re.Match[str]") -> None:
    """RULE 702.33b/PAR-17 — see `ConditionPrefix.rewrite_params`."""
    if match.group("kind").lower() == "bargained":
        return  # Bargain announces no {X} of its own
    for key, value in list(params.items()):
        if value == "x":
            params[key] = "kicker_x"


def kicked_condition(match: "re.Match[str]") -> dict[str, Any]:
    kind = match.group("kind").lower()
    if kind == "bargained":
        # RULE 601.2b, Beseech the Mirror — a different optional additional
        # cost, so a flag rather than Kicker's count.
        return {"kind": "flag", "flag": "bargained"}
    # "was kicked" and "was kicked twice" (RULE 702.34a Multikicker) are the
    # same quantity at two thresholds, which is one row now rather than the
    # two unrelated keys the flat vocabulary needed.
    return {"kind": "kicked", "min": 2 if "twice" in kind else 1}


#: Gates peeled **before** `match_clause` and the connector split, in the
#: order they were tried before. Order still matters between rows whose
#: patterns could both match a body, which is why it is preserved verbatim.


#: PAR-119: RULE 603.1 lets one ability print two independent trigger
#: conditions sharing a body — "when X and whenever Y, Z" is "when X, Z" *and*
#: "whenever Y, Z". Each half is a whole ordinary trigger, so it is parsed as one
#: (the halves stop at the first comma, which is where the body begins).
_COMPOUND_TRIGGER_RE = re.compile(
    r"^(?P<kw>when|whenever|at) (?P<cond>[^,]+?),\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)
_COMPOUND_AND_RE = re.compile(r" and (?P<kw>when|whenever|at) ", re.IGNORECASE)
_COMPOUND_OR_RE = re.compile(r" or ", re.IGNORECASE)


_SHARED_TAIL_RE = re.compile(r"\b(?:from|during|for the first time|this turn)\b")


def compound_candidates(line: str) -> "list[tuple[str, str]]":
    """Every way to read one trigger line as two independent trigger lines sharing its body
    (RULE 603.2): "when X and whenever Y, Z" / "when X and at the beginning of Y, Z" split at
    the second keyword, "whenever X or Y, Z" at an "or" — each half keeps the keyword and the
    body, and the caller keeps only a split whose halves both parse as whole triggers."""
    m = _COMPOUND_TRIGGER_RE.match(line.strip())
    if m is None:
        return []
    kw, cond, body = m.group("kw"), m.group("cond"), m.group("body")
    out: "list[tuple[str, str]]" = []
    for sep in _COMPOUND_AND_RE.finditer(cond):
        out.append((f"{kw} {cond[:sep.start()]}, {body}", f"{sep.group('kw')} {cond[sep.end():]}, {body}"))
    for sep in _COMPOUND_OR_RE.finditer(cond):
        left, right = cond[:sep.start()], cond[sep.end():]
        if _SHARED_TAIL_RE.search(right):
            # "you play a land or cast a spell **from anywhere other than your hand**": the tail
            # qualifies both verbs, so the right half alone is a different (broader) trigger
            # for the left one — no faithful split exists without distributing it.
            continue
        out.append((f"{kw} {left}, {body}", f"{kw} {right}, {body}"))
        if left.startswith("you "):
            # "you play a land or cast a spell": the second verb keeps the first one's subject.
            out.append((f"{kw} {left}, {body}", f"{kw} you {right}, {body}"))
    return out


#: PAR-124 (RULE 603.7a): a spell's "Whenever <event> this turn, <effect>" / "Until end
#: of turn, whenever <event>, <effect>" creates a triggered ability that lasts the turn —
#: it is not a permanent's ability, so it must not be parsed as one.
TURN_TRIGGER_RE = re.compile(
    r"^(?:until end of turn,\s*(?P<kw1>whenever|when)\s+(?P<cond1>[^,]+?)"
    r"|(?P<kw2>whenever|when)\s+(?P<cond2>[^,]+?)\s+this turn),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: "when you next cast an instant or sorcery spell this turn" — the one-shot variant.
NEXT_CAST_RE = re.compile(r"\byou next cast\b")


#: PAR-124: "When **target creature** dies this turn, return that card to
#: the battlefield under its owner's control." (Graceful Reprieve) — the
#: chosen RULE 115 target, not a group condition, is the trigger's own
#: subject: `turn_trigger_segment` rewrites this to the ordinary
#: self-subject phrasing ("~ `<verb>`") before the inner `segment_line`
#: call, and stamps `target_kind="creature"` on the outer `create_turn_
#: trigger` spec so `CreateTurnTriggerEffect` binds the ability with the
#: chosen object itself as its source (see that class's own docstring).
TARGET_CREATURE_SUBJECT_RE = re.compile(r"^target creature (?P<verb>.+)$", re.IGNORECASE)

#: PAR-102: "Target creature gets +2/+0 until end of turn. When **that creature** dies this turn, …" — the
#: subject is the creature the *preceding clause* chose, so it is only read as such when the caller says
#: a previous clause did (`previous_subject`); otherwise "that creature" names nothing and stays unclaimed.
#: PAR-160: "the creature" is the same referent when worded that way (Phantasmal Mount's second rider).
THAT_CREATURE_SUBJECT_RE = re.compile(
    r"^(?:that creature|the creature|it) (?P<verb>(?:dies|leaves the battlefield|attacks(?: the monarch)?"
    r"|becomes blocked|deals combat damage to a player(?: or planeswalker)?))$", re.IGNORECASE,
)
#: PAR-286 (RULE 603.7c): "Whenever **a creature [you control] dealt damage this way** dies this turn, <effect>" -- the
#: creatures the preceding damage clause hit (`GameContext.damaged_this_way`). Rewritten to the plain group head
#: ("a creature [you control] dies") with the watched set stamped on the `create_turn_trigger` (`damaged_this_way`).
DEALT_DAMAGE_THIS_WAY_SUBJECT_RE = re.compile(
    r"^(?P<subject>a creature(?: you control)?) dealt damage this way dies$", re.IGNORECASE,
)
#: PAR-160: "When **~** leaves the battlefield this turn, sacrifice **that creature**." — the trigger is the
#: source's own and the body names the creature an earlier clause chose (`previous_subject`), baked in at creation.
SOURCE_LEAVES_RE = re.compile(r"^~ (?:dies|leaves the battlefield)$", re.IGNORECASE)
