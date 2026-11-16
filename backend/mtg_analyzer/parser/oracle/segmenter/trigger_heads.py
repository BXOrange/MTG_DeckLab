"""Segmenter: trigger heads (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from ..catalogue.clause_reading import ClauseReading, STANDALONE
from dataclasses import replace
from typing import Any, Optional
from ..catalogue.clause_primitives import TARGET_PARAM_KEYS, TRIGGER_ONCE_PER_TURN_MARKER
from ..catalogue.effect_rows.shared import base_verb
from ..spec import AbilitySpec, EffectSpec, ParserProvenance
from .segment_types import Segment
from .optional_peel import peel_optional
from .late import parse_effect_body

#: RULE 603.1's object-subject trigger *verbs*, longest phrase first, each
#: mapped to the `EventType` the engine actually fires for it. **One table**
#: feeding everything below — `TRIGGER_EVENTS` (which verb a condition
#: names), `_VERB_EVENTS` (the compound "<verb> or <verb>" shape) and the
#: verb alternation every subject regex shares — so widening the vocabulary
#: is a single edit here rather than six regexes drifting apart.
#:
#: Each entry earns its place by pointing at an event the engine fires with
#: an ``instance_id`` naming the object the condition is about, which is what
#: `effect_binder._subject_condition` scopes on; a verb with no such event
#: stays out and its cards stay `UNMODELED` (fail-closed). "Becomes
#: untapped" used to be the canonical example of this — `EventType.UNTAP`
#: was fired once per untap *step*, keyed by player, never per permanent —
#: until MEC-43 round 4E (Mesmeric Orb) widened `RulesEngine.set_tapped`
#: (the untap direction's own choke point, mirroring the already-per-
#: permanent `TAPPED`) into every real untap route and gave it its own
#: `EventType.UNTAPPED`, so the row now belongs below like any other.
#: ("Becomes monstrous" is *not* absent — RULE 701.37a's own
#: `BECAME_MONSTROUS` row sits below with the rest of this table; an earlier
#: version of this comment listed it here by mistake.)
_TRIGGER_VERBS: tuple[tuple[str, str], ...] = (
    # RULE 506.5's "attacks **alone**" comes first: the bare "attacks" row
    # would otherwise claim it and silently drop the "alone" qualifier (a
    # strictly wrong, over-firing trigger). Its own aggregate event, fired
    # once combat locks in — see `EventType.ATTACKS_ALONE`.
    ("attacks alone", "ATTACKS_ALONE"),
    ("becomes attached to a creature", "ATTACHED_TO_CREATURE"),
    # RULE 708.8: "when ~ is turned face up" — the morph/megamorph/disguise
    # trigger family (`game/face_down.py`), and the single largest verb the
    # engine could already fire but the grammar couldn't name.
    ("is turned face up", "TURNED_FACE_UP"),
    # RULE 603.6c: "when ~ leaves the battlefield" — matched before "enters"
    # can't be an issue (different verb), but the trailing "the battlefield"
    # is part of the phrase here, unlike "enters the battlefield".
    ("leaves the battlefield", "LEAVES_BATTLEFIELD"),
    # RULE 509.5: "whenever ~ becomes blocked" — the attacker-side event,
    # distinct from "blocks" (the blocker's own).
    ("becomes blocked", "BECOMES_BLOCKED"),
    # RULE 701.21b: "whenever ~ becomes tapped".
    ("becomes tapped", "TAPPED"),
    # RULE 701.22/603.2: "whenever ~ becomes untapped" (Mesmeric Orb,
    # MEC-43 round 4E) — matched before the bare "becomes tapped" row
    # can't be an issue (different adjective — "un"tapped vs "tapped" are
    # different words entirely, not a prefix relationship), listed right
    # after it for readability.
    ("becomes untapped", "UNTAPPED"),
    # RULE 702.140c: "whenever this creature mutates".
    ("mutates", "MUTATES"),
    # RULE 701.37a: "when ~ becomes monstrous" — the trigger half of the
    # monstrosity family, and the one that carries most of those cards
    # (the activated ability alone is rarely the whole text). Matched
    # before the bare "becomes tapped"/"becomes blocked" rows can't be an
    # issue (different adjective), but it sits with them for readability.
    ("becomes monstrous", "BECAME_MONSTROUS"),
    # RULE 605.1: "whenever enchanted land is tapped for mana" (Wild Growth) — `GameEngine.tap_for_mana` fires
    # `TAPPED_FOR_MANA` with the land's own ``instance_id``, so the self/attached subject scopes as for any verb.
    ("is tapped for mana", "TAPPED_FOR_MANA"),
    ("enters", "ENTERS_BATTLEFIELD"),
    # RULE 700.4's expanded spelling of "dies".  The condition grammar
    # below additionally verifies the owner-relative "your graveyard"
    # scope, so this event recognition cannot over-claim a generic zone move.
    ("is put into your graveyard from the battlefield", "DIES"),
    ("dies", "DIES"),
    ("attacks", "ATTACKS"),
    ("blocks", "BLOCKS"),
)

#: Trigger phrase → `EventType` value (mirrors `models/events.py`). Conservative
#: on purpose: only the events the engine actually fires and the binder can wire.
#: Anything not here leaves the ability unclaimed → its card stays `UNMODELED`
#: (docs/09 fail-closed), never a wrong trigger. Order is `_TRIGGER_VERBS`'
#: order, which is why the longest phrases sit first.
TRIGGER_EVENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(verb) + r"\b"), event) for verb, event in _TRIGGER_VERBS
]

#: The same verbs as a plain phrase → `EventType` dict, for the compound
#: "~ enters or attacks" shape below (`SELF_MULTI_EVENT_RE`) — kept
#: separate from `TRIGGER_EVENTS`' regex/event pairs since that list is
#: matched by `.search()` (first hit wins, order matters for a single-verb
#: condition) while this one needs an exact per-verb lookup instead.
_VERB_EVENTS: dict[str, str] = {verb: event for verb, event in _TRIGGER_VERBS}

#: The verb alternation every RULE 603.1 subject regex below shares, in
#: `_TRIGGER_VERBS` order so a longer phrase always wins over a prefix of it.
_VERB_ALT = "|".join(re.escape(verb) for verb, _ in _TRIGGER_VERBS)

#: RULE 603.1's compound "~ <verb> or <verb>" trigger condition (The Wise
#: Mothman: "Whenever The Wise Mothman enters or attacks, ...") — two
#: *different* firing events for the same self-subject ability, not the
#: single-event shape `trigger_event`/`trigger_condition` handle (a bare
#: "~ enters or attacks" fails `SELF_SUBJECT_RE`'s anchored single-verb
#: match today, so it already fails closed rather than silently binding
#: just the first verb — this is real, additional recognition, not a bugfix).
#: Self-subject only (no real card needs a "group"/"attached_permanent"
#: compound-event trigger yet); `AbilitySpec.trigger["event"]` becomes a
#: *list* of two `EventType` strings instead of one, and `effect_binder.
#: bind_ability` builds one `TriggeredAbility` per listed event, each with
#: its own freshly-bound effects (never sharing effect instances across the
#: two abilities).
#: RULE 701.27f: "transforms into ~" is a self-subject firing condition with
#: no bare-verb spelling — it always names the face transformed *into* (a
#: DFC front face, folded to "~" by `normalize`). The `TRANSFORMED` engine
#: event (fired by `RulesEngine.transform_permanent`) carries the object's
#: own `instance_id`, so `_SUBJECT_EVENT_KEYS`' default self scoping matches
#: it exactly like `ENTERS_BATTLEFIELD`; the face-name gate is implicit —
#: the trigger only *exists* on the object while it's that face (abilities
#: are rebound per face).
_MULTI_EVENT_VERB_ALT = _VERB_ALT + r"|transforms into ~"
_MULTI_EVENT_EXTRA = {"transforms into ~": "TRANSFORMED"}
SELF_MULTI_EVENT_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|land|permanent|equipment))\s+"
    rf"(?P<v1>{_MULTI_EVENT_VERB_ALT})(?:\s+the\s+battlefield)?"
    r"\s+or\s+"
    rf"(?P<v2>{_MULTI_EVENT_VERB_ALT})(?:\s+the\s+battlefield)?$"
)


def multi_event_name(token: str) -> str:
    return _MULTI_EVENT_EXTRA.get(token.lower(), _VERB_EVENTS.get(token.lower(), ""))


#: "When ~ enters **and at the beginning of your first main phase**, …"
#: (Crack in Time — a Vanishing enchantment that re-exiles each of its own
#: upcoming main phases). Two firing conditions with *different* triggers:
#: a self-subject `ENTERS_BATTLEFIELD` and a controller-scoped `STEP_BEGIN`
#: filtered to the precombat main step — handled the same one-spec-per-event
#: way as `VARIANT_TRIGGER_CONDITIONS`' compound plane template, since the
#: phase half's `{"step": …}` filter can't ride the enters half's payload.
ENTERS_AND_MAIN_PHASE_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|permanent))\s+enters"
    r" and at the beginning of your (?:first main phase|precombat main phase)$",
    re.IGNORECASE,
)

#: RULE 9's casual-variant trigger conditions — the fixed phrasings a plane
#: (RULE 901) and a scheme (RULE 904) share, which no object-verb grammar
#: above can express because their subject is the *player* ("when **you**
#: planeswalk to ~") while the ability still belongs to the card named.
#: Matched against the *condition* text `TRIGGER_RE` peels out — i.e. with
#: the leading "when"/"whenever" already stripped, the same text
#: `trigger_event`/`trigger_condition` see.
#: Each maps to one `EventType` and needs no subject scoping: only the
#: face-up plane's own abilities are ever collected in the first place
#: (`game/variants.py`'s `command_zone_ability_sources`), so "this plane" is
#: the only plane there is.
#:
#: The compound "when you planeswalk to ~ **and at the beginning of your
#: upkeep**" is the single commonest plane template (22 of 207), and is two
#: firing conditions — handled the same way `SELF_MULTI_EVENT_RE` handles
#: "~ enters or attacks": `AbilitySpec.trigger["event"]` becomes a list, and
#: the binder builds one ability per event. Its upkeep half needs no
#: `phase_relation`: a plane's controller is whoever last planeswalked to it,
#: and the upkeep meant is theirs.
VARIANT_TRIGGER_CONDITIONS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (
        re.compile(
            r"^you planeswalk (?:to (?:~|this plane)|here)"
            r" and at the beginning of your upkeep$"
        ),
        ["PLANESWALKED_TO", "STEP_BEGIN"],
    ),
    (
        re.compile(r"^you planeswalk (?:to (?:~|this plane)|here)$"),
        "PLANESWALKED_TO",
    ),
    (
        re.compile(r"^you planeswalk away from (?:~|this plane)$"),
        "PLANESWALKED_AWAY",
    ),
    # RULE 901.17: a phenomenon's own wording for "you planeswalked to me" —
    # same event, since encountering one *is* planeswalking to it.
    (
        re.compile(r"^you encounter (?:~|this phenomenon|this)$"),
        "PLANESWALKED_TO",
    ),
    (re.compile(r"^chaos ensues$"), "CHAOS_ENSUED"),
    (
        re.compile(r"^you set this scheme in motion$"),
        "SCHEME_SET_IN_MOTION",
    ),
)


#: A triggered-ability wrapper: "When/Whenever/At <condition>, <body>".
#: PAR-139: a comma inside the *condition* when it continues a noun-phrase list — "whenever you discard a
#: noncreature, nonland card, draw a card" and "whenever you discard an island, pirate, or vehicle card, …":
#: a comma followed by "non…", or by further list items ending in "card(s)"/"creature(s)"/… before the
#: separator that really starts the body. A body such as "draw a card" has no list separator, so it never
#: reads as list items.
_TRIGGER_LIST_NOUN = r"(?:cards?|creatures?|permanents?|artifacts?|enchantments?|lands?|spells?)"
TRIGGER_RE = re.compile(
    r"^(?:when|whenever|at)\b(?P<cond>(?:[^,]|,\s+(?=non[a-z]+\b)"
    rf"|,\s+(?=(?:[a-z'-]+(?:,\s+(?:or\s+)?|\s+or\s+))+[a-z'-]+ {_TRIGGER_LIST_NOUN}\b)"
    rf"|,\s+(?=or\s+[a-z'-]+ {_TRIGGER_LIST_NOUN}\b)"
    rf"|,\s+(?=(?:or\s+)?(?:{_MULTI_EVENT_VERB_ALT}|becomes the target)\b))*),\s*(?P<body>.+)$",
    re.S,
)

#: RULE 603.2's other printed spelling of the once-per-turn cap (PAR-14) —
#: an inline qualifier on the trigger *condition* itself ("whenever you
#: surveil **for the first time each turn**", Whispering Snitch) rather
#: than `TRIGGER_ONCE_PER_TURN_MARKER`'s trailing-sentence-in-the-body
#: shape. Stripped once, right off ``cond_text``, before any of the
#: condition-family dispatch below (self/group/player/variant) — the
#: suffix appears across every one of those subject shapes ("~ attacks",
#: "you gain life", "1 or more counters are put on ~", …), so catching it
#: here means every family gets `AbilitySpec.trigger["limit"]` for free
#: rather than needing its own copy of this regex.
ONCE_PER_TURN_CONDITION_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)\s+for the first time each turn$", re.IGNORECASE
)


def strip_trigger_once_per_turn_marker(effects: list[EffectSpec]) -> tuple[list[EffectSpec], bool]:
    """Split `TRIGGER_ONCE_PER_TURN_MARKER` (PAR-14's trailing "This ability
    triggers only once each turn." sentence) out of a parsed effect body,
    returning the remaining real effects and whether the marker was present.
    Mirrors `effect_binder.bind_ability`'s marker-then-strip idiom for
    activated-ability markers, just done here since `AbilitySpec.trigger`
    (where this one lands, as ``"limit"``) is assembled in this module, not
    the binder.
    """
    remaining = [e for e in effects if e.type != TRIGGER_ONCE_PER_TURN_MARKER]
    found = len(remaining) != len(effects)
    # PAR-175: "you may X. If you do, Y. This ability triggers only once each turn." reads as one `optional` whose
    # body swallowed the trailing sentence; the limit belongs to the trigger, not to the yes/no, so hoist it out.
    unwrapped: list[EffectSpec] = []
    for effect in remaining:
        inner = effect.params.get("effects") if effect.type == "optional" else None
        if isinstance(inner, list) and any(
            isinstance(e, dict) and e.get("type") == TRIGGER_ONCE_PER_TURN_MARKER for e in inner
        ):
            found = True
            effect = replace(effect, params={**effect.params, "effects": [
                e for e in inner if not (isinstance(e, dict) and e.get("type") == TRIGGER_ONCE_PER_TURN_MARKER)
            ]})
        unwrapped.append(effect)
    return unwrapped, found

#: RULE ~702.156-ish "ability word" Magecraft — "Magecraft — Whenever you
#: cast or copy an instant or sorcery spell, <effect>." (Professor Onyx/
#: Witherbloom Apprentice-shaped). A dedicated whole-line recognizer rather
#: than the generic `TRIGGER_RE`/`trigger_event`/`trigger_condition`
#: grammar, since: (1) the "Magecraft — " label (an ability word, RULE
#: 207.2c — no rules meaning of its own) needs peeling before the sentence
#: even looks like an ordinary "whenever ..." trigger; (2) "cast or copy" is
#: two alternate firing conditions the single-event `AbilitySpec.
#: trigger["event"]` shape can't express directly — this binds only the
#: "cast" half (`EventType.SPELL_CAST`). The engine has no general
#: spell-copy event bus at all yet (a real, separate, cross-cutting gap —
#: nothing in the engine can currently produce a spell copy in the first
#: place — tracked in BACKLOG.md), so the missing "copy" branch is
#: unreachable by any game state the engine can currently produce, not a
#: silently wrong one. ``spell_subtype_any`` (an existing `effect_binder`
#: trigger predicate, built for "cast an Aura/Equipment/Vehicle spell"
#: triggers but equally valid here since it just substring-matches the
#: printed type line) narrows the cast spell to instant/sorcery.
MAGECRAFT_RE = re.compile(
    r"^magecraft\s*—\s*whenever you cast or copy an instant or sorcery spell,\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 701.42a Meld, phase-trigger form: "At the beginning of <phase>, if
#: you both own and control ~ and a[n] <type> named <X>, exile them, then
#: meld them into <Y>." (Gisela, the Broken Blade — your end step; Graf Rats
#: — combat on your turn). A dedicated whole-line recognizer, like
#: `MAGECRAFT_RE`, because the "if you both own and control … and a
#: creature named …" gate is meld-specific and the partner/result names
#: carry commas. The RULE 603.4 intervening-if is dropped: `MeldEffect`
#: re-checks own+control of the named partner at resolution and fails
#: closed, so the board outcome is identical. Titania's own extra
#: "if there are N land cards in your graveyard and …" prefix deliberately
#: doesn't match here (a compound condition of its own).
MELD_TRIGGER_RE = re.compile(
    r"^at the beginning of (?:your )?(?P<step>upkeep|draw|end|combat)"
    r"(?: step| on your turn)?, if you both own and control ~ and "
    r"(?:an?|the) (?:creature|land|artifact|permanent) named (?P<partner>.+?), "
    r"exile them, then meld them into (?P<result>.+?)\.?$",
    re.IGNORECASE,
)
ATTACK_MELD_TRIGGER_RE = re.compile(
    r"^whenever you attack, (?P<before>.+?)\. if ~ and a creature named "
    r"(?P<partner>.+?) are attacking, and you both own and control them, exile them, "
    r"then meld them into (?P<result>.+?)\. it enters tapped and attacking\.?$",
    re.IGNORECASE,
)


def cast_spell_trigger_condition(subj: str) -> dict[str, Any]:
    """``{"subject": …}`` for a cast-spell/draw-card trigger's ``you``/``an
    opponent``/``a player`` subject — shared by the composed cast head
    (`CAST_TRIGGER_COMPOSED_RE`), `DRAW_TRIGGER_PLAIN_RE` and the remaining
    bespoke cast rows, so the three-way mapping lives in exactly one place."""
    subj = subj.lower()
    if subj == "you":
        return {"subject": "you"}
    if subj == "an opponent":
        return {"subject": "group", "controller": "not_you"}
    if subj == "enchanted player":
        # RULE 303.4: a Curse is attached to a *player*; only that player's casts count (`binding.core._subject_condition`).
        return {"subject": "player", "scope": "enchanted"}
    return {"subject": "group"}

#: PAR-119: the composed cast-trigger head — actor + "cast" + a spell phrase
#: that `catalogue.spell_phrase.parse_spell_phrase` builds from shared word
#: tables (characteristic adjectives, ``with`` qualifiers, cast-from zone,
#: ownership, targets). One row for what used to be one regex *and* one ~25-line
#: dispatch block per adjective combination. PAR-131 retired those rows
#: (`_CAST_SPELL_TRIGGER_RE`, `_NEG_`, `_PLAIN_`, `_MV_`, `_HISTORIC_`, …): this
#: head now owns every plain "you/an opponent/a player cast(s) a <phrase> spell".
CAST_TRIGGER_COMPOSED_RE = re.compile(
    r"^(?:whenever|when) (?P<subj>you|an opponent|a player|enchanted player) casts? "
    r"(?P<copies>or (?:copy|copies) )?"
    # PAR-104: a comma list of card types ("an artifact, instant, or sorcery spell") is part of the phrase.
    r"(?P<phrase>(?:an?|another|your|their) (?:(?:[a-z'-]+, )+or [a-z'-]+ |[^,]*?)\bspell\b[^,]*),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def cast_trigger_segment(
    raw: str, subj: str, trigger_keys: dict[str, Any], body_text: str, provenance: ParserProvenance
) -> Segment:
    """The one dispatch for a `SPELL_CAST` trigger whose head is already parsed
    into ``trigger_keys``: optional peel, the two-rider mana-spent shape, the
    intervening "if at least N mana was spent", then the body."""
    body, optional = peel_optional(body_text)
    trigger = {
        "event": "SPELL_CAST",
        "condition": cast_spell_trigger_condition(subj),
        **trigger_keys,
    }
    two_rider_parts = _cast_mana_two_rider_parts(body, reading=ClauseReading(self_subject=True))
    if two_rider_parts is not None:
        base_effects, riders = two_rider_parts
        base_spec = AbilitySpec("triggered", effects=base_effects, trigger=trigger,
            optional=optional, raw_text=raw, parser=provenance)
        rider_specs = [
            AbilitySpec("triggered", effects=effects,
                trigger={**trigger, "spell_mana_spent_at_least": threshold}, optional=optional,
                raw_text=raw, parser=provenance)
            for threshold, effects in riders
        ]
        return Segment(raw=raw, spec=base_spec, extra_specs=rider_specs, claimed=True)
    rider_parts = _cast_mana_rider_parts(body, reading=ClauseReading(self_subject=True))
    if rider_parts is not None:
        base_effects, threshold, rider_effects, replaces = rider_parts
        if replaces:
            low = AbilitySpec("triggered", effects=base_effects,
                trigger={**trigger, "spell_mana_spent_less_than": threshold}, optional=optional,
                raw_text=raw, parser=provenance)
            high = AbilitySpec("triggered", effects=rider_effects,
                trigger={**trigger, "spell_mana_spent_at_least": threshold}, optional=optional,
                raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=low, extra_specs=[high], claimed=True)
        base_spec = AbilitySpec("triggered", effects=base_effects, trigger=trigger,
            optional=optional, raw_text=raw, parser=provenance)
        rider_spec = AbilitySpec("triggered", effects=rider_effects,
            trigger={**trigger, "spell_mana_spent_at_least": threshold}, optional=optional,
            raw_text=raw, parser=provenance)
        return Segment(raw=raw, spec=base_spec, extra_specs=[rider_spec], claimed=True)
    body, mana_spent_at_least = _peel_spell_mana_spent_at_least(body)
    effects = _counter_triggering_spell_effects(body) or parse_effect_body(body, reading=ClauseReading(self_subject=True))
    if effects is None:
        return Segment(raw=raw)
    # RULE 603.2: "This ability triggers only once each turn." (Basim Ibn Ishaq).
    effects, body_limit = strip_trigger_once_per_turn_marker(effects)
    if not effects:
        return Segment(raw=raw)
    if body_limit:
        trigger = {**trigger, "limit": True}
    if mana_spent_at_least is not None:
        trigger = {**trigger, "spell_mana_spent_at_least": mana_spent_at_least}
    spec = AbilitySpec("triggered", effects=effects, trigger=trigger,
        optional=optional, raw_text=raw, parser=provenance)
    return Segment(raw=raw, spec=spec, claimed=True)


CAST_TWO_COLOR_SPELL_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell that'?s both "
    r"(?P<c1>white|blue|black|red|green) and (?P<c2>white|blue|black|red|green),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-79 sixth increment: "…, if at least N mana was spent to cast
#: it/that spell, `<effect>`" (Sahagin) — a RULE 603.4 intervening-if on a
#: cast trigger's own body, reading `effect_binder`'s new
#: `spell_mana_spent_at_least` predicate (the *spent*-mana sibling of
#: `spell_mana_value_at_least`, `game/binding/core.py`). A shared peel
#: function rather than a dedicated whole-line regex per cast-trigger
#: filter combination (`COUNTER_FREE_SPELL_RE`'s own "no mana spent"
#: shape is exactly the one-regex-per-combination pattern
#: handler-recipe.md's decomposition rule warns against) — wired into
#: whichever cast-trigger dispatch a real card needs it on, same
#: "extend as a real card needs it" convention as `_FILTER_KEYWORD_WORDS`.
_SPELL_MANA_SPENT_AT_LEAST_IF_RE = re.compile(
    r"^if at least (?P<n>\d+) mana was spent to cast (?:it|that spell),\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

ADAMANT_MANA_SPENT_IF_RE = re.compile(
    r"^if at least (?P<n>\d+) (?P<color>white|blue|black|red|green|colorless) mana was spent to cast "
    r"(?:it|this spell),\s*(?P<rest>.+)$", re.IGNORECASE | re.S,
)

_ADAMANT_MANA_KEYS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}


def adamant_mana_spent_condition(m: "re.Match[str]") -> dict[str, Any]:
    """The closed, spell-local condition behind Adamant's printed rider."""
    return {
        "kind": "mana_color_spent_to_cast_at_least",
        "color": _ADAMANT_MANA_KEYS[m.group("color").lower()],
        "amount": int(m.group("n")),
    }


def _peel_spell_mana_spent_at_least(body: str) -> tuple[str, Optional[int]]:
    """Strip a leading "if at least N mana was spent to cast it/that spell,"
    off ``body``, returning ``(remaining_body, threshold)`` — or
    ``(body, None)`` unchanged if the prefix isn't present."""
    m = _SPELL_MANA_SPENT_AT_LEAST_IF_RE.match(body.strip())
    if m is None:
        return body, None
    return m.group("rest"), int(m.group("n"))

_CAST_MANA_RIDER_RE = re.compile(
    r"^(?P<base>.+?)\.\s*if (?P<n>\d+) or more mana was spent to cast that spell,\s*"
    r"(?P<instead>instead\s+)?(?P<rider>.+)$", re.IGNORECASE | re.S,
)

#: Tellah, Great Sage is the sole current cast-trigger with *two* additive
#: total-mana riders.  Keep it adjacent to the one-rider peel: both reuse the
#: same trigger predicate and, crucially, each threshold is independently
#: true (eight mana draws the cards *and* performs the final rider).
_CAST_MANA_TWO_RIDERS_RE = re.compile(
    r"^(?P<base>.+?)\.\s*if (?P<n1>\d+) or more mana was spent to cast that spell,\s*"
    r"(?P<rider1>.+?)\.\s*if (?P<n2>\d+) or more mana was spent to cast that spell,\s*"
    r"(?P<rider2>.+)$", re.IGNORECASE | re.S,
)


def _cast_mana_rider_parts(body: str, *, reading: ClauseReading = STANDALONE) -> Optional[tuple[list[EffectSpec], int, list[EffectSpec], bool]]:
    """Parse PAR-96's one-rider cast-trigger body without losing its gate."""
    m = _CAST_MANA_RIDER_RE.match(body.strip())
    if m is None:
        return None
    base = parse_effect_body(m.group("base"), reading=ClauseReading(self_subject=reading.self_subject))
    rider_text = m.group("rider").strip().rstrip(".").strip()
    # Oracle places both modifiers after the effect as often as before it:
    # "~ also gains …" and "~ gets … instead".  They describe the rider's
    # relation to the base branch, not its effect grammar.
    replaces = bool(m.group("instead")) or rider_text.lower().endswith(" instead")
    if rider_text.lower().endswith(" instead"):
        rider_text = rider_text[:-len(" instead")].rstrip()
    rider_text = re.sub(r"^(~) also\s+", r"\1 ", rider_text, flags=re.I)
    # In a mutually-exclusive high branch the original target isn't carried
    # by a prior resolving effect; this exact mill wording therefore needs a
    # fresh, equivalent target-player requirement.
    rider_text = re.sub(r"^that player mills", "target player mills", rider_text, flags=re.I)
    mana_from_power = re.fullmatch(r"add an amount of \{(?P<color>[wubrgc])\} equal to ~'?s power", rider_text, re.I)
    rider = (
        [EffectSpec("add_mana", {"color": mana_from_power.group("color").upper(), "amount_selector": "source_power"})]
        if mana_from_power is not None
        else parse_effect_body(rider_text.removeprefix("also "), reading=ClauseReading(self_subject=reading.self_subject))
    )
    if base is None or rider is None:
        return None
    return base, int(m.group("n")), rider, replaces


def _cast_mana_two_rider_parts(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[tuple[list[EffectSpec], list[tuple[int, list[EffectSpec]]]]]:
    """Parse PAR-96's additive two-threshold trigger body (Tellah)."""
    m = _CAST_MANA_TWO_RIDERS_RE.match(body.strip())
    if m is None:
        return None
    base = parse_effect_body(m.group("base"), reading=ClauseReading(self_subject=reading.self_subject))
    first = parse_effect_body(m.group("rider1").strip().rstrip("."), reading=ClauseReading(self_subject=reading.self_subject))
    second_text = m.group("rider2").strip().rstrip(".")
    # ``that much`` is the total mana paid for the spell that caused this
    # trigger, carried by SPELL_CAST's event payload.  The preceding
    # sacrifice is a sequence, not a cost, so it remains an ordinary effect.
    if re.fullmatch(r"sacrifice ~ and it deals that much damage to each opponent", second_text, re.I):
        second = [
            EffectSpec("sacrifice_self", {}),
            EffectSpec("damage", {
                "amount": 0, "selector": "each_opponent",
                "amount_from_trigger_event": "mana_spent",
            }),
        ]
    else:
        second = parse_effect_body(second_text, reading=ClauseReading(self_subject=reading.self_subject))
    if base is None or first is None or second is None:
        return None
    return base, [(int(m.group("n1")), first), (int(m.group("n2")), second)]

#: PAR-75: "Whenever you cast a Doctor spell or creature spell with
#: doctor's companion, `<effect>`." (Rose Noble) — an OR of two structurally
#: different cast-trigger filters (a creature-subtype match vs. a card-type
#: + printed-keyword match), which neither `_CAST_SPELL_TRIGGER_RE`'s single
#: ``types`` slot nor any AND-combined `trigger` dict can express as one
#: condition. Rather than build a general trigger-condition OR combinator
#: for a shape no other cached card uses, this emits *two* independent
#: triggered abilities sharing the same effects (`Segment.extra_specs`, the
#: same "one clause, several `AbilitySpec`s" idiom modal/EAP casting uses) —
#: safe because a real Doctor card and a real companion card are never the
#: same physical card (RULE 702.124m's two Time Lord partner halves), so
#: the two conditions can never both fire off one cast and double the
#: payoff. "Doctor" is a creature type (every printed Doctor card is a
#: Legendary Creature), read the same way `_CAST_SPELL_SUBTYPE_WORDS` reads
#: any other subtype cast filter.
DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE = re.compile(
    r"^whenever you casts? a doctor spell or creature spell with "
    r"doctor'?s companion,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


#: "Whenever you cast a spell that targets one or more permanents,
#: `<effect>`." (Tiller of Flesh) — a RULE 608.2b targeting filter on the
#: cast trigger. Distinct from `_CAST_SPELL_TRIGGER_PLAIN_RE` above (that
#: one needs a comma right after "a spell"; here " that targets …" sits
#: between), so it must be tried first. `normalize` already folds
#: "one" → "1"; both spellings are accepted for robustness. The engine
#: side is `effect_binder`'s ``requires_spell_targets_permanent`` predicate
#: reading `SPELL_CAST`'s new ``targets_a_permanent`` flag.
CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell that targets "
    r"(?:1|one) or more permanents,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: RULE 702.34a's un-keyworded **Heroic** template — "Whenever you cast a
#: spell that targets ~, `<effect>`." (Akroan Skyguard / Battlewise Hoplite
#: / Hero of Iroas / Legolas, Master Archer / Phalanx Leader-adjacent). The
#: engine side is `effect_binder`'s ``requires_spell_targets_source``
#: predicate, reading `SPELL_CAST`'s new ``target_instance_ids`` frozenset
#: against the bound ability's own object. Always "you cast" (the ability's
#: own controller); the body is parsed ``self_subject`` so "~" means this
#: creature. Tried before `CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE` — the
#: "targets ~" and "targets 1 or more permanents" clauses don't overlap,
#: this is just for locality.
#: "Whenever you cast a spell that shares a creature type with ~, …"
#: (Folk Hero's granted trigger) — `effect_binder`'s ``spell_shares_
#: creature_type_with_source`` predicate compares the still-on-stack
#: spell's subtypes with the ability's source.
CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE = re.compile(
    r"^whenever you cast a spell that shares a creature type with ~,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE = re.compile(
    r"^whenever you cast a spell that targets ~,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: RULE 601.2i: "When you cast this spell, `<effect>`." — a self-referential
#: cast trigger, meant to fire *while its own spell is still on the stack*
#: (it resolves above the spell). The engine side is done (MEC-43):
#: `RulesEngine._collect_self_cast_triggers` scans stack items for a
#: `SPELL_CAST` trigger scoped ``{"subject": "self"}`` and
#: `effect_binder.bind_ability` sets `TriggeredAbility.functions_from_stack`
#: off exactly that shape — only the parser recognizer was missing. The
#: Emrakul-brood "cast" cycle, Bringer cycle, Distended Mindbender &c.; the
#: body is parsed ``self_subject`` so a bare "it"/"copy it" means this
#: spell.
CAST_THIS_SPELL_TRIGGER_RE = re.compile(
    r"^when you cast this spell,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

#: RULE 601.2h's "free spell" hate: "Whenever a player casts a spell, if no
#: mana was spent to cast it, counter that spell." (Vexing Bauble — the one
#: real card printing this exact template). A standalone whole-line
#: recognizer rather than decomposed into the generic trigger-condition +
#: body machinery: the "if no mana was spent" clause is folded straight into
#: the trigger's own ``spell_no_mana_spent`` gate (`binding/core.py`) and
#: "counter that spell" resolves off the firing SPELL_CAST event's own
#: object (`CounterSpellEffect.target_from_trigger_event`), not a RULE 115
#: target — no other card needs this exact combination yet, so it isn't
#: split into reusable pieces the way the untyped/typed cast-trigger rows
#: above are.
COUNTER_FREE_SPELL_RE = re.compile(
    r"^whenever a player casts a spell, if no mana was spent to cast it,\s*"
    r"counter that spell\.?\s*$",
    re.IGNORECASE,
)

#: "counter that spell" / "counter it" as the *body* of a SPELL_CAST-
#: triggered ability — resolves off the firing event's own object
#: (`CounterSpellEffect.target_from_trigger_event`, same idiom as
#: `COUNTER_FREE_SPELL_RE` at line ~3571), not a RULE 115 target.
#: `parse_effect_body` deliberately doesn't claim this (a bare "counter
#: that spell" outside a cast trigger has no antecedent), so trigger-row
#: consumers that can legitimately carry it call this helper first.
_COUNTER_TRIGGERING_SPELL_RE = re.compile(r"^counter (?:that spell|it)\.?\s*$", re.IGNORECASE)


def _counter_triggering_spell_effects(body: str) -> Optional[list["EffectSpec"]]:
    if _COUNTER_TRIGGERING_SPELL_RE.match(body.strip()):
        return [EffectSpec("counter", {"target_from_trigger_event": "instance_id"})]
    return None

#: The general form of the above (RULE 601.2h's "free spell" hate isn't
#: only Vexing Bauble's "counter it" — Roiling Vortex's own "…this
#: enchantment deals 5 damage to that player." prints the same trigger
#: condition with an arbitrary payoff). Reuses the trigger's own
#: ``spell_no_mana_spent`` gate exactly as `COUNTER_FREE_SPELL_RE` does;
#: only the body is generic here rather than hardcoded to "counter that
#: spell". Tried *after* the exact-match row above so a real Vexing Bauble
#: still gets that row's more specific ``target_from_trigger_event``
#: wording (both bind to the same behaviour either way, so order is a
#: style choice, not a correctness one).
CAST_SPELL_NO_MANA_TRIGGER_RE = re.compile(
    r"^whenever a player casts a spell, if no mana was spent to cast (?:it|that spell),\s*"
    r"(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: "Whenever a player casts a spell, if it's not their turn, <effect>."
#: (Scytheclaw Raptor) — RULE 603.4's intervening-if reusing
#: `_build_group_ok`'s existing ``not_controllers_turn`` flag verbatim
#: (Price of Glory's own "if it's not that player's turn" — `SPELL_CAST`'s
#: ``player_id`` is already in `_GROUP_CONTROLLER_EVENT_KEYS`).
#: "When ~ enters, if you cast it, `<effect>`." (Rocco, Cabaretti Caterer-
#: shaped RULE 601.2b intervening-if, ~57 cache-wide cards) — a dedicated
#: whole-line row rather than folded into the generic ETB dispatch, since
#: this "if you cast it" gate needs `EffectSpec.condition`'s new
#: ``source_was_cast`` key stamped onto every resulting effect, which no
#: other ETB shape needs.
ENTERS_IF_CAST_RE = re.compile(
    r"^when ~ enters, if you cast it,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

#: PAR-139, RULE 702.35 / 603.4: "When ~ enters, if its madness cost was paid, `<effect>`." (Grave Scrabbler) — the
#: intervening-if reads the flag `RulesEngine.cast_spell` stamped (`GameObject.madness_cost_paid`). RULE 702.117's
#: "if its surge cost was paid" (Reckless Bushwhacker, Tyrant of Valakut) is the same shape on `surge_cost_paid`.
ENTERS_IF_MADNESS_PAID_RE = re.compile(
    r"^when ~ enters, if its (?P<cost>madness|surge) cost was paid,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE = re.compile(
    r"^whenever a player casts a spell, if it'?s not their turn,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: RULE 120/613's "Whenever you/an opponent/a player draws a card, <effect>."
#: (Sheoldred, the Apocalypse/Underworld Dreams/Consecrated Sphinx-shaped
#: draw-matters triggers — the single most-requested missing trigger
#: condition in the cache, ~50+ cards). Exactly the same shape as
#: `_CAST_SPELL_TRIGGER_PLAIN_RE` just above — a bare player-subject
#: event with no type filter — reusing that row's own docstring reasoning
#: verbatim: `effect_binder`'s ``{"subject": "you"}``/``{"subject":
#: "group", "controller": "not_you"/None}`` scoping over `EventType.DRAW`
#: is already proven (Smothering Tithe's hand-authored entry), so this is
#: purely the missing oracle-text recognizer, no new engine primitive.
DRAW_TRIGGER_PLAIN_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) draws? a card,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: "Whenever a player casts their second spell each turn, …" (Hearthborn
#: Battler) — the ordinal-count sibling of `_CAST_SPELL_TRIGGER_PLAIN_RE`;
#: only "second" is in scope (the one real printed ordinal), so a small
#: closed word→int map rather than a general ordinal-word parser.
#: "first" (n=1) rides the same `_nth_spell_ok`/`is_nth_draw_this_turn`
#: range check as the higher ordinals (`total == n`) — added for PAR-31's
#: Jace, Unraveler emblem body and the "casts their first spell each turn"
#: cluster (Mind's Dilation, The Lord of Pain, Pain Distributor).
CAST_SPELL_ORDINAL_WORDS: dict[str, int] = {"first": 1, "second": 2, "third": 3, "fourth": 4}

#: "Whenever you draw your second card each turn, …" / "Whenever an opponent
#: draws their second card each turn, …" (Faerie Mastermind / Bard the
#: Bowman / The Unagi of Kyoshi Island — the ~44-SOLO ordinal-draw cluster).
#: The draw-side sibling of `_CAST_SPELL_TRIGGER_NTH_RE`, reusing its closed
#: ordinal→int map; `effect_binder`'s ``is_nth_draw_this_turn`` predicate
#: (`GameState.cards_drawn_this_turn`, RULE 120.3) is already proven by
#: Faerie Mastermind's hand-authored entry, so this is purely the missing
#: oracle-text recognizer.
DRAW_CARD_TRIGGER_NTH_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) draws? (?:your|their) "
    rf"(?P<ordinal>{'|'.join(CAST_SPELL_ORDINAL_WORDS)}) card each turn,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
#: "Reveal the first card you draw each turn. Whenever you reveal a
#: `<type>` card this way, …" (Primitive Etchings, Rowen): the reveal has no
#: game effect of its own here, so it is the first-draw trigger above with
#: its body gated on that card's type.
REVEAL_FIRST_DRAW_RE = re.compile(
    r"^reveal the first card you draw each turn\.\s*whenever you reveal an? "
    r"(?P<basic>basic )?(?P<type>artifact|creature|enchantment|instant|land|planeswalker|sorcery)"
    r" card this way,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: RULE 605.1: "Whenever you/a player taps a `<land type>`/land for mana,
#: <effect>." (Crypt Ghast/Wild Growth-shaped, hitherto only hand-authored
#: — Bubbling Muck/High Tide's own symmetric, unscoped "a player" form).
#: `EventType.TAPPED_FOR_MANA` already carries everything a RULE 603.1
#: group-subject condition over the tapped *land* needs (`type`/`subtypes`/
#: `controller`); "you" narrows to the ability's own controller the same
#: way `cast_spell_trigger_condition` does for cast/draw triggers, "a
#: player" leaves it unscoped (any player's land).
#: Effect types that add mana — a `TAPPED_FOR_MANA` trigger whose body is only these is a
#: RULE 605.1b triggered mana ability.
MANA_ADDING_EFFECTS: frozenset[str] = frozenset({"add_mana", "mirror_produced_mana"})

TAP_FOR_MANA_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|a player) taps? an? "
    r"(?P<land>swamp|island|mountain|forest|plains|land) for mana,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


#: PAR-79 fifth increment: "When ~ enters and whenever you cast <cast-
#: trigger clause>, <effect>." (Hraesvelgr of the First Brood/Brinelin, the
#: Moon Kraken/Flaring Cinder/Jessie Zane, Fangbringer/Up the Beanstalk/
#: Angel of Unity) — RULE 603.1 lets one ability print two independent
#: trigger conditions sharing a single effect body: "when X and whenever Y,
#: Z" is legally "when X, Z" *and* "whenever Y, Z" as two separate
#: triggered abilities (RULE 603.2 fires each on its own — a card that both
#: enters and casts a matching spell in the same window legitimately
#: triggers twice, not once), not a single fused condition. Rather than
#: build a fused ETB-or-cast condition, or re-derive every cast-trigger
#: filter (mana value, card type, subtype, "from your graveyard", …) a
#: second time just for this shape, this reconstructs each half as its own
#: ordinary trigger line ("when ~ enters, <body>" / "whenever <cast
#: clause>, <body>") and re-enters `segment_line` on each — reusing the
#: *entire* existing ETB/cast-trigger grammar rather than duplicating any of
#: it, the handler-recipe.md "decompose into atomic grammar units" rule
#: applied at the trigger-condition level instead of a single clause. Two
#: independent `AbilitySpec`s sharing the same effects (`Segment.
#: extra_specs`, the same idiom PAR-75's Doctor/companion OR-of-two-
#: conditions split already uses).
ETB_AND_CAST_TRIGGER_RE = re.compile(
    r"^(?:when|whenever) ~ enters and whenever (?P<cast_clause>you casts? .+?),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


#: "Whenever you cast a **red** spell, …" (Balefire Liege, Runaway Steam-Kin)
#: — a single colour word in `_CAST_SPELL_TRIGGER_RE`'s ``types`` slot maps
#: to `effect_binder`'s existing ``cast_of_color`` trigger key (a live
#: colour check on the cast object). "colorless" is deliberately excluded:
#: `cast_of_color` is a membership test, not an empty-identity one.
CAST_SPELL_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

#: RULE 702.28c's own trigger condition — "When you cycle this card,
#: `<effect>`." (Krosan Tusker/Shark Typhoon-shaped — ranked the single
#: biggest template blocker in this family, ~37 real cards). Fires off the
#: new `EventType.CYCLED` (`GameEngine._pay_activation_cost`, gated on
#: `ActivationCost.is_cycling` so a Channel card's own unrelated
#: ``discard_self`` never misfires it) via `RulesEngine.
#: _collect_cycled_triggers`'s graveyard-scoped scan — a card's own
#: Cycling keyword line is recognized separately (the "privileged fast
#: path" keyword grammar), so this only needs to claim the bonus sentence.
CYCLE_TRIGGER_RE = re.compile(
    r"^when you cycle this card,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

#: RULE 603.1/701.9: "When(ever) a spell or ability an opponent controls
#: causes you to discard `<~|this card|a card>`, `<effect>`." (PAR-126 — the
#: Wild Mongrel-era Guerrilla Tactics/Metrognome/Spiritual Focus cycle). The
#: engine side is MEC-101's `DISCARD_CARD.cause_controller_id` stamp plus the
#: ``requires_opponent_caused_discard`` trigger predicate, which is what keeps
#: a cleanup or own-cost discard (no cause) from firing it. The self form
#: ("this card"/"~") is the card's own discard, so subject ``self``; "a card"
#: watches any of your discards, so subject ``you``.
OPPONENT_CAUSED_DISCARD_TRIGGER_RE = re.compile(
    r"^when(?:ever)? a spell or ability an opponent controls causes you to discard "
    r"(?P<what>~|this card|a card),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: The body's delayed tail — "[`<pre>`, and ]you return this card from your
#: graveyard to `<zone>` at the beginning of the next end step" (Mangara's
#: Blessing, Sand Golem). Only the return clause is delayed (RULE 603.7), so
#: the optional prefix is parsed as an ordinary immediate effect.
_CAUSED_DISCARD_DELAYED_RETURN_RE = re.compile(
    r"^(?:(?P<pre>.+?),?\s+and\s+)?(?:you\s+)?(?P<ret>return (?:this card|~) from your graveyard to .+?)"
    r" at the beginning of the next end step\.?$",
    re.IGNORECASE | re.S,
)

#: "that player loses N life" — the player whose spell/ability caused the
#: discard (Psychic Purge); `LoseLifeEffect.selector="cause_controller"`.
_CAUSED_DISCARD_THAT_PLAYER_LOSES_RE = re.compile(
    r"^that player loses (?P<n>\d+) life\.?$", re.IGNORECASE,
)

#: The discarded card sits in the graveyard when this trigger resolves
#: (RULE 701.9a), so the bare "return it to your hand" means the graveyard
#: return (Quagnoth).
_CAUSED_DISCARD_RETURN_IT_RE = re.compile(r"^return it to your hand\.?$", re.IGNORECASE)

#: RULE 614.1: "If a spell or ability an opponent controls causes you to
#: discard this card, put it onto the battlefield [with N +1/+1 counters on
#: it] instead of putting it into your graveyard." (Wilt-Leaf Liege) — a
#: replacement effect, not a trigger: `discard_to_battlefield` (MEC-102).
CAUSED_DISCARD_REPLACEMENT_RE = re.compile(
    r"^if a spell or ability an opponent controls causes you to discard (?:~|this card),\s*"
    r"put it onto the battlefield instead of putting it into your graveyard\.?$",
    re.IGNORECASE,
)


def caused_discard_effects(body: str, is_self: bool) -> Optional[list[EffectSpec]]:
    """The effect list of an opponent-caused-discard trigger body."""
    text = body.strip()
    that_player = _CAUSED_DISCARD_THAT_PLAYER_LOSES_RE.match(text)
    if that_player is not None:
        return [EffectSpec("lose_life", {
            "amount": int(that_player.group("n")), "selector": "cause_controller",
        })]
    if is_self and _CAUSED_DISCARD_RETURN_IT_RE.match(text):
        return [EffectSpec("return_self_from_graveyard_to_hand", {})]
    delayed = _CAUSED_DISCARD_DELAYED_RETURN_RE.match(text)
    if delayed is not None and is_self:
        returned = parse_effect_body(delayed.group("ret"), reading=ClauseReading(self_subject=True))
        if returned is None or any(e.condition is not None for e in returned):
            return None
        effects: list[EffectSpec] = []
        if delayed.group("pre"):
            immediate = parse_effect_body(delayed.group("pre"), reading=ClauseReading(self_subject=True))
            if immediate is None:
                return None
            effects.extend(immediate)
        effects.append(EffectSpec("create_delayed_trigger", {
            "step": "end", "scope": "any",
            "effects": [{"type": e.type, "params": dict(e.params)} for e in returned],
            "description": "return this card from your graveyard at the beginning of the next end step",
        }))
        return effects
    return parse_effect_body(body, reading=ClauseReading(self_subject=is_self))


#: RULE 701.17/603.1's "Whenever you sacrifice a Food, …" (Experimental
#: Confectioner/Trail of Crumbs-shaped Food-matters payoffs) — a player-
#: subject trigger like `_PLAYER_TRIGGER_CONDITIONS`'s bare event-name
#: table, but that table has no way to carry a type filter, and RULE 122.1a
#: "sacrifice a `<type>`" always means *some* type. Scoped to the same
#: closed named-token vocabulary `catalogue.effect_rows.shared.NAMED_TOKEN_WORDS`
#: already trusts (Treasure/Clue/Food) rather than any noun — a fail-closed
#: choice, not a card-count one: `EventType.SACRIFICE`'s own `object_types`
#: payload (`RulesEngine.put_into_graveyard`) is the *card's printed type
#: line*, so "a permanent" or an arbitrary creature type would need its own
#: (much wider, unverified) matching rules this narrow vocabulary sidesteps.
SACRIFICE_TYPE_TRIGGER_RE = re.compile(
    r"^when(?:ever)? you sacrifice an? (?P<type>treasure|clue|food)(?: or (?P<type2>treasure|clue|food))?,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: "When you control no `<basic land type>`, sacrifice ~." (RULE 603.8
#: state trigger — Bog Serpent, Sea Serpent, Dandân, the original
#: colour-gated creature cycle; 11 SOLO). Modeled as a `LEAVES_BATTLEFIELD`
#: trigger gated by a live "the controller now controls none of that
#: printed land subtype" check (`effect_binder`'s new ``controls_none_of_
#: type`` trigger predicate) — the same "gate an ordinary event on a state
#: read" idiom `source_counters_at_least` uses instead of a general
#: state-trigger subsystem. The ETB edge (playing the creature while you
#: already control none) is a documented simplification — not modeled.
BASIC_LAND_TYPE_SINGULAR: dict[str, str] = {
    "swamps": "swamp", "swamp": "swamp", "islands": "island", "island": "island",
    "plains": "plains", "mountains": "mountain", "mountain": "mountain",
    "forests": "forest", "forest": "forest",
}
#: PAR-152 (Olivia, Crimson Bride's granted ability): "When you don't control a legendary Vampire, exile ~." — the
#: state trigger of RULE 603.8 over a legendary/subtype quality, the sibling of the basic-land-type row below.
CONTROL_NONE_MATCHING_RE = re.compile(
    r"^when you don'?t control an? (?P<leg>legendary )?(?P<sub>[a-z]+),\s*"
    r"(?P<body>(?:sacrifice|exile) (?:~|this \w+))\.?$",
    re.IGNORECASE | re.S,
)
CONTROL_NONE_SACRIFICE_RE = re.compile(
    r"^when you control no (?P<type>swamps?|islands?|plains|mountains?|forests?),\s*"
    r"(?P<body>sacrifice (?:~|this \w+))\.?$",
    re.IGNORECASE | re.S,
)

#: RULE 702.19a's own declare-attackers-time choice, spelled out in full
#: (Scryfall still tags these ``keywords: ['Exert']`` even though there's
#: no bare reminder-text keyword line to match — `combat.has(obj, "exert")`
#: already reads that list, so this only needs to claim the sentence for
#: `MODELED` coverage). An optional leading "If ~ hasn't been exerted this
#: turn, " guard (Combat Celebrant's own self-loop guard, printed only on
#: that one card in the cache) is swallowed rather than parsed into a
#: condition — narrow enough to hand-author instead of building a general
#: "once per turn" trigger-condition primitive for a single card.
EXERT_TRIGGER_RE = re.compile(
    r"^(?:if ~ hasn'?t been exerted this turn,\s*)?"
    r"you may exert (?:~|it) as (?:it|he|she) attacks\.\s*when you do,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: The bare rider with no "when you do" bonus (Rakdos Cackler-shaped) —
#: `combat.has`/`declare_attackers` already give it real behaviour off the
#: Scryfall keyword alone, so this is a pure `keyword_line` claim, the same
#: "covered, contributes no spec" idiom every other bare keyword sentence
#: uses.
EXERT_BARE_RE = re.compile(
    r"^you may exert ~ as (?:it|he|she) attacks\.$", re.IGNORECASE,
)

#: RULE 603.1's "whenever you exert a creature, `<effect>`." (Rafiq of the
#: Many-adjacent payoffs, e.g. Long-Term Plans-cycle rewards) — a
#: player-subject trigger like `SACRIFICE_TYPE_TRIGGER_RE`, just with no
#: type filter (any creature the ability's controller exerts, including
#: itself) since `EventType.EXERTED`'s own ``player_id`` is already scoped
#: to *who* exerted, not *what*.
EXERT_PLAYER_TRIGGER_RE = re.compile(
    r"^whenever you exert a creature,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)


#: RULE 500.7's "at the beginning of the [upkeep/draw/end/…] step" turn-
#: structure trigger family — a genuinely common template distinct from
#: RULE 603.1's object-subject "when/whenever X enters/dies/attacks/blocks"
#: shape `trigger_condition` handles above, so it's a separate, dedicated
#: recognizer (checked before the generic `TRIGGER_RE` dispatch, which
#: would otherwise also match "at ..." but then fail to classify the
#: condition text) rather than another `trigger_condition` subject shape.
#: Scoped to the step-name vocabulary `game/phases.py`'s
#: `default_turn_sequence` actually names, mapped onto the
#: `EventType.STEP_BEGIN` event's own ``step`` payload
#: (`game/game_engine.py` fires it once per step, every turn).
#:
#: Four printed scope words, each its own named group so the shared step
#: vocabulary doesn't have to be repeated per scope: "the"/"each" (unscoped —
#: fires every such step, any player's turn — real templating uses "each"
#: for the modern un-scoped form, "the ... step" for an older/rarer one),
#: "your" (only the ability's own controller's step), "each opponent's"
#: (any step that *isn't* the controller's own — RULE 603.4-style). The
#: scoped forms carry no rules meaning the un-scoped one doesn't already
#: have other than *whose* turn it is, so `AbilitySpec.trigger` gets a
#: ``phase_relation`` of ``"you"``/``"not_you"``/absent, consumed by
#: `effect_binder._trigger_condition` (STEP_BEGIN events carry no controller
#: of their own to key off, unlike RULE 603.1's object-subject events, so
#: this checks `context.state.active_player` instead of an event field).
#: The printed step words this family recognizes → the ``step`` name
#: `game/phases.py`'s `default_turn_sequence` actually fires. The three
#: **phase**-named rows are why this is a mapping rather than a bare
#: alternation: a card says "at the beginning of combat"/"of your second main
#: phase", but `EventType.STEP_BEGIN` names that phase's own first (and, for
#: a main phase, only) step.
PHASE_STEP_WORDS: dict[str, str] = {
    "upkeep": "upkeep", "draw": "draw", "end": "end", "cleanup": "cleanup",
    # RULE 507: "at the beginning of combat on your turn" — by a wide margin
    # the most common phase trigger after upkeep/end step.
    "combat": "begin_combat",
    # RULE 505: the two main phases, printed either by ordinal or by
    # pre-/postcombat name.
    "first main phase": "main1",
    "precombat main phase": "main1",
    "second main phase": "main2",
    "postcombat main phase": "main2",
}

#: "each of your main phases" (Frontier Siege) — both main phases (RULE 505), one trigger apiece.
EACH_MAIN_PHASE_STEPS = ("main1", "main2")

#: The step/phase alternation, longest first so "first main phase" wins over
#: any prefix of it.
_PHASE_STEP_ALT = "|".join(
    re.escape(word) for word in sorted(PHASE_STEP_WORDS, key=len, reverse=True)
)

#: "At the beginning of each player's upkeep, ~ deals N damage to them."
#: (Roiling Vortex/Manabarbs-adjacent punishers) — tried only inside the
#: unscoped ``"each player's <step>"`` branch of `PHASE_TRIGGER_RE` below
#: (`relation is None`), where "them" unambiguously means whoever's step
#: it is: `effects.DealDamageEffect`'s new ``selector="active_player"``
#: (`GameState.active_player`, read live at resolution — unchanged since
#: the step began). Not folded into the generic `_SELECTOR_WORD_MAP` "that
#: player"/``event_player`` row, since STEP_BEGIN carries no acting player
#: on the event at all — a body-only regex has no way to know which
#: pronoun meaning applies outside this specific wrapper.
PHASE_DAMAGE_TO_THEM_RE = re.compile(
    r"^(?:~|it) deals (?P<n>\d+) damage to (?:them|that player)\.?\s*$", re.IGNORECASE,
)

#: PAR-120: "at the beginning of each opponent's/each player's `<step>`, if
#: that player has `<N or fewer>`/no cards in hand, `<effect>`." (Davriel,
#: Rogue Shadowmage; the Shrieking Affliction/Hellfire Mongrel/Lavaborn Muse
#: "hellbent-punisher" cluster) — "that player" is the same whoever's-step-
#: it-is referent `PHASE_DAMAGE_TO_THEM_RE` already reads, one clause
#: earlier: a phase-trigger-only peel (not folded into the shared
#: `static_condition()` table `GENERIC_IF_PREFIX_RE` also reaches) because
#: the identical wording means something else entirely off this surface —
#: an activated ability's own "target opponent discards a card. then if
#: **that player** has no cards in hand, …" (Nezumi Shortfang) means the
#: just-targeted opponent, not whoever's turn it is.
THAT_PLAYER_HAND_IF_RE = re.compile(
    r"^if that player has (?:no cards|(?P<n>\d+) or fewer cards) in hand,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: The handful of effect-verb shapes this cluster's bodies use, each aimed
#: at the same "that player"/"them" referent (`effect_operands.PLAYER_
#: SCOPES`' own ``"active_player"`` string, already resolved generically by
#: `DrawCardEffect.player`/`LoseLifeEffect.player`'s ENG-37 operand path —
#: no new engine code needed for either). The damage shape is
#: `PHASE_DAMAGE_TO_THEM_RE` above, tried by the caller first.
_ACTIVE_PLAYER_DRAWS_RE = re.compile(
    r"^that player draws (?P<n>\d+) cards?\.?\s*$", re.IGNORECASE,
)
_ACTIVE_PLAYER_LOSES_LIFE_RE = re.compile(
    r"^(?:they|that player) lose[s]? (?P<n>\d+) life\.?\s*$", re.IGNORECASE,
)


def active_player_phase_body(rest: str) -> Optional[list[EffectSpec]]:
    """Read a phase body's "that player" as the player whose step it is.

    Shared second-person grammar handles linked instructions and choices.
    Bodies naming another player referent fall back to the ordinary parser.
    """
    search = re.fullmatch(
        r"that player loses (?P<n>\d+) life, searches their library for a card, "
        r"puts it into their hand, then shuffles\.?", rest,
    )
    if search is not None:
        return [EffectSpec("trigger_subject_referent", {
            "acting": "active_player", "effects": [
                EffectSpec("lose_life", {"amount": int(search.group("n"))}).to_dict(),
                EffectSpec("search", {"criteria": "", "destination": "hand", "optional": False}).to_dict(),
            ],
        })]
    # PAR-207: "they lose 1 life and you gain 1 life" (Curse of Leeches) -- a life loss for the step's player, then a
    # clause about the ability's controller: each half is read under its own player. Only the life-loss shape: other
    # "that player ... and you ..." bodies name two player referents and stay unclaimed.
    split_players = re.fullmatch(
        r"(?P<theirs>(?:they|that player) lose[s]? \d+ life) and (?P<yours>you [^.]+)\.?", rest)
    if split_players is not None:
        theirs = active_player_phase_body(split_players.group("theirs"))
        yours = parse_effect_body(split_players.group("yours"))
        if theirs is not None and yours is not None:
            return theirs + yours
    if rest.startswith("that player ") and not re.search(r"\b(?:you|your|target)\b", rest):
        targeted = parse_effect_body('target player ' + rest[len('that player '):])
        if targeted and all(
            [spec.params[k] for k in TARGET_PARAM_KEYS if spec.params.get(k) is not None] == ['player']
            for spec in targeted
        ):
            return [EffectSpec('trigger_subject_referent', {
                'referent': 'active_player', 'effects': [e.to_dict() for e in targeted],
            })]
    # RULE 109.5 / 608.2c: scope only instructions addressed to the step
    # player. A separate "you" instruction keeps the ability controller.
    pieces = re.split(r"\.\s+| and (?=you\b)|,? then (?=you\b)", rest.rstrip("."))
    if len(pieces) > 1 and re.search(r"\b(?:you|your)\b", rest):
        effects = []
        for piece in pieces:
            parsed = active_player_phase_body(piece) or parse_effect_body(piece)
            if parsed is None:
                return None
            effects.extend(parsed)
        return effects
    if re.match(r"^(?:that player|they)\b", rest) and not re.search(r"\b(?:you|your|target)\b", rest):
        rewritten = re.sub(r"\bthat player\b|\bthey\b", "you", rest)
        rewritten = re.sub(r"\btheir\b", "your", rewritten)
        rewritten = re.sub(r"\byou (?!may\b)([a-z]+)\b",
                           lambda m: "you " + base_verb(m.group(1)), rewritten)
        rewritten = re.sub(r"\bthen (draws|discards)\b", lambda m: "then " + base_verb(m[1]), rewritten)
        rewritten = re.sub(r"\bif (?:the player|you) does?\b", "if you do", rewritten)
        effects = parse_effect_body(rewritten)
        if effects is not None:
            return [EffectSpec("trigger_subject_referent", {
                "acting": "active_player", "effects": [e.to_dict() for e in effects],
            })]
    m = PHASE_DAMAGE_TO_THEM_RE.match(rest)
    if m is not None:
        return [EffectSpec("damage", {"amount": int(m.group("n")), "selector": "active_player"})]
    m = _ACTIVE_PLAYER_DRAWS_RE.match(rest)
    if m is not None:
        return [EffectSpec("draw", {"count": int(m.group("n")), "player": "active_player"})]
    m = _ACTIVE_PLAYER_LOSES_LIFE_RE.match(rest)
    if m is not None:
        return [EffectSpec("lose_life", {"amount": int(m.group("n")), "player": "active_player"})]
    return None

#: MEC-46 (Galadriel, Elven-Queen) — the RULE 603.4 intervening-if a phase
#: trigger's body can lead with: "if another `<subtype>` entered the
#: battlefield under your control this turn, `<rest>`." Peeled off the body
#: and attached as the trigger's own ``active_if`` (`static_conditions`'
#: ``another_subtype_entered_this_turn`` kind — a live battlefield scan, no
#: new per-turn tracker), so the trigger only fires while it holds.
ANOTHER_SUBTYPE_ENTERED_IF_RE = re.compile(
    r"^if another (?P<sub>[a-z][a-z-]+) entered the battlefield "
    r"under your control this turn,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-32 phase-trigger intervening-ifs backed by two new per-turn
#: `static_conditions` trackers (`GameState.creature_card_to_graveyard_
#: this_turn` / `damage_dealt_by_this_turn`) — Cloakwood Hermit /
#: Dragon Cultist's granted end-step token makers.
CREATURE_CARD_TO_GY_IF_RE = re.compile(
    r"^if a creature card was put into your graveyard from anywhere this turn,"
    r"\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
YOU_DEALT_DAMAGE_IF_RE = re.compile(
    r"^if a source you controlled dealt (?P<n>\d+) or more damage this turn,"
    r"\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: MEC-79 / RULE 701.64b — the leading "if ~ is harnessed," that
#: `normalize._rewrite_infinity_ability` injects when it turns an Infinity
#: Stone's "``∞ —``" marker line into an ordinary phase trigger. Peeled here
#: into the trigger's own `active_if` (`static_conditions`' ``source_harnessed``).
SOURCE_HARNESSED_IF_RE = re.compile(
    r"^if ~ is harnessed,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-60 wave 18 — a phase trigger's leading RULE 603.4 intervening-if
#: "if you control no `<subtype>`[s]" / "if you don't control a `<subtype>`
#: [creature] token" (Ophiomancer, Pest Rescuer, Jadar). Attached as the
#: trigger's `active_if` via `static_conditions`' ``control_count`` with
#: ``max=0`` over the ``creatures_you_control_of_type_<subtype>`` selector
#: `continuous.count_selector` already resolves. **Documented
#: simplification:** the "…token" qualifier is dropped (a non-token Snake/
#: Pest is a rare edge). A curated subtype whitelist — an open one would
#: over-fire (an unknown word counts 0, so "control no <word>" is always
#: true).
CONTROL_NO_SUBTYPE_WORDS: frozenset[str] = frozenset({
    "snake", "pest", "thopter", "zombie", "saproling", "spirit", "goblin",
    "elf", "soldier", "insect", "wolf", "cat", "bird", "elemental", "dragon",
    "servo", "myr", "golem", "wall", "faerie", "rat", "squid", "eldrazi",
})
YOU_CONTROL_NO_SUBTYPE_IF_RE = re.compile(
    r"^if you (?:control no (?P<sub1>[a-z][a-z-]+?)s"
    r"|don'?t control (?:a|an|any) (?P<sub2>[a-z][a-z-]+?)(?: creature)?(?: token)?)"
    r",\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

PHASE_TRIGGER_RE = re.compile(
    r"^at the beginning of (?:"
    # "each player's upkeep" reads exactly like "each upkeep" to this engine
    # — every player's turn has one — so it shares the unscoped branch.
    rf"(?:the|each)(?: player'?s)? (?P<step_any>{_PHASE_STEP_ALT})(?:\s+step)?"
    rf"|your (?P<step_you>{_PHASE_STEP_ALT})(?:\s+step)?"
    # "at the beginning of each of your postcombat main phases" — the plural
    # form of the "your <phase>" row above, same meaning.
    r"|each of your (?P<step_both_mains>main phases)"
    rf"|each of your (?P<step_you_each>{_PHASE_STEP_ALT})s?(?:\s+steps?)?"
    # RULE 507's own idiom: the phase is named, the scope trails it.
    r"|(?P<step_combat_you>combat) on your turn"
    r"|(?P<step_combat_opp>combat) on each opponent'?s turn"
    rf"|each opponent'?s (?P<step_opp>{_PHASE_STEP_ALT})(?:\s+step)?"
    rf"|each other player'?s (?P<step_other>{_PHASE_STEP_ALT})(?:\s+step)?"
    # RULE 303.4m / 603.2b: the step belongs to the current controller of
    # the enchanted host, independently of who controls the Aura.
    rf"|the (?P<step_attached>{_PHASE_STEP_ALT})(?:\s+step)? of enchanted "
    r"(?:creature|artifact|land|enchantment|permanent)'?s controller"
    # PAR-207: the step belongs to a *player* the permanent names -- the one it enchants (a Curse, RULE 303.4t) or the
    # one chosen as it entered (Black Vise, RULE 700.2g `GameObject.chosen_player_id`).
    rf"|enchanted player'?s (?P<step_enchanted>{_PHASE_STEP_ALT})(?:\s+step)?"
    rf"|the chosen player'?s (?P<step_chosen>{_PHASE_STEP_ALT})(?:\s+step)?"
    r"),\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 603.1's condition *subject* — "self" ("~"/"this creature" itself) —
#: scoped so e.g. "when ~ enters the battlefield, draw a card" only fires for
#: its own source, never any other permanent entering (the over-firing bug
#: this grammar exists to close). The verb itself is still resolved by
#: `trigger_event` above; this only decides *whose* enters/dies/attacks/
#: blocks the ability cares about. "class" is included directly (rather than
#: relying on `normalize._fold_self_reference`, which deliberately leaves
#: "this Class"/"this Saga" un-folded to ``~`` — its own docstring notes they
#: have "their own dedicated parsing") since a Class commonly opens with
#: "When this Class enters, <effect>." (RULE 717) and has no other automatic
#: ETB effect the way a Saga's chapter I gives it — "saga" is deliberately
#: left out: real Saga cards never print this phrasing outside stripped
#: reminder text (chapter I already covers it).
SELF_SUBJECT_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|land|permanent|equipment|class))\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?"
    # RULE 508.1: "~ attacks **a player**"/"**an opponent**" — the defender
    # kind scopes nothing the bare ATTACKS event doesn't already carry (a
    # real attacker can only ever attack a player or their planeswalker), so
    # it's consumed for subject classification, not turned into a predicate.
    r"(?:\s+an?\s+(?:player|opponent))?(?:\s+alone)?$"
)

#: RULE 508.1 with a *defender-property* qualifier: "~ attacks a player who
#: controls N or more lands" (Owlbear Cub). Still a `{"subject": "self"}`
#: ATTACKS trigger, but gated on the defending player's land count via
#: `effect_binder`'s `defender_controls_lands_at_least` predicate (the
#: ATTACKS event carries `defending_player_id`) — the same "gate an
#: ordinary event on a state read" idiom as `controls_none_of_type`.
ATTACKS_DEFENDER_LANDS_RE = re.compile(
    r"^(?:~|this creature) attacks a player who controls (?P<n>\d+) or more lands$"
)

#: PAR-79 fifth increment: "~ attacks the player with the most life or tied
#: for most life" (Undercover Butler/Seraphic Greatsword/Preacher of the
#: Schism) — the same "gate an ordinary ATTACKS trigger on a defender
#: property" idiom as `ATTACKS_DEFENDER_LANDS_RE` just above, this time via
#: `defender_has_most_life_predicate` (`game/binding/core.py`).
ATTACKS_DEFENDER_MOST_LIFE_RE = re.compile(
    r"^(?:~|this creature) attacks the player with the most life or tied for most life$"
)

#: RULE 603.4 intervening-if on an "~ attacks a player" trigger, as a body
#: *prefix*: "…, if no opponent has more life than that player, `<effect>`"
#: (the Baldur's Gate "attack the player who isn't winning" cycle — Agent
#: of the Shadow Thieves / Guild Artisan / Hardy Outlander / Sword Coast
#: Sailor / Veteran Soldier). "that player" is the attacked player; the
#: gate is that their life is ≤ every opponent's (of this ability's
#: controller). Stamped as `attacked_player_has_lowest_life` on the
#: trigger and checked by `effect_binder` off the ATTACKS event's own
#: `defending_player_id`, the `defender_controls_lands_at_least` idiom.
ATTACKED_PLAYER_LOWEST_LIFE_IF_RE = re.compile(
    r"^if no opponent has more life than that player,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-120: "whenever a creature attacks 1 of your opponents, that player
#: loses/gains N life." (Calculating Lich) — "that player" is RULE 506.4's
#: defending player again, the same referent the row above already reads
#: off the same phrase under a *self*-subject ATTACKS trigger; here the
#: subject is a group (any creature), so it's caught before the generic
#: group-subject "its controller" dispatch (see the call site).
ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE = re.compile(
    r"^that player (?P<verb>loses|gains) (?P<n>\d+) life\.?$", re.IGNORECASE,
)


CREATURE_EXPLORES_TRIGGER_RE = re.compile(
    r"^a creature you control explores(?: a (?P<result>land|nonland) card)?$",
    re.IGNORECASE,
)

#: RULE 603.3f — Quintorius, Field Historian: one trigger for the complete
#: zone-change event, whether one card is flashback-cast or many are returned
#: together. The optional timing tail is an intervening trigger condition.
CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more (?:(?P<types>[a-z]+(?:(?: and/or | or )[a-z]+)*) )?cards leave "
    r"your graveyard(?P<during> during your turn)?$"
)
#: PAR-245, RULE 603.2c: the per-card sibling -- "whenever a creature card leaves your / an opponent's graveyard" triggers
#: once for each card that leaves, so it listens to `CARD_LEFT_GRAVEYARD` (one event per card), not the batch.
CARD_LEAVES_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:a|an) (?P<types>[a-z]+(?:(?: and/or | or )[a-z]+)*) card leaves "
    r"(?P<owner>your|an opponent's) graveyard$"
)
#: The card-type words a typed graveyard exit may name ("creature cards", "artifact
#: and/or creature cards") — RULE 205.2a's card types, nothing else.
GRAVEYARD_EXIT_TYPES = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker",
    "sorcery", "kindred",
})

#: PAR-97 / RULE 701.13: a milling instruction moves a batch, so “one or
#: more [<type>] cards are put into your graveyard from your library” must
#: bind the aggregate event rather than the legacy per-card MILL_CARD event.
#: PAR-231: "whenever 1 or more nonland cards are milled" -- the same `CARDS_MILLED` batch, any player's library.
NONLAND_CARDS_MILLED_TRIGGER_RE = re.compile(r"^(?:1|one) or more nonland cards are milled$")
NONLAND_MILLED_COUNT: dict[str, Any] = {"kind": "trigger_event", "field": "nonland_count"}
CARDS_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more (?:(?P<type>artifact|creature|enchantment|instant|land|planeswalker|sorcery) )?"
    r"cards? are put into your graveyard from your library$"
)

#: Narcomoeba/Creeping Chill: this card's own zone-change trigger functions
#: from the graveyard it has just entered, unlike the battlefield batch
#: triggers above.  The source-id predicate identifies the relevant card in
#: the same milling-instruction snapshot.
#: RULE 702.62a: "the last time counter is removed from this card[ while it's
#: exiled]" (Riftmarked Knight/Veiling Oddity). The exile clause is redundant —
#: the event only ever fires for a suspended card in exile.
LAST_TIME_COUNTER_REMOVED_COND_RE = re.compile(
    r"^the last time counter is removed from (?:~|this card)(?: while it'?s exiled)?$",
    re.IGNORECASE,
)

SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:this card|~) is put into your graveyard from your library$"
)

#: Pedantic Learning's singular form is deliberately a per-card trigger,
#: unlike the “one or more” aggregate above.
ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^a (?P<type>artifact|creature|enchantment|instant|land|planeswalker|sorcery) card "
    r"is put into your graveyard from your library$"
)


#: RULE 303.4/301.5's "enchanted/equipped creature" trigger subject (Acquired
#: Mutation's "whenever enchanted creature attacks", a Sword's "whenever
#: equipped creature deals combat damage to a player" — the latter still
#: reaches the engine only via the hand-authored catalogue, since its own
#: wrapper is `_SELF_DAMAGE_TRIGGER_RE`'s ``~``-only grammar, not this one).
#: Maps onto `effect_binder._subject_condition`'s existing
#: ``{"subject": "attached_permanent"}`` predicate — that engine primitive
#: already exists (built for the Sword cycle); only the oracle-text
#: recognition was missing. ``permanent``/``land``/``artifact`` included
#: alongside ``creature`` since Auras/Equipment can enchant/equip any of
#: those on some real cards.
ATTACHED_SUBJECT_RE = re.compile(
    r"^(?:enchanted|equipped)\s+(?:creature|permanent|land|artifact)\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: The two-verb sibling — "whenever enchanted creature **attacks or blocks**,
#: …" (Sinister Possession / Contaminated Bond / Luminous Wake / the
#: Curse/Impetus Aura cycles). Maps to a list-valued ``event`` with a
#: ``{"subject": "attached_permanent"}`` condition, exactly the way
#: `SELF_MULTI_EVENT_RE` does for the bare-`~` subject.
ATTACHED_MULTI_EVENT_RE = re.compile(
    r"^(?:enchanted|equipped)\s+(?:creature|permanent|land|artifact)\s+"
    rf"(?P<v1>{_VERB_ALT})(?:\s+the\s+battlefield)?\s+or\s+"
    rf"(?P<v2>{_VERB_ALT})(?:\s+the\s+battlefield)?$"
)

#: RULE 603.1's condition subject scoped by a **designation** instead of a
#: characteristic: "whenever a **goaded** creature attacks" (Vengeful
#: Ancestor), "whenever a **goaded attacking or blocking** creature dies"
#: (Baeloth Barrityl), "whenever a goaded creature deals combat damage to one
#: of your opponents" (The Rani — through `_DAMAGE_TRIGGER_RE`'s own path).
#: Goaded is not a type, a subtype or a controller, so it needs its own key
#: (`effect_binder._build_group_ok`'s ``goaded``/``in_combat``) rather than a
#: value in one of the existing vocabularies. The "attacking or blocking"
#: qualifier rides along as ``in_combat`` because it only ever appears
#: attached to this subject on real cards; both are snapshotted onto the DIES
#: event, since RULE 400.7 means the object is gone by the time the check runs.
GOADED_SUBJECT_RE = re.compile(
    r"^(?P<article>an|a)\s+goaded\s+(?P<combat>attacking or blocking\s+)?"
    r"(?P<type>creature)\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: RULE 700.4's fully-spelled-out dies wording, with an owner-relative
#: graveyard rather than a controller-relative "you control" qualifier.
OWN_GRAVEYARD_DIES_SUBJECT_RE = re.compile(
    r"^(?P<article>an|a)\s+(?P<nontoken>nontoken\s+)?(?P<type>creature) "
    r"is put into your graveyard from the battlefield$"
)

#: MEC-49: RULE 603.1's condition subject scoped by *damage history* — "a
#: creature **dealt damage by ~ this turn** dies" (Baron Sengir, Abattoir
#: Ghoul, Blood Cultist &c.). Not a type/subtype/controller/designation, so
#: its own key (`effect_binder._build_group_ok`'s
#: ``damaged_by_source_this_turn``, a `GameState.creatures_damaged_by_
#: source_this_turn` lookup keyed on this ability's own source). Only
#: "dies" appears on real cards; the dying creature is anyone's ("a
#: creature", no "you control").
#: ``by ~`` — this ability's own source; ``by enchanted creature`` — the
#: Aura's host (Vampiric Embrace), resolved via ``via_attached`` in
#: `_build_group_ok`.
DAMAGED_BY_SOURCE_SUBJECT_RE = re.compile(
    r"^a\s+creature\s+dealt\s+damage\s+by\s+(?P<by>~|enchanted creature)\s+this\s+turn\s+dies$"
)
