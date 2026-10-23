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

import copy
import json
import re
from .catalogue.clause_reading import (
    COUNTERED, COUNTERED_REFERENT, CREATED, CREATED_GROUP_REFERENT, CREATED_REFERENT, SELECTOR, SELECTOR_REFERENT, STANDALONE, TARGET, TARGET_REFERENT,
    ClauseReading, Referent,
)
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from .catalogue.object_trigger_head import legacy_group_condition, parse_object_trigger_head
from .catalogue.cost_text import scan_cost_text
from .catalogue.count_phrase import SACRIFICED_TERM, parse_amount_phrase, parse_count_phrase
from .catalogue.spell_phrase import parse_spell_phrase
from .catalogue.clause_primitives import (
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    FROM_HAND_MARKER,
    ONCE_PER_TURN_MARKER,
    PLACEMENT_WITH_RIDERS,
    POWERUP_COST_REDUCTION_MARKER,
    TARGET_PARAM_KEYS,
    TRIGGER_ONCE_PER_TURN_MARKER,
    announces_creature_target,
    stamp_counters_on_referent,
)
from .catalogue.clause_hooks import register_segmenter
from .catalogue.flicker_sequences import (
    delayed_dying_return_specs,
    flicker_sequence_specs,
    linked_pool_return_specs,
    source_return_specs,
)
from .catalogue.dying_hosts import dying_host_return_specs
from .catalogue.physical_properties import physical_fight_specs
from .catalogue.target_groups import target_group_specs
from .catalogue.zone_ability_sequences import exile_grant_specs
from .catalogue.effect_rows.costs_mana_limits import MAY_COST_THEN_CLAUSE, MAY_EFFECT_THEN_ANTECEDENT_PHRASES
from .catalogue.effect_rows.draw_discard_cast import CYCLING_XX_TOKEN_RE, cycling_xx_token
from .catalogue.effect_rows.pump_stats import DELAYED_SAC_EXILE_TAIL_RE
from .catalogue.effect_rows.shared import base_verb
from .catalogue.handlers import match_clause
from .catalogue.keywords import ALIAS_DISPLAYS, EQUIP_DASH_COST_RE, EQUIP_ONCE_EACH_TURN_RE, GIFT_QUALITIES, KEYWORDS, KeywordShape
from .catalogue.referent_condition import PRONOUN_NOUN_ALT, parse_referent_condition
from .catalogue.replacements import replacement_clause_specs, standing_ability_kind
from .catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from .catalogue.static_handlers import (
    enter_choice_specs,
    static_condition,
    static_effect_specs,
)
from .catalogue.subgrammars import COLOR_WORD_ALT, resolve_color_word
from .spec import GROUP_SUBJECT_KEY_SENTINEL, TARGET_CHOOSER_OPPONENT, AbilitySpec, EffectSpec, ParserProvenance

#: RULE 603.1's object-subject trigger *verbs*, longest phrase first, each
#: mapped to the `EventType` the engine actually fires for it. **One table**
#: feeding everything below — `_TRIGGER_EVENTS` (which verb a condition
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
_TRIGGER_EVENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(verb) + r"\b"), event) for verb, event in _TRIGGER_VERBS
]

#: The same verbs as a plain phrase → `EventType` dict, for the compound
#: "~ enters or attacks" shape below (`_SELF_MULTI_EVENT_RE`) — kept
#: separate from `_TRIGGER_EVENTS`' regex/event pairs since that list is
#: matched by `.search()` (first hit wins, order matters for a single-verb
#: condition) while this one needs an exact per-verb lookup instead.
_VERB_EVENTS: dict[str, str] = {verb: event for verb, event in _TRIGGER_VERBS}

#: The verb alternation every RULE 603.1 subject regex below shares, in
#: `_TRIGGER_VERBS` order so a longer phrase always wins over a prefix of it.
_VERB_ALT = "|".join(re.escape(verb) for verb, _ in _TRIGGER_VERBS)

#: RULE 603.1's compound "~ <verb> or <verb>" trigger condition (The Wise
#: Mothman: "Whenever The Wise Mothman enters or attacks, ...") — two
#: *different* firing events for the same self-subject ability, not the
#: single-event shape `_trigger_event`/`_trigger_condition` handle (a bare
#: "~ enters or attacks" fails `_SELF_SUBJECT_RE`'s anchored single-verb
#: match today, so it already fails closed rather than silently binding
#: just the first verb — this is real, additional recognition, not a bugfix).
#: Self-subject only (no real card needs a "group"/"attached_permanent"
#: compound-event trigger yet); `AbilitySpec.trigger["event"]` becomes a
#: *list* of two `EventType` strings instead of one, and `effect_binder.
#: bind_ability` builds one `TriggeredAbility` per listed event, each with
#: its own freshly-bound effects (never sharing effect instances across the
#: two abilities).
#: RULE 712.8: "transforms into ~" is a self-subject firing condition with
#: no bare-verb spelling — it always names the face transformed *into* (a
#: DFC front face, folded to "~" by `normalize`). The `TRANSFORMED` engine
#: event (fired by `RulesEngine.transform_permanent`) carries the object's
#: own `instance_id`, so `_SUBJECT_EVENT_KEYS`' default self scoping matches
#: it exactly like `ENTERS_BATTLEFIELD`; the face-name gate is implicit —
#: the trigger only *exists* on the object while it's that face (abilities
#: are rebound per face).
_MULTI_EVENT_VERB_ALT = _VERB_ALT + r"|transforms into ~"
_MULTI_EVENT_EXTRA = {"transforms into ~": "TRANSFORMED"}
_SELF_MULTI_EVENT_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|land|permanent|equipment))\s+"
    rf"(?P<v1>{_MULTI_EVENT_VERB_ALT})(?:\s+the\s+battlefield)?"
    r"\s+or\s+"
    rf"(?P<v2>{_MULTI_EVENT_VERB_ALT})(?:\s+the\s+battlefield)?$"
)


def _multi_event_name(token: str) -> str:
    return _MULTI_EVENT_EXTRA.get(token.lower(), _VERB_EVENTS.get(token.lower(), ""))


#: "When ~ enters **and at the beginning of your first main phase**, …"
#: (Crack in Time — a Vanishing enchantment that re-exiles each of its own
#: upcoming main phases). Two firing conditions with *different* triggers:
#: a self-subject `ENTERS_BATTLEFIELD` and a controller-scoped `STEP_BEGIN`
#: filtered to the precombat main step — handled the same one-spec-per-event
#: way as `_VARIANT_TRIGGER_CONDITIONS`' compound plane template, since the
#: phase half's `{"step": …}` filter can't ride the enters half's payload.
_ENTERS_AND_MAIN_PHASE_RE = re.compile(
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
#: `_trigger_event`/`_trigger_condition` see.
#: Each maps to one `EventType` and needs no subject scoping: only the
#: face-up plane's own abilities are ever collected in the first place
#: (`game/variants.py`'s `command_zone_ability_sources`), so "this plane" is
#: the only plane there is.
#:
#: The compound "when you planeswalk to ~ **and at the beginning of your
#: upkeep**" is the single commonest plane template (22 of 207), and is two
#: firing conditions — handled the same way `_SELF_MULTI_EVENT_RE` handles
#: "~ enters or attacks": `AbilitySpec.trigger["event"]` becomes a list, and
#: the binder builds one ability per event. Its upkeep half needs no
#: `phase_relation`: a plane's controller is whoever last planeswalked to it,
#: and the upkeep meant is theirs.
_VARIANT_TRIGGER_CONDITIONS: tuple[tuple[re.Pattern[str], Any], ...] = (
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
_ONCE_PER_TURN_CONDITION_SUFFIX_RE = re.compile(
    r"^(?P<base>.+?)\s+for the first time each turn$", re.IGNORECASE
)


def _strip_trigger_once_per_turn_marker(effects: list[EffectSpec]) -> tuple[list[EffectSpec], bool]:
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
#: than the generic `TRIGGER_RE`/`_trigger_event`/`_trigger_condition`
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
_MAGECRAFT_RE = re.compile(
    r"^magecraft\s*—\s*whenever you cast or copy an instant or sorcery spell,\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 701.42a Meld, phase-trigger form: "At the beginning of <phase>, if
#: you both own and control ~ and a[n] <type> named <X>, exile them, then
#: meld them into <Y>." (Gisela, the Broken Blade — your end step; Graf Rats
#: — combat on your turn). A dedicated whole-line recognizer, like
#: `_MAGECRAFT_RE`, because the "if you both own and control … and a
#: creature named …" gate is meld-specific and the partner/result names
#: carry commas. The RULE 603.4 intervening-if is dropped: `MeldEffect`
#: re-checks own+control of the named partner at resolution and fails
#: closed, so the board outcome is identical. Titania's own extra
#: "if there are N land cards in your graveyard and …" prefix deliberately
#: doesn't match here (a compound condition of its own).
_MELD_TRIGGER_RE = re.compile(
    r"^at the beginning of (?:your )?(?P<step>upkeep|draw|end|combat)"
    r"(?: step| on your turn)?, if you both own and control ~ and "
    r"(?:an?|the) (?:creature|land|artifact|permanent) named (?P<partner>.+?), "
    r"exile them, then meld them into (?P<result>.+?)\.?$",
    re.IGNORECASE,
)
_ATTACK_MELD_TRIGGER_RE = re.compile(
    r"^whenever you attack, (?P<before>.+?)\. if ~ and a creature named "
    r"(?P<partner>.+?) are attacking, and you both own and control them, exile them, "
    r"then meld them into (?P<result>.+?)\. it enters tapped and attacking\.?$",
    re.IGNORECASE,
)


def _cast_spell_trigger_condition(subj: str) -> dict[str, Any]:
    """``{"subject": …}`` for a cast-spell/draw-card trigger's ``you``/``an
    opponent``/``a player`` subject — shared by the composed cast head
    (`_CAST_TRIGGER_COMPOSED_RE`), `_DRAW_TRIGGER_PLAIN_RE` and the remaining
    bespoke cast rows, so the three-way mapping lives in exactly one place."""
    subj = subj.lower()
    if subj == "you":
        return {"subject": "you"}
    if subj == "an opponent":
        return {"subject": "group", "controller": "not_you"}
    return {"subject": "group"}

#: PAR-119: the composed cast-trigger head — actor + "cast" + a spell phrase
#: that `catalogue.spell_phrase.parse_spell_phrase` builds from shared word
#: tables (characteristic adjectives, ``with`` qualifiers, cast-from zone,
#: ownership, targets). One row for what used to be one regex *and* one ~25-line
#: dispatch block per adjective combination. PAR-131 retired those rows
#: (`_CAST_SPELL_TRIGGER_RE`, `_NEG_`, `_PLAIN_`, `_MV_`, `_HISTORIC_`, …): this
#: head now owns every plain "you/an opponent/a player cast(s) a <phrase> spell".
_CAST_TRIGGER_COMPOSED_RE = re.compile(
    r"^(?:whenever|when) (?P<subj>you|an opponent|a player) casts? "
    r"(?P<copies>or (?:copy|copies) )?"
    # PAR-104: a comma list of card types ("an artifact, instant, or sorcery spell") is part of the phrase.
    r"(?P<phrase>(?:an?|another|your|their) (?:(?:[a-z'-]+, )+or [a-z'-]+ |[^,]*?)\bspell\b[^,]*),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def _cast_trigger_segment(
    raw: str, subj: str, trigger_keys: dict[str, Any], body_text: str, provenance: ParserProvenance
) -> Segment:
    """The one dispatch for a `SPELL_CAST` trigger whose head is already parsed
    into ``trigger_keys``: optional peel, the two-rider mana-spent shape, the
    intervening "if at least N mana was spent", then the body."""
    body, optional = peel_optional(body_text)
    trigger = {
        "event": "SPELL_CAST",
        "condition": _cast_spell_trigger_condition(subj),
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
    effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
    if not effects:
        return Segment(raw=raw)
    if body_limit:
        trigger = {**trigger, "limit": True}
    if mana_spent_at_least is not None:
        trigger = {**trigger, "spell_mana_spent_at_least": mana_spent_at_least}
    spec = AbilitySpec("triggered", effects=effects, trigger=trigger,
        optional=optional, raw_text=raw, parser=provenance)
    return Segment(raw=raw, spec=spec, claimed=True)


_CAST_TWO_COLOR_SPELL_TRIGGER_RE = re.compile(
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
#: filter combination (`_COUNTER_FREE_SPELL_RE`'s own "no mana spent"
#: shape is exactly the one-regex-per-combination pattern
#: handler-recipe.md's decomposition rule warns against) — wired into
#: whichever cast-trigger dispatch a real card needs it on, same
#: "extend as a real card needs it" convention as `_FILTER_KEYWORD_WORDS`.
_SPELL_MANA_SPENT_AT_LEAST_IF_RE = re.compile(
    r"^if at least (?P<n>\d+) mana was spent to cast (?:it|that spell),\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

_ADAMANT_MANA_SPENT_IF_RE = re.compile(
    r"^if at least (?P<n>\d+) (?P<color>white|blue|black|red|green|colorless) mana was spent to cast "
    r"(?:it|this spell),\s*(?P<rest>.+)$", re.IGNORECASE | re.S,
)

_ADAMANT_MANA_KEYS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C",
}


def _adamant_mana_spent_condition(m: "re.Match[str]") -> dict[str, Any]:
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
_DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE = re.compile(
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
_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE = re.compile(
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
#: creature. Tried before `_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE` — the
#: "targets ~" and "targets 1 or more permanents" clauses don't overlap,
#: this is just for locality.
#: "Whenever you cast a spell that shares a creature type with ~, …"
#: (Folk Hero's granted trigger) — `effect_binder`'s ``spell_shares_
#: creature_type_with_source`` predicate compares the still-on-stack
#: spell's subtypes with the ability's source.
_CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE = re.compile(
    r"^whenever you cast a spell that shares a creature type with ~,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
_CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE = re.compile(
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
_CAST_THIS_SPELL_TRIGGER_RE = re.compile(
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
_COUNTER_FREE_SPELL_RE = re.compile(
    r"^whenever a player casts a spell, if no mana was spent to cast it,\s*"
    r"counter that spell\.?\s*$",
    re.IGNORECASE,
)

#: "counter that spell" / "counter it" as the *body* of a SPELL_CAST-
#: triggered ability — resolves off the firing event's own object
#: (`CounterSpellEffect.target_from_trigger_event`, same idiom as
#: `_COUNTER_FREE_SPELL_RE` at line ~3571), not a RULE 115 target.
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
#: ``spell_no_mana_spent`` gate exactly as `_COUNTER_FREE_SPELL_RE` does;
#: only the body is generic here rather than hardcoded to "counter that
#: spell". Tried *after* the exact-match row above so a real Vexing Bauble
#: still gets that row's more specific ``target_from_trigger_event``
#: wording (both bind to the same behaviour either way, so order is a
#: style choice, not a correctness one).
_CAST_SPELL_NO_MANA_TRIGGER_RE = re.compile(
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
_ENTERS_IF_CAST_RE = re.compile(
    r"^when ~ enters, if you cast it,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

#: PAR-139, RULE 702.35 / 603.4: "When ~ enters, if its madness cost was paid, `<effect>`." (Grave Scrabbler) — the
#: intervening-if reads the flag `RulesEngine.cast_spell` stamped (`GameObject.madness_cost_paid`). RULE 702.117's
#: "if its surge cost was paid" (Reckless Bushwhacker, Tyrant of Valakut) is the same shape on `surge_cost_paid`.
_ENTERS_IF_MADNESS_PAID_RE = re.compile(
    r"^when ~ enters, if its (?P<cost>madness|surge) cost was paid,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)

_CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE = re.compile(
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
_DRAW_TRIGGER_PLAIN_RE = re.compile(
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
_CAST_SPELL_ORDINAL_WORDS: dict[str, int] = {"first": 1, "second": 2, "third": 3, "fourth": 4}

#: "Whenever you draw your second card each turn, …" / "Whenever an opponent
#: draws their second card each turn, …" (Faerie Mastermind / Bard the
#: Bowman / The Unagi of Kyoshi Island — the ~44-SOLO ordinal-draw cluster).
#: The draw-side sibling of `_CAST_SPELL_TRIGGER_NTH_RE`, reusing its closed
#: ordinal→int map; `effect_binder`'s ``is_nth_draw_this_turn`` predicate
#: (`GameState.cards_drawn_this_turn`, RULE 120.3) is already proven by
#: Faerie Mastermind's hand-authored entry, so this is purely the missing
#: oracle-text recognizer.
_DRAW_CARD_TRIGGER_NTH_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) draws? (?:your|their) "
    rf"(?P<ordinal>{'|'.join(_CAST_SPELL_ORDINAL_WORDS)}) card each turn,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
#: "Reveal the first card you draw each turn. Whenever you reveal a
#: `<type>` card this way, …" (Primitive Etchings, Rowen): the reveal has no
#: game effect of its own here, so it is the first-draw trigger above with
#: its body gated on that card's type.
_REVEAL_FIRST_DRAW_RE = re.compile(
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
#: way `_cast_spell_trigger_condition` does for cast/draw triggers, "a
#: player" leaves it unscoped (any player's land).
#: Effect types that add mana — a `TAPPED_FOR_MANA` trigger whose body is only these is a
#: RULE 605.1b triggered mana ability.
_MANA_ADDING_EFFECTS: frozenset[str] = frozenset({"add_mana", "mirror_produced_mana"})

_TAP_FOR_MANA_TRIGGER_RE = re.compile(
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
_ETB_AND_CAST_TRIGGER_RE = re.compile(
    r"^(?:when|whenever) ~ enters and whenever (?P<cast_clause>you casts? .+?),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


#: "Whenever you cast a **red** spell, …" (Balefire Liege, Runaway Steam-Kin)
#: — a single colour word in `_CAST_SPELL_TRIGGER_RE`'s ``types`` slot maps
#: to `effect_binder`'s existing ``cast_of_color`` trigger key (a live
#: colour check on the cast object). "colorless" is deliberately excluded:
#: `cast_of_color` is a membership test, not an empty-identity one.
_CAST_SPELL_COLOR_WORDS: dict[str, str] = {
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
_CYCLE_TRIGGER_RE = re.compile(
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
_OPPONENT_CAUSED_DISCARD_TRIGGER_RE = re.compile(
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
_CAUSED_DISCARD_REPLACEMENT_RE = re.compile(
    r"^if a spell or ability an opponent controls causes you to discard (?:~|this card),\s*"
    r"put it onto the battlefield instead of putting it into your graveyard\.?$",
    re.IGNORECASE,
)


def _caused_discard_effects(body: str, is_self: bool) -> Optional[list[EffectSpec]]:
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
_SACRIFICE_TYPE_TRIGGER_RE = re.compile(
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
_BASIC_LAND_TYPE_SINGULAR: dict[str, str] = {
    "swamps": "swamp", "swamp": "swamp", "islands": "island", "island": "island",
    "plains": "plains", "mountains": "mountain", "mountain": "mountain",
    "forests": "forest", "forest": "forest",
}
#: PAR-152 (Olivia, Crimson Bride's granted ability): "When you don't control a legendary Vampire, exile ~." — the
#: state trigger of RULE 603.8 over a legendary/subtype quality, the sibling of the basic-land-type row below.
_CONTROL_NONE_MATCHING_RE = re.compile(
    r"^when you don'?t control an? (?P<leg>legendary )?(?P<sub>[a-z]+),\s*"
    r"(?P<body>(?:sacrifice|exile) (?:~|this \w+))\.?$",
    re.IGNORECASE | re.S,
)
_CONTROL_NONE_SACRIFICE_RE = re.compile(
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
_EXERT_TRIGGER_RE = re.compile(
    r"^(?:if ~ hasn'?t been exerted this turn,\s*)?"
    r"you may exert (?:~|it) as (?:it|he|she) attacks\.\s*when you do,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: The bare rider with no "when you do" bonus (Rakdos Cackler-shaped) —
#: `combat.has`/`declare_attackers` already give it real behaviour off the
#: Scryfall keyword alone, so this is a pure `keyword_line` claim, the same
#: "covered, contributes no spec" idiom every other bare keyword sentence
#: uses.
_EXERT_BARE_RE = re.compile(
    r"^you may exert ~ as (?:it|he|she) attacks\.$", re.IGNORECASE,
)

#: RULE 603.1's "whenever you exert a creature, `<effect>`." (Rafiq of the
#: Many-adjacent payoffs, e.g. Long-Term Plans-cycle rewards) — a
#: player-subject trigger like `_SACRIFICE_TYPE_TRIGGER_RE`, just with no
#: type filter (any creature the ability's controller exerts, including
#: itself) since `EventType.EXERTED`'s own ``player_id`` is already scoped
#: to *who* exerted, not *what*.
_EXERT_PLAYER_TRIGGER_RE = re.compile(
    r"^whenever you exert a creature,\s*(?P<body>.+)$", re.IGNORECASE | re.S,
)


#: RULE 500.7's "at the beginning of the [upkeep/draw/end/…] step" turn-
#: structure trigger family — a genuinely common template distinct from
#: RULE 603.1's object-subject "when/whenever X enters/dies/attacks/blocks"
#: shape `_trigger_condition` handles above, so it's a separate, dedicated
#: recognizer (checked before the generic `TRIGGER_RE` dispatch, which
#: would otherwise also match "at ..." but then fail to classify the
#: condition text) rather than another `_trigger_condition` subject shape.
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
_PHASE_STEP_WORDS: dict[str, str] = {
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
_EACH_MAIN_PHASE_STEPS = ("main1", "main2")

#: The step/phase alternation, longest first so "first main phase" wins over
#: any prefix of it.
_PHASE_STEP_ALT = "|".join(
    re.escape(word) for word in sorted(_PHASE_STEP_WORDS, key=len, reverse=True)
)

#: "At the beginning of each player's upkeep, ~ deals N damage to them."
#: (Roiling Vortex/Manabarbs-adjacent punishers) — tried only inside the
#: unscoped ``"each player's <step>"`` branch of `_PHASE_TRIGGER_RE` below
#: (`relation is None`), where "them" unambiguously means whoever's step
#: it is: `effects.DealDamageEffect`'s new ``selector="active_player"``
#: (`GameState.active_player`, read live at resolution — unchanged since
#: the step began). Not folded into the generic `_SELECTOR_WORD_MAP` "that
#: player"/``event_player`` row, since STEP_BEGIN carries no acting player
#: on the event at all — a body-only regex has no way to know which
#: pronoun meaning applies outside this specific wrapper.
_PHASE_DAMAGE_TO_THEM_RE = re.compile(
    r"^(?:~|it) deals (?P<n>\d+) damage to (?:them|that player)\.?\s*$", re.IGNORECASE,
)

#: PAR-120: "at the beginning of each opponent's/each player's `<step>`, if
#: that player has `<N or fewer>`/no cards in hand, `<effect>`." (Davriel,
#: Rogue Shadowmage; the Shrieking Affliction/Hellfire Mongrel/Lavaborn Muse
#: "hellbent-punisher" cluster) — "that player" is the same whoever's-step-
#: it-is referent `_PHASE_DAMAGE_TO_THEM_RE` already reads, one clause
#: earlier: a phase-trigger-only peel (not folded into the shared
#: `static_condition()` table `_GENERIC_IF_PREFIX_RE` also reaches) because
#: the identical wording means something else entirely off this surface —
#: an activated ability's own "target opponent discards a card. then if
#: **that player** has no cards in hand, …" (Nezumi Shortfang) means the
#: just-targeted opponent, not whoever's turn it is.
_THAT_PLAYER_HAND_IF_RE = re.compile(
    r"^if that player has (?:no cards|(?P<n>\d+) or fewer cards) in hand,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: The handful of effect-verb shapes this cluster's bodies use, each aimed
#: at the same "that player"/"them" referent (`effect_operands.PLAYER_
#: SCOPES`' own ``"active_player"`` string, already resolved generically by
#: `DrawCardEffect.player`/`LoseLifeEffect.player`'s ENG-37 operand path —
#: no new engine code needed for either). The damage shape is
#: `_PHASE_DAMAGE_TO_THEM_RE` above, tried by the caller first.
_ACTIVE_PLAYER_DRAWS_RE = re.compile(
    r"^that player draws (?P<n>\d+) cards?\.?\s*$", re.IGNORECASE,
)
_ACTIVE_PLAYER_LOSES_LIFE_RE = re.compile(
    r"^(?:they|that player) lose[s]? (?P<n>\d+) life\.?\s*$", re.IGNORECASE,
)


def _active_player_phase_body(rest: str) -> Optional[list[EffectSpec]]:
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
    # RULE 504 / 109.5: a phase's "that player" is the player whose turn
    # it is. Reuse second-person bodies, including optional choices and
    # linked instructions, while retaining the actual ability controller.
    # Explicit "you" or a target would introduce another player referent.
    if rest.startswith("that player ") and not re.search(r"\b(?:you|your|target)\b", rest):
        rewritten = re.sub(r"\bthat player\b|\bthey\b", "you", rest)
        rewritten = re.sub(r"\btheir\b", "your", rewritten)
        rewritten = re.sub(r"\byou (draws|loses|gains|searches|puts|discards|shuffles)\b",
                           lambda m: "you " + base_verb(m.group(1)), rewritten)
        rewritten = re.sub(r"\bthen (draws|discards)\b",
                           lambda m: "then " + base_verb(m.group(1)), rewritten)
        effects = parse_effect_body(rewritten)
        if effects is not None:
            return [EffectSpec("trigger_subject_referent", {
                "acting": "active_player", "effects": [e.to_dict() for e in effects],
            })]
    m = _PHASE_DAMAGE_TO_THEM_RE.match(rest)
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
_ANOTHER_SUBTYPE_ENTERED_IF_RE = re.compile(
    r"^if another (?P<sub>[a-z][a-z-]+) entered the battlefield "
    r"under your control this turn,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-32 phase-trigger intervening-ifs backed by two new per-turn
#: `static_conditions` trackers (`GameState.creature_card_to_graveyard_
#: this_turn` / `damage_dealt_by_this_turn`) — Cloakwood Hermit /
#: Dragon Cultist's granted end-step token makers.
_CREATURE_CARD_TO_GY_IF_RE = re.compile(
    r"^if a creature card was put into your graveyard from anywhere this turn,"
    r"\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_YOU_DEALT_DAMAGE_IF_RE = re.compile(
    r"^if a source you controlled dealt (?P<n>\d+) or more damage this turn,"
    r"\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: MEC-79 / RULE 701.64b — the leading "if ~ is harnessed," that
#: `normalize._rewrite_infinity_ability` injects when it turns an Infinity
#: Stone's "``∞ —``" marker line into an ordinary phase trigger. Peeled here
#: into the trigger's own `active_if` (`static_conditions`' ``source_harnessed``).
_SOURCE_HARNESSED_IF_RE = re.compile(
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
_CONTROL_NO_SUBTYPE_WORDS: frozenset[str] = frozenset({
    "snake", "pest", "thopter", "zombie", "saproling", "spirit", "goblin",
    "elf", "soldier", "insect", "wolf", "cat", "bird", "elemental", "dragon",
    "servo", "myr", "golem", "wall", "faerie", "rat", "squid", "eldrazi",
})
_YOU_CONTROL_NO_SUBTYPE_IF_RE = re.compile(
    r"^if you (?:control no (?P<sub1>[a-z][a-z-]+?)s"
    r"|don'?t control (?:a|an|any) (?P<sub2>[a-z][a-z-]+?)(?: creature)?(?: token)?)"
    r",\s*(?P<rest>.+)$",
    re.IGNORECASE | re.DOTALL,
)

_PHASE_TRIGGER_RE = re.compile(
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
    r"),\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 603.1's condition *subject* — "self" ("~"/"this creature" itself) —
#: scoped so e.g. "when ~ enters the battlefield, draw a card" only fires for
#: its own source, never any other permanent entering (the over-firing bug
#: this grammar exists to close). The verb itself is still resolved by
#: `_trigger_event` above; this only decides *whose* enters/dies/attacks/
#: blocks the ability cares about. "class" is included directly (rather than
#: relying on `normalize._fold_self_reference`, which deliberately leaves
#: "this Class"/"this Saga" un-folded to ``~`` — its own docstring notes they
#: have "their own dedicated parsing") since a Class commonly opens with
#: "When this Class enters, <effect>." (RULE 716) and has no other automatic
#: ETB effect the way a Saga's chapter I gives it — "saga" is deliberately
#: left out: real Saga cards never print this phrasing outside stripped
#: reminder text (chapter I already covers it).
_SELF_SUBJECT_RE = re.compile(
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
_ATTACKS_DEFENDER_LANDS_RE = re.compile(
    r"^(?:~|this creature) attacks a player who controls (?P<n>\d+) or more lands$"
)

#: PAR-79 fifth increment: "~ attacks the player with the most life or tied
#: for most life" (Undercover Butler/Seraphic Greatsword/Preacher of the
#: Schism) — the same "gate an ordinary ATTACKS trigger on a defender
#: property" idiom as `_ATTACKS_DEFENDER_LANDS_RE` just above, this time via
#: `defender_has_most_life_predicate` (`game/binding/core.py`).
_ATTACKS_DEFENDER_MOST_LIFE_RE = re.compile(
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
_ATTACKED_PLAYER_LOWEST_LIFE_IF_RE = re.compile(
    r"^if no opponent has more life than that player,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-120: "whenever a creature attacks 1 of your opponents, that player
#: loses/gains N life." (Calculating Lich) — "that player" is RULE 506.4's
#: defending player again, the same referent the row above already reads
#: off the same phrase under a *self*-subject ATTACKS trigger; here the
#: subject is a group (any creature), so it's caught before the generic
#: group-subject "its controller" dispatch (see the call site).
_ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE = re.compile(
    r"^that player (?P<verb>loses|gains) (?P<n>\d+) life\.?$", re.IGNORECASE,
)


_CREATURE_EXPLORES_TRIGGER_RE = re.compile(
    r"^a creature you control explores(?: a (?P<result>land|nonland) card)?$",
    re.IGNORECASE,
)

#: RULE 603.3f — Quintorius, Field Historian: one trigger for the complete
#: zone-change event, whether one card is flashback-cast or many are returned
#: together. The optional timing tail is an intervening trigger condition.
_CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more (?:(?P<types>[a-z]+(?:(?: and/or | or )[a-z]+)*) )?cards leave "
    r"your graveyard(?P<during> during your turn)?$"
)
#: The card-type words a typed graveyard exit may name ("creature cards", "artifact
#: and/or creature cards") — RULE 205.2a's card types, nothing else.
_GRAVEYARD_EXIT_TYPES = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker",
    "sorcery", "kindred",
})

#: PAR-97 / RULE 701.13: a milling instruction moves a batch, so “one or
#: more [<type>] cards are put into your graveyard from your library” must
#: bind the aggregate event rather than the legacy per-card MILL_CARD event.
_CARDS_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
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
_LAST_TIME_COUNTER_REMOVED_COND_RE = re.compile(
    r"^the last time counter is removed from (?:~|this card)(?: while it'?s exiled)?$",
    re.IGNORECASE,
)

_SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:this card|~) is put into your graveyard from your library$"
)

#: Pedantic Learning's singular form is deliberately a per-card trigger,
#: unlike the “one or more” aggregate above.
_ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
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
_ATTACHED_SUBJECT_RE = re.compile(
    r"^(?:enchanted|equipped)\s+(?:creature|permanent|land|artifact)\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: The two-verb sibling — "whenever enchanted creature **attacks or blocks**,
#: …" (Sinister Possession / Contaminated Bond / Luminous Wake / the
#: Curse/Impetus Aura cycles). Maps to a list-valued ``event`` with a
#: ``{"subject": "attached_permanent"}`` condition, exactly the way
#: `_SELF_MULTI_EVENT_RE` does for the bare-`~` subject.
_ATTACHED_MULTI_EVENT_RE = re.compile(
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
_GOADED_SUBJECT_RE = re.compile(
    r"^(?P<article>an|a)\s+goaded\s+(?P<combat>attacking or blocking\s+)?"
    r"(?P<type>creature)\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: RULE 700.4's fully-spelled-out dies wording, with an owner-relative
#: graveyard rather than a controller-relative "you control" qualifier.
_OWN_GRAVEYARD_DIES_SUBJECT_RE = re.compile(
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
_DAMAGED_BY_SOURCE_SUBJECT_RE = re.compile(
    r"^a\s+creature\s+dealt\s+damage\s+by\s+(?P<by>~|enchanted creature)\s+this\s+turn\s+dies$"
)

def _is_activation_cost(cost: str) -> bool:
    """Whether the text left of a colon is an activation cost (RULE 602.1):
    the lexical `_COST_LOOKS_REAL` sniff, or (ENG-51) a text the cost
    grammar reads *completely* — "Tap enchanted creature", "Pay half your
    life, rounded up", "Exile the top card of your graveyard" name no symbol
    the sniff keys on, yet nothing in them is left unread."""
    if _COST_LOOKS_REAL.search(cost):
        return True
    scan = scan_cost_text(cost)
    return scan.leftover is None and bool(set(scan.hits) - {"ability_word"})


#: ENG-51: "`<cost>` or `<cost>`: …" — two alternative costs, each starting
#: with a mana/tap symbol ("{3}, {T} or {U}, {T}", Crystal Shard).
_ALTERNATIVE_COST_RE = re.compile(r"(?P<a>\{[^:]*?\})\s+or\s+(?P<b>\{[^:]*)", re.IGNORECASE)

#: The one announced-X mana effect the engine scales — mirrors `game/
#: mana_abilities._ADD_X_ANY_ONE_COLOR_RE` (the front-end can't import it).
_MANA_ABILITY_X_SUPPORTED_RE = re.compile(
    r"add x mana of any (?:one|1) colou?r\.?(?:\s*you gain x life\.?)?", re.IGNORECASE
)
#: A "Sacrifice X `<things>`" cost on a *mana* ability — see its guard.
_MANA_ABILITY_SACRIFICE_X_RE = re.compile(r"\bsacrifice x\b", re.IGNORECASE)

#: An activated-ability wrapper: "<cost>: <effect>" (RULE 602.1). The cost is
#: everything before the first colon. Excludes `"` from the cost group too —
#: a real cost never contains a literal quote, but a quoted-ability-grant
#: line ("equipped creature has '{3}, {Q}: ...'") does, and its *inner*
#: colon isn't this line's own cost/effect boundary; without this guard the
#: quote-blind ``[^:]+`` swallows straight through to that inner colon
#: first, so the grant is never reached by `static_effect_specs` below.
_ACTIVATED_RE = re.compile(r'^(?P<cost>[^:"]+):\s*(?P<effect>.+)$', re.S)

#: Throne of Eldraine's colour-lock rider on its second ability — a trailing
#: "Spend only mana of the chosen color to activate this ability." sentence,
#: peeled off the effect body and recorded as an `ActivationCost` flag.
_SPEND_ONLY_CHOSEN_COLOR_RE = re.compile(
    r"\s*\.?\s*spend only mana of the chosen colou?r to activate this ability\.?",
    re.IGNORECASE,
)

#: "This ability costs {1} less to activate for each creature in your
#: party." (Seafloor Stalker, PAR-72) — a trailing sentence on the ability's
#: own effect body, peeled off and folded into `ActivationCost.
#: dynamic_reduction` (already wired for a `count_selector`-scaled per-
#: activation reduction, `costs.parse_activation_cost`'s ``dynamic_
#: reduction`` key — Eiganjo, Seat of the Empire's own hand-authored shape,
#: PAR-72 is the oracle-text route to the same primitive) rather than
#: becoming a (non-existent) effect.
_ACTIVATION_COST_REDUCTION_PARTY_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate "
    r"for each creature in your party\.?",
    re.IGNORECASE,
)

# PAR-94: the general trailing, per-unit activation discount.  This stays a
# closed vocabulary: the engine may only receive a count selector it actually
# evaluates, and a novel "for each" phrase must leave its card unclaimed.
_ACTIVATION_COST_REDUCTION_FOR_EACH_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate "
    r"for each (?P<what>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)

_ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate if there are "
    r"(?P<minimum>\d+) or more mana values among cards in your graveyard\.?$",
    re.IGNORECASE,
)

_ACTIVATION_COST_REDUCTION_CONDITIONAL_RE = re.compile(
    r"\s*\.?\s*this ability costs \{(?P<n>\d+)\} less to activate if "
    r"(?P<condition>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)
_ACTIVATION_COST_REDUCTION_COLORED_RE = re.compile(
    r"\s*\.?\s*this ability costs (?P<generic>\{\d+\})?"
    r"(?P<symbols>(?:\{[WUBRG]\})+) less to activate if "
    r"(?P<condition>.+?)(?=\.?\s*(?:activate\b|$))",
    re.IGNORECASE,
)

#: PAR-120: the quantity a counter-gated leaving trigger goes on to use —
#: "…if it had 1 or more +1/+1 counters on it, you may put **that many**
#: +1/+1 counters on target creature" (Reyhan), "…if it had counters on it,
#: create x … tokens, **where x is the number of counters on that
#: creature**" (Felisa). Both name the departing object's counters, which only
#: the event's RULE 400.7 snapshot still holds (`effect_amounts`'
#: ``trigger_event_counter``). Recognized only behind that gate, where "that
#: many" can mean nothing else.
_LEAVING_COUNTER_THAT_MANY_RE = re.compile(r"\bthat (?:many|number of)\b", re.IGNORECASE)
_LEAVING_COUNTER_WHERE_X_RE = re.compile(
    r"^(?P<rest>.+?),\s*where x is the number of (?:(?P<kind>\+1/\+1|-1/-1|[a-z]+) )?"
    r"counters (?:it had )?on (?:that creature|that permanent|it)\.?$",
    re.IGNORECASE | re.DOTALL,
)
_LEAVING_COUNTER_COPY_RE = re.compile(
    r"^create (?P<count>\d+) tokens? that are copies of it\.?$", re.IGNORECASE,
)
_LEAVING_COUNTER_RETURN_LOSE_RE = re.compile(
    r"^return it to the battlefield under its owner'?s control and "
    r"it loses all abilities\.?$", re.I,
)
_LEAVING_COUNTER_IF_ELSE_RE = re.compile(
    r"^exile it if it had a (?P<kind>[a-z]+) counter on it\.\s*"
    r"otherwise,? return it to the battlefield under your control and "
    r"put a (?P=kind) counter on it\.?$", re.I | re.S,
)
#: "…, create a token that's a copy of it at the beginning of the next end
#: step. The token enters with half that many +1/+1 counters on it, rounded
#: down." (Ochre Jelly's Split). "That many" may already read "x" here.
_LEAVING_COUNTER_DELAYED_COPY_RE = re.compile(
    r"^create a token that's a copy of it at the beginning of the next end step\.\s*"
    r"the token enters with half (?:that many|x) (?P<kind>\+1/\+1|[a-z]+) counters on it,"
    r" rounded down\.?$", re.I | re.S,
)
_LEAVING_COUNTER_CREATE_TRANSFER_RE = re.compile(
    r"^(?P<create>create a 0/0 [^.]+? creature token),? then "
    r"put ~'s counters on that token\.?$", re.I | re.S,
)

_COST_PAID_SOURCE_HAD_RE = re.compile(
    r"\bif it had (?P<n>\d+) or more (?P<kind>\+1/\+1|[a-z]+) counters on it,", re.I,
)
_LEAVING_COUNTER_INTERVENING_RE = re.compile(
    r"^if it had (?:(?P<no>no)|(?P<count>\d+) or more|(?P<article>a|an))?\s*"
    r"(?P<kind>\+\d+/\+\d+|\-\d+/\-\d+|[a-z]+)?\s*"
    r"counters? on it,\s*(?P<rest>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-120 (PARSER_VERSION 470): PAR-94's original 14-entry table shrunk to
#: the six shapes the shared `count_phrase` grammar genuinely doesn't reach
#: — a distinct-land-*type* count (not an object count), the "and" union
#: idiom (RULE 400.1, same reasoning as `static_handlers._SELF_COST_PER_PHRASES`), a
#: two-card-type union, and the "other `<X>`"/"modified `<X>`" qualifiers
#: (`not_reference`/a modified flag aren't reachable through this entry
#: point — confirmed via direct `parse_count_phrase` checks, not assumed).
#: A `+1/+1 counter` *count* is a different measurement axis entirely (how
#: many counters, not how many objects), so it was never going to be a
#: `count_phrase` selector regardless. `_activation_cost_reduction_selector`
#: below tries the grammar first for everything else — six of the original
#: fourteen entries retired that way, plus the old `island`-only land
#: fallback (the same subtype match the grammar already makes generically).
_ACTIVATION_COST_REDUCTION_SELECTORS: dict[str, str] = {
    "basic land type among lands you control": "basic_land_types_among_lands_you_control",
    "instant and sorcery card in your graveyard": "instant_or_sorcery_cards_in_your_graveyard",
    "legendary creature and planeswalker you control": "legendary_creatures_and_planeswalkers_you_control",
    "other artifact you control": "other_artifacts_you_control",
    "other equipment you control": "other_permanents_you_control_of_subtype_equipment",
    "other town you control": "other_permanents_you_control_of_subtype_town",
    "modified creature you control": "modified_creatures_you_control",
    "+1/+1 counter on creatures you control": "plus_one_counters_on_creatures_you_control",
}


def _activation_cost_reduction_selector(what: str) -> "Optional[str | dict]":
    """Map PAR-94's per-unit discount vocabulary to live readers."""
    normalized = " ".join(what.lower().split())

    structured = parse_count_phrase(normalized)
    if structured is not None:
        return structured
    selector = _ACTIVATION_COST_REDUCTION_SELECTORS.get(normalized)
    if selector is not None:
        return selector
    counter = re.fullmatch(
        r"(?P<kind>[a-z][a-z-]*) counters? on (?:~|this (?:artifact|creature|enchantment))",
        normalized,
    )
    if counter is not None:
        return f"source_{counter.group('kind')}_counters"
    power = re.fullmatch(
        r"creature with power (?P<n>\d+) or greater your opponents control", normalized
    )
    if power is not None:
        return f"creatures_opponents_control_with_power_ge_{power.group('n')}"
    return None

# An activated ability may end with its RULE 602 legality sentence rather
# than making it a separate oracle line: "{1}: Draw a card. Activate only if
# <condition> [and only once]."  Peel only this closed tail before parsing
# the actual body; the existing handler catalogue supplies the condition
# marker and the existing binder owns both activation limits.
_ANY_PLAYER_MAY_ACTIVATE_RE = re.compile(
    r"\s*\bany player may activate this ability(?P<sorcery> but only as a sorcery)?\.?\s*$", re.IGNORECASE
)
_ACTIVATE_ONLY_IF_TRAILING_RE = re.compile(
    r"\.\s*activate (?:this ability )?only (?:if (?P<cond>.+?)|during the (?P<step>declare attackers) step"
    r"(?: and only if (?P<cond2>.+?))?)(?P<once> and only once)?\.?$",
    re.IGNORECASE,
)

#: A cost is only trusted as one if it actually *looks* like a cost — a mana/
#: {T} symbol, or one of the non-mana cost words. This keeps a stray sentence
#: colon (and loyalty "[+1]:" costs, not modeled yet — RULE 606) from being
#: mis-read as an activation cost (fail-closed). "put a counter on this/~"
#: is Devoted Druid's "Put a -1/-1 counter on this creature: Untap this
#: creature." cost; "tap ... untapped ... you control" is Birchlore Rangers'/
#: Heritage Druid's bulk-tap cost (RULE 602.1, `costs.tap_others`); "remove a
#: [+1/+1] counter from this creature" is Walking Ballista/Triskelion's
#: counter-removal cost (RULE 701.19, `costs.remove_counters` — this module
#: can't import `game/costs.py`'s `_REMOVE_COUNTERS_RE` directly, front-end
#: security boundary, so the count/kind shape here is kept loose and just
#: needs to sniff "is this a cost at all", not fully parse it — keep the verb
#: fragment in sync if that regex's grammar ever changes).
_COST_LOOKS_REAL = re.compile(
    r"\{[^}]+\}|sacrifice|pay \d+ life|discard|put an? .+ counter on|"
    # RULE 701.59a / 701.61a / 701.68 keyword-action costs — Gristle
    # Glutton ("{T}, Blight 1: …"), Polygraph Orb / Hedge Whisperer /
    # Tenth District Hero ("…, collect evidence N: …"). All three are real
    # `costs.parse_activation_cost` fragments (`ActivationCost.collect_
    # evidence`/`forage`/`blight`) charged by `_can`/`_pay_player_cost`.
    r"collect evidence \d+|forage|blight \d+|"
    r"tap .+ untapped .+ you control|remove .+ counters?|"
    r"return an? [a-z]+ you control to (?:its|your) owner'?s?\s*hand|"
    r"exile (?:this \w+|~) from (?:your|their) hand|"
    # An attached Aura/Equipment can be named in a quoted granted ability's
    # cost (Blinding Powder). The nested grant parser supplies the precise
    # granting-object reference after this lexical cost check.
    r"unattach (?:this \w+|~|[a-z][a-z' -]+)|"
    # "Exile a creature you control: …" (Food Chain, MEC-40) — a RULE
    # 605.1a mana-ability cost component (`costs._EXILE_CREATURE_RE`),
    # the battlefield-zone sibling of the hand-zone exile cost just above.
    r"exile an? [a-z]+ you control",
    re.I,
)

#: A planeswalker loyalty ability: "+N:", "-N:", "0:" then the effect (RULE
#: 606.5c) — real Scryfall oracle text prints the sign/digit bare, with no
#: surrounding brackets ("+1: Target player mills two cards. Draw a card.",
#: not "[+1]: ..."); an optional bracket pair is still accepted too (some
#: older fixtures/UI conventions use it), so either form matches. Bare
#: sign+digit+colon is unambiguous as a loyalty cost — no mana-cost/
#: sacrifice/pay-life/discard activated-ability cost is ever templated this
#: way — so this is checked before the generic activated case whose cost
#: sniff (`_COST_LOOKS_REAL`) wouldn't accept a bare "+1" anyway.
_LOYALTY_LINE_RE = re.compile(
    r"^\s*\[?\s*([+\-−]?)\s*(\d+|x)\s*\]?\s*:\s*(?P<effect>.+)$", re.S
)

#: A mana ability's effect ("add {g}", "add 1 mana of any color"): the engine
#: models these in `game/mana_abilities.py`, not through effect specs, so such a
#: line is *claimed* here (covered) but contributes no spec.
_MANA_EFFECT_RE = re.compile(r"^add\b", re.I)

#: "For each color among permanents you control, add one mana of that
#: color." (Bloom Tender/Faeburrow Elder-shaped) — doesn't start with "add"
#: (that's mid-sentence, after the "for each" clause), so `_MANA_EFFECT_RE`
#: above never matches it; mirrors `game/mana_abilities.py`'s own
#: `_COLORS_AMONG_PERMANENTS_RE` exactly; this module can't import that one
#: directly (front-end security boundary), so the shape is duplicated
#: rather than shared — keep the two in sync if it ever changes.
_COLORS_AMONG_PERMANENTS_MANA_RE = re.compile(
    r"^for each colou?r among permanents you control, add (?:one|1) mana of that colou?r\.?$",
    re.IGNORECASE,
)

#: "Choose a color. Add an amount of mana of that color equal to your
#: devotion to that color." (Nykthos, Shrine to Nyx) — same "doesn't start
#: with 'add'" gap `_COLORS_AMONG_PERMANENTS_MANA_RE` closes, this time for
#: `game/mana_abilities.py`'s ``"devotion_to_chosen_color"`` kind; mirrors
#: `mana_abilities.py`'s own `_DEVOTION_CHOSEN_COLOR_ADD_RE` (front-end
#: can't import `game/`, so the shape is duplicated, not shared).
_DEVOTION_CHOSEN_COLOR_MANA_RE = re.compile(
    r"^choose a colou?r\. add an amount of mana of that colou?r equal to "
    r"your devotion to that colou?r\.?$",
    re.IGNORECASE,
)

#: "Play with the top card of your library revealed." (Oracle of Mul
#: Daya/Future Sight-shaped) — purely informational, no separate game-state
#: effect: it's always printed as its own line right next to the actual
#: play/cast-from-top permission (`catalogue.static_handlers.
#: _TOP_LIBRARY_PERMISSION_RE`), whose own grant already implies visibility
#: (`game/top_library.py`'s `may_look_at_top_of_library` — "a permission to
#: play cards from the top implies seeing them"), so this line adds no new
#: information over that grant. Claimed as a documented no-op (mirroring how
#: a mana-ability's own effect line is "covered but no spec" above) rather
#: than wired into new behaviour. Contrast the *standalone* "you may look at
#: the top card of your library any time." line (Sphinx of Jwar Isle-shaped,
#: no accompanying play/cast permission on ~57 real cards) — that one is a
#: genuine, independent RULE 400.2-adjacent visibility grant, so it's
#: claimed by `static_handlers._LOOK_AT_TOP_ANY_TIME_RE` instead, as a real
#: `top_library_permission {"look": True}` spec, not here.
_PLAY_WITH_TOP_REVEALED_RE = re.compile(
    r"^play with the top card of your library revealed\.?$", re.IGNORECASE
)

#: Connectors that chain two effect clauses in one ability body, tried in this
#: order when the whole body isn't a single handled clause.
#: PAR-141: a comma before a *pronoun-led* effect clause is a sentence boundary too ("put a +1/+1 counter on that
#: creature, it gains haste until end of turn, and it becomes a Vampire …", Olivia) — only when the next clause
#: opens with "it"/"that creature" plus a verb that acts on it, so a comma inside one clause is never split.
_PRONOUN_COMMA_CONNECTOR = r",\s+(?:and\s+)?(?=(?:it|that creature)\s+(?:gains?|becomes|gets?|has|loses)\b)"
#: Effects that neither target nor create anything, so a pronoun chain runs straight through them: "clash with
#: an opponent" (PAR-30) and the player designations ("you take the initiative", "you become the monarch" —
#: PAR-139: From the Catacombs' "put … onto the battlefield … with a corpse counter on it. You take the
#: initiative. If that creature would leave the battlefield, exile it instead …").
_REFERENT_TRANSPARENT_TYPES: frozenset[str] = frozenset(
    {"clash", "coin_flip", "roll_die", "take_initiative", "become_monarch"}
)

#: PAR-137: the longest run of consecutive sentences a clause row may claim as one unit when a body
#: is split on periods ("return up to 1 target … to the battlefield. Exile the top 2 cards of your
#: library. Until the end of your next turn, you may play those cards." — the exile row owns *two*
#: sentences). Four covers the longest multi-sentence rows (a dig with its rest and else tail);
#: a longer window would only be a slower way of failing.
_MAX_SENTENCE_WINDOW = 4
_MAY_HAVE_TARGET_GET_RE = re.compile(
    r"(\byou may )have (target (?:[a-z-]+ )*?creature) (get|gain) ", re.IGNORECASE
)
_AND_CONNECTOR = r"\s+and\s+"
_CONNECTORS: tuple[str, ...] = (
    r"\.\s+", r";\s+", r",?\s+then\s+", _PRONOUN_COMMA_CONNECTOR, _AND_CONNECTOR,
)


def _split_effect_connector(body: str, separator: str) -> list[str]:
    """Keep a quoted ability intact while splitting the surrounding effects."""
    spans = [(m.start(), m.end()) for m in re.finditer(separator, body)
             if body[:m.start()].count('"') % 2 == 0]
    if separator == _CONNECTORS[0]:
        # A quoted ability's final period also ends its
        # enclosing sentence; retain the closing quote in that first part.
        spans.extend((m.start() + 1, m.end()) for m in re.finditer(r'(?<=\.)"\s+', body)
                     if body[:m.start()].count('"') % 2 == 1)
    parts = []
    start = 0
    for left, right in sorted(spans):
        if left < start:
            continue
        parts.append(body[start:left])
        start = right
    parts.append(body[start:])
    return [part for part in parts if part.strip()]
#: "**target player|opponent** draws a card" … "and **loses** 2 life": a third-person-singular verb opening a
#: later "and" part has no subject of its own (the bare "lose" of "you draw and lose" is the controller's).
_ELIDED_TARGET_LOSS_RE = re.compile(r"\b(?:other|another)\b", re.IGNORECASE)
#: ENG-52 (RULE 109.5/115.3): a later clause naming "any other target" / "another target …" / "a third target" must
#: not repeat what an earlier clause of the same ability chose. `resolve_target_kind` reads those words down to the
#: plain kind, so the distinctness is stamped on the clause's own effect (`TargetSpec.distinct_from_others`).
_OTHER_TARGET_PART_RE = re.compile(
    r"\b(?:(?:any )?other|another|a third) target\b|\bup to (?:one|two|three|\d+) other targets?\b", re.IGNORECASE,
)
#: The single-requirement effect types the flag is stamped on (`binding.build_effects` applies it to the effect's
#: `TargetSpec`; `damage`/`add_counters` also read it in their own factory). A verb with several requirements of
#: its own (fight, damage equal to power) keeps its dedicated parameter.
_DISTINCT_FROM_OTHERS_TYPES = frozenset({"damage", "add_counters", "pump", "destroy", "exile", "tap", "return_to_hand"})


def _stamp_distinct_from_others(effects: list[EffectSpec]) -> tuple[list[EffectSpec], bool]:
    """``effects`` with ``distinct_from_others`` set on each targeting effect that supports it, and whether
    any was stamped (a clause whose effect has no such parameter keeps its old reading)."""
    stamped = False
    out: list[EffectSpec] = []
    for effect in effects:
        if (
            effect.type in _DISTINCT_FROM_OTHERS_TYPES
            and effect.params.get("selector") is None and effect.params.get("group") is None
            and (effect.params.get("target_kind") is not None or effect.type in ("damage", "add_counters"))
        ):
            out.append(EffectSpec(effect.type, {**effect.params, "distinct_from_others": True}, condition=effect.condition))
            stamped = True
        else:
            out.append(effect)
    return out, stamped
_ELIDED_AMOUNT_VERBS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("~ deals ", re.compile(r"^(?:\d+|x) damage\b", re.IGNORECASE)),
    ("you gain ", re.compile(r"^(?:\d+|x) life\b", re.IGNORECASE)),
)
_TARGET_PLAYER_SUBJECT_RE = re.compile(r"^target (?:player|opponent) ", re.IGNORECASE)
_ELIDED_PLAYER_VERB_RE = re.compile(r"^(?:loses|gains|draws|discards|mills)\b", re.IGNORECASE)
#: How each effect type is pointed at the player an earlier clause of the same sentence chose
#: (`GameContext.previous_targets`): a flag the effect reads, or a ``player`` referent. A type missing here
#: has no such reading, so the sentence is refused rather than left acting on the controller.
_PREVIOUS_PLAYER_STAMPS: dict[str, dict[str, Any]] = {
    "lose_life": {"previous_subject": True},
    "discard": {"previous_subject": True},
    "draw": {"player": {"of": "previous_player"}},
    "gain_life": {"player": {"of": "previous_player"}},
}


def _elides_player_subject(first_part: str, part: str) -> bool:
    return (_TARGET_PLAYER_SUBJECT_RE.match(first_part.strip()) is not None
            and _ELIDED_PLAYER_VERB_RE.match(part.strip()) is not None)


def _stamp_previous_player(effects: list[EffectSpec]) -> "Optional[list[EffectSpec]]":
    """See `_PREVIOUS_PLAYER_STAMPS`; ``None`` when an effect has no such reading."""
    stamped: list[EffectSpec] = []
    for effect in effects:
        if any(effect.params.get(k) is not None for k in TARGET_PARAM_KEYS):
            stamped.append(effect)  # it names its own target
            continue
        extra = _PREVIOUS_PLAYER_STAMPS.get(effect.type)
        if extra is None:
            return None
        stamped.append(EffectSpec(effect.type, {**effect.params, **extra}, condition=effect.condition))
    return stamped

#: RULE 702.33b/701.x's "if `<this spell was kicked|it was kicked[
#: twice]|this spell/it was bargained>`, `<effect>`." — a *second,
#: additional* effect gated on an optional cost actually having been paid.
#: "This spell" (Vastwood Surge-shaped: a base effect, then this as its own
#: sentence) is a spell's own resolution; "it" (PAR-17, Heartstabber
#: Mosquito/Citanul Woodreaders-shaped) is the *same* gate as a triggered
#: ability's own — and, there, only — effect body, "it" being the
#: ability's source rather than a spell. Three gates: bare "kicked" (Kicker
#: paid at least once), "kicked twice" (RULE 702.34a Multikicker's own
#: count threshold — Archangel of Wrath, ``kicked_at_least``), and
#: "bargained" (RULE 701.x, Beseech the Mirror — `effects.
#: ConditionalEffect._condition_holds` has supported this key since the
#: cEDH-cube batch, but no oracle-text recognizer ever reached it until
#: now). Only "additional effect" shapes are recognised; "if kicked, it
#: deals N damage instead" (overriding an *earlier* effect's own amount —
#: Burst Lightning/Rite of Replication-shaped) is a different, unmodeled
#: grammar — the wrapped ``rest`` there fails `match_clause` on its own (no
#: target/full clause of its own), so it fails closed here too rather than
#: needing a separate check.
_KICKED_CONDITION_RE = re.compile(
    r"^if (?:this spell|it) was (?P<kind>kicked(?: twice)?|bargained),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: PAR-30 / RULE 601.2b: "if this spell's additional cost was paid,
#: `<effect>`." (Ruinous Waterbending, Secret of Bloodbending, Katara
#: Seeking Revenge's ETB) — the generic optional-additional-cost sibling of
#: `_KICKED_CONDITION_RE`, onto `EffectSpec.condition`'s
#: ``"additional_cost_paid"`` key (`GameObject.additional_cost_paid`, set at
#: cast time). Only the *additive* "if paid, <extra effect>" shape; the
#: "…, <effect> instead" amount-override shape (Spirit Water Revival) fails
#: `match_clause` on ``rest`` the same way the "if kicked … instead" shape
#: does, so it stays unclaimed here too.
_ADDITIONAL_COST_PAID_CONDITION_RE = re.compile(
    r"^if (?:this spell's|the spell's|its|her|his|their) additional cost was paid,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: MEC-106 / RULE 702.174k: "if the gift was[n't] promised, `<effect>`." — an additive rider
#: gated on the caster having promised the gift. "Instead" overrides ("… , instead `<effect>`")
#: are a different, override grammar and fall to `_INSTEAD_OVERRIDE_RE`.
_GIFT_PROMISED_CONDITION_RE = re.compile(
    r"^if the gift (?P<neg>was|wasn'?t) promised,\s*(?P<rest>(?!instead\b).+)$", re.IGNORECASE,
)

#: PAR-56 / RULE 702.194: Teamwork is an optional additional cost with its
#: own cast-state marker, so ordinary "if this spell was cast using
#: teamwork" riders use the same additive conditional-effect path as Kicker.
_TEAMWORK_PAID_CONDITION_RE = re.compile(
    r"^if this spell was cast using teamwork,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: PAR-30 / RULE 601.2b: the *negative, suffix* sibling — "`<effect>` unless
#: `<its>` additional cost was paid." (Katara, Seeking Revenge — "draw a
#: card, then discard a card **unless her additional cost was paid**."):
#: the effect body applies only when the optional cost was *not* paid, so
#: each spec is tagged ``condition={"additional_cost_paid": False}``.
_ADDITIONAL_COST_NOT_PAID_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?) unless (?:this spell's|the spell's|its|her|his|their) additional cost was paid$",
    re.IGNORECASE,
)

#: RULE 603.4 intervening-if as a *suffix* — "`<effect>` **if an opponent
#: lost N or more life this turn**." (Davros, Dalek Creator's own end-step
#: token). Same "parse the rest, tag every spec's condition" idiom as the
#: prefix conditions above, onto `EffectSpec.condition`'s
#: ``"opponent_lost_life_this_turn_at_least"`` key (`GameState.
#: life_lost_this_turn`). ``rest`` is non-greedy so the shortest clause that
#: still parses carries the gate.
_OPPONENT_LOST_LIFE_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?) if an opponent lost (?P<n>\d+) or more life this turn$",
    re.IGNORECASE,
)

#: RULE 603.4-style intervening-if keyed to a just-chosen *target*, rather
#: than an announced-cost flag (The Ghoul, Gunslinger: "target player gets
#: two rad counters. If that player is you, create a Treasure token.") —
#: mirrors `_KICKED_CONDITION_RE`'s "wrap the rest, tag the condition" idiom
#: exactly, onto `EffectSpec.condition`'s ``"target_is_controller"`` key
#: instead of ``"kicked"``. "If that player isn't you, ..." (the negation)
#: is real MTG templating too, so both polarities are recognised here.
_TARGET_IS_CONTROLLER_RE = re.compile(
    r"^if that player is(?P<neg> not|n't)? you,\s*(?P<rest>.+)$", re.IGNORECASE
)

#: RULE 119.3's "if you gained N or more life this turn, `<effect>`."
#: (Frodo, Adventurous Hobbit's own first clause) — same "wrap the rest, tag
#: the condition" idiom as `_KICKED_CONDITION_RE`, onto `GameState.
#: life_gained_this_turn` via `EffectSpec.condition`'s new
#: ``"life_gained_this_turn_at_least"`` key. ``rest`` is non-greedy with an
#: explicit ``trailing`` tail for Frodo's own printed shape — "if A, effect1.
#: Then if B, effect2." is *two* independently-gated sentences, not one
#: condition spanning both; without splitting here the naive greedy-``.+``
#: reading would slap *this* condition onto the second sentence's own
#: `EffectSpec` too, silently discarding its real "if ~ is your Ring-bearer
#: and the Ring has tempted you N or more times" gate — a wrong-but-modeled
#: card, worse than leaving it unclaimed.
_LIFE_GAINED_THIS_TURN_CONDITION_RE = re.compile(
    r"^if you gained (?P<n>\d+) or more life this turn,\s*(?P<rest>.+?)"
    r"(?P<trailing>\.\s+then\s+if\s+.+)?$",
    re.IGNORECASE,
)

#: RULE 603.4's own textbook example — "if it's the first combat phase of
#: the turn, `<effect>`." (Karlach, Fury of Avernus/Finest Hour/Genji
#: Glove/Raiyuu-shaped — every one of them an extra-combat-granting
#: trigger guarding against re-triggering itself in the extra phase it just
#: made, the same self-loop `not_already_exerted` guards for Exert) — same
#: "wrap the rest, tag the condition" idiom as `_KICKED_CONDITION_RE`, onto
#: `effects.ConditionalEffect`'s new ``"is_first_combat_phase"`` key
#: (`GameState.combats_this_turn`).
#: PAR-120: "…if this is the second time this ability has resolved this
#: turn" (Rumor Gatherer, Elrond, Tannuk) and the ladder that continues it —
#: "`<effect>` if this is the first time …. if it's the second time,
#: `<effect>`. if it's the third time, `<effect>`." (Omnath, Locus of
#: Creation; Belladonna Took; Vito). The bare "it's the second time" only
#: ever prints as such a ladder's continuation, naming the same count. Read
#: off `GameContext.ability_resolution_count` (the resolution now happening
#: included — "the third time" is exactly the third, never the fourth, per
#: the cards' rulings), so it is an effect-time gate only: deliberately not
#: in `static_condition()`, where an "as long as" static could claim it.
_RESOLUTION_ORDINALS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
}
_RESOLUTION_TIME = (
    r"(?:this is|it'?s|it is) the (?P<ord>first|second|third|fourth|fifth)"
    r"(?: or (?P<ord2>second|third|fourth|fifth))? time"
    r"(?: this ability has resolved this turn)?"
)
_RESOLUTION_COUNT_PREFIX_RE = re.compile(
    rf"^if {_RESOLUTION_TIME},\s*(?P<rest>.+)$", re.IGNORECASE | re.DOTALL,
)
_RESOLUTION_COUNT_SUFFIX_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+if {_RESOLUTION_TIME}\.?$", re.IGNORECASE | re.DOTALL,
)


def _resolution_count_condition(match: "re.Match[str]") -> dict[str, Any]:
    low = _RESOLUTION_ORDINALS[match.group("ord").lower()]
    high = _RESOLUTION_ORDINALS[(match.group("ord2") or match.group("ord")).lower()]
    return {"kind": "ability_resolution_count", "min": low, "max": high}


_FIRST_COMBAT_PHASE_CONDITION_RE = re.compile(
    r"^if it'?s the first combat phase of the turn,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: RULE 701.52a's Ring-bearer intervening-if, two printed shapes (Tales of
#: Middle-earth): "if you chose a creature **other than** ~ as your
#: Ring-bearer" (Aragorn, Company Leader/Faramir, Field Commander/Galadriel
#: of Lothlórien/Gandalf, Friend of the Shire — ``is_ring_bearer=False``)
#: and Frodo, Adventurous Hobbit's own compound "if ~ **is** your
#: Ring-bearer and the Ring has tempted you N or more times this game" —
#: one `EffectSpec.condition` dict carrying *both*
#: ``"is_ring_bearer"``/``"ring_tempted_at_least"`` keys, which
#: `effects.ConditionalEffect._condition_holds`'s AND-fold requires
#: together (the primitive built for exactly this card).
#: Both tolerate an optional leading "then " — `_CONNECTORS`' period-split
#: (tried before its own ",? then " connector, since it's earlier in that
#: tuple and already yields 2+ parts on "…tempts you. Then if ~ is…") lands
#: a literal "Then " prefix on the second half, which neither regex would
#: otherwise expect.
_RING_BEARER_OTHER_CONDITION_RE = re.compile(
    r"^(?:then )?if you chose a creature other than ~ as your ring-bearer,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_RING_BEARER_AND_TEMPTED_CONDITION_RE = re.compile(
    r"^(?:then )?if ~ is your ring-bearer and the ring has tempted you (?P<n>\d+) or more "
    r"times this game,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: "if you don't control a Food, `<effect>`." (Butterbur, Bree Innkeeper-
#: shaped upkeep/end-step "keep a permanent type replenished" payoffs) —
#: same "wrap the rest, tag the condition" idiom as `_LIFE_GAINED_THIS_
#: TURN_CONDITION_RE`, onto `ConditionalEffect`'s new
#: ``"controls_none_of_type"`` key. Scoped to the same closed named-token
#: vocabulary `catalogue.effect_rows.shared.NAMED_TOKEN_WORDS`/`segmenter._
#: SACRIFICE_TYPE_TRIGGER_RE` already trust (Treasure/Clue/Food) rather
#: than an arbitrary noun — a fail-closed choice, not a card-count one.
_CONTROLS_NONE_OF_TYPE_CONDITION_RE = re.compile(
    r"^if you don'?t control an? (?P<type>treasure|clue|food),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: PAR-30: "if there's a `<subtype>` card in your graveyard, `<effect>`."
#: (Walltop Sentries — "when ~ dies, if there's a lesson card in your
#: graveyard, you gain 2 life.") — the trigger intervening-if sibling of
#: the `subtype_in_graveyard` static gate, onto `ConditionalEffect`'s
#: already-built ``"graveyard_has_type"`` key (a live type-line scan). One
#: subtype word, so it can't swallow a "N or more cards" count phrasing.
_GRAVEYARD_HAS_SUBTYPE_CONDITION_RE = re.compile(
    r"^if there(?:'s| is| are) an? (?P<sub>[a-z][a-z-]+) card in your graveyard,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: The pre-daybound Innistrad **werewolf** day/night check (RULE 603.4
#: intervening-if — ~26 front faces + their backs): "if no spells were cast
#: last turn, transform ~." (front → werewolf) and its mirror "if a player
#: cast 2 or more spells last turn, transform ~." (back → human). Same
#: "wrap the rest, tag the condition" idiom as the rows above, onto
#: `effects.ConditionalEffect`'s ``"no_spells_cast_last_turn"`` /
#: ``"two_or_more_spells_cast_last_turn"`` keys, which read
#: `GameState._last_turn_spell_count` — the same field
#: `RulesEngine.apply_day_night_turn_check` (RULE 731.2a/2b) already uses
#: for the daybound/nightbound successor mechanic.
_WEREWOLF_NO_SPELLS_CONDITION_RE = re.compile(
    r"^if no spells were cast last turn,\s*(?P<rest>.+)$", re.IGNORECASE,
)
_WEREWOLF_TWO_SPELLS_CONDITION_RE = re.compile(
    r"^if a player cast (?:2|two) or more spells last turn,\s*(?P<rest>.+)$",
    re.IGNORECASE,
)

#: RULE 701.30d's "clash with an opponent. **if you win**, `<effect>`.
#: **otherwise**, `<effect>`." branch (PAR-29) — same "wrap the rest, tag the
#: condition" idiom as `_KICKED_CONDITION_RE`, onto `effects.
#: ConditionalEffect`'s ``"clash_won"`` key. The `_CONNECTORS` period-split
#: hands each of "clash with an opponent" / "if you win, …" / "otherwise, …"
#: to `parse_effect_body` separately; `_clash` (handlers.py) claims the
#: first, these two the rest. "if you won" (past tense — Entangling Trap's
#: "whenever you clash, … if you won, …", where the clash is the trigger)
#: reads the firing `CLASHED` event instead, handled by the same condition
#: key. "otherwise" carries no explicit "clash" word, so it's deliberately
#: only recognised as a *split part* here (a top-level body never starts
#: with a bare "otherwise") and fails closed if its `<effect>` isn't
#: modelled — and `ConditionalEffect` refuses it anyway when no clash is in
#: scope.
_IF_YOU_WIN_CLASH_RE = re.compile(
    r"^if you w(?:in|on)(?: the clash)?,\s*(?P<rest>.+)$", re.IGNORECASE,
)
_OTHERWISE_RE = re.compile(
    r"^otherwise,\s*(?P<rest>.+)$", re.IGNORECASE,
)

#: RULE 705 (PAR-151): "flip a coin. **if you win the flip**, `<effect>`. **if you lose the
#: flip**, `<effect>`." — the clash idiom for coin flips: sibling specs gated on the
#: ``coin_won`` condition (the outcome `CoinFlipEffect` left on `GameContext.coin_outcome`),
#: "lose" being its negation. "if the coin comes up heads/tails" is the same two outcomes
#: spelled by face (heads = a won flip, `RulesEngine.coin_flip`'s ``True``).
_COIN_FLIP_RESULT_RE = re.compile(
    r"^if (?:you (?P<res>win|lose|won|lost) (?:the|a) (?:coin )?flip"
    r"|(?:the coin|it) comes up (?P<face>heads|tails)),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)


def _coin_flip_condition(m: "re.Match[str]") -> dict[str, Any]:
    won = {"kind": "coin_won"}
    outcome = (m.group("res") or m.group("face")).lower()
    return won if outcome in ("win", "won", "heads") else {"kind": "not", "condition": won}


#: RULE 706 (PAR-147): a die roll's outcome as a branch condition — "if the result is 3 or less, `<effect>`",
#: "if you roll a 6, …", "if you rolled 2, 3, or 12, …", "if both results are the same, …", "if any of those
#: results was 10 or higher, …" and the "On a 3 or 4, `<effect>`." spelling. The roll leaves its kept dice on
#: `GameContext.die_results` / ``die_result`` (the sum, "the result"), so the gate is an ordinary
#: ``amount_compare`` over that amount — sibling specs gated on it announce their own targets at cast
#: (RULE 601.2c) exactly like the ``coin_won`` branches, and "otherwise" is the negated gate.
_DIE_VALUE_LIST = r"\d+(?:, \d+)*(?:,? or \d+)?(?: or (?:less|lower|fewer|more|higher|greater))?"
_DIE_IF_RE = re.compile(
    r"^if (?P<cond>(?:the (?:result|roll) (?:is|was) (?:a )?(?P<rvals>" + _DIE_VALUE_LIST + r")"
    r"|the (?:result|roll) (?:is|was) equal to or (?P<eqdir>less|more|greater) than (?P<amt>the number of [^,]+?)"
    r"|you (?:a )?roll(?:ed)? (?:a )?(?P<yvals>" + _DIE_VALUE_LIST + r")(?: exactly)?"
    r"|you rolled (?P<face>\d+) exactly (?P<times>\d+) times"
    r"|(?P<same>both results are the same|you rolled doubles)"
    r"|any of those results was (?P<anyvals>\d+ or (?:higher|more|greater|lower|less)))),\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_DIE_ON_A_RE = re.compile(
    r"^on an? (?P<rvals>" + _DIE_VALUE_LIST + r"),\s*(?P<rest>.+)$", re.IGNORECASE,
)
_DIE_DIRECTION_OPS = {
    "less": "le", "lower": "le", "fewer": "le", "more": "ge", "higher": "ge", "greater": "ge",
}


def _die_compare(op: str, right: "dict[str, Any]") -> "dict[str, Any]":
    return {"kind": "amount_compare", "left": {"kind": "die_result"}, "right": right, "op": op}


def _die_value_condition(values: str) -> "Optional[dict[str, Any]]":
    """"3 or less" / "6" / "2, 3, or 12" / "7 or 11" → the ``die_result`` gate for that value list."""
    direction = re.search(r" or (less|lower|fewer|more|higher|greater)$", values)
    if direction is not None:
        number = values[: direction.start()]
        if not number.isdigit():
            return None
        return _die_compare(_DIE_DIRECTION_OPS[direction.group(1)], {"kind": "fixed", "amount": int(number)})
    numbers = [int(n) for n in re.findall(r"\d+", values)]
    if not numbers:
        return None
    equals = [_die_compare("eq", {"kind": "fixed", "amount": n}) for n in numbers]
    return equals[0] if len(equals) == 1 else {"kind": "any", "conditions": equals}


def _die_result_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    groups = m.groupdict()
    if groups.get("times"):
        # "if you rolled 6 exactly seven times": the number of kept dice showing that face.
        return {
            "kind": "amount_compare", "op": "eq",
            "left": {"kind": "die_results", "which": "equal", "value": int(groups["face"])},
            "right": {"kind": "fixed", "amount": int(groups["times"])},
        }
    if groups.get("same"):
        return {"kind": "rolled_doubles"}
    if groups.get("anyvals"):
        number, _, direction = groups["anyvals"].partition(" or ")
        return {"kind": "any_die_result", "op": _DIE_DIRECTION_OPS[direction], "value": int(number)}
    if groups.get("amt"):
        counted = parse_amount_phrase(groups["amt"])
        if counted is None:
            return None
        return _die_compare(
            "le" if groups["eqdir"] == "less" else "ge", {"kind": "count_selector", "selector": counted},
        )
    return _die_value_condition(groups.get("rvals") or groups.get("yvals") or "")


_THAT_MUCH_RE = re.compile(r"\bthat much\b", re.IGNORECASE)


def _die_that_much_specs(
    rest: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"…, you lose **that much** life" / "~ deals **that much** damage to you" after a die gate — "that much" is
    the result just rolled (the gate's own roll), so it reads as X bound to ``die_result``."""
    if _THAT_MUCH_RE.search(rest) is None:
        return None
    return _bind_x_specs(
        _THAT_MUCH_RE.sub("x", rest), {"kind": "die_result"}, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject, previous_selector=False),
    )


def _is_die_gate(condition: "Optional[dict[str, Any]]") -> bool:
    """Whether ``condition`` only reads this resolution's die roll (a fact no sibling branch changes)."""
    if not condition:
        return False
    kind = condition.get("kind")
    if kind in ("rolled_doubles", "any_die_result"):
        return True
    if kind == "amount_compare":
        return (condition.get("left") or {}).get("kind") in ("die_result", "die_results")
    if kind in ("any", "all"):
        subs = condition.get("conditions") or []
        return bool(subs) and all(_is_die_gate(sub) for sub in subs)
    return False


def _otherwise_specs(
    rest: str, preceding: "list[EffectSpec]", *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"…`<A>` if `<condition>`. **Otherwise**, `<B>`." → the ``if_else`` that replaces `<A>`.

    `<B>` runs exactly when `<A>`'s gate did not hold, whatever it was (RULE 701.30d's "if you
    win the clash" is one case). The gate has to be *decided once*, before either branch runs:
    "draw a card if you have no cards in hand, otherwise discard" must not re-read the hand
    after the draw — hence one node rather than a second, negated gate. The preceding clause
    must carry a condition; without one there is nothing "otherwise" could mean, so the body
    stays unclaimed rather than guessed at."""
    if not preceding:
        return None
    gate = preceding[0].condition
    if gate is None or any(spec.condition != gate for spec in preceding):
        return None
    inner = parse_effect_body(rest, reading=reading)
    if not inner or any(spec.condition is not None for spec in inner):
        return None
    if gate in ({"kind": "clash_won"}, {"kind": "coin_won"}) or _is_die_gate(gate):
        # RULE 701.30d's clash outcome (and RULE 705's flip outcome) is a fact of the resolution
        # that no branch changes, so the two gated lists it always had are equivalent — and the
        # gated siblings announce their own targets (RULE 601.2c), which `if_else` cannot.
        negated = {"kind": "not", "condition": gate}
        return list(preceding) + [
            EffectSpec(spec.type, dict(spec.params), condition=negated) for spec in inner
        ]
    return [EffectSpec("if_else", {
        "condition": gate,
        "then": [EffectSpec(spec.type, dict(spec.params)).to_dict() for spec in preceding],
        "else": [spec.to_dict() for spec in inner],
    })]


#: MEC-50: "`<process>`, then clash with an opponent. If you win, **repeat
#: this process**." (Hoarder's Greed) — the win branch loops the *whole*
#: preceding process (`RepeatProcessEffect`, capped), not a fresh clause,
#: so it can't ride the generic `_IF_YOU_WIN_CLASH_RE` peel (which appends
#: a condition-gated sibling). ``process`` is parsed recursively; a bare
#: `clash` is appended so the loop's own re-clash runs each pass.
_CLASH_REPEAT_PROCESS_RE = re.compile(
    r"^(?P<process>.+?),\s*then clash with an opponent\.\s*"
    r"if you w(?:in|on), repeat this process$",
    re.IGNORECASE | re.S,
)

#: MEC-50: "Clash with an opponent, then return target creature to its
#: owner's hand. **If you win, you may put that creature on top of its
#: owner's library instead**." (Whirlpool Whelm) — the win branch
#: *overrides the destination* of the earlier bounce rather than adding an
#: effect (and "that creature" would be a stale RULE 400.7 reference after
#: the hand move), so it's folded into `ReturnToHandEffect.to_library_top_
#: if_clash_won` on the one bounce spec.
_CLASH_BOUNCE_OR_LIBRARY_RE = re.compile(
    r"^clash with an opponent, then return target creature to its owner'?s hand\.\s*"
    r"if you w(?:in|on), you may put (?:that creature|it) on top of its owner'?s "
    r"library instead$",
    re.IGNORECASE | re.S,
)

#: PAR-30 Suspect one-off shapes / RULE 701.60c: "choose up to one target
#: creature. If it's suspected, exile it. Otherwise, suspect it." (Agrus
#: Kos, Spirit of Justice) — an if/else over the chosen creature's own
#: suspected state, emitted as two mutually complementary condition-gated
#: specs (the `_IF_YOU_WIN_CLASH_RE`/`clash_won` idiom). The exile branch
#: carries the RULE 115 ``target_spec`` ("up to one" ⇒ ``optional``); the
#: "otherwise, suspect it" branch reads that same creature back off
#: `GameContext.previous_targets`. Deliberately the exact printed template
#: only — a card that swapped the two branch bodies is a new shape.
_CHOOSE_TARGET_IF_SUSPECTED_RE = re.compile(
    r"^choose up to (?:1|one) target creature\.\s*"
    r"if it'?s suspected, exile it\.\s*otherwise, suspect it$",
    re.IGNORECASE,
)

#: "Destroy target X. It can't be regenerated." (Terminate/Doom Blade's
#: mass/multi/filtered siblings — Death Bomb, Big Game Hunter, Cruel
#: Revival, …) — the single most repeated removal-spell tail in the cache
#: (110 cards SOLO-blocked on it alone, `parser_probe.py blocked`). Unlike
#: every wrapper above, this doesn't prefix-condition the *rest* of the
#: body — it's a trailing sentence that retroactively modifies whichever
#: `destroy` clause came before it (RULE 701.16's "can't be regenerated"
#: shield-denial is a property of *that* destruction, not a free-standing
#: effect), so `parse_effect_body` special-cases it below instead of
#: reaching `match_clause`/the connector-split loop: split on this
#: sentence, parse "before"/"after" independently, then set
#: ``can_be_regenerated: False`` on the last "destroy" spec `before`
#: produced. Deliberately requires the sentence to stand alone (end of
#: body, or followed by its own ``. ``-bounded sentence) — "…it can't be
#: regenerated **this turn**" (Orcish Healer/Carbonize-shaped) is a
#: genuinely different, free-standing prevent-regeneration effect and must
#: NOT match here.
_NO_REGEN_SENTENCE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*(?:it|they) can'?t be regenerated"
    r"(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Add {R}. **Until end of turn, you don't lose this mana as steps and phases end.**" (Brazen Collector, Savage
#: Ventmaw, Neheb, Sakiko, Avatar Roku's "until end of combat") — a trailing sentence that is a property of the mana
#: the previous clause added, so it tags that clause's `add_mana` specs with ``keep_until`` (`ManaPool.kept`)
#: rather than being an effect of its own. Anything before it that adds no mana fails closed.
_KEEP_MANA_SENTENCE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*until (?P<until>end of turn|end of combat), (?:you|they) don'?t lose this mana as "
    r"steps(?: and phases)? end(?:\.\s*(?P<after>.+))?\.?$",
    re.IGNORECASE | re.DOTALL,
)
_KEEP_MANA_UNTIL = {"end of turn": "end_of_turn", "end of combat": "end_of_combat"}

#: PAR-109 (Desolation of Smaug, Sarkhan Fireblood, Jaya Ballard, Geosurge, Metamorphosis, Abstract Paintmage): "Add
#: {R}{R}{R}. Spend this mana only to cast instant or sorcery spells." -- RULE 106.6 / 605.3a. Like the keep-mana
#: sentence above it is a property of the mana the previous clause added, so it tags that clause's `add_mana` specs
#: with a ``restriction`` dict (the shape `game/mana_abilities._parse_restriction` builds for a printed mana ability;
#: this package cannot import `game/`, so the closed vocabulary is mirrored). Anything before it that adds no mana, or
#: a restriction outside the vocabulary, fails closed.
_SPEND_MANA_SENTENCE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*spend this mana only to cast (?P<what>[a-z]+(?: (?:or|and) [a-z]+)? spells|spells)"
    r"(?:\.\s*(?P<after>.+))?\.?$",
    re.IGNORECASE | re.DOTALL,
)
_SPEND_MANA_ANY_SPELL = {"kind": "spell"}
_SPEND_MANA_INSTANT_SORCERY = {"kind": "instant_or_sorcery_spell"}
#: Card-type words a "cast a(n) `<type>` spell" restriction may name (a `type_spell` restriction reads the spell's
#: types and subtypes alike through `continuous.has_subtype`).
_SPEND_MANA_TYPE_WORD_RE = re.compile(r"^[a-z]+$")


def _spend_mana_restriction(what: str) -> Optional[dict[str, Any]]:
    """The restriction dict for "`<X>` spells" in "spend this mana only to cast `<X>` spells", or ``None``."""
    words = what.lower().removesuffix(" spells").removesuffix("spells").strip()
    if not words:
        return dict(_SPEND_MANA_ANY_SPELL)
    parts = re.split(r" (?:or|and) ", words)
    if parts == ["instant", "sorcery"]:
        return dict(_SPEND_MANA_INSTANT_SORCERY)
    if not all(_SPEND_MANA_TYPE_WORD_RE.match(part) for part in parts) or len(parts) > 2:
        return None
    if parts == ["creature"]:
        return {"kind": "creature_spell", "allow_ability": False}
    return {"kind": "type_spell", "types": parts, "allow_ability": False}

#: "~ deals N damage to target creature. **If that creature would die this
#: turn, exile it instead.**" (RULE 616 / 701.11 — Magma Spray / Feed the
#: Flames / Bot Bashing Time / Elspeth's Smite; also the pump form, Bleed
#: Dry's "target creature gets -13/-13 …. If that creature would die this
#: turn, exile it instead.") — the same "trailing sentence retroactively
#: modifies the previous clause's target" idiom as `_NO_REGEN_SENTENCE_RE`.
#: Not a second RULE 115 target: the rider arms `grant_die_to_exile_this_
#: turn` on whatever creature the "before" clause already chose
#: (`previous_subject`, off `GameContext.previous_targets`). Fail-closed
#: unless "before" actually announces a creature/permanent target.
#: "~ deals 3 damage to any target. **If it's a creature, it can't be regenerated this
#: turn, and if it would die this turn, exile it instead.**" (Carbonize, Disintegrate) /
#: "**If this spell was kicked, that creature can't be regenerated this turn and if it
#: would die this turn, exile it instead.**" (Scorching Lava) — both riders on the hit
#: set of the damage clause before them, under one gate: "it's a creature" narrows the
#: hit set to creatures (a planeswalker or player takes the damage but neither rider);
#: any other gate becomes the specs' own `condition`.
_REGEN_EXILE_RIDER_RE = re.compile(
    r"^(?P<before>.+?)\.\s*if (?P<gate>it'?s a creature|this spell was kicked),\s*(?:it|that creature)"
    r" can'?t be regenerated this turn,?\s*and if (?:it|that creature) would die this turn,"
    r" exile it instead\.?$",
    re.IGNORECASE | re.DOTALL,
)
_DIE_TO_EXILE_SENTENCE_RE = re.compile(
    # PAR-62: "a creature dealt damage this way" and "that creature or
    # planeswalker" are the same rider in two more printed spellings. Safe to
    # accept because the use site already refuses a body that announced no
    # target — mass damage ("deals 3 damage to each creature") leaves nothing
    # for `previous_subject` to arm on and so fails closed there, rather than
    # arming a replacement on nobody.
    r"^(?P<before>.+?)\.\s*if (?:that creature(?: or planeswalker)?|that permanent"
    r"|an? (?:creature|permanent) dealt damage this way|it) would die this turn,"
    r" exile it instead(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: MEC-82 / RULE 614: "Target creature gets -2/-2 until end of turn. **If
#: this spell was kicked, that creature gets -6/-6 until end of turn
#: instead.**" (Final Flourish / Vayne's Treachery / Explosive Growth /
#: Marsh Casualties; and the Bargain sibling — Candy Grapple). The trailing
#: sentence *replaces* the "before" pump's own P/T magnitude — it is not a
#: second additive pump — so it is stamped onto that spec as
#: `power_if_kicked`/`toughness_if_kicked` (`PumpEffect`'s
#: `DealDamageEffect.amount_if_kicked` sibling), never routed through
#: `if_else`. Fail-closed unless "before" produced a pump with a P/T
#: magnitude; the "instead … and gains <kw>" form (Colossal Growth) is
#: excluded — that is magnitude *plus* a keyword grant, more than an
#: override.
_KICKED_MAGNITUDE_OVERRIDE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*if this spell was (?P<cost>kicked|bargained),\s*"
    r"(?:that creature|those creatures|it) gets? "
    r"(?P<p>[+-]\d+)/(?P<t>[+-]\d+)(?: until end of turn)?\s*instead\.?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Create <a token / a token copy>. **The token[s] enter[s] tapped and
#: attacking.**" (RULE 508.4 — Ghired, Kari Zev, Stangg, Living Laser) — a
#: trailing sentence that retroactively describes how the just-created
#: token(s) entered, the same `_NO_REGEN_SENTENCE_RE` idiom: split it off,
#: parse "before" independently, then stamp ``tapped``/``attacking`` onto
#: the last `create_token`/`copy_permanent` spec it produced. "It"/"they"
#: are the created-token pronoun here (not a RULE 115 target).
_CREATED_ENTERS_ATTACKING_RE = re.compile(
    r"^(?P<before>.+?)\.\s*"
    # subject: a pronoun for the just-made token/tokens, or the token's own
    # name (Kari Zev — "create Ragavan, …. Ragavan enters tapped and
    # attacking."). The name form is only honoured when it matches the
    # ``token_name`` of a spec the "before" half produced (handler below).
    r"(?:the tokens?|that token|those tokens|it|they"
    r"|(?P<name_subj>[a-z][a-z]+(?:\s[a-z]+){0,2})) enters?"
    r" tapped and attacking"
    # "that player"/"that opponent" (Echoing Assault) — the defender the
    # source is already attacking, derived engine-side, consumed here.
    r"(?: that (?:player|opponent))?"
    r"(?:\.\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Look at the top N cards of your library. Put M of them into your hand
#: and the rest `<destination>`." (Anticipate/Dig Through Time/Diabolic
#: Vision/Ancestral Memories-shaped — the single biggest template blocker
#: found in the whole cache, 60 cards SOLO-blocked on it alone,
#: `parser_probe.py blocked`). Two sentences that are one indivisible
#: instruction (the "look" alone and the "put" alone are each meaningless),
#: so — same idiom as `_NO_REGEN_SENTENCE_RE` just above — this is a
#: `parse_effect_body`-level special case checked on the *whole* two-sentence
#: span before the ordinary connector-split loop would otherwise shatter it
#: into unmatchable halves, with an optional trailing sentence
#: (`Bitter Revelation`'s "You lose 2 life.") recursed into via `after`.
#: `RulesEngine.look_top_select` is the fixed-count sibling of scry/surveil's
#: per-card away/stay decision (`_LOOK_TOP_KINDS`) built for this. Deliberately
#: doesn't handle a *leading* clause before "look at the top…" (Creative
#: Outburst's "~ deals 5 damage to any target. Look at…") — the connector
#: loop splits that off before this check ever sees the two halves together,
#: which is a real, known, narrow gap (one card in the cache) rather than an
#: oversight; a genuinely three-way split ("put 1 into hand, 1 on the
#: bottom, and exile 1" — Expressive Iteration) correctly stays unclaimed too,
#: since the ``dest`` alternation only knows the four two-way destinations
#: real cards actually print.
_LOOK_TOP_SELECT_RE = re.compile(
    r"^look at the top (?P<n>\d+|x) cards? of your library"
    r"(?:, where x is the number of (?P<removed>[a-z]+) counters removed this way)?"
    r"(?:\.\s*|, then\s+)"
    r"put (?P<m>\d+) of (?:them|those cards) into your hand and the (?:rest|other)\s+"
    r"(?P<dest>on the bottom of your library in any order|"
    r"on the bottom of your library in a random order|"
    r"on top of your library in any order|"
    r"into your graveyard)\.?"
    r"(?:\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
_LOOK_TOP_SELECT_DESTINATIONS: dict[str, tuple[str, Optional[str]]] = {
    "on the bottom of your library in any order": ("library_bottom", "any"),
    "on the bottom of your library in a random order": ("library_bottom", "random"),
    "on top of your library in any order": ("library_top", "any"),
    "into your graveyard": ("graveyard", None),
}

#: "Look at the top N cards of your library. You may put a [<subtype>]
#: creature card from among them onto the battlefield tapped and attacking.
#: [It gains <keyword> until end of turn.] Put the rest [of the cards] on
#: the bottom of your library in a random order." (RULE 508.4 — Arthur,
#: Marigold Knight; Owlbear Cub; The Joiner of Cats; **Winota, Joiner of
#: Forces / A-Winota** carry the mid-clause "It gains indestructible until
#: end of turn." interpose — v193). Emitted as an `impulsive_look` with
#: ``hit_destination="battlefield_attacking"`` — the search destination
#: `_put_searched_card` grew for the put-from-hand form (v178), which
#: enters the card tapped and calls `put_onto_battlefield_attacking`; the
#: interpose adds ``hit_grant_keywords`` (temp_keywords on the placed card).
_LOOK_TOP_PUT_ATTACKING_RE = re.compile(
    r"^look at the top (?P<n>\d+) cards? of your library\.\s*"
    r"you may put an? (?P<filter>[a-z, ]+?) card from among them "
    # trailing "that player"/"that opponent" (Owlbear Cub) names the defender
    # the source is already attacking — derived engine-side, so consumed here.
    r"onto the battlefield tapped and attacking(?: that (?:player|opponent))?\.\s*"
    # optional "It gains <kw>[ and <kw>] until end of turn." (Winota) —
    # validated against `_LOOK_TOP_HIT_GRANT_KEYWORDS`, fail-closed.
    r"(?:it gains (?P<hitkw>[a-z, ]+?(?: and [a-z ]+?)?) until end of turn\.\s*)?"
    r"put the rest(?: of the cards)? on the bottom of your library in a random order\.?"
    # optional else-branch: "if you don't put a card onto the battlefield
    # this way, <body>." (The Joiner of Cats) → `miss_effect_specs`. Runs to
    # end of string (no real card has both an else-branch and a trailing
    # sentence), so the `after` tail below can't also steal it.
    r"(?:\s*if you don'?t put a card onto the battlefield this way, (?P<elsebody>.+?)\.?\s*$)?"
    r"(?:\s*(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)

#: Keyword-grant tokens the ``look_top`` "It gains <kw> until end of turn."
#: interpose (Winota, Joiner of Forces) may name → engine ``temp_keywords``
#: slugs (RULE 514.2 cleanup). Deliberately the small combat-relevant set;
#: anything outside it fails the clause match closed.
_LOOK_TOP_HIT_GRANT_KEYWORDS: dict[str, str] = {
    "indestructible": "indestructible",
    "haste": "haste",
    "trample": "trample",
    "flying": "flying",
    "vigilance": "vigilance",
    "lifelink": "lifelink",
    "deathtouch": "deathtouch",
    "menace": "menace",
    "first strike": "first_strike",
    "double strike": "double_strike",
    "hexproof": "hexproof",
}

#: "Gain control of target creature until end of turn. **Untap that
#: creature. It gains haste until end of turn.**" (Act of Treason/Claim the
#: Firstborn-shaped) — same "trailing sentence retroactively describing the
#: previous clause" idiom as `_NO_REGEN_SENTENCE_RE` just above, not a
#: second effect: `effects.GainControlUntilEndOfTurnEffect` (built for the
#: hand-authored Zealous Conscripts) already untaps and grants haste as
#: *part of* the control change itself, so a bare "it gains haste until end
#: of turn." restatement is reprinting what the single `gain_control_until_
#: eot` effect (`catalogue.effect_rows.search_control_attach._gain_control_eot`) already does — it's
#: absorbed here rather than re-modeled.
#:
#: The ``grant`` group generalises that tail to the *richer* restatements
#: real cards pair with a threaten ("untap it. **it gains trample and haste
#: until end of turn.**" — Traitorous Blood; "…**it gains haste and myriad
#: until end of turn.**" — Firbolg Flutist): whatever is not the bare-haste
#: form recurses back through `parse_effect_body` with ``previous_subject``
#: on, so the existing `_prev_subject_singular … gains <kw> until end of
#: turn` handler (→ `pump(previous_subject=True)`, writing `temp_keywords`
#: on the just-controlled creature) claims it — no second RULE 115 target,
#: it reads `GameContext.previous_targets`. Requires the "gain control"
#: clause to be the immediately preceding sentence (anchored on "until end
#: of turn" right before the period) so this can't misfire onto an
#: unrelated creature-choosing clause followed by an unrelated genuine
#: untap effect.
_GAIN_CONTROL_HASTE_TAIL_RE = re.compile(
    r"^(?P<before>gain control of (?:another )?target .+? until end of turn)\.\s*"
    r"untap (?:that creature|that permanent|that artifact|it)[.,]?\s*(?:and\s+)?"
    r"(?P<grant>(?:it|they) gains? [a-z, ]*?haste[a-z, ]*? until end of turn"
    r"|until end of turn, (?:it|they) (?:gains?|has|have|becomes?) .+)"
    r"(?:[.,]\s*(?:and\s+)?(?P<after>.+))?$",
    re.IGNORECASE | re.DOTALL,
)
_GAIN_CONTROL_BARE_HASTE_RE = re.compile(
    r"^(?:it|they) gains? haste until end of turn$", re.IGNORECASE
)

#: "Sacrifice it. **When you do,** `<effect>`." (RULE 603.3's "when you do"
#: sub-trigger, Maestros Theater/Bant Panorama's cousin cycle-shaped) —
#: deliberately narrow, not a general "you may X. When you do, Y." handler:
#: RULE 603.3's own "when you do" only fires *if* the triggering action
#: happened, which for an unconditional "Sacrifice it." antecedent (no
#: "may") is a certainty, so the two clauses collapse to one plain sequence
#: with no interactive branch needed. The 200+ cache hits on "you may
#: `<action>`. When you do, `<effect>`." are a real, much bigger family
#: (RULE 603.3's genuine optional-then-branch shape, needing its own
#: pending_choice) deliberately NOT attempted here — this regex only matches
#: when the clause immediately before "When you do,"/"If you do," is exactly
#: a bare self-sacrifice, so it can never misfire onto one of those.
#:
#: PAR-74: the "**If** you do," connector (Dreamcatcher: "You may sacrifice
#: ~. If you do, draw a card.") collapses the exact same way as "When you
#: do,": by the time `parse_effect_body` sees this clause, the *outer*
#: "you may" has already been peeled off the whole triggered ability
#: (`optional=True` on the `AbilitySpec`, at the cast-trigger dispatch
#: site) — so what's left here, "sacrifice ~. if/when you do, `<effect>`.",
#: is itself an unconditional antecedent once the ability has already been
#: accepted, same as the plain "Sacrifice it." shape this row was built
#: for. RULE 603.3 and 603.4's own "if"/"when" reflexive triggers are a real
#: distinction elsewhere, but not one this already-certain antecedent can
#: ever make observable.
_SACRIFICE_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>sacrifice (?:it|this \w+|~))\.\s*(?:when|if) you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-74: "[You may] exile ~. If you do, return it to the battlefield under
#: its owner's control at the beginning of the next end step." (Hikari,
#: Twilight Guardian) — the exile-zone sibling of
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE`'s own collapse: once the outer "you may"
#: has already been peeled off the whole triggered ability, a bare
#: self-exile is just as certain as a bare self-sacrifice (RULE 400, no
#: failure state), so "if you do" reduces the same way to one plain
#: sequence — an `ExileEffect(remember=True)` linking the exiled object onto
#: this ability's own source (`GameObject.linked_exile_id`, the O-Ring-
#: shaped mechanism `ReturnLinkedExileEffect` already reads), plus a RULE
#: 603.7 delayed trigger (`create_delayed_trigger`, ``step="end"``,
#: ``scope="any"`` — "the next end step" isn't controller-scoped) that fires
#: it at the named step. Narrow to exactly this destination/timing (no
#: "tapped"/"under your control" variant seen yet) rather than a general
#: "exile ~, delayed-return" grammar no other card has needed.
_EXILE_SELF_THEN_DELAYED_RETURN_RE = re.compile(
    r"^(?P<before>exile (?:it|this \w+|~))\.\s*(?:when|if) you do, "
    r"return it to the battlefield under its owner'?s control "
    r"at the beginning of the next end step$",
    re.IGNORECASE | re.DOTALL,
)

#: "Earthbend N. **When you do,** `<effect>`." (RULE 701.66 + RULE 603.3's
#: "when you do" sub-trigger — Earth Rumble). Same collapse rationale as
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE`: "earthbend N" is a mandatory keyword
#: action (no "may"), so RULE 603.3's "when you do" is a certainty and the
#: two sentences reduce to one plain sequence — `[earthbend N, <effect>]` —
#: with no interactive branch. Narrow: only when the clause immediately
#: before "When you do," is exactly `earthbend N`, so it can never misfire
#: onto the genuine optional "you may `<action>`. When you do, …" family.
_EARTHBEND_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>earthbend \d+)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: RULE 706 + 603.11: "Roll a d20. When you do, <payoff where X is the
#: result>." The roll is mandatory, but its payoff is nevertheless a fresh
#: reflexive trigger: Ancient Bronze Dragon's targets must be chosen after
#: its controller knows X. ``RollDieEffect`` owns the deferred trigger; this
#: parser layer only folds the two printed sentences into ``then_trigger``.
_ROLL_DIE_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>roll (?:a |an |\d+ )?(?:d\d+|\d+-sided die(?:s)?))\.\s*"
    r"when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: "Discard a card. **If you do,** `<effect>`." (Gristle Glutton's
#: `{T}, Blight 1:` loot body, and the wider mandatory-discard-then-draw
#: family). Same collapse rationale as the two above — a plain "discard a
#: card" antecedent all but always succeeds, so the "if you do" gate
#: reduces to a sequence `[discard, <effect>]`. **Documented
#: simplification:** the one case it *can* fail (an empty hand) isn't
#: modeled. Narrow: the clause before "if you do," must be exactly a bare
#: mandatory discard, so it never misfires onto the optional
#: "you may discard …. If you do, …" family (`_pay_cost_then_or_else`).
_DISCARD_THEN_IF_YOU_DO_RE = re.compile(
    r"^(?P<before>discard (?:a card|\d+ cards?|your hand))\.\s*(?:if|when) you do,?\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

# A completed action and its reflexive payoff have separate announcements.
_ACTION_THEN_WHEN_YOU_DO_RE = re.compile(
    r'^(?P<before>(?:exile|create) (?:"[^"]*"|[^."])+?)\.\s*when you do,\s*(?P<after>.+)$',
    re.IGNORECASE | re.DOTALL,
)

#: PAR-164: "You may exile `<it / ~>`. **When you do,** `<effect>`." — a dies trigger's source is already a card in
#: its owner's graveyard (RULE 400.7), so the optional exile is the antecedent and the effect is RULE 603.12's
#: reflexive trigger, whose target is chosen only after the exile happened. Unlike the certain-antecedent rows
#: above, the "may" is *kept* (the exile is the choice), so `_PAY_ENERGY_THEN_PEEL_GUARD_RE` leaves it un-peeled and
#: this row lowers the pair onto `may_exile_source_then` (Greenwarden of Murasa / Undead Butler's primitive).
_MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^you may exile (?:it|that card|~)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-121: the rows above whose antecedent is **certain** — a sacrifice of the source, an earthbend, a bare
#: mandatory discard — share one body: parse the antecedent, require the spec type it must produce, then the
#: "when/if you do" sentence is just the next clause (`_with_after_tail`). Each entry is ``(regex, the antecedent
#: spec type it must yield)``; a row's own connective wording stays in its regex, since it is what keeps a
#: *may* antecedent ("you may discard a card. If you do, …" — `_pay_cost_then_or_else`) from collapsing.
#: The antecedents start with different verbs, so the order is immaterial.
_CERTAIN_ANTECEDENT_ROWS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (_SACRIFICE_THEN_WHEN_YOU_DO_RE, "sacrifice_self"),
    (_EARTHBEND_THEN_WHEN_YOU_DO_RE, "earthbend"),
    (_DISCARD_THEN_IF_YOU_DO_RE, "discard"),
)

#: PAR-79 eighth increment: a *preceding* sentence in front of
#: `catalogue.effect_rows.pump_stats._DELAYED_SAC_EXILE_WHEN_FIRST_RE`'s own "at the
#: beginning of the next end step, sacrifice/exile/return `<it>`[. if you
#: do, `<effect>`]." shape (the Alora, Cheerful `<X>` cycle's own
#: unblockable-target sentence ahead of the delayed return). Deliberately
#: loose — it only has to find the split point; `match_clause` re-validates
#: the ``delayed`` half against the real handler, so a wrong split just
#: fails closed rather than misparsing anything. ``before`` is non-greedy
#: so it stops at the *first* such delayed clause, matching how a real
#: card only ever prints one.
_PREFIXED_DELAYED_SAC_EXILE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*(?P<delayed>at the beginning of (?:the|your) next end step, "
    r"(?:sacrifice|exile|return)\b.+)$",
    re.IGNORECASE | re.DOTALL,
)

# PAR-98: the tail-form sibling is attached to an activated ability after
# an ordinary target effect (Wings of Hubris / Goblin Sappers).  As above,
# the catalogue handler validates the tail itself; this only protects the
# two-sentence composition from the generic connector splitter.
_PREFIXED_DELAYED_TAIL_RE = re.compile(
    r"^(?P<before>.+?)\.\s*(?P<delayed>(?:then )?(?:its controller )?"
    r"(?:sacrifice|exile|destroy)\b.+?"
    r"(?:at the beginning of (?:the|your) next end step|at end of combat))$",
    re.IGNORECASE | re.DOTALL,
)

_MILL_LAND_THIS_WAY_RE = re.compile(
    r"^(?P<before>mill (?:a|\d+) cards?)\.\s*if a land card was milled this way,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

_COUNTER_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>put a \+1/\+1 counter on ~)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

_REFLEXIVE_TAP_PEEL_RE = re.compile(
    r"^(?:you may )?(?P<rest>tap another untapped merfolk you control\.\s*when you do,.+)$",
    re.IGNORECASE | re.DOTALL,
)

_TAP_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>tap another untapped [a-z]+ you control)\.\s*when you do,\s*(?P<after>return target creature card with mana value \d+ or less from your graveyard to the battlefield)\.?$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-18/ENG-33: "Exile [up to N] target <X> card from [a/your] graveyard.
#: [If you do / If you exiled a card this way,] create a token that's a copy
#: of **that card**[, except <tail>]." — the reanimator-token cycle (Ardyn,
#: Anikthea, Séance, God-Pharaoh's Gift, Sauron the Necromancer, Sin,
#: Soul Separator &c.). Two sentences that are one instruction: the exiled
#: card *is* the pronoun antecedent (RULE 608.2 — `GameContext.
#: previous_targets`) the copy clause reads back, so — same
#: `parse_effect_body`-level idiom as `_LOOK_TOP_SELECT_RE` /
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE` — the whole span is matched here before
#: the connector-split loop shatters it into a bare "if you do, create …"
#: half no handler claims. The reflexive "if you do" / "if you exiled …
#: this way" connector needs no `pending_choice`: `CopyPermanentEffect
#: (referent="previous")` already no-ops when `previous_targets` is empty,
#: which is exactly the state the connector gates on. Deliberately narrow —
#: the ``after`` group is anchored on "create a … token that's a copy of
#: that card" (an effect that is safe to run unconditionally because it
#: self-gates on the antecedent), never a general reflexive-clause stripper.
_EXILE_THEN_COPY_SENTENCE_RE = re.compile(
    r"^(?P<before>(?:you may )?exile .+?graveyard[^.]*?)\.\s*"
    r"(?:(?:if you do|if you exiled (?:a|up to \w+|\w+) cards?(?: this way)?)"
    r"(?: this way)?,\s*)?"
    r"(?P<after>create a (?:tapped and attacking |tapped |attacking )?"
    r"token that'?s a copy of that card.*)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-30 reanimator-token residue — the *X-count "for each card exiled this
#: way"* sibling of `_EXILE_THEN_COPY_SENTENCE_RE`: "Exile X target creature
#: cards from your graveyard. For each [creature] card exiled this way,
#: `<create clause>`." (Hour of Eternity — a copy token; Midnight Ritual — a
#: plain inline token). The exile is a many-target RULE 107.3 {X} pick
#: (`count_selector="source_x_paid"`, the same one Foggy Swamp Visions'
#: waterbend-X exile uses); the follow-up scales off it — one copy of *each*
#: exiled card (`copy_permanent` ``referent="previous_each"``) or N inline
#: tokens (`create_token` ``count_from_context="objects_exiled_this_way"``).
_EXILE_X_GY_FOR_EACH_CREATE_RE = re.compile(
    r"^exile x target creature cards from your graveyard\.\s*"
    r"for each (?:creature )?card exiled this way,\s*"
    r"(?P<create>create .+)$",
    re.IGNORECASE | re.DOTALL,
)

#: RULE 601.2b/604.3's additional-cost line: "As an additional cost to cast
#: this spell, <cost>." — instants/sorceries only (gated by
#: ``allow_spell_effect`` at the call site below, same as a bare imperative).
#: The wrapper is recognised here; the "<cost>" clause itself is a small
#: closed vocabulary (`_additional_cost_dict`) — anything outside it leaves
#: the whole line unclaimed (fail-closed), never a guessed/partial cost.
_ADDITIONAL_COST_LINE_RE = re.compile(
    r"^as an additional cost to cast this spell,\s*(?P<cost>.+?)\.?\s*$", re.IGNORECASE
)
#: Bite Down on Crime — an optional collect-evidence additional cost followed
#: by the spell's own conditional discount.  These are two distinct ability
#: records: the cost must be offered during casting, while the static
#: reduction must be visible before mana is paid (RULE 601.2f).
_COLLECT_EVIDENCE_COST_REDUCTION_RE = re.compile(
    r"^as an additional cost to cast this spell,\s*you may collect evidence (?P<evidence>\d+)\.\s*"
    r"this spell costs \{(?P<reduction>\d+)\} less to cast if evidence was collected\.?$",
    re.IGNORECASE,
)
_ADDITIONAL_COST_SACRIFICE_RE = re.compile(
    r"^sacrifice an?\s+(creature|artifact|land)$", re.IGNORECASE
)
_ADDITIONAL_COST_SACRIFICE_OR_MANA_RE = re.compile(
    r"^sacrifice a (?P<what>creature) or pay (?P<mana>(?:\{[^{}]+\})+)$",
    re.IGNORECASE,
)
#: "sacrifice an artifact or creature" (RULE 601.2b — Deadly Dispute/Costly
#: Plunder-shaped, the single most-repeated compound sacrifice cost in the
#: cache) — the two-way sibling of `misc_mixin._matches_permanent_type`'s
#: existing ``"creature_artifact_or_land"``/``"creature_or_planeswalker"``
#: sentinels, same idiom: a fixed compound word `costs.parse_activation_cost`
#: reads verbatim (never a general N-way list — RAW only prints a handful of
#: real combinations, so each earns its own sentinel rather than a generic
#: parser).
_ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE = re.compile(
    r"^sacrifice an? (?:artifact or creature|creature or artifact)$", re.IGNORECASE
)
_ADDITIONAL_COST_DISCARD_RE = re.compile(r"^discard\s+(?P<n>an?|x)\s+cards?$", re.IGNORECASE)
#: RULE 601.2b: "exile N [<type>] cards from your graveyard" as an
#: additional cast cost (Cobbled Lancer / Headless Skaab / Makeshift Mauler
#: — "exile a creature card …"; Abhorrent Oculus — "exile 6 cards …"). A
#: hard gate, no "or pay {N}" alternative here. ``type`` is a single main-
#: type word ("creature" is the only one real cards print in this shape).
_ADDITIONAL_COST_EXILE_GRAVEYARD_RE = re.compile(
    r"^exile\s+(?P<n>an?|x|\d+)\s+(?P<type>creature\s+)?cards?\s+from your graveyard$",
    re.IGNORECASE,
)
_ADDITIONAL_COST_PAY_LIFE_RE = re.compile(r"^pay\s+(x|\d+)\s+life$", re.IGNORECASE)
#: "pay N life or pay `<cost>`" (Redirect Lightning) — RULE 601.2b's
#: alternative-additional-cost shape has no `AbilitySpec.additional_cost`
#: representation yet (that field is a single fixed cost, never a
#: player-facing choice between two). **Documented simplification**: only
#: the life-payment alternative is modeled (`{"pay_life": N}`), the same
#: idiom Force of Will's dropped pitch-cost alternative uses elsewhere in
#: this codebase — a real card here always ends up paying the life, never
#: offered the cheaper mana option.
_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE = re.compile(
    r"^pay\s+(x|\d+)\s+life or pay\s+\{[^}]+\}$", re.IGNORECASE
)
#: RULE 701.4a (Behold, PAR-29 — Tarkir: Dragonstorm): "behold a `<type>`
#: [or pay {N}]" as an additional cast cost (Caustic Exhale/Lys Alana
#: Dignitary/Silvergill Mentor/Kinsbaile Aspirant). The type word is a
#: creature type for every real card. **Documented simplification**: the
#: "or pay {N}" mana alternative is dropped (same idiom as
#: `_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE` just above) — a spell is beheld
#: for if a matching permanent/hand card exists and casts regardless. A
#: trailing "and exile it." (the Champion cycle) deliberately fails this
#: anchor — it is `_ADDITIONAL_COST_BEHOLD_EXILE_RE`'s shape instead.
_ADDITIONAL_COST_BEHOLD_RE = re.compile(
    r"^behold an?\s+(?P<q>[a-z][a-z'-]*)(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: RULE 701.4a (Behold, PAR-30 — the Lorwyn "Champion" cycle reflavoured,
#: Champion of the Clachan/Path/Weird, Champions of the Perfect/Shoal):
#: "behold a `<type>` and exile it." as a *mandatory* additional cast cost
#: (no "or pay {N}" alternative — unlike `_ADDITIONAL_COST_BEHOLD_RE`, this
#: one blocks casting when unpayable). The exiled card is given back by the
#: card's own "when ~ leaves the battlefield, return the exiled card to its
#: owner's hand" trigger.
_ADDITIONAL_COST_BEHOLD_EXILE_RE = re.compile(
    r"^behold an?\s+(?P<q>[a-z][a-z'-]*)\s+and exile it$", re.IGNORECASE
)
#: RULE 701.68 (Blight, PAR-29 — Bloomburrow): "blight N [or pay {M}]" as
#: an additional cast cost (Bogslither's Embrace/Wild Unraveling). Same
#: documented "or pay {M}" drop as `_ADDITIONAL_COST_BEHOLD_RE`.
_ADDITIONAL_COST_BLIGHT_RE = re.compile(
    r"^blight\s+(?P<n>\d+)(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: ENG-32 (RULE 701.67, Avatar: TLA): "as an additional cost to cast this
#: spell, waterbend {N}." — a fixed {N} generic mana cost folded into the
#: spell's total (`casting_mixin.effective_cast_cost`). PAR-30: "waterbend
#: {X}" (Crashing Wave / Foggy Swamp Visions / Waterbender's Restoration)
#: now matches too — `{"waterbend": "x"}`, folded with the announced X
#: (`legal_actions` surfaces `has_x` off a mandatory variable additional
#: cost, `effective_cast_cost` folds `mana.with_x(x)`, `x_paid` carries it
#: to the body). "you may waterbend {N}" (a Kicker-shaped *optional*
#: additional cost) is `_ADDITIONAL_COST_OPTIONAL_RE`'s job, not this one.
_ADDITIONAL_COST_WATERBEND_RE = re.compile(
    r"^waterbend\s+\{(?P<n>\d+|x)\}$", re.IGNORECASE
)
#: RULE 701.61 (Forage, PAR-29 — Bloomburrow): "as an additional cost to
#: cast this spell, forage [or pay {M}]." (Feed the Cycle). Same documented
#: "or pay {M}" drop as `_ADDITIONAL_COST_BEHOLD_RE`/`_BLIGHT_RE` — the
#: spell forages if it can and casts regardless. `ActivationCost.forage`
#: (already charged by `_can`/`_pay_activation_cost`).
_ADDITIONAL_COST_FORAGE_RE = re.compile(
    r"^forage(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: PAR-30 / RULE 601.2b: the *optional* additional-cost prefix — "as an
#: additional cost to cast this spell, **you may** <cost>." (Katara Seeking
#: Revenge, Ruinous Waterbending, Burning Curiosity, Graven Archfiend, …).
#: Stripped before `_additional_cost_dict`, and flagged onto
#: `AbilitySpec.additional_cost_optional` so the cost is offered as its own
#: cast variant (`game/engine/legal_actions_mixin._offer_cast`) and its
#: being paid recorded on `GameObject.additional_cost_paid`.
_ADDITIONAL_COST_OPTIONAL_PREFIX_RE = re.compile(r"^you may\s+(?P<cost>.+)$", re.IGNORECASE)

#: RULE 601.2f-adjacent: "If you control a commander, you may cast this
#: spell without paying its mana cost." (Deadly Rollick/Deflecting Swat/
#: Fierce Guardianship-shaped) — a standalone line, own oracle-text sentence
#: from the spell's actual effect, mirroring the additional-cost line's
#: wrapper shape above (recognized whole, produces its own spec carrying no
#: effects). Only "control a commander" is recognized today — any other
#: condition on this exact template leaves the whole line unclaimed
#: (fail-closed), matching `AbilitySpec.free_cast_condition`'s whitelist.
_FREE_CAST_IF_COMMANDER_RE = re.compile(
    r"^if you control a commander,\s*you may cast this spell without paying its mana cost\.?\s*$",
    re.IGNORECASE,
)
_FREE_CAST_IF_ANOTHER_COLOR_RE = re.compile(
    r"^if you'?ve cast another (?P<color>white|blue|black|red|green) spell this turn,\s*"
    r"you may cast this spell without paying its mana cost\.?\s*$", re.IGNORECASE,
)
_CAST_ONLY_IF_ANOTHER_COLOR_RE = re.compile(
    r"^cast this spell only if you'?ve cast another "
    r"(?P<color>white|blue|black|red|green) spell this turn\.?$", re.IGNORECASE,
)

#: "If an opponent cast three or more spells this turn, you may pay {0}
#: rather than pay this spell's mana cost." (Mindbreak Trap-shaped RULE
#: 702's "Trap" template, MEC-12) — a differently-worded but functionally
#: identical `free_cast_condition` alternative (paying ``{0}`` is paying
#: nothing), gated by a *board-count* condition instead of
#: `_FREE_CAST_IF_COMMANDER_RE`'s boolean one — `AbilitySpec.
#: free_cast_condition`'s ``opponent_spells_cast_this_turn_at_least`` key.
_FREE_CAST_IF_OPPONENT_SPELLS_RE = re.compile(
    r"^if an opponent cast (?P<n>\d+) or more spells this turn,\s*"
    r"you may pay \{0\} rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: "If an opponent controls a Forest and you control an Island, you may
#: cast this spell without paying its mana cost." (Submerge — the one real
#: card printing this exact compound board-state gate) — a fixed named
#: condition rather than a generic "opponent controls type X and you
#: control type Y" combinator, same idiom as `_FREE_CAST_IF_COMMANDER_RE`'s
#: own single boolean flag (`AbilitySpec.free_cast_condition`'s
#: ``opponent_controls_forest_and_you_control_island`` key).
_FREE_CAST_IF_OPPONENT_FOREST_YOU_ISLAND_RE = re.compile(
    r"^if an opponent controls a forest and you control an island,\s*"
    r"you may cast this spell without paying its mana cost\.?\s*$",
    re.IGNORECASE,
)

#: RULE 702.8b: "You may cast this spell as though it had flash if it
#: targets a commander." (Timely Ward-shaped, MEC-7) — the same standalone-
#: line wrapper shape as `_FREE_CAST_IF_COMMANDER_RE` just above, but a
#: *timing* permission (`AbilitySpec.conditional_flash`) rather than a
#: *cost* one (`free_cast_condition`). Only "targets a commander" is
#: recognized today, matching `ALLOWED_CAST_CONDITION_KEYS`'s whitelist.
_CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE = re.compile(
    r"^you may cast this spell as though it had flash if it targets a commander\.?\s*$",
    re.IGNORECASE,
)
#: PAR-30, Molten Exhale: "You may cast this spell as though it had flash if
#: you behold a `<type>` as an additional cost to cast it." →
#: `conditional_flash={"controller_beholds_subtype": "<type>"}` (the caster
#: could behold one). The type word is a creature type for every real card.
_CONDITIONAL_FLASH_IF_BEHOLD_RE = re.compile(
    r"^you may cast this spell as though it had flash if you behold an?\s+"
    r"(?P<q>[a-z][a-z'-]*) as an additional cost to cast it\.?\s*$",
    re.IGNORECASE,
)
#: PAR-35's deliberately narrow Mercadian-Masques combat window.
_DECLARE_ATTACKERS_IF_ATTACKED_RE = re.compile(
    r"^cast this spell only during the declare attackers step and only if you've been "
    r"attacked this step\.?$", re.IGNORECASE,
)
#: RULE 506.7b-c: combat-local points plus explicit turn ownership.
_COMBAT_CAST_ONLY_RE = re.compile(
    r"^cast this spell only (?P<window>during combat|during the declare blockers step)"
    r"(?: on (?P<turn>your|an opponent's) turn)?"
    r"(?: (?P<point>before|after) blockers are declared)?\.?$", re.IGNORECASE,
)
_BEFORE_BLOCKERS_CAST_ONLY_RE = re.compile(
    r"^cast this spell only (?:before combat or during combat )?before blockers are declared\.?$",
    re.IGNORECASE,
)

#: PAR-35: paid Flash, where the mana applies only outside a normal sorcery
#: window (enforced by ``GameEngine.effective_cast_cost``).
_CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE = re.compile(
    r"^you may cast this spell as though it had flash if you pay (?P<cost>(?:\{[^{}]+\})+) "
    r"more to cast it\.?$", re.IGNORECASE,
)
#: PAR-35's common Necromancy-style rider.  The delayed trigger primitives
#: already exist; this gives their exact recurring wording a parser route.
_FLASH_THEN_CLEANUP_SAC_RE = re.compile(
    r"^you may cast this spell as though it had flash\. if you cast it any time a sorcery "
    r"couldn't have been cast, the controller of the permanent it becomes sacrifices it at "
    r"the beginning of the next cleanup step\.?$", re.IGNORECASE,
)

#: "Strive — This spell costs `<cost>` more to cast for each target beyond
#: the first." (MEC-4) — not a RULE 702 keyword (no CR entry defines it, see
#: `AbilitySpec.strive_cost`'s docstring), so it's recognized as its own
#: standalone-line template here rather than through `keywords.py`'s
#: numbered catalogue. ``<cost>`` is a run of brace-delimited symbols, same
#: shape `_STRIVE_COST_RE` (`parser/oracle/spec.py`) validates.
_STRIVE_LINE_RE = re.compile(
    # `normalize._strip_unregistered_keyword_labels` removes the "Strive —"
    # label before this runs (Scryfall lists "Strive" in the card's
    # ``keywords`` but it's not a registered RULE 701/702 keyword), so the
    # prefix is optional here — the sentence is unambiguous on its own.
    r"^(?:strive\s*[—-]\s*)?this spell costs (?P<cost>(?:\{[^{}]+\})+) more to cast "
    r"for each target beyond the first\.?\s*$",
    re.IGNORECASE,
)

#: RULE 118.9's "pitch" alternative cost: "You may exile a `<color>` card
#: from your hand rather than pay this spell's mana cost." (MEC-15 — the
#: Force of Will cycle/Misdirection/Pyrokinesis/Snapback/Unmask-shaped
#: family, previously only reachable one card at a time via `ability_
#: catalogue.py`'s `alt_cost={"exile_hand_card_color": …}` — this is the
#: same shape's first oracle-text route). Same standalone-line treatment as
#: every other `alt_cost`/`free_cast_condition` row above.
_ALT_COST_EXILE_HAND_COLOR_RE = re.compile(
    rf"^you may exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: RULE 118.9's other three "pitch"-family shapes (MEC-12's own diagnosed
#: remaining gap, past the "exile a colored card" one above): "You may
#: sacrifice a `<permanent type>` rather than pay this spell's mana cost."
#: (Downhill Charge's "a Mountain") — a bare subtype word, `AbilitySpec.
#: alt_cost`'s ``sacrifice`` key (reused verbatim from the ordinary-cost
#: field, `_matches_sacrifice_type`'s own subtype fallback now recognizes
#: it rather than the old "any permanent" catch-all).
_ALT_COST_SACRIFICE_TYPE_RE = re.compile(
    r"^you may sacrifice an? (?P<what>[a-z]+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "…a nontoken `<color>` creature…" (Flare of Denial) — a qualifier beyond
#: a bare type word, so it's a `combat.matches_object_filter`-shaped dict
#: (``sacrifice_filter``) instead of the plain ``sacrifice`` word above.
_ALT_COST_SACRIFICE_NONTOKEN_COLOR_CREATURE_RE = re.compile(
    rf"^you may sacrifice a nontoken (?P<color>{COLOR_WORD_ALT}) creature "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may return two `<Type>`s you control to their owner's hand rather
#: than pay this spell's mana cost." (Gush) — `AbilitySpec.alt_cost`'s
#: ``return_to_hand_count`` key, the count-generalized sibling of the
#: already-shipped singular ``return_to_hand``. Only "two" is a real
#: cache-wide printing today; a future count word widens the alternation,
#: not the shape.
_ALT_COST_RETURN_TWO_RE = re.compile(
    r"^you may return 2 (?P<subtype>[a-z]+)s you control to their owner'?s hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If you control a `<land type>`, you may pay `<N>` life rather than pay
#: this spell's mana cost." (Snuff Out) — a *board-state-conditioned*
#: pay-life, unlike the already-shipped unconditional Phyrexian-mana-style
#: `pay_life`: `AbilitySpec.alt_cost`'s own ``condition`` key (already
#: used for ``not_your_turn``) gains `condition_query.
#: free_cast_condition_holds`'s new ``control_land_type`` kind.
_ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may pay (?P<n>\d+) life "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: RULE 118.9's plain, unconditional form — "You may pay `<mana>` rather
#: than pay this spell's mana cost." (the Bringer cycle — five-color
#: {W}{U}{B}{R}{G} — among others) is a genuinely *different fixed cost*,
#: not "no cost" (`free_cast_condition`'s job) — `AbilitySpec.alt_cost`'s
#: own ``mana`` key, newly wired into `GameEngine._can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost` (previously unread: `alt_cost=True` always routed
#: through `RulesEngine.cast_without_paying`, which skips mana entirely).
#: The generic unconditional form remains immediately below; the Raid form
#: now has its own earlier, condition-preserving rule.
#: "Raid — If you attacked this turn, you may pay `<mana>` rather than pay
#: this spell's mana cost." (Admiral's Order) — declaration history, not a
#: live attacker count: the condition remains true after combat ends.
_ALT_COST_PAY_MANA_IF_YOU_ATTACKED_RE = re.compile(
    r"^if you attacked this turn, you may pay (?P<mana>(?:\{[^{}]+\})+) "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

_ALT_COST_PAY_MANA_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-19: "If `<N>` or more creatures are attacking, you may pay `<cost>`
#: rather than pay this spell's mana cost." (Lethargy Trap/Arrow Volley
#: Trap — RULE 702's "Trap" template) — a board-*count* gate on the plain
#: mana-payment alt_cost above, the combat-count sibling of
#: `_ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE`'s land-type gate on a life
#: payment; shares that row's ``condition`` key idiom
#: (`AbilitySpec.alt_cost`'s new ``creatures_attacking_at_least``).
_ALT_COST_PAY_MANA_IF_ATTACKING_RE = re.compile(
    r"^if (?P<n>\d+) or more creatures are attacking, you may pay "
    r"(?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: Snuff Out's own sibling shapes (MEC-12's "broader gaps" — the compound
#: "board condition gates a non-mana alt_cost" family, same ``condition``
#: key `_ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE` already carries, just paired
#: with ``sacrifice``/``tap_others`` instead of ``pay_life``). "If you
#: control a `<land type>`, you may sacrifice a creature rather than pay
#: this spell's mana cost." (Dark Triumph).
_ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may sacrifice an? (?P<what>[a-z]+) "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If you control a `<land type>`, you may tap an untapped creature you
#: control rather than pay this spell's mana cost." (Angelic Favor) —
#: `AbilitySpec.alt_cost`'s ``tap_others`` key (RULE 602.1's "Tap N
#: untapped `<type>`s you control", reused verbatim from the ordinary-cost
#: field — `GameEngine._tap_others_pool` now also matches a bare main type
#: like "creature", not just a subtype).
_ALT_COST_TAP_CREATURE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may tap an? untapped creature you control "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may pay `<cost>` and return a basic land you control to its owner's
#: hand rather than pay this spell's mana cost." (the Borderpost cycle) —
#: ``mana``+``return_to_hand_count`` combined in one `alt_cost` dict; both
#: keys are independently checked/paid already (`_can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost`), so no new payment logic, just the new
#: ``"basic land"`` qualifier `_return_to_hand_count_candidates` reads.
_ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) and return a basic land you control "
    r"to its owner'?s hand rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may sacrifice `<N>` `<land type>`s rather than pay this spell's
#: mana cost." (the Odyssey/Judgment "Mountain-cycle"-shaped family) —
#: `AbilitySpec.alt_cost`'s ``sacrifice_count`` key, the count-generalized
#: sibling of the already-shipped singular ``sacrifice``.
_ALT_COST_SACRIFICE_COUNT_RE = re.compile(
    r"^you may sacrifice (?P<n>\d+) (?P<subtype>[a-z]+)s "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-19's own "pitch" residue, all three shapes real cards print past the
#: singular `_ALT_COST_EXILE_HAND_COLOR_RE`/plain
#: `_ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE` rows above:
#:
#: "You may exile 2 `<color>` cards from your hand rather than pay this
#: spell's mana cost." (Soul Spike/Sunscour/Allosaurus Rider/Commandeer/
#: Fury of the Horde-shaped) — `AbilitySpec.alt_cost`'s new
#: ``exile_hand_card_color_count`` key, the counted sibling of the already-
#: shipped singular ``exile_hand_card_color`` (same singular/counted split
#: `return_to_hand`/`return_to_hand_count` and `sacrifice`/`sacrifice_count`
#: already use twice in this family). Only "2" is a real cache-wide
#: printing today, same "widen the alternation, not the shape" note
#: `_ALT_COST_RETURN_TWO_RE` carries.
_ALT_COST_EXILE_HAND_COLOR_COUNT_RE = re.compile(
    rf"^you may exile 2 (?P<color>{COLOR_WORD_ALT}) cards from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If it's not your turn, you may exile a `<color>` card from your hand
#: rather than pay this spell's mana cost." (Force of Virtue/Force of
#: Despair/Force of Rage — the wider Force cycle past the four MEC-15
#: hand-authored ones) — the singular ``exile_hand_card_color`` gated by
#: the same ``not_your_turn`` `condition` key Force of Negation/Vigor's own
#: hand-authored entries already use, now reachable straight from oracle
#: text instead of needing a catalogue entry per card.
_ALT_COST_EXILE_HAND_COLOR_IF_NOT_YOUR_TURN_RE = re.compile(
    rf"^if it'?s not your turn, you may exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may pay 1 life and exile a `<color>` card from your hand rather
#: than pay this spell's mana cost." (Contagion/Force of Rowan) — ``pay_life``
#: + ``exile_hand_card_color`` combined in one `alt_cost` dict; both keys
#: are already independently checked/paid (`_can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost`), so no new payment logic, the same "combine two
#: already-wired keys" idiom `_ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE`
#: uses for ``mana``+``return_to_hand_count``.
_ALT_COST_PAY_LIFE_AND_EXILE_HAND_COLOR_RE = re.compile(
    rf"^you may pay (?P<n>\d+) life and exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may discard a `<basic land type>` card rather than pay this spell's
#: mana cost." (Abolish/Flameshot/Outbreak/Snag — the "Pitch" basic-land
#: cycle) — `AbilitySpec.alt_cost`'s new ``discard_land_type`` key, the
#: discard-zone sibling of ``exile_hand_card_color``.
_ALT_COST_DISCARD_LAND_TYPE_RE = re.compile(
    r"^you may discard an? (?P<land>plains|island|swamp|mountain|forest) card "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: PAR-19's own genuinely new primitive: "You may pay `<cost>` rather than
#: pay this spell's mana cost. Spend only mana produced by Treasures to
#: cast it this way." (Security Rhox/A-Security Rhox) — the plain
#: unconditional mana alt-cost (`_ALT_COST_PAY_MANA_RE`'s own shape) plus a
#: *source-kind* restriction on that specific payment, both sentences on
#: one oracle-text line so one row claims the whole thing (mirrors
#: `_ALT_COST_PAY_MANA_IF_ATTACKING_RE`'s "two sentences, one row" idiom).
#: `AbilitySpec.alt_cost`'s new ``mana_source_kind`` key
#: (`ManaPool.pool_by_source`, `game/mana_abilities.MANA_SOURCE_KINDS`) —
#: real cards print only "Treasures" here.
_ALT_COST_PAY_MANA_IF_TREASURE_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\. "
    r"spend only mana produced by (?P<kind>treasures) to cast it this way\.?\s*$",
    re.IGNORECASE,
)
#: RULE 605.3a's *other* direction, as the spell's own standing restriction
#: rather than an alternative payment at all — "Spend only mana produced by
#: basic lands/creatures to cast this spell." (Imperiosaur/Myr Superion).
#: `AbilitySpec.cast_mana_source_restriction`, not `alt_cost` — these two
#: cards print no alternative cost whatsoever, just a qualifier on their
#: ordinary printed mana cost.
_CAST_MANA_SOURCE_RESTRICTION_RE = re.compile(
    r"^spend only mana produced by (?P<kind>basic lands|creatures) to cast this spell\.?\s*$",
    re.IGNORECASE,
)


#: "`<cost>` or pay {N}" / "pay {N} or `<cost>`" (RULE 601.2b — Lightning Axe "discard a card or pay {5}", Annihilating
#: Glare "pay {4} or sacrifice an artifact or creature", Soaring Stoneglider "exile 2 cards from your graveyard or pay
#: {1}{W}", Daring Buccaneer "reveal a Pirate card from your hand or pay {2}"): the caster picks one branch when
#: casting — the mana by default, the other cost as the `pay_additional` variant (`additional_cost["or_mana"]`).
_ADDITIONAL_COST_OR_MANA_RE = re.compile(
    r"^(?:(?P<cost_first>.+?) or pay (?P<mana_first>(?:\{[^{}]+\})+)"
    r"|pay (?P<mana_second>(?:\{[^{}]+\})+) or (?P<cost_second>.+))$",
    re.IGNORECASE,
)
_OR_MANA_SACRIFICE_PHRASES: dict[str, str] = {
    "creature": "creature", "artifact": "artifact", "land": "land",
    "artifact or creature": "artifact_or_creature", "creature or artifact": "artifact_or_creature",
    "creature or planeswalker": "creature_or_planeswalker", "creature or enchantment": "creature_or_enchantment",
    "creature or land": "creature_or_land", "permanent": "permanent",
}
_ADDITIONAL_COST_TAP_UNTAPPED_RE = re.compile(r"^tap an untapped (?P<what>artifact|creature|land) you control$", re.IGNORECASE)
_ADDITIONAL_COST_OR_MANA_SACRIFICE_RE = re.compile(r"^sacrifice an? (?P<what>.+)$", re.IGNORECASE)
_ADDITIONAL_COST_PAY_N_LIFE_RE = re.compile(r"^pay (?P<n>\d+) life$", re.IGNORECASE)
_ADDITIONAL_COST_REVEAL_FROM_HAND_RE = re.compile(
    r"^reveal an? (?P<type>[a-z]+) card from your hand$", re.IGNORECASE
)


def _or_mana_inner_cost(text: str) -> Optional[dict[str, Any]]:
    """The non-mana half of an "… or pay {N}" additional cost — a closed vocabulary of single costs."""
    text = text.strip().lower()
    if re.fullmatch(r"discard a card", text):
        return {"discard": 1}
    life = _ADDITIONAL_COST_PAY_N_LIFE_RE.match(text)
    if life is not None:
        return {"pay_life": int(life.group("n"))}
    sac = _ADDITIONAL_COST_OR_MANA_SACRIFICE_RE.match(text)
    if sac is not None:
        word = _OR_MANA_SACRIFICE_PHRASES.get(sac.group("what").strip())
        return None if word is None else {"sacrifice": word}
    reveal = _ADDITIONAL_COST_REVEAL_FROM_HAND_RE.match(text)
    if reveal is not None:
        return {"reveal_from_hand": reveal.group("type")}
    tap = _ADDITIONAL_COST_TAP_UNTAPPED_RE.match(text)
    if tap is not None:
        return {"tap_others": [1, tap.group("what")]}
    exile_gy = _ADDITIONAL_COST_EXILE_GRAVEYARD_RE.match(text)
    if exile_gy is not None and not exile_gy.group("type") and exile_gy.group("n").isdigit():
        return {"exile_from_graveyard": {"count": int(exile_gy.group("n"))}}
    return None


def _additional_cost_dict(text: str) -> Optional[dict[str, Any]]:
    """One additional-cost clause's closed vocabulary → its dict, or ``None``.

    Matches `AbilitySpec.additional_cost`'s shape exactly: ``{"sacrifice":
    "creature"|"artifact"|"land"|"artifact_or_creature"}``, ``{"discard": 1|"x"}``, or
    ``{"pay_life": N|"x"}``, or ``{"collect_evidence": N}``.
    """
    text = text.strip().lower()
    collect_evidence = re.fullmatch(r"collect evidence (?P<n>\d+)", text)
    if collect_evidence is not None:
        return {"collect_evidence": int(collect_evidence.group("n"))}
    sac_or_mana = _ADDITIONAL_COST_SACRIFICE_OR_MANA_RE.match(text)
    if sac_or_mana is not None:
        return {"sacrifice_or_mana": {
            "sacrifice": sac_or_mana.group("what"), "mana": sac_or_mana.group("mana"),
        }}
    or_mana = _ADDITIONAL_COST_OR_MANA_RE.match(text)
    if or_mana is not None:
        inner = _or_mana_inner_cost(or_mana.group("cost_first") or or_mana.group("cost_second"))
        if inner is not None:
            return {"or_mana": {"cost": inner, "mana": or_mana.group("mana_first") or or_mana.group("mana_second")}}
    if _ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE.match(text):
        return {"sacrifice": "artifact_or_creature"}
    sac = _ADDITIONAL_COST_SACRIFICE_RE.match(text)
    if sac is not None:
        return {"sacrifice": sac.group(1)}
    # "sacrifice a creature or enchantment" (Final Flare) — a single compound-type sacrifice, tried before the
    # "<A> or <B>" split below so its own " or " isn't read as a branch point.
    compound = _ADDITIONAL_COST_OR_MANA_SACRIFICE_RE.match(text)
    if compound is not None:
        inner = _or_mana_inner_cost(text)
        if inner is not None:
            return inner
    # "<cost A> or <cost B>" with no mana half (Bone Shards): the first " or " that leaves two valid single costs.
    for match in re.finditer(r" or ", text):
        first, second = _or_mana_inner_cost(text[:match.start()]), _or_mana_inner_cost(text[match.end():])
        if first is not None and second is not None:
            return {"either": [first, second]}
    discard = _ADDITIONAL_COST_DISCARD_RE.match(text)
    if discard:
        return {"discard": "x" if discard.group("n").lower() == "x" else 1}
    exile_gy = _ADDITIONAL_COST_EXILE_GRAVEYARD_RE.match(text)
    if exile_gy is not None:
        n = exile_gy.group("n").lower()
        # Single-key dict (RULE 601.2b `AbilitySpec.additional_cost` shape),
        # value structured as ``{"count", "type"?}``.
        value: dict[str, Any] = {"count": "x" if n == "x" else 1 if n in ("a", "an") else int(n)}
        if exile_gy.group("type"):
            value["type"] = "creature"
        return {"exile_from_graveyard": value}
    life = _ADDITIONAL_COST_PAY_LIFE_RE.match(text)
    if life is not None:
        amount = life.group(1)
        return {"pay_life": "x" if amount.lower() == "x" else int(amount)}
    life_or_mana = _ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE.match(text)
    if life_or_mana is not None:
        amount = life_or_mana.group(1)
        return {"pay_life": "x" if amount.lower() == "x" else int(amount)}
    beh_exile = _ADDITIONAL_COST_BEHOLD_EXILE_RE.match(text)
    if beh_exile is not None:
        return {"behold_exile": beh_exile.group("q").strip()}
    beh = _ADDITIONAL_COST_BEHOLD_RE.match(text)
    if beh is not None:
        return {"behold": beh.group("q").strip()}
    blt = _ADDITIONAL_COST_BLIGHT_RE.match(text)
    if blt is not None:
        return {"blight": int(blt.group("n"))}
    wtr = _ADDITIONAL_COST_WATERBEND_RE.match(text)
    if wtr is not None:
        n = wtr.group("n").lower()
        return {"waterbend": "x" if n == "x" else int(n)}
    if _ADDITIONAL_COST_FORAGE_RE.match(text):
        return {"forage": True}
    return None


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
_COMPOUND_PARAM_START_RE = re.compile(
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


def _is_compound_keyword_line(stripped: str) -> bool:
    """A keyword-only line whose own parameter contains commas (PAR-27)."""
    return any(rx.match(stripped) for rx in _COMPOUND_KEYWORD_LINE_RES)


#: RULE 702.174: "Gift a/an `<quality>`" — only the gifts the CR defines are a keyword line.
_GIFT_TOKEN_RE = re.compile(r"^gift an? (?P<quality>[a-z][a-z ]*?)\s*$", re.IGNORECASE)


def _is_keyword_token(tok: str) -> bool:
    # MEC-109: a cost-adjustment sentence is an ability, not a keyword line.
    if tok.startswith("blitz costs "):
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


@dataclass
class Segment:
    """One ability's parse: either a spec (claimed) or the unclaimed raw text."""

    raw: str
    spec: Optional[AbilitySpec] = None
    claimed: bool = False
    #: True when the line is a pure keyword line (claimed elsewhere, by the
    #: keyword catalogue) — it contributes no effect spec here but *is* covered.
    keyword_line: bool = False
    #: Further abilities the same printed line produces. Empty for almost
    #: every line: one printed line is one ability. The exception is RULE
    #: 700.2's *compact* inline modal on an activated ability ("Enchanted
    #: creature gets +1/-1 **or** -1/+1 until end of turn." — Pemmin's
    #: Aura), which is faithfully modeled as two separately-activatable
    #: abilities sharing a cost: choosing which one to activate **is** the
    #: printed choice, so no mode-selection machinery is needed for it.
    extra_specs: list[AbilitySpec] = field(default_factory=list)


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


def _inline_pt_modal_bodies(body: str) -> Optional[list[str]]:
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


def _trigger_event(condition: str) -> Optional[str]:
    """Map a trigger condition phrase to an `EventType`, or ``None`` (fail-closed)."""
    for pattern, event in _TRIGGER_EVENTS:
        if pattern.search(condition):
            return event
    return None


def _variant_trigger_event(condition: str) -> Any:
    """A RULE 9 variant trigger condition (a plane's planeswalk/chaos, a
    scheme's set-in-motion) → its `EventType`, a *list* of two for the
    compound plane template, or ``None`` for anything else."""
    cond = condition.strip()
    for pattern, event in _VARIANT_TRIGGER_CONDITIONS:
        if pattern.match(cond):
            return list(event) if isinstance(event, list) else event
    return None


def _trigger_condition(condition: str) -> Optional[dict[str, Any]]:
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
    if _SELF_SUBJECT_RE.match(cond):
        return {"subject": "self"}
    if _ATTACHED_SUBJECT_RE.match(cond):
        return {"subject": "attached_permanent"}
    m = _OWN_GRAVEYARD_DIES_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "group", "type": m.group("type"), "nontoken": bool(m.group("nontoken")),
            "controller": "any", "owner": "you", "other": False,
        }
    # MEC-49 — "a creature dealt damage by ~ / enchanted creature this turn
    # dies" (before the composed group head below, which has no "dealt damage
    # by …" tail).
    dbs = _DAMAGED_BY_SOURCE_SUBJECT_RE.match(cond)
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
    m = _GOADED_SUBJECT_RE.match(cond)
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
    # Its event must agree with `_trigger_event`'s, which the caller pairs with it.
    composed = legacy_group_condition(cond)
    if composed is not None and composed[0] == _trigger_event(cond):
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
    event = _trigger_event(cond)
    if event is not None:
        condition = _trigger_condition(cond)
        if condition is not None:
            return {"event": event, "condition": condition}
    head = parse_object_trigger_head(cond)
    if head is not None:
        return {"event": head.event, "condition": head.condition, **head.trigger}
    return None


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
            return origin is not None and origin != "battlefield"
        return other.get("to_zone") not in (None, "graveyard")
    # The same event: only "~ … or another … " names two disjoint objects.
    subjects = {(first.get("condition") or {}).get("subject"),
                (second.get("condition") or {}).get("subject")}
    if subjects != {"self", "group"}:
        return False
    group = first if (first.get("condition") or {}).get("subject") == "group" else second
    return bool(group["condition"].get("other"))


def _compound_trigger_heads(cond: str) -> Optional[list[str]]:
    """RULE 603.1's coordinated trigger condition → its independent heads, or ``None``.

    Either two whole heads ("a creature dies or a creature card is put into a graveyard
    from a library" — Dreadhound; "~ dies or another artifact you control dies") or one
    subject with a second verb ("~ or another nontoken artifact you control dies or is
    put into exile from the battlefield" — Psychomancer). After "dies", a bare "is put
    into exile" is the battlefield departure it pairs with (Syr Vondam).
    """
    cond = cond.strip()
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


def _compound_trigger_segment(
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
        part = _segment_line_unsplit(
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
class _ConditionPrefix:
    #: Must expose a ``rest`` group — the effect text the gate applies to.
    #: An optional ``trailing`` group is a *second*, independently-gated
    #: sentence the same match swallowed (see
    #: `_LIFE_GAINED_THIS_TURN_CONDITION_RE`), parsed separately and appended.
    pattern: "re.Pattern[str]"
    #: ``None`` means "this row matched but its condition phrase is outside
    #: the whitelisted vocabulary" — `_peel_condition` then fails the body
    #: closed rather than emitting an ungated effect.
    build: "Callable[[re.Match[str]], Optional[dict[str, Any]]]"
    #: Rewrites the parsed params of each gated spec. Only Kicker needs it:
    #: an "X" inside a "was kicked" wrapper means Kicker's own announced {X}
    #: (`GameObject.kicker_x_paid`), a different sentinel from the spell's.
    rewrite_params: "Optional[Callable[[dict[str, Any], re.Match[str]], None]]" = None
    #: An alternative reading of the gated effect text, tried before the ordinary grammar; ``None`` from
    #: it means "no special reading". Called as ``parse_rest(rest, **parse_effect_body flags)``.
    parse_rest: "Optional[Callable[..., Optional[list[EffectSpec]]]]" = None


def _rewrite_kicker_x(params: dict[str, Any], match: "re.Match[str]") -> None:
    """RULE 702.33b/PAR-17 — see `_ConditionPrefix.rewrite_params`."""
    if match.group("kind").lower() == "bargained":
        return  # Bargain announces no {X} of its own
    for key, value in list(params.items()):
        if value == "x":
            params[key] = "kicker_x"


def _kicked_condition(match: "re.Match[str]") -> dict[str, Any]:
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

#: PAR-62: "if `<cond>`, `<A>`. otherwise, `<B>`." — the one connective that
#: needs the ``if_else`` node rather than a ``condition=`` gate, because it has
#: a second branch. RULE 701.30d's clash "otherwise" is the motivating shape.
#:
#: ENG-37's node is three-valued on purpose: a condition whose referent does
#: not exist runs **neither** branch. That is why this can emit an else at all
#: — a two-valued gate would make ``else`` the catch-all for every unmodelled
#: condition, which is fail-*open*.
_IF_OTHERWISE_RE = re.compile(
    r"^if (?P<cond>[^,]{2,160}),\s+(?P<then>.+?)[.]\s+otherwise,?\s+(?P<els>.+)$",
    re.IGNORECASE)


#: "put a +1/+1 counter on `<X>` and a +1/+1 counter on `<Y>`" — two placements in one sentence.
_DOUBLE_COUNTERS_RE = re.compile(
    r"^put (?P<first>(?:an?|\d+) [+\-]?[a-z0-9/+\-]+ counters? on [^,]+?) "
    r"and (?P<second>(?:an?|\d+) [+\-]?[a-z0-9/+\-]+ counters? on [^,]+)$",
    re.IGNORECASE,
)

#: The suffix spelling of the same branch — "`<A>` if `<cond>`. Otherwise, `<B>`." — with the
#: negated second sentence ("If it doesn't, `<B>`.") read as its "otherwise".
_IF_OTHERWISE_SUFFIX_RE = re.compile(
    r"^(?P<then>[^.]+?),?\s+if (?P<cond>[^,.]{2,80})\.\s+"
    r"(?:otherwise|if (?:it|that creature) (?:doesn'?t|does not)),?\s+(?P<els>.+)$",
    re.IGNORECASE)


def _if_else_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"if `<cond>`, `<A>`. otherwise, `<B>`." → an ``if_else`` node.

    Fails closed unless all three parts resolve: the condition through the
    shared whitelist, and both branches through the ordinary grammar.
    """
    match = _IF_OTHERWISE_RE.match(body) or _IF_OTHERWISE_SUFFIX_RE.match(body)
    if match is None:
        return None
    condition = _group_pronoun_condition(
        match.group("cond"), static_condition(match.group("cond")), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if condition is None:
        return None
    branches = []
    for group in ("then", "els"):
        parsed = parse_effect_body(
            match.group(group).strip(), reading=reading.unattached(),
        )
        if not parsed:
            return None
        branches.append([spec.to_dict() for spec in parsed])
    return [EffectSpec("if_else", {
        "condition": condition, "then": branches[0], "else": branches[1],
    })]


_INSTEAD_OVERRIDE_RE = re.compile(
    r"^(?P<base>[^.]+)\.\s*if (?P<cond>[^,]{2,120}),\s*"
    r"(?:(?P<replacement>[^.]+?) instead|instead (?P<leading>[^.]+?))\.?$", re.I | re.S,
)
_DESTROY_TARGET_COUNTER_TOKEN_RE = re.compile(
    r"^destroy target creature\.\s*if that creature had a \+1/\+1 counter on it, "
    r"(?P<create>create [^.]+? creature token)\.?$", re.I | re.S,
)
_CREATED_TOKENS_HAVE_CDA_RE = re.compile(
    r'^(?P<create>each player creates a [^.]+ creature token)\.\s*'
    r'those creatures have "(?P<cda>(?:this token|this creature|~)\'s power[^\"]+)"\.?$',
    re.I | re.S,
)


def _created_tokens_have_cda_specs(body: str) -> Optional[list[EffectSpec]]:
    """Fuse a distributive create and its quoted token ability (RULE 111.5)."""
    match = _CREATED_TOKENS_HAVE_CDA_RE.fullmatch(body)
    if match is None:
        return None
    # In the created token's *own* ability, "your" means that token's
    # controller. The source spell's controller is irrelevant (RULE 109.4).
    oracle = match.group("cda").replace("its controller's graveyard", "your graveyard")
    created = parse_effect_body(f'{match.group("create")} with "{oracle}"')
    if not created or len(created) != 1 or created[0].type != "create_token":
        return None
    return created


_CREATED_TOKENS_HAVE_ABILITY_RE = re.compile(
    r'^(?P<create>(?:you )?create [^.]+ creature tokens)\.\s*'
    r'(?:they|those tokens) have "(?P<ability>[^"]+)"$', re.I | re.S,
)


def _created_tokens_have_ability_specs(body: str) -> Optional[list[EffectSpec]]:
    """RULE 111.3: a fully parsed quoted ability belongs to each new token."""
    match = _CREATED_TOKENS_HAVE_ABILITY_RE.fullmatch(body)
    if match is None:
        return None
    created = parse_effect_body(match.group("create"))
    ability = segment_line(match.group("ability"), allow_spell_effect=False, provenance=ParserProvenance())
    if (not created or len(created) != 1 or created[0].type != "create_token"
            or not ability.claimed or ability.spec is None):
        return None
    # Preserve the token's own Oracle text. create_token binds this text on
    # each new object, so self references and controllers belong to the token.
    params = dict(created[0].params)
    params["oracle_text"] = "\n".join(filter(None, (
        params.get("oracle_text"), match.group("ability"),
    )))
    return [EffectSpec("create_token", params)]


def _destroy_target_counter_token_specs(body: str) -> Optional[list[EffectSpec]]:
    """Measure the target before destruction, then branch on that snapshot."""
    match = _DESTROY_TARGET_COUNTER_TOKEN_RE.fullmatch(body)
    if match is None:
        return None
    made = parse_effect_body(match.group("create"))
    if not made or len(made) != 1 or made[0].type != "create_token":
        return None
    return [EffectSpec("bind", {
        "name": "n", "amount": {"kind": "counters", "counter": "+1/+1", "of": "target"},
        "effects": [
            EffectSpec("destroy", {"target_kind": "creature"}).to_dict(),
            EffectSpec("if_else", {
                "condition": {"kind": "amount_compare",
                              "left": {"kind": "fixed", "amount": "$n"},
                              "right": {"kind": "fixed", "amount": 0}, "op": "gt"},
                "then": [made[0].to_dict()], "else": [],
            }).to_dict(),
        ],
    })]


_OVERRIDE_NUMBER_RE = re.compile(r"\b\d+\b")
_OVERRIDE_TARGET_RE = re.compile(
    # A graveyard card, with its qualifiers: "target creature card with mana
    # value 3 or less from your graveyard" (Doctor Jane Foster). First, so
    # "target creature" doesn't claim its head.
    r"\btarget (?:[a-z ]*?(?P<card>card)(?: with [^,.]+?)? from your graveyard"
    r"|(?P<noun>creature|player|opponent|permanent)"
    r"(?P<scope> you control| an opponent controls| you don't control)?\b)", re.I,
)


def _resolve_override_referents(base_text: str, replacement_text: str) -> str:
    """Spell the replacement's back-reference as the base's own target phrase.

    RULE 608.2c: "that creature" in "… instead" is the object the base
    targeted, and "she"/"he"/"it" leading the sentence is its subject (~).
    With exactly one target in the base the rewrite is unambiguous; with
    none or several the text is returned unchanged and fails to match.
    """
    rewritten = re.sub(r"^(?:she|he|it)\b", "~", replacement_text.strip(), flags=re.I)
    # PAR-139 (madness overrides): "instead create X of those tokens" names the base's own tokens, and
    # "divided … among those permanents and/or players" the base's own "any number of targets".
    base_tokens = re.search(r"\bcreate \d+ (?P<phrase>.+? tokens?)\b", base_text, flags=re.I)
    if base_tokens is not None:
        rewritten = re.sub(r"\b(?P<n>x|\d+) of those tokens\b",
                           lambda m: f"{m.group('n')} {base_tokens.group('phrase')}", rewritten, flags=re.I)
    if "among any number of targets" in base_text:
        rewritten = rewritten.replace("among those permanents and/or players", "among any number of targets")
    # "~ deals 2 damage to any target. If you're the monarch, it deals 7 damage instead." (Court of
    # Ire): a replacement that names no recipient hits the base's own.
    bare_damage = re.fullmatch(r"~ deals? \d+ damage", rewritten, flags=re.I)
    base_recipient = re.match(r"~ deals? \d+ damage( to .+)$", base_text.strip(), flags=re.I)
    if bare_damage is not None and base_recipient is not None:
        rewritten += base_recipient.group(1)
    targets = list(_OVERRIDE_TARGET_RE.finditer(base_text))
    if len(targets) != 1:
        return rewritten
    noun = (targets[0].group("noun") or targets[0].group("card")).lower()
    that = "player" if noun in ("player", "opponent") else noun
    # Only the first mention is the announced target; a later "that player"
    # in the same sentence stays a back-reference to it (Devour Intellect).
    return re.sub(rf"\bthat {that}\b", targets[0].group(0).lower(), rewritten,
                  count=1, flags=re.I)


#: Params that narrow *which* objects are legal targets or how many — two
#: branches announcing one requirement must agree on all of them.
_TARGET_SHAPE_KEYS: frozenset[str] = frozenset({
    "count_max", "optional", "max_mana_value", "min_mana_value", "mana_value",
    "color", "colors", "spell_filter", "creature_filter", "filter", "target_filter",
    "max_power", "exclude_self", "another",
})
#: Effect types whose ``count`` is a quantity (cards, counters, tokens), never
#: the number of targets — for every other type ``count`` shapes the target.
_COUNT_IS_A_QUANTITY: frozenset[str] = frozenset({
    "discard", "draw", "mill", "add_counters", "create_token", "scry", "surveil",
})


def _target_signature(specs: list["EffectSpec"]) -> list[tuple[str, Any]]:
    """What a branch announces (RULE 601.2c), or ``[]`` when it targets nothing."""
    signature: list[tuple[str, Any]] = []
    for spec in specs:
        if not _names_a_target(spec):
            continue
        keys = set(TARGET_PARAM_KEYS | _TARGET_SHAPE_KEYS)
        if spec.type not in _COUNT_IS_A_QUANTITY:
            keys.add("count")
        signature.extend((key, spec.params.get(key)) for key in sorted(keys)
                         if spec.params.get(key) is not None)
    return signature


def _magnitude_override_specs(
    base_text: str, replacement_text: str, condition: dict[str, Any], *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """"~ deals 3 damage to target creature. If `<cond>`, ~ deals 5 damage to
    that creature instead." (Galvanize) — one effect, one target, two sizes.

    The replacement must be the base with only its number changed, so the
    target announced for the base is the one the bigger effect hits (RULE
    115.1). A `bind` measures the size once and keeps the base's target.
    """
    base_numbers = _OVERRIDE_NUMBER_RE.findall(base_text)
    new_numbers = _OVERRIDE_NUMBER_RE.findall(replacement_text)
    if len(base_numbers) != 1 or len(new_numbers) != 1:
        return None
    rewritten = _resolve_override_referents(base_text, replacement_text)
    if _OVERRIDE_NUMBER_RE.sub("#", rewritten).lower() != (
            _OVERRIDE_NUMBER_RE.sub("#", base_text.strip()).lower()):
        return None
    base = parse_effect_body(base_text, reading=reading)
    bigger = parse_effect_body(rewritten, reading=reading)
    if not base or not bigger or len(base) != 1 or len(bigger) != 1:
        return None
    [base_spec], [bigger_spec] = base, bigger
    keys = [key for key in _MAGNITUDE_PARAM_KEYS
            if base_spec.params.get(key) == int(base_numbers[0])
            and bigger_spec.params.get(key) == int(new_numbers[0])]
    if (len(keys) != 1 or base_spec.type != bigger_spec.type
            # A targeted ``count`` fixes how many targets are announced, which
            # a resolution-time measurement cannot supply (RULE 601.2c).
            or (keys[0] == "count" and _names_a_target(base_spec)
                and base_spec.type not in _COUNT_IS_A_QUANTITY)
            or base_spec.condition is not None
            or {**base_spec.params, keys[0]: None} != {**bigger_spec.params, keys[0]: None}):
        return None
    return [EffectSpec("bind", {
        "name": "n",
        "amount": {"kind": "if", "condition": condition,
                   "then": int(new_numbers[0]), "otherwise": int(base_numbers[0])},
        "effects": [EffectSpec(base_spec.type, {**base_spec.params, keys[0]: "$n"}).to_dict()],
    })]


def _instead_override_specs(body: str, *, reading: ClauseReading = STANDALONE) -> Optional[list[EffectSpec]]:
    """Replace an effect under one shared condition (RULE 614.6).

    The base must not resolve first: a second conditional effect after it
    would scry *and* draw for Rumor Gatherer. A targeted replacement is
    claimed only when it targets exactly what the base did, so `if_else`
    announces one requirement for whichever branch runs.
    """
    match = _INSTEAD_OVERRIDE_RE.fullmatch(body)
    if match is None:
        return None
    ordinal = re.fullmatch(_RESOLUTION_TIME, match.group("cond"), re.I)
    condition = (_resolution_count_condition(ordinal) if ordinal is not None
                 else static_condition(match.group("cond")))
    if condition is None:
        return None
    base_text = match.group("base")
    replacement_text = match.group("replacement") or match.group("leading")
    # "If a creature died this turn, A. If seven or more died, instead B."
    # (Tallyman of Nurgle): the first gate covers the whole override — with
    # it false there is no A for B to replace (RULE 614.6).
    outer = re.fullmatch(r"if (?P<cond>[^,]{2,120}),\s*(?P<rest>.+)", base_text, re.I | re.S)
    if outer is not None:
        outer_condition = static_condition(outer.group("cond"))
        inner = _instead_override_specs(
            f"{outer.group('rest')}. {body[match.end('base') + 1:].strip()}", reading=reading)
        if outer_condition is None or not inner or len(inner) != 1 or inner[0].condition:
            return None
        return [EffectSpec(inner[0].type, inner[0].params, condition=outer_condition)]
    magnitude = _magnitude_override_specs(base_text, replacement_text, condition, reading=reading)
    if magnitude is not None:
        return magnitude
    base = parse_effect_body(base_text, reading=reading)
    replacement = parse_effect_body(
        _resolve_override_referents(base_text, replacement_text), reading=reading)
    if (not base or not replacement
            or any(spec.condition is not None for spec in [*base, *replacement])):
        return None
    # Both branches must announce the same requirement (or none), the only case `if_else`
    # can announce a target (RULE 601.2c) — unless the cast itself already decided which
    # branch runs (a promised gift, RULE 702.174m), when only that branch announces, so the
    # two may differ ("destroy target artifact" / "destroy two target artifacts").
    if not _is_announced_condition(condition) and (
            _target_signature(base) != _target_signature(replacement)
            or (_target_signature(base) and (len(base) != 1 or len(replacement) != 1))):
        return None
    return [EffectSpec("if_else", {
        "condition": condition,
        "then": [spec.to_dict() for spec in replacement],
        "else": [spec.to_dict() for spec in base],
    })]


#: Flags the cast itself decides before targets are chosen — the parser-side mirror of
#: `game/effect_conditions.ANNOUNCED_FLAGS` (this package must not import `game/`).
_ANNOUNCED_FLAGS: frozenset[str] = frozenset({"gift_promised", "madness_cost_paid", "surge_cost_paid"})


def _is_announced_condition(condition: Optional[dict[str, Any]]) -> bool:
    """Whether ``condition`` is a (possibly negated) flag the cast already settled (RULE 601.2b)."""
    while condition and condition.get("kind") == "not":
        condition = condition.get("condition")
    return bool(condition and condition.get("kind") == "flag"
                and condition.get("flag") in _ANNOUNCED_FLAGS and "of" not in condition)


def _names_a_target(spec: "EffectSpec") -> bool:
    return any(
        key in spec.params and spec.params[key] is not None
        for key in TARGET_PARAM_KEYS
    )


#: The *quantity*-shaped "for each" operands — a number to multiply by, not a
#: group to iterate over. "for each card in your hand" is `effect_amounts`'
#: ``resource`` reading, and belongs on ENG-37's ``bind`` node (measure once,
#: hand the number to the body) rather than on ``for_each``, which would
#: iterate over objects that aren't on the battlefield at all.
#:
#: PAR-120 (PARSER_VERSION 471): "card[s] in your hand"/"card[s] in your
#: graveyard" retired — `_count_amount`'s own `parse_count_phrase` fallback
#: below already reaches an unfiltered hand/graveyard zone count (`{"zone":
#: "hand"/"graveyard", "of": "you"}`), proven to count identically to
#: `_resource_of`'s `len(player.hand/graveyard)` (`test_par120_count_
#: phrase.py`). RULE 702.42a Domain stays: a *distinct-land-type* count, not
#: an object/card count, so it was never a `count_phrase` selector shape.
_FOR_EACH_AMOUNTS: dict[str, dict[str, Any]] = {
    "basic land type among lands you control": {"kind": "domain"},
    "basic land types among lands you control": {"kind": "domain"},
    # MEC-84's turn history (Kutzil's Flanker) — the creatures are gone, so no zone
    # count can see them; `GameState.creatures_left_battlefield_this_turn` can.
    "creature that left the battlefield under your control this turn": {
        "kind": "count_selector", "selector": "creatures_that_left_battlefield_this_turn",
    },
    "creatures that left the battlefield under your control this turn": {
        "kind": "count_selector", "selector": "creatures_that_left_battlefield_this_turn",
    },
    # RULE 702.108a: "where X is the number of colors of mana spent to cast this spell" (Radiant Flames).
    "colors of mana spent to cast this spell": {"kind": "count_selector", "selector": "converge"},
    # RULE 705 (PAR-151): the flips of this resolution's coin-flip instruction, by result.
    "flip you win": {"kind": "coin_flips", "won": True},
    "flip you won": {"kind": "coin_flips", "won": True},
    "flip you lose": {"kind": "coin_flips", "won": False},
    "flip you lost": {"kind": "coin_flips", "won": False},
    # RULE 706 (PAR-147): the dice a roll kept, by what they show — "for each even result, …".
    "even result": {"kind": "die_results", "which": "even"},
    "odd result": {"kind": "die_results", "which": "odd"},
    "different result": {"kind": "die_results", "which": "different"},
}

#: The params an effect states its own magnitude in. A ``bind`` body has to
#: name exactly one of these for the measured number to land somewhere; a body
#: with none (or several) is refused rather than guessed at.
_MAGNITUDE_PARAM_KEYS: tuple[str, ...] = ("amount", "count")


#: "for each creature destroyed this way" / "the number of permanents exiled this way" (Fumigate, Death Begets Life,
#: Sunfall) — `GameContext`'s own per-resolution tallies. They count every object the resolution destroyed or
#: exiled, so only the unqualified nouns are read (a "nontoken creature destroyed this way" is a narrower count).
_THIS_WAY_TALLY_RE = re.compile(r"^(?:creature|permanent|card)s? (?P<verb>destroyed|exiled) this way$")
_THIS_WAY_TALLY_NAMES = {"destroyed": "permanents_destroyed_this_way", "exiled": "objects_exiled_this_way"}


_THIS_WAY_COUNT_PHRASE_RE = re.compile(
    r"^(?P<non>non)?(?P<color>white|blue|black|red|green)?(?P<type>creature|artifact|land|enchantment|planeswalker|instant|sorcery|permanent)? ?"
    r"(?:cards?|creatures?|artifacts?|lands?|enchantments?|permanents?)? ?(?P<verb>destroyed|exiled|milled) this way$"
)


def _this_way_filter(m: "re.Match[str]") -> dict[str, Any]:
    """The ``card_type`` / ``negate`` / ``color`` filter a `_THIS_WAY_TYPES` match names (shared by every "this way" reader)."""
    filt: dict[str, Any] = {}
    if m.group("type"):  # "permanent" stays: RULE 110.4 permanent cards are matched by the engine marker
        filt["card_type"] = m.group("type")
        if m.group("non"):
            filt["negate"] = True
    if m.group("color"):
        filt["color"] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color")]
    return filt


def _count_amount(
    phrase: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[dict[str, Any]]":
    """The quantity a "for each `<phrase>`" / "the number of `<phrase>`" measures, as an
    `effect_amounts` spec, or ``None`` for a phrase outside every reading."""
    phrase = phrase.strip().lower()
    amount = _FOR_EACH_AMOUNTS.get(phrase)
    if amount is not None:
        return amount
    this_way = _THIS_WAY_TALLY_RE.match(phrase)
    if this_way is not None:
        return {"kind": "this_way", "tally": _THIS_WAY_TALLY_NAMES[this_way.group("verb")]}
    typed = _THIS_WAY_COUNT_PHRASE_RE.match(phrase)
    if typed is not None:
        # PAR-175 M4b: "the number of creature cards exiled this way" -- the typed handle (`effect_amounts.this_way_count`).
        filt = _this_way_filter(typed)
        if typed.group("verb") == "milled" or filt:
            return {"kind": "this_way_count", "pool": typed.group("verb"), **filt}
    cm = _FOR_EACH_COUNTER_RE.match(phrase)
    if cm is not None:
        who = cm.group("who").lower()
        # "~"/"this <type>" name the source; a bare "it" is the source under a
        # self-subject trigger ("when ~ dies, draw a card for each +1/+1 counter on
        # it") and an earlier clause's target only when one was announced — with
        # neither, nothing says which permanent it is, so the phrase is refused
        # rather than measured against an empty referent (which reads 0).
        if who == "~" or who.startswith("this ") or (who == "it" and reading.self_subject):
            of = "source"
        elif reading.previous_subject:
            of = "previous_target"
        else:
            return None
        return {"kind": "counters", "counter": cm.group("counter").lower(), "of": of}
    # PAR-120: any other count phrase — a structured selector over the shared
    # noun-phrase grammar, not a table row.
    selector = parse_count_phrase(phrase)
    if selector is None:
        return None
    amount = {"kind": "count_selector", "selector": selector}
    filt = selector.get("filter") if isinstance(selector, dict) else None
    if isinstance(filt, dict) and (
        filt.get("blocking_source") or filt.get("shares_creature_type_with_reference")
        or (filt.get("not_reference") and reading.group_subject and not reading.previous_subject)
    ):
        # The counted-against object is the one a pronoun names — "for each creature blocking
        # **it**", "for each **other** creature that shares a creature type with **it**" — which
        # under a group trigger is the firing object, after an earlier clause its pick.
        if reading.group_subject and not reading.previous_subject:
            amount["reference"] = "trigger_subject"
        elif reading.previous_subject:
            amount["reference"] = "previous_target"
    return amount


def _for_each_amount_specs(
    match: "re.Match[str]", phrase: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"<effect> for each `<quantity>`" → a ``bind`` node, or ``None``.

    Fails closed on an unlisted quantity phrase, a body that doesn't parse, a
    body that announces a target, or a body whose magnitude isn't a single
    recognised param — in the last case there is nowhere unambiguous to put
    the measured number, and putting it in the wrong place would scale
    something the card never scaled.
    """
    amount = _count_amount(
        phrase, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if amount is None:
        return None
    return _bound_for_each_amount(
        match, amount, reading=reading.unattached(),
    )


def _bound_pump_for_each(spec: EffectSpec, amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """"gets +1/+0 until end of turn for each `<quantity>`" (PAR-123) — a ``pump`` scales
    per counted object, so each nonzero printed half takes the measured number. Two
    different nonzero halves ("+2/+1 for each …") would need a per-half multiplier
    and are refused; so is anything that isn't a plain printed +N/+M."""
    params = dict(spec.params)
    halves = {k: params.get(k) for k in ("power", "toughness")}
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in halves.values()):
        return None
    scaled = {k: v for k, v in halves.items() if v}
    if not scaled or len(set(scaled.values())) != 1:
        return None
    unit = next(iter(scaled.values()))
    if unit > 1:
        amount = {**amount, "multiply": unit}
    for key in scaled:
        params[key] = "$n"
    return [EffectSpec("bind", {
        "name": "n", "amount": amount,
        "effects": [{"type": "pump", "params": params}],
    })]


#: PAR-132: "<Tap/Sacrifice/Return/Discard> any number of `<what>`. `<body>` for each `<what>` `<verb>ed` this way."
#: (Harmony of Nature, Minas Tirith Garrison, Charge Across the Araba, Mind Maggots, ...). RULE 608.2c: "this way"
#: names the objects the first instruction actually acted on, so the pick and its payoff are one `choose_objects`
#: whose ``then_that_many`` body is bound to how many were picked (the "x" sentinel, `_substitute_x_specs`) --
#: the body is the ordinary "for each" bind over that count. The pool noun must be the counted noun, so "for each
#: *other* thing" never aliases the pick.
_THIS_WAY_PAST = {"tap": "tapped", "sacrifice": "sacrificed", "return": "returned", "discard": "discarded"}
_THIS_WAY_PICK_ACTION = {"tap": "tap", "sacrifice": "sacrifice", "return": "return_to_hand", "discard": "discard"}
_ANY_NUMBER_LEAD = (
    r"(?:you may )?(?P<verb>tap|sacrifice|return|discard) any number of (?P<what>[a-z ]+?)"
    r"(?: to (?:its owner's|their owner's|their owners') hands?)?"
)
_ANY_NUMBER_THIS_WAY_TRAILING_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*(?P<rest>[^.]+?),? for each (?P<noun>[a-z ]+?) (?P<past>[a-z]+) this way\.?$"
)
_ANY_NUMBER_THIS_WAY_LEADING_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*for each (?P<noun>[a-z ]+?) (?P<past>[a-z]+) this way, (?P<rest>[^.]+?)\.?$"
)
#: The pick-pool characteristics a `choose_objects` ``permanent_filter`` can carry for this family.
_THIS_WAY_FILTER_KEYS = frozenset({"card_type", "subtype"})


#: "Discard your hand[, then draw N cards]." (Pyretic Charge, Malfegor): the whole hand is the pick, so it is the
#: any-number pick made mandatory and complete; the redraw runs after the discard and its tally.
_DISCARD_HAND_LEAD_RE = re.compile(
    r"^discard (?:your hand|all the cards in your hand)(?:, then draw (?P<draw>\d+) cards)?\.\s*"
)


def _any_number_pick_pool(verb: str, what: str) -> "Optional[tuple[dict[str, Any], dict[str, Any]]]":
    """The pick pool of "<verb> any number of `what`": ``(parsed count phrase, its filter)`` or ``None``."""
    # The pool is the controller's own permanents ("you control") or, for a discard, their hand ("cards").
    if verb == "discard":
        if not what.endswith(" cards") and what != "cards":
            return None
        pool_phrase = what
    elif what.endswith(" you control"):
        pool_phrase = what[: -len(" you control")]
    elif verb == "sacrifice":
        pool_phrase = what  # "sacrifice any number of creatures": always the controller's own
    else:
        return None
    untapped = pool_phrase.startswith("untapped ")
    if untapped != (verb == "tap"):
        return None
    pool = parse_count_phrase(pool_phrase.removeprefix("untapped "))
    if pool is None:
        return None
    pool_filter = dict(pool.get("filter") or {})
    if set(pool_filter) - _THIS_WAY_FILTER_KEYS:
        return None
    return pool, pool_filter


def _any_number_pick_params(verb: str, pool_filter: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "action": _THIS_WAY_PICK_ACTION[verb], "what": "permanent", "count": "all", "optional": True,
    }
    if pool_filter:
        params["permanent_filter"] = pool_filter
    if verb == "tap":
        params["require_untapped"] = True
    if verb == "discard":
        params["pool_zones"] = ["hand"]
    return params


#: PAR-132: "<Sacrifice/Discard> any number of `<what>`. `<body naming that many/much>`" (Landslide, Last-Ditch Effort,
#: Scapeshift, Rites of Spring, Angelic Aberration, Nantuko Cultivator). RULE 608.2c / 701.21: "that many" is how many
#: the first instruction actually sacrificed / discarded, so the pick (a mandatory-free `choose_objects`) is bracketed by
#: a `mark_event_log` and each body effect's one printed number is bound to the `sacrificed_this_way` /
#: `discarded_this_way` count over that window. Unlike the `then_that_many` form the body stays a top-level effect,
#: so a body target (Landslide's "target player or planeswalker") is announced on cast as usual (RULE 601.2c).
_ANY_NUMBER_THAT_MANY_RE = re.compile(
    rf"^{_ANY_NUMBER_LEAD}\.\s*(?:if you do, )?(?P<rest>[^.]*\bthat (?:many|much)\b[^.]*?)\.?$"
)
_THAT_MANY_TO_ONE_RE = re.compile(r"\bthat (?:many|much)\b")
_THIS_WAY_PICK_VERB_PAST = {"sacrifice": "sacrificed", "discard": "discarded"}


def _any_number_that_many_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    m = _ANY_NUMBER_THAT_MANY_RE.match(body)
    if m is None or m.group("verb") not in _THIS_WAY_PICK_VERB_PAST:
        return None
    verb = m.group("verb")
    pick = _any_number_pick_pool(verb, m.group("what"))
    if pick is None:
        return None
    _, pool_filter = pick
    # The measured number replaces one printed "1": parse the body with the placeholder, then bind it.
    inner = parse_effect_body(
        _THAT_MANY_TO_ONE_RE.sub("1", m.group("rest").strip()), reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if not inner:
        return None
    amount = {"kind": f"{_THIS_WAY_PICK_VERB_PAST[verb]}_this_way"}
    bound: list[EffectSpec] = []
    for spec in inner:
        one = _bind_magnitude(spec, amount)
        if one is None or '"type": "sacrifice"' in json.dumps(one[0].to_dict(), default=str):
            return None
        bound += one
    return [EffectSpec("mark_event_log", {}), EffectSpec("choose_objects", _any_number_pick_params(verb, pool_filter)), *bound]


def _any_number_this_way_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    whole_hand = _DISCARD_HAND_LEAD_RE.match(body)
    if whole_hand is not None:
        specs = _any_number_this_way_specs(
            "discard any number of cards. " + body[whole_hand.end():], reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
        )
        if specs is None:
            return None
        # The whole hand is the pick, so it is mandatory; the `mark_event_log` bracket of the "that many" form
        # (index 0 there) is left in front of it.
        at = next(i for i, spec in enumerate(specs) if spec.type == "choose_objects")
        specs[at] = EffectSpec("choose_objects", {**specs[at].params, "optional": False})
        draw = whole_hand.group("draw")
        return specs + ([EffectSpec("draw", {"count": int(draw)})] if draw else [])
    m = _ANY_NUMBER_THIS_WAY_TRAILING_RE.match(body) or _ANY_NUMBER_THIS_WAY_LEADING_RE.match(body)
    if m is None:
        return _any_number_that_many_specs(body, reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
    verb = m.group("verb")
    if m.group("past") != _THIS_WAY_PAST[verb]:
        return None
    pick = _any_number_pick_pool(verb, m.group("what"))
    if pick is None:
        return None
    _, pool_filter = pick
    counted = parse_count_phrase(m.group("noun"))
    if counted is None:
        return None
    # Every pick is in the pool, so a counted noun that is the pool's own or broader ("for each card discarded"
    # after "any number of creature cards") counts exactly the picks; a narrower one would not.
    counted_filter = dict(counted.get("filter") or {})
    if counted_filter and counted_filter != pool_filter:
        return None
    bound = _bound_for_each_amount(
        re.match(r"(?P<rest>.+)", m.group("rest").strip()), {"kind": "fixed", "amount": "x"},
        reading=ClauseReading(self_subject=reading.self_subject, previous_subject=False, group_subject=reading.group_subject, previous_selector=False),
    )
    if bound is None or len(bound) != 1 or '"target_kind"' in json.dumps(bound[0].to_dict(), default=str):
        return None
    params = {**_any_number_pick_params(verb, pool_filter), "then_that_many": {"effects": [bound[0].to_dict()]}}
    return [EffectSpec("choose_objects", params)]


#: PAR-132 / PAR-175 M4b: "<instruction>. If a [non]creature card was `<verb>`ed this way, <body>." and "<instruction>.
#: <effect> for each [non]land card `<verb>`ed this way." / "for each … this way, <effect>." (Diregraf Scavenger,
#: Seasoned Pyromancer, Multani's Decree, Tribune of Rot ...). RULE 608.2c: "this way" is exactly what the instruction
#: before it exiled / destroyed / milled / discarded / sacrificed -- one grammar over one typed handle
#: (`effect_amounts.THIS_WAY_POOLS`, the ``this_way_pool`` condition, the ``this_way_count`` amount). A discard or
#: sacrifice can pause for the affected player's answer, so those two read the `mark_event_log` window instead of a
#: per-resolution list; their amounts keep the older ``discarded_this_way`` / ``sacrificed_this_way`` spelling.
_THIS_WAY_TYPES = (
    r"(?P<non>non)?(?P<color>white|blue|black|red|green)?(?P<type>creature|artifact|land|enchantment|planeswalker|instant|sorcery|permanent)?"
)
#: verb -> the effect types that perform it (the first clause must contain one) and whether it needs the event window.
_THIS_WAY_VERBS: dict[str, tuple[frozenset[str], bool]] = {
    "exiled": (frozenset({"exile"}), False),
    "destroyed": (frozenset({"destroy"}), False),
    "milled": (frozenset({"mill"}), False),
    "discarded": (frozenset({"discard"}), True),
    "sacrificed": (frozenset({"sacrifice"}), True),
}
_THIS_WAY_VERB_RE = "|".join(_THIS_WAY_VERBS)
_THIS_WAY_IF_RE = re.compile(
    rf"^if an? {_THIS_WAY_TYPES} ?(?:card )?(?P<aux>was|is) (?P<verb>{_THIS_WAY_VERB_RE}) this way, (?P<then>.+?)\.?$"
)
_THIS_WAY_EACH_RE = re.compile(
    rf"^(?:then )?(?P<rest>.+?) for each {_THIS_WAY_TYPES} ?(?:card )?(?P<verb>{_THIS_WAY_VERB_RE}) this way\.?$"
)
_THIS_WAY_EACH_LEAD_RE = re.compile(
    rf"^for each {_THIS_WAY_TYPES} ?(?:card )?(?P<verb>{_THIS_WAY_VERB_RE}) this way, (?P<rest>.+?)\.?$"
)
_THIS_WAY_SPLIT_RE = re.compile(
    rf"\.\s+(?=(?:if an? [a-z]+ (?:card )?(?:was|is) (?:{_THIS_WAY_VERB_RE}) this way, "
    rf"|for each [a-z ]*(?:{_THIS_WAY_VERB_RE}) this way, "
    rf"|.+ for each [a-z ]*(?:{_THIS_WAY_VERB_RE}) this way))"
)


def _announces_real_target(specs: "list[EffectSpec]") -> bool:
    """Whether any (nested) spec names a RULE 115 target; ``target_kind`` null/"source" is the untargeted self form."""
    return re.search(
        r'"target_kind": "(?!source")', json.dumps([spec.to_dict() for spec in specs], default=str),
    ) is not None


def _this_way_sequences(
    body: str, *, verbs: frozenset[str], reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """The instruction + its "this way" consumers (see the block comment above), for the pools in ``verbs``."""
    if " this way" not in body or not any(f" {v} this way" in body for v in verbs):
        return None
    parts = _THIS_WAY_SPLIT_RE.split(body)
    if len(parts) < 2:
        return None
    before = parse_effect_body(parts[0].strip().rstrip("."), reading=ClauseReading(group_subject=reading.group_subject))
    if not before:
        return None
    before_json = json.dumps([s.to_dict() for s in before], default=str)
    windowed = False
    specs = list(before)
    for sentence in parts[1:]:
        sentence = sentence.strip()
        m = _THIS_WAY_IF_RE.match(sentence)
        each = None
        if m is None:
            each = m = _THIS_WAY_EACH_RE.match(sentence) or _THIS_WAY_EACH_LEAD_RE.match(sentence)
        if m is None or (m.group("non") and not m.group("type")) or m.group("verb") not in verbs:
            return None
        verb = m.group("verb")
        producers, needs_window = _THIS_WAY_VERBS[verb]
        # The measured verb must be the one the first clause performs ("sacrificed this way" after a discard is not).
        if not any(f'"type": "{effect_type}"' in before_json for effect_type in producers):
            return None
        windowed = windowed or needs_window
        filt: dict[str, Any] = {}
        if m.group("type"):
            filt["card_type"] = m.group("type")
            if m.group("non"):
                filt["negate"] = True
        if m.group("color"):
            filt["color"] = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[m.group("color")]
        if each is None:
            if verb == "destroyed" and m.group("aux") == "is":
                return None  # "if a creature is destroyed this way" is the older condition-peel row's (`static_handlers`)
            if verb in ("destroyed", "milled") and re.search(r"\b(?:it|its|that|those|them|they|their)\b", m.group("then")):
                return None  # a pronoun would name the pooled object, which no row can bind yet: stay unclaimed
            then = parse_effect_body(m.group("then"), reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
            if not then or any(spec.condition for spec in then) or _announces_real_target(then):
                return None
            condition: dict[str, Any] = {"kind": "this_way_pool", "pool": verb, **filt}
            specs += [EffectSpec(spec.type, dict(spec.params), condition=condition) for spec in then]
            continue
        if verb in ("destroyed", "exiled") and not filt.get("negate") and not filt.get("color") and filt.get("card_type", "creature") in ("creature", "permanent"):
            return None  # the untyped destroyed/exiled tally (`_THIS_WAY_TALLY_RE`, permanents_destroyed_this_way) already owns this
        amount: dict[str, Any] = (
            {"kind": f"{verb}_this_way", **filt} if needs_window else {"kind": "this_way_count", "pool": verb, **filt}
        )
        bound = _bound_for_each_amount(
            m, amount, reading=ClauseReading(self_subject=reading.self_subject, previous_subject=False, group_subject=reading.group_subject, previous_selector=False),
        )
        # A `bind` only scales effects whose factory reads a ``$n`` count (a `sacrifice` count is a plain int).
        if bound is None or _announces_real_target(bound) or '"type": "sacrifice"' in json.dumps(
                [s.to_dict() for s in bound], default=str):
            return None
        specs += bound
    return [EffectSpec("mark_event_log", {}), *specs] if windowed else specs


def _bound_for_each_amount(
    match: "re.Match[str]", amount: dict[str, Any], *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """The body of "<effect> for each `<quantity>`" bound to a measured ``amount``."""
    inner = parse_effect_body(
        match.group("rest").strip(), reading=reading.unattached(),
    )
    if not inner or len(inner) != 1:
        return None
    # RULE 601.2c: unlike `for_each`, a `bind` runs its body exactly once and
    # `BindEffect.target_specs` forwards the body's requirement, so "target
    # opponent loses 1 life for each Vampire you control" keeps its target
    # (PAR-128). The measured amount never reads the target.
    if inner[0].type == "pump":
        # "other" counts against the ability's own source; under a group trigger the
        # counted-against object is the firing creature, which the count can't name yet.
        if reading.group_subject and "'not_reference': True" in repr(amount) and not amount.get("reference"):
            return None
        return _bound_pump_for_each(inner[0], amount)
    wrapper = inner[0].params
    if inner[0].type == "trigger_subject_referent" and not wrapper.get("acting") and len(
            wrapper.get("effects") or []) == 1:
        # "put a +1/+1 counter on that hero for each …": the scaled effect is the wrapper's one
        # body, so the measurement is bound inside it, where the firing object is in scope.
        nested = wrapper["effects"][0]
        bound = _bind_magnitude(EffectSpec(nested["type"], nested.get("params") or {}), amount)
        if bound is None:
            return None
        return [EffectSpec("trigger_subject_referent", {**wrapper, "effects": [bound[0].to_dict()]})]
    return _bind_magnitude(inner[0], amount)


def _bind_magnitude(spec: "EffectSpec", amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """``spec`` with its one printed magnitude replaced by the measured ``amount`` (a ``bind``)."""
    keys = [k for k in _MAGNITUDE_PARAM_KEYS if k in spec.params]
    if len(keys) != 1:
        return None
    params = dict(spec.params)
    printed = params[keys[0]]
    if isinstance(printed, bool) or not isinstance(printed, int) or printed < 1:
        return None  # only a printed number can scale the count ("lose 2 life for each …")
    if printed > 1:
        amount = {**amount, "multiply": printed}
    params[keys[0]] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": spec.type, "params": params}],
    })]


#: PAR-62: "<effect> for each <group>" (`13_` 5.2's 5.9% connective) as an
#: ENG-37 ``for_each`` node over `continuous.group_selector_objects`.
#:
#: Deliberately narrow, for one reason the measurement made concrete: only
#: *object-group* phrases belong on this node. The other frequent "for each"
#: operands are counts, not battlefield groups — "for each card in your
#: hand", "for each +1/+1 counter on it" — and those are an *amount*
#: (`game/effect_amounts.py`), not an iteration; routing them here would
#: iterate over nothing and silently do nothing at all.
#:
#: PAR-120 (PARSER_VERSION 473): the eleven values this table used to
#: hand-maintain are gone — `parse_count_phrase` resolves every one of them
#: to an equivalent *structured* selector instead of a named string (proven
#: equivalent to the `group_selector_objects` string each replaced,
#: `test_par120_count_phrase.py`; `group_selector_objects` itself now
#: accepts the structured form directly — see its own docstring). The
#: *phrase set* stays exactly these eleven, though, not "whatever the shared
#: grammar happens to recognize": the grammar is far more permissive than
#: this table ever was, and `_for_each_amount_specs` below already reaches
#: `parse_count_phrase` too, for the *count* reading of a "for each `<X>`"
#: this node's own group/iteration reading isn't right for. Widening the
#: phrase set here would silently steal phrases that must stay on the
#: amount path — a `bind`-scaled single effect, not a `for_each` node
#: repeating the body once per object — which are not always
#: interchangeable even when they add up to the same total (`for_each`
#: hands each object to the body as its own target, `bind` never targets
#: anything the body didn't already announce).
_FOR_EACH_GROUP_PHRASES: frozenset[str] = frozenset({
    "creature you control", "creatures you control",
    "artifact you control", "artifacts you control",
    "land you control", "lands you control",
    "permanent you control", "permanents you control",
    "legendary creature you control",
    "attacking creature", "attacking creatures",
})

_FOR_EACH_SUFFIX_RE = re.compile(
    # MEC-83 widened the group class to admit "+1/+1 counter on it" — digits
    # and `+`/`/` — alongside the plain "creatures you control" phrasings;
    # PAR-120 adds `~` ("for each verse counter on ~", Lost Isle Calling).
    r"^(?P<rest>.+?),?\s+for each (?P<group>[a-z0-9+/ ~-]{3,70})$", re.IGNORECASE)

#: MEC-83: "<effect> for each `<X>` counter on (it|~|this <type>)" — a named
#: counter read (`effect_amounts` ``counters`` kind), the amount sibling of
#: the group phrases in `_FOR_EACH_AMOUNTS`. Built dynamically rather than
#: enumerated: any `<word>` a card prints before "counter" *is* a real
#: counter name (RULE 122.1), and `GameObject.counters.get(name, 0)` is 0 on
#: a permanent that has none — safe either way.
_FOR_EACH_COUNTER_RE = re.compile(
    r"^(?P<counter>[+\-]?\d+/[+\-]?\d+|[a-z][a-z-]*) counters? on "
    r"(?P<who>it|~|this [a-z]+)$",
    re.IGNORECASE,
)


def _for_each_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """"<effect> for each <group>" → a ``for_each`` node, or ``None``.

    Fails closed on anything it cannot represent exactly: an unlisted group
    phrase, a body that doesn't parse, or — the subtle one — a body that
    **announces a target**. `ForEachEffect` hands each selected object to the
    body *as its targets*, which is right for "create a token for each …" and
    flatly wrong for "deal 1 damage to target creature for each …", where it
    would override the announced RULE 115 target with the iteration item.
    """
    match = _FOR_EACH_SUFFIX_RE.match(body)
    if match is None:
        return None
    phrase = match.group("group").strip().lower()
    selector = parse_count_phrase(phrase) if phrase in _FOR_EACH_GROUP_PHRASES else None
    if selector is None:
        return _for_each_amount_specs(
            match, phrase, reading=reading.unattached(),
        )
    inner = parse_effect_body(
        match.group("rest").strip(), reading=reading.unattached(),
    )
    if not inner:
        return None
    if any(_names_a_target(spec) for spec in inner):
        return None
    return [EffectSpec("for_each", {
        "over": {"selector": selector},
        "effects": [spec.to_dict() for spec in inner],
    })]


#: PAR-120: "`<effect with x>`, where X is the number of `<count phrase>`" and "`<you gain
#: life | draw cards | ~ deals damage>` equal to the number of `<count phrase>`" — the
#: effect parsed with a literal X (every X-capable handler already reads it) and the X
#: bound to one measured count, instead of one row per verb × per quantity.
_WHERE_X_RE = re.compile(
    r"^(?P<rest>.+?),?\s+where x is the number of (?P<phrase>.+)$", re.IGNORECASE
)
_EQUAL_TO_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage) equal to the number of (?P<phrase>.+?)"
    r"(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)
#: The same quantity with the recipient *before* "equal to": "~ deals damage to target creature equal to
#: the number of lands you control." (Earth Tremor, Will of the Mardu, ~40 cards) — read as the
#: `_EQUAL_TO_RE` spelling "~ deals X damage to target creature" with X bound to the count.
_DAMAGE_TO_EQUAL_TO_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?P<noun>damage)(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))"
    r" equal to the number of (?P<phrase>.+)$",
    re.IGNORECASE,
)
#: "`<verb>` life/cards/damage equal to **the greatest power among creatures you control**" (Garruk,
#: Primal Hunter; ~25 cards) — an aggregate over a group rather than a count of it, read by
#: `count_phrase.parse_amount_phrase`. The recipient may sit before "equal to" or after the term.
_EQUAL_TO_AGGREGATE_RE = re.compile(
    r"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage)(?P<pre>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?"
    r" equal to (?P<phrase>the (?:greatest|total) (?:mana value|power|toughness) (?:among|of) .+?|"
    rf"{SACRIFICED_TERM})"
    r"(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)
#: The params an X can sit in once an X-capable handler has parsed the body.
_X_PARAM_KEYS: tuple[str, ...] = ("amount", "count", "power", "toughness", "max_mana_value")


#: "`<effect with x>`, where x is the sacrificed creature's power" (Ghoulcaller Gisa, Atogatog) — X as an
#: amount term rather than "the number of …": read by `count_phrase.parse_amount_phrase` like the aggregates.
_WHERE_X_AMOUNT_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+where x is (?P<phrase>(?:\d+ plus )?(?:{SACRIFICED_TERM}"
    r"|the amount of life you (?:gained|lost) this turn"
    r"|the (?:greatest|total) (?:mana value|power|toughness) (?:among|of) [^.]+?))$", re.IGNORECASE
)
#: RULE 107.2: "where x is half the number of <phrase>, rounded up/down" -- the count of `_WHERE_X_RE` halved.
_HALF_DIVISOR = 2
_WHERE_X_HALF_COUNT_RE = re.compile(
    r"^(?P<rest>.+?),?\s+where x is half the number of (?P<phrase>.+?), rounded (?P<round>up|down)$", re.IGNORECASE
)
#: "`<sentence>`, where x is `<phrase>`. `<more sentences>`" — the sentence defining X is not the last.
_WHERE_X_MID_BODY_RE = re.compile(
    r"^(?P<head>[^.]*?),\s*where x is (?P<phrase>[^.]+?)\.\s+(?P<tail>.+)$",
    re.IGNORECASE,
)


#: "`<head>`, where x is `<phrase>`, then `<tail>`" — the definition sits between two parts of one
#: sentence ("look at the top x cards of your library, where x is the number of cards in your hand, then
#: put them back in any order", Descendant of Soramaro). Moved to the end, X is the same measurement.
_WHERE_X_THEN_RE = re.compile(
    r"^(?P<head>[^.]*?),\s*where x is (?P<phrase>[^.,]+?),\s*then (?P<tail>[^.]+)$", re.IGNORECASE,
)


_MINUS_TAIL_RE = re.compile(r"\s+minus (?P<n>\d+)$")

#: RULE 706 (PAR-147): the number a die roll just produced, as the amount a sentence measures —
#: "`<effect with x>`, where x is **the result**" (Numbing Jellyfish), "`<verb>` life/cards/damage
#: equal to **the result**" (Big Boa Constrictor), "put a number of `<kind>` counters on `<where>` equal
#: to the result" and "create a number of `<tokens>` equal to the result" (Mother Kangaroo, Box of
#: Free-Range Goblins). The effect is parsed with a literal X and the X bound to the ``die_result``
#: amount (`GameContext.die_result`, the sum of the kept dice — so a kept die after "ignore one" is
#: what "the result" reads). "the total of those results" is the same sum; "minus N" floors at 0.
_DIE_PHRASE_AMOUNTS: dict[str, dict[str, Any]] = {
    "the result": {"kind": "die_result"},
    "the total of those results": {"kind": "die_result"},
    # The Endeavor cycle's "roll two dice and choose one result": the picked die and the one left over.
    "that result": {"kind": "die_choice", "which": "chosen"},
    "the other result": {"kind": "die_choice", "which": "other"},
}
_DIE_RESULT_PHRASE = "|".join(_DIE_PHRASE_AMOUNTS)
_DIE_MINUS_TAIL = r"(?: minus (?P<minus>\d+))?"
_DIE_DAMAGE_RECIPIENT = (
    r"(?:any target|target [a-z ]+?|each opponent|each player|that player|you"
    r"|each (?:creature|other creature|creature (?:you control|your opponents control|you don't control)))"
)
_WHERE_X_DIE_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+where x is (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE
)
_EQUAL_TO_DIE_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage) equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}"
    rf"(?P<tail>\s+to {_DIE_DAMAGE_RECIPIENT})?$",
    re.IGNORECASE,
)
_DAMAGE_TO_EQUAL_TO_DIE_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>damage)(?P<tail>\s+to {_DIE_DAMAGE_RECIPIENT})"
    rf" equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)
_COUNTERS_EQUAL_DIE_RE = re.compile(
    r"^put (?:a number of )?(?P<kind>[+\-]\d+/[+\-]\d+ |[a-z]+ )?counters? on (?P<where>.+?) equal to "
    rf"(?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)
_TOKENS_EQUAL_DIE_RE = re.compile(
    rf"^create a number of (?P<what_token>.+?) tokens?(?P<with> with [a-z, ]+?)? equal to "
    rf"(?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$",
    re.IGNORECASE,
)


#: "search your library for a number of basic land cards equal to the other result, put them onto the battlefield
#: tapped, then shuffle" (Wild Endeavor) is "search your library for X basic land cards, …".
_SEARCH_NUMBER_DIE_RE = re.compile(
    rf"^(?P<head>search your library for) a number of (?P<what>.+?) equal to (?P<phrase>{_DIE_RESULT_PHRASE})"
    rf"{_DIE_MINUS_TAIL}(?P<tail>,.*)$", re.IGNORECASE,
)
#: "you may cast an instant or sorcery spell with mana value less than or equal to the other result from your hand
#: without paying its mana cost" (Arcane Endeavor) is "… with mana value X or less …".
_CAST_MV_DIE_RE = re.compile(
    rf"^(?P<pre>.+? with mana value) less than or equal to (?P<phrase>{_DIE_RESULT_PHRASE})"
    rf"{_DIE_MINUS_TAIL}(?P<post> from your hand.*)$", re.IGNORECASE,
)
#: "return a creature card from your graveyard to the battlefield with a number of +1/+1 counters on it equal to
#: that result" (Grave Endeavor) is "… with X +1/+1 counters on it".
_RETURN_COUNTERS_DIE_RE = re.compile(
    rf"^(?P<head>return .+? to the battlefield) with a number of (?P<kind>[+\-]\d+/[+\-]\d+|[a-z]+) counters on it"
    rf" equal to (?P<phrase>{_DIE_RESULT_PHRASE}){_DIE_MINUS_TAIL}$", re.IGNORECASE,
)

_DESTROY_POWER_AT_LEAST_DIE_RE = re.compile(
    rf"destroy each creature with power greater than or equal to (?P<phrase>{_DIE_RESULT_PHRASE})", re.IGNORECASE,
)
_SCRY_NUMBER_OF_RE = re.compile(r"(?P<verb>scry|surveil) a number of", re.IGNORECASE)


def _die_x_rest(text: str) -> "Optional[tuple[str, dict[str, Any]]]":
    """``(rest, amount)`` for a sentence measuring the die result, with the X written literally in
    ``rest``; ``None`` for any other sentence. See `_DIE_RESULT_PHRASE`."""
    m = _WHERE_X_DIE_RE.match(text)
    if m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_DIE_RE.match(text) or _DAMAGE_TO_EQUAL_TO_DIE_RE.match(text)
        if m is not None:
            verb = m.group("verb")
            scry = _SCRY_NUMBER_OF_RE.fullmatch(verb) if m.group("noun").startswith("card") else None
            if scry is not None:  # "scry a number of cards equal to the result" is "scry X"
                rest = f"{scry.group('verb')} x"
            else:
                rest = f"{verb} x {m.group('noun')}{m.groupdict().get('tail') or ''}"
        else:
            m = _COUNTERS_EQUAL_DIE_RE.match(text)
            if m is not None:
                kind = (m.group("kind") or "").strip()
                if kind in ("a", "the", "that", "x"):  # "put a counter" / "put x counters": not a kind word
                    return None
                rest = f"put x {kind + ' ' if kind else ''}counters on {m.group('where')}"
            else:
                m = _TOKENS_EQUAL_DIE_RE.match(text)
                if m is not None:
                    rest = f"create x {m.group('what_token')} tokens{m.group('with') or ''}"
                else:
                    m = _SEARCH_NUMBER_DIE_RE.match(text)
                    if m is not None:
                        rest = f"{m.group('head')} x {m.group('what')}{m.group('tail')}"
                    else:
                        m = _CAST_MV_DIE_RE.match(text)
                        if m is not None:
                            rest = f"{m.group('pre')} x or less{m.group('post')}"
                        else:
                            m = _RETURN_COUNTERS_DIE_RE.match(text)
                            if m is None:
                                return None
                            rest = f"{m.group('head')} with x {m.group('kind')} counters on it"
    amount: dict[str, Any] = dict(_DIE_PHRASE_AMOUNTS[m.group("phrase").lower()])
    if m.group("minus"):
        # RULE 107.1b: a negative X is 0.
        amount = {**amount, "minus": int(m.group("minus")), "minimum": 0}
    return rest, amount


def _where_x_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
    several: bool = False,
    divide_by: "Optional[tuple[int, bool]]" = None,
) -> "Optional[list[EffectSpec]]":
    """See `_WHERE_X_RE`; ``None`` unless the body parses to one effect holding the X — or,
    with ``several``, to several effects that share it ("~ deals X damage to target
    creature and you gain X life, where X is …" — one X for the whole sentence)."""
    text = body.strip().rstrip(".").strip()
    halved = _WHERE_X_HALF_COUNT_RE.match(text)
    if halved is not None and divide_by is None:
        # RULE 107.2: "where x is half the number of <phrase>, rounded up/down" is the count with a rounded halving.
        return _where_x_specs(
            f"{halved.group('rest')}, where x is the number of {halved.group('phrase')}",
            reading=reading.unattached(),
            several=several,
            divide_by=(_HALF_DIVISOR, halved.group("round") == "up"),
        )
    between = _WHERE_X_THEN_RE.match(text)
    if between is not None:
        scope = reading.unattached()
        # One effect that reads "then" inside itself ("look at the top x cards …, then put them back in any order")…
        whole = _where_x_specs(
            f"{between.group('head')}, then {between.group('tail')}, where x is {between.group('phrase')}",
            several=several, reading=scope,
        )
        if whole is not None:
            return whole
        # …otherwise X belongs to the first effect only and the rest follows it ("scry x, where x is …, then
        # draw 3 cards", Ugin's Insight): measured before the first effect, which nothing earlier can change.
        head = _where_x_specs(f"{between.group('head')}, where x is {between.group('phrase')}", reading=scope)
        tail = parse_effect_body(between.group("tail").strip(), reading=scope) if head is not None else None
        return None if head is None or not tail else head + tail
    power_bound = _DESTROY_POWER_AT_LEAST_DIE_RE.fullmatch(text)
    if power_bound is not None:
        # "destroy each creature with power greater than or equal to that result" (Valiant Endeavor): the bound
        # is inside the mass filter, where the plain X holders of `_bind_x_specs` do not reach.
        return [EffectSpec("bind", {
            "name": "n", "amount": dict(_DIE_PHRASE_AMOUNTS[power_bound.group("phrase").lower()]),
            "effects": [{"type": "destroy", "params": {"selector": "all_creatures", "filter": {"min_power": "$n"}}}],
        })]
    die_x = _die_x_rest(text)
    if die_x is not None:
        return _bind_x_specs(
            die_x[0], die_x[1], reading=reading.unattached(),
            several=several,
        )
    m = _WHERE_X_RE.match(text)
    amount_m = _WHERE_X_AMOUNT_RE.match(text) if m is None else None
    if amount_m is not None:
        m = amount_m
    elif m is None or "." in m.group("phrase"):
        # PAR-137: the definition sits mid-body — "exile the top x cards of your library, where x is
        # the number of creatures you control. You may play those cards this turn." X is one
        # measurement for the whole ability, so it reads the same moved to the end.
        mid = _WHERE_X_MID_BODY_RE.match(text)
        if mid is not None:
            return _where_x_specs(
                f"{mid.group('head')}. {mid.group('tail')}, where x is {mid.group('phrase')}",
                reading=reading.unattached(),
                several=several,
            )
        if m is not None:
            return None  # a sentence break inside the phrase that is not this shape: not an X definition
    aggregate = None
    if amount_m is not None:
        aggregate, rest = m, m.group("rest")
    elif m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_RE.match(text) or _DAMAGE_TO_EQUAL_TO_RE.match(text)
        if m is None:
            m = aggregate = _EQUAL_TO_AGGREGATE_RE.match(text)
        if m is None:
            return None
        recipient = (m.groupdict().get("pre") or "") + (m.group("tail") or "")
        rest = f"{m.group('verb')} x {m.group('noun')}{recipient}"
    if aggregate is not None:
        term = parse_amount_phrase(m.group("phrase"))
        amount = None if term is None else {"kind": "count_selector", "selector": term}
    else:
        phrase = m.group("phrase")
        # "…the number of cards in your hand **minus 4**" (Ivory Tower): a negative X counts as 0
        # (RULE 107.1b), so the subtraction is floored.
        minus = _MINUS_TAIL_RE.search(phrase)
        if minus is not None:
            phrase = phrase[: minus.start()]
        amount = _count_amount(phrase, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET)), )
        if amount is None and " plus the number of " in phrase:
            # "…the number of caves you control **plus the number of** cave cards in your graveyard" (Calamitous
            # Cave-In): a sum of counts, which the amount grammar reads as one expression.
            summed = parse_amount_phrase(f"the number of {phrase}")
            if isinstance(summed, dict) and "terms" in summed:
                amount = {"kind": "count_selector", "selector": summed}
        if amount is not None and minus is not None:
            amount = {**amount, "minus": int(minus.group("n")), "minimum": 0}
    if amount is None:
        return None
    if divide_by is not None:
        amount = {**amount, "divide": divide_by[0], **({"round_up": True} if divide_by[1] else {})}
    return _bind_x_specs(
        rest, amount, reading=reading.unattached(),
        several=several,
    )


def _bind_x_specs(
    rest: str, amount: "dict[str, Any]", *, reading: ClauseReading = STANDALONE,
    several: bool = False,
) -> "Optional[list[EffectSpec]]":
    """``rest`` parsed with a literal X, the X bound to the measured ``amount`` (see `_where_x_specs`)."""
    inner = parse_effect_body(
        rest.strip(), reading=reading.unattached(),
    )
    if not inner or (len(inner) != 1 and not several):
        return None
    effects: list[dict[str, Any]] = []
    bound_any = False
    for spec in inner:
        params = dict(spec.params)
        # "-x" (a pump's -X/-X) binds as the negated measurement.
        negated = [k for k in _X_PARAM_KEYS if params.get(k) == "-x"]
        if any(v == "-x" for k, v in params.items() if k not in _X_PARAM_KEYS):
            return None
        holders = [k for k in _X_PARAM_KEYS if params.get(k) in ("x", "-x")]
        nested = False
        if not holders and isinstance(params.get("then_effects"), list):
            # An X inside the effects that follow a pick ("return a creature card … with X counters on it").
            params["then_effects"], nested = _replace_x(params["then_effects"])
        if isinstance(params.get('return_effects'), list):
            params['return_effects'], return_x = _replace_x(params['return_effects'])
            nested = nested or return_x
        if isinstance(params.get('extra_counters'), dict):
            params['extra_counters'], counter_x = _replace_x(params['extra_counters'])
            nested = nested or counter_x
        if several and not (holders or nested):
            # "put a +1/+1 counter on ~, then create X tokens, where X is the number of
            # counters on ~" (Anim Pakal) measures *after* the first effect; a bind
            # measures once, before all of them. Only a sentence whose every effect
            # takes the X is one shared measurement.
            return None
        for key in holders:
            params[key] = "-$n" if key in negated else "$n"
        bound_any = bound_any or bool(holders) or nested
        entry = {"type": spec.type, "params": params}
        if spec.condition is not None:
            entry["condition"] = dict(spec.condition)
        effects.append(entry)
    if not bound_any:
        return None
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": effects})]


#: PAR-123: an amount that is a characteristic of the object a pronoun names — "put x +1/+1 counters
#: on it, where x is **its power**", "gain life equal to **that creature's toughness**", "create X
#: tokens, where X is **that creature's mana value**". The effect is parsed with a literal X and the
#: X bound to that object's characteristic (`effect_amounts`' ``characteristic``), the same shape
#: `_where_x_specs` gives a counted quantity.
_REFERENT_WHAT = r"(?P<what>power|toughness|mana value)"
_REFERENT_POSSESSIVE = rf"(?:its|that {PRONOUN_NOUN_ALT}'s)"
_WHERE_X_CHARACTERISTIC_RE = re.compile(
    rf"^(?P<rest>.+?),?\s+where x is {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$", re.IGNORECASE
)
_EQUAL_TO_CHARACTERISTIC_RE = re.compile(
    rf"^(?P<verb>.+?)\s+(?P<noun>life|cards?|damage) equal to {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}"
    r"(?P<tail>\s+to (?:any target|target [a-z ]+?|each opponent|each player|that player))?$",
    re.IGNORECASE,
)
#: "put +1/+1 counters on X equal to its power" / "put a number of +1/+1 counters on X equal to its
#: power" / "create a number of 1/1 … tokens equal to its power" — the count is the X.
_COUNTERS_EQUAL_CHARACTERISTIC_RE = re.compile(
    rf"^put (?:a number of )?(?P<kind>[+\-]\d+/[+\-]\d+ )?counters? on (?P<where>.+?) equal to "
    rf"{_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$", re.IGNORECASE,
)
_TOKENS_EQUAL_CHARACTERISTIC_RE = re.compile(
    rf"^create a number of (?P<what_token>.+?) tokens? equal to {_REFERENT_POSSESSIVE} {_REFERENT_WHAT}$",
    re.IGNORECASE,
)
_CHARACTERISTIC_NAMES = {"power": "power", "toughness": "toughness", "mana value": "mana_value"}


def _replace_x(node: Any) -> "tuple[Any, bool]":
    """``node`` with each "x" magnitude in its nested effect specs swapped for the bound ``$n``."""
    if isinstance(node, dict):
        replaced = False
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _X_PARAM_KEYS and value == "x":
                out[key] = "$n"
                replaced = True
            else:
                out[key], inner = _replace_x(value)
                replaced = replaced or inner
        return out, replaced
    if isinstance(node, list):
        pairs = [_replace_x(item) for item in node]
        return [p[0] for p in pairs], any(p[1] for p in pairs)
    return node, False


def _referent_characteristic_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """See `_REFERENT_WHAT`; ``None`` unless the body reads as one X-taking effect."""
    if reading.self_subject or not (reading.group_subject or reading.previous_subject):
        return None
    text = body.strip().rstrip(".").strip()
    m = _WHERE_X_CHARACTERISTIC_RE.match(text)
    if m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_CHARACTERISTIC_RE.match(text)
        if m is not None:
            rest = f"{m.group('verb')} x {m.group('noun')}{m.group('tail') or ''}"
        else:
            m = _COUNTERS_EQUAL_CHARACTERISTIC_RE.match(text)
            if m is not None:
                rest = f"put x {m.group('kind') or ''}counters on {m.group('where')}"
            else:
                m = _TOKENS_EQUAL_CHARACTERISTIC_RE.match(text)
                if m is None:
                    return None
                rest = f"create x {m.group('what_token')} tokens"
    if re.match(r"(?:gains|draws|loses|discards|mills|sacrifices)\b", rest.strip(), re.IGNORECASE):
        # A third-person verb with no subject of its own ("…, then gains life equal to that
        # creature's toughness") acts for whoever the clause before it named — not necessarily "you".
        return None
    amount = {
        "kind": "characteristic", "characteristic": _CHARACTERISTIC_NAMES[m.group("what").lower()],
        "of": "trigger_subject" if reading.group_subject and not reading.previous_subject else "previous_target",
    }
    inner = parse_effect_body(
        rest.strip(), reading=ClauseReading(self_subject=False, group_subject=reading.group_subject, referents=reading.referents),
    )
    if not inner:
        return None
    effects: list[dict[str, Any]] = []
    bound_any = False
    for spec in inner:
        data, replaced = _replace_x(spec.to_dict())
        if replaced and spec.type == "trigger_subject_referent":
            pass
        bound_any = bound_any or replaced
        effects.append(data)
    if not bound_any:
        return None
    return [EffectSpec("bind", {"name": "n", "amount": amount, "effects": effects})]


#: PAR-128: the player-subject slot. "each player mills 3 cards", "each opponent gains 10
#: life", "target opponent becomes the monarch" — the verb's own grammar already reads
#: "target player `<verb>`" (one player target, nothing else), so the subject is a
#: slot over that reading rather than a word in every verb's row: "each player / each
#: opponent" iterates the body over those players (`for_each` hands each one to it as
#: its target, APNAP order, RULE 101.4), and "target opponent" narrows the target.
_PLAYER_SCOPE_SUBJECT_RE = re.compile(
    r"^(?P<who>each player|each opponent|target opponent) (?P<rest>.+)$", re.IGNORECASE
)
_PLAYER_SCOPE_ITERATION = {"each player": "each_player", "each opponent": "each_opponent"}


def _player_scope_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    """See `_PLAYER_SCOPE_SUBJECT_RE`; ``None`` unless every effect of the "target
    player" reading targets exactly that one player and nothing else."""
    m = _PLAYER_SCOPE_SUBJECT_RE.match(body.strip())
    if m is None:
        return None
    inner = parse_effect_body(
        f"target player {m.group('rest')}", reading=reading.unattached(),
    )
    if not inner:
        return None
    for spec in inner:
        named = [spec.params[k] for k in TARGET_PARAM_KEYS if spec.params.get(k) is not None]
        if named != ["player"] or spec.type in ("for_each", "bind", "if_else", "seq"):
            return None
    who = m.group("who").lower()
    if who == "target opponent":
        return [
            EffectSpec(spec.type, {**spec.params, "target_kind": "opponent"}, condition=spec.condition)
            for spec in inner
        ]
    return [EffectSpec("for_each", {
        "over": {"players": _PLAYER_SCOPE_ITERATION[who]},
        "effects": [spec.to_dict() for spec in inner],
    })]


#: PAR-112: the object-scope sibling of the player-subject slot above — a *leading*
#: "for each `<count phrase>`, `<body>`" whose body names the iterated object as "it"
#: ("for each token you control that entered this turn, create a token that's a copy of
#: it" — Ocelot Pride, Chief Magistrate of Mercadia, Saheeli the Gifted). RULE 101.4:
#: one pass per object, each a separate instruction. The body is parsed with the
#: pronoun reading on, and only effects that name their object through a ``referent``
#: are accepted — each is re-pointed at `GameContext.iteration_item`. Anything else (a
#: body that targets, or a pronoun some other effect family reads) fails closed.
_LEADING_FOR_EACH_OBJECT_RE = re.compile(
    r"^for each (?P<group>[a-z0-9+/ '~-]{3,80}?), (?P<rest>.+)$", re.IGNORECASE
)
#: The ``referent`` values that are the pronoun "it" — re-pointed at the loop item.
_ITERATION_REFERENTS = frozenset({"previous"})
#: The zones a leading "for each <objects>" may iterate: the battlefield, and exile (cards a prior clause exiled).
_ITERATION_ZONES = frozenset({"battlefield", "exile"})


#: RULE 705 (PAR-151): "for each flip you win, `<effect>`" — the leading spelling of the suffix
#: "`<effect>` for each flip you won": the effect's one printed magnitude is bound to the
#: ``coin_flips`` amount (`_count_amount` reads the same phrase), so it fails closed on any body
#: without exactly one scalable count.
_LEADING_FOR_EACH_FLIP_RE = re.compile(
    r"^for each (?P<what>flip you (?:win|lose|won|lost)|(?:even|odd|different) result),\s*(?P<rest>.+)$", re.IGNORECASE
)


def _leading_for_each_flip_specs(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> "Optional[list[EffectSpec]]":
    m = _LEADING_FOR_EACH_FLIP_RE.match(body.strip())
    if m is None:
        return None
    return _for_each_amount_specs(
        m, m.group("what").lower(), reading=reading.unattached(),
    )


def _leading_for_each_object_specs(body: str) -> "Optional[list[EffectSpec]]":
    """See `_LEADING_FOR_EACH_OBJECT_RE`."""
    m = _LEADING_FOR_EACH_OBJECT_RE.match(body.strip())
    if m is None:
        return None
    over: dict[str, Any]
    if m.group("group") == "of them":
        # PAR-119: "whenever 1 or more tokens … enter, for each of them, …" (Kambal) — the
        # members of the firing batch that matched its head (``matching_ids``); the
        # segmenter keeps it off any head that isn't a batch.
        over = {"batch_members": True}
    else:
        selector = parse_count_phrase(m.group("group"))
        # PAR-153: a card zone too — "for each creature card you own in exile with a memory counter on it,
        # create a … token that's a copy of it" (Altaïr); `ForEachEffect` reads the zone's cards.
        if (
            selector is None or selector.get("zone") not in _ITERATION_ZONES or "terms" in selector
            or "distinct" in selector or "aggregate" in selector
        ):
            return None
        over = {"selector": selector}
    inner = parse_effect_body(m.group("rest").strip(), reading=ClauseReading(previous_subject=True))
    if not inner:
        return None
    effects = []
    for spec in inner:
        if spec.params.get("referent") not in _ITERATION_REFERENTS or _names_a_target(spec):
            return None
        entry: dict[str, Any] = {
            "type": spec.type, "params": {**spec.params, "referent": "iteration"},
        }
        if spec.condition is not None:
            entry["condition"] = dict(spec.condition)
        effects.append(entry)
    return [EffectSpec("for_each", {"over": over, "effects": effects})]


def _bind_x(effects: list[EffectSpec], amount: dict[str, Any]) -> "Optional[list[EffectSpec]]":
    """Bind the single X-holding param of a one-effect body to ``amount``
    (the `_where_x_specs` idiom, for a caller that already has the amount).
    ``None`` unless exactly one effect carries an X — the measured number
    must have exactly one unambiguous place to go."""
    if len(effects) != 1:
        return None
    wrapped = effects[0].params.get("effects") if effects[0].type == "trigger_subject_referent" else None
    if wrapped and len(wrapped) == 1 and not effects[0].params.get("acting"):
        # "put that many +1/+1 counters on **it**": the X sits in the firing-object wrapper's one body.
        bound = _bind_x([EffectSpec(wrapped[0]["type"], wrapped[0].get("params") or {})], amount)
        if bound is None:
            return None
        return [EffectSpec(
            "trigger_subject_referent", {**effects[0].params, "effects": [bound[0].to_dict()]},
            condition=effects[0].condition,
        )]
    params = dict(effects[0].params)
    holders = [k for k in _X_PARAM_KEYS if params.get(k) == "x"]
    if not holders or any(v == "-x" for v in params.values()):
        return None
    for key in holders:
        params[key] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": effects[0].type, "params": params}],
    }, condition=effects[0].condition)]


#: PAR-62 (`14_` S4): the generic RULE 603.4 gate. Every row above names one
#: printed phrasing; these two name the *shape* and hand the condition text to
#: `static_handlers.static_condition` — the same whitelisted recognizer the
#: RULE 613.6 "as long as" statics use, which returns a `game/static_
#: conditions.py` dict. One vocabulary for "is this true", read at both ends of
#: the pipeline, instead of a second table of effect-time conditions.
#:
#: A phrase outside that whitelist returns ``None`` and fails the body closed
#: (`_peel_condition`), which is why these can sit last without over-claiming:
#: they only ever convert an *already-unclaimed* body into a gated one.
_GENERIC_IF_PREFIX_RE = re.compile(
    r"^if (?P<cond>[^,]{2,160}),\s+(?P<rest>.+)$", re.IGNORECASE)
_GENERIC_IF_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?),?\s+if (?P<cond>[^,]{2,160})$", re.IGNORECASE)
#: "…unless `<x>`" is the same gate negated — ENG-36 added the ``not``
#: combinator to `static_conditions` for exactly this shape.
_GENERIC_UNLESS_PREFIX_RE = re.compile(
    r"^unless (?P<cond>[^,]{2,160}),\s+(?P<rest>.+)$", re.IGNORECASE)
_GENERIC_UNLESS_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?),?\s+unless (?P<cond>[^,]{2,160})$", re.IGNORECASE)


def _generic_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    return static_condition(m.group("cond"))


def _generic_negated_condition(m: "re.Match[str]") -> "Optional[dict[str, Any]]":
    inner = static_condition(m.group("cond"))
    return None if inner is None else {"kind": "not", "condition": inner}


_CONDITION_PREFIXES: tuple[_ConditionPrefix, ...] = (
    # Adamant's spell-local payment fact is not a board-state phrase for the
    # generic condition grammar: it must be recognized before an effect body
    # can be claimed, so the rider never silently becomes unconditional.
    _ConditionPrefix(_ADAMANT_MANA_SPENT_IF_RE, _adamant_mana_spent_condition),
    # "`<effect>` if an opponent lost N or more life this turn." (Davros,
    # Dalek Creator) — a suffix, but peeled here with the prefixes because it
    # gates the whole pre-split body.
    _ConditionPrefix(
        _OPPONENT_LOST_LIFE_SUFFIX_RE,
        lambda m: {"kind": "opponent_lost_life_this_turn", "min": int(m.group("n"))},
    ),
    _ConditionPrefix(_KICKED_CONDITION_RE, _kicked_condition, _rewrite_kicker_x),
    _ConditionPrefix(
        _ADDITIONAL_COST_PAID_CONDITION_RE,
        lambda m: {"kind": "flag", "flag": "additional_cost_paid"},
    ),
    _ConditionPrefix(
        _TEAMWORK_PAID_CONDITION_RE,
        lambda m: {"kind": "flag", "flag": "teamwork_paid"},
    ),
    _ConditionPrefix(
        _GIFT_PROMISED_CONDITION_RE,
        lambda m: (
            {"kind": "not", "condition": {"kind": "flag", "flag": "gift_promised"}}
            if m.group("neg").lower() != "was" else {"kind": "flag", "flag": "gift_promised"}
        ),
    ),
    # "If that player is[n't] you, `<effect>`." (The Ghoul, Gunslinger) — the
    # negative polarity is the ``not`` combinator, not a second predicate.
    _ConditionPrefix(
        _TARGET_IS_CONTROLLER_RE,
        lambda m: (
            {"kind": "not", "condition": {"kind": "is_you", "of": "target"}}
            if m.group("neg") else {"kind": "is_you", "of": "target"}
        ),
    ),
    # RULE 701.30d's two complementary clash branches.
    _ConditionPrefix(_IF_YOU_WIN_CLASH_RE, lambda m: {"kind": "clash_won"}),
    # RULE 705: the coin-flip counterpart.
    _ConditionPrefix(_COIN_FLIP_RESULT_RE, _coin_flip_condition),
    # RULE 706: the die-roll counterpart (PAR-147).
    _ConditionPrefix(_DIE_IF_RE, _die_result_condition, parse_rest=_die_that_much_specs),
    _ConditionPrefix(_DIE_ON_A_RE, _die_result_condition, parse_rest=_die_that_much_specs),
    # RULE 119.3, Frodo, Adventurous Hobbit — carries a ``trailing`` group,
    # because "if A, effect1. Then if B, effect2." is two independently
    # gated sentences and the naive greedy read would gate both with A.
    _ConditionPrefix(
        _LIFE_GAINED_THIS_TURN_CONDITION_RE,
        lambda m: {"kind": "gained_life_this_turn", "amount": int(m.group("n"))},
    ),
    # "If you don't control a Food, …" (Butterbur, Bree Innkeeper).
    _ConditionPrefix(
        _CONTROLS_NONE_OF_TYPE_CONDITION_RE,
        lambda m: {
            "kind": "not",
            "condition": {
                "kind": "controls_subtype",
                "subtype": m.group("type").lower(),
                "min": 1,
            },
        },
    ),
    # "If there's a `<subtype>` card in your graveyard, …" (Walltop Sentries)
    # — the same predicate a static's ``active_if`` already used for the
    # standing version of this clause.
    _ConditionPrefix(
        _GRAVEYARD_HAS_SUBTYPE_CONDITION_RE,
        lambda m: {"kind": "subtype_in_graveyard", "subtype": m.group("sub").lower()},
    ),
    # The pre-daybound Innistrad werewolf day/night check — one quantity,
    # two bounds, where the flat vocabulary spelled two unrelated keys.
    _ConditionPrefix(
        _WEREWOLF_NO_SPELLS_CONDITION_RE,
        lambda m: {"kind": "spells_cast_last_turn", "max": 0},
    ),
    _ConditionPrefix(
        _WEREWOLF_TWO_SPELLS_CONDITION_RE,
        lambda m: {"kind": "spells_cast_last_turn", "min": 2},
    ),
    # RULE 603.4's textbook example, and every extra-combat grant's guard
    # against re-triggering itself in the phase it just made.
    _ConditionPrefix(
        _FIRST_COMBAT_PHASE_CONDITION_RE,
        lambda m: {"kind": "combats_this_turn", "max": 1},
    ),
    # RULE 701.52a's two printed Ring-bearer shapes: "a creature **other
    # than** ~" is the negation, and Frodo's compound "~ **is** your
    # Ring-bearer **and** the Ring has tempted you N or more times" is the
    # ``all`` combinator the flat form spelled as a two-key dict.
    _ConditionPrefix(
        _RING_BEARER_OTHER_CONDITION_RE,
        lambda m: {"kind": "not", "condition": {"kind": "is_ring_bearer"}},
    ),
    _ConditionPrefix(
        _RING_BEARER_AND_TEMPTED_CONDITION_RE,
        lambda m: {
            "kind": "all",
            "conditions": [
                {"kind": "is_ring_bearer"},
                {"kind": "ring_tempted", "min": int(m.group("n"))},
            ],
        },
    ),
)

#: Gates peeled **after** the connector split, so each binds to only its own
#: clause — see the call site for why that has to be a separate pass.
#: PAR-62's generic rows, kept in a table of their own because *where* they
#: run is the whole point. The specific `_CONDITION_PREFIXES` rows are peeled
#: **before** `match_clause`, so a base handler can never claim a clause
#: without its gate. These cannot sit there: they match on shape rather than
#: on a printed phrase, so a body like "gain control of target creature …. if
#: that creature is a goat, it also gets +3/+0 …" (Goatnap) would be gated as
#: a whole on a condition outside the vocabulary and fail closed — losing the
#: connector split that used to claim it. Measured: 7 such cards regressed.
#:
#: Run last instead, after `match_clause` *and* the connector cascade, and
#: they are purely additive — the same placement rule the mid-body "you may"
#: node follows.
_GENERIC_CONDITION_ROWS: tuple[_ConditionPrefix, ...] = (
    _ConditionPrefix(_RESOLUTION_COUNT_PREFIX_RE, _resolution_count_condition),
    _ConditionPrefix(_RESOLUTION_COUNT_SUFFIX_RE, _resolution_count_condition),
    _ConditionPrefix(_GENERIC_IF_PREFIX_RE, _generic_condition),
    _ConditionPrefix(_GENERIC_UNLESS_PREFIX_RE, _generic_negated_condition),
    _ConditionPrefix(_GENERIC_IF_SUFFIX_RE, _generic_condition),
    _ConditionPrefix(_GENERIC_UNLESS_SUFFIX_RE, _generic_negated_condition),
)


_CONDITION_SUFFIXES: tuple[_ConditionPrefix, ...] = (
    # "`<effect>` unless `<its>` additional cost was paid." (Katara, Seeking
    # Revenge) — the negative of `_ADDITIONAL_COST_PAID_CONDITION_RE`.
    _ConditionPrefix(
        _ADDITIONAL_COST_NOT_PAID_SUFFIX_RE,
        lambda m: {
            "kind": "not",
            "condition": {"kind": "flag", "flag": "additional_cost_paid"},
        },
    ),
)


#: A condition phrase whose subject is a bare pronoun — "**it** has flying", "**that creature**
#: was attacking", "**its** power is 3 or greater".
_PRONOUN_CONDITION_RE = re.compile(
    rf"^(?:it|its|that {PRONOUN_NOUN_ALT}|you cast it)\b", re.IGNORECASE
)


def _group_pronoun_condition(
    cond_text: str, condition: Optional[dict[str, Any]], *,
    reading: ClauseReading = STANDALONE,
) -> Optional[dict[str, Any]]:
    """PAR-123: a gate whose subject is "it" under a group trigger is a gate on the firing object.

    ``condition`` is what the shared vocabulary made of the phrase (or ``None``); a phrase it does
    not know is tried against the referent grammar (`parse_referent_condition`), and the result is
    scoped to the object that fired the trigger."""
    if (
        condition is None and reading.previous_subject and not reading.self_subject and not reading.group_subject
        and _PRONOUN_CONDITION_RE.match(cond_text) is not None
    ):
        # "destroy target … . If that permanent's mana value was 3 or less, …" (Carnivorous Canopy): the printed
        # mana value reads the same in any zone, so the gate survives the pick having just left the battlefield.
        # Power, toughness and keywords are last-known information (RULE 608.2h) the engine does not keep here.
        referent = parse_referent_condition(cond_text)
        return referent if referent is not None and referent.get("kind") == "mana_value" else None
    if not reading.group_subject or reading.self_subject or reading.previous_subject or _PRONOUN_CONDITION_RE.match(cond_text) is None:
        return condition
    if condition is None:
        condition = parse_referent_condition(cond_text)
    return None if condition is None else _rescope_to_trigger_subject(condition)

#: The condition kinds that talk about one object (the ``of`` referent), rather than the board or a
#: player — the ones "it"/"that creature" can be the subject of.
_SUBJECT_SCOPED_CONDITION_KINDS: frozenset[str] = frozenset({
    "source_tapped", "source_untapped", "source_attacking", "source_blocking", "source_counters",
    "source_attacked_this_turn", "is_card_type", "is_color", "is_subtype", "is_legendary", "is_basic",
    "was_dealt_damage_this_turn", "flag", "power", "toughness", "mana_value", "has_keyword",
    "source_monstrous", "source_equipped", "source_enchanted", "entered_this_turn",
})


def _rescope_to_trigger_subject(condition: dict[str, Any], of: str = "trigger_subject") -> dict[str, Any]:
    """PAR-123: a condition about "it" under a group trigger is about the object that fired it.

    The condition vocabulary reads the ability's own source unless told otherwise (or, for a few
    rows written for a pronoun after a targeting clause, ``previous_target``); under a group
    trigger that would be the Enchantment carrying the ability, not the creature that entered.
    ``trigger_subject`` is the firing object straight off the event, so a gate needs no seed.
    PAR-135: ``of="previous_target"`` is the same rescoping for "it" after a targeting clause
    ("choose target creature. If it's tapped, …" — Shackle Slinger), the pick an earlier clause made."""
    kind = condition.get("kind")
    if kind in ("all", "any"):
        return {**condition, "conditions": [
            _rescope_to_trigger_subject(sub, of) for sub in condition.get("conditions") or []
        ]}
    if kind == "not" and isinstance(condition.get("condition"), dict):
        return {**condition, "condition": _rescope_to_trigger_subject(condition["condition"], of)}
    if kind in _SUBJECT_SCOPED_CONDITION_KINDS and condition.get("of") in (None, "source", "previous_target"):
        return {**condition, "of": of}
    return condition


#: The pronoun-row condition kinds that have a source-scoped reading and a last-known (snapshot) one.
_SELF_PRONOUN_CHARACTERISTIC_KEYS: dict[str, str] = {
    "is_card_type": "card_type", "is_subtype": "subtype", "is_color": "color",
}


def _rescope_self_pronoun_condition(condition: dict[str, Any], *, past: bool) -> Optional[dict[str, Any]]:
    """A pronoun gate ("if it was a Demon") under a *self-subject* trigger → a condition that can hold.

    The shared rows build ``of: previous_target`` — right after a targeting clause, but a self trigger has no
    pick, so the gate never held and the card silently never acted (Weatherseed Totem, Infernal Vessel). Present
    tense ("if it's a creature") is the source itself; past tense ("if it was/wasn't …") asks what the source
    *was* — the death/leave event's last-known snapshot (`effect_conditions` ``trigger_event_object``, RULE
    603.10a). ``None`` (fail closed) for any other kind still naming ``previous_target``."""
    kind = condition.get("kind")
    if kind in ("all", "any"):
        subs = [_rescope_self_pronoun_condition(sub, past=past) for sub in condition.get("conditions") or []]
        return None if any(sub is None for sub in subs) else {**condition, "conditions": subs}
    if kind == "not" and isinstance(condition.get("condition"), dict):
        inner = _rescope_self_pronoun_condition(condition["condition"], past=past)
        return None if inner is None else {**condition, "condition": inner}
    if condition.get("of") != "previous_target":
        return condition
    key = _SELF_PRONOUN_CHARACTERISTIC_KEYS.get(str(kind))
    if key is None or key not in condition:
        return None
    if past:
        return {"kind": "trigger_event_object", key: condition[key]}
    return {k: v for k, v in condition.items() if k != "of"}


def _peel_condition(
    body: str,
    table: tuple[_ConditionPrefix, ...],
    *,
    reading: ClauseReading = STANDALONE,
) -> tuple[bool, Optional[list[EffectSpec]]]:
    """The one rule behind every row of ``table``.

    Returns ``(matched, specs)``. ``matched`` says a row claimed the body at
    all; ``specs`` is ``None`` when it did but the gated effect text came
    back unclaimed — which fails the whole body, because emitting the effect
    without its gate would be a *wrong* card rather than an unmodeled one.
    """
    for row in table:
        match = row.pattern.match(body)
        if match is None:
            continue
        inner = None
        if row.parse_rest is not None:
            inner = row.parse_rest(
                match.group("rest"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
            )
        if inner is None:
            inner = parse_effect_body(
                match.group("rest"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
            )
        if inner is None:
            return True, None
        condition = row.build(match)
        condition = _group_pronoun_condition(
            match.groupdict().get("cond") or "", condition, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if (
            condition is not None and reading.previous_subject and not reading.self_subject and not reading.group_subject
            and _PRONOUN_CONDITION_RE.match(match.groupdict().get("cond") or "") is not None
        ):
            # PAR-135: "it"/"that creature" after a clause that chose a target is that pick. The shared rows
            # read the ability's source unless they name a pick themselves, so "tap target creature. If it's
            # tapped, …" gated on the *source* being tapped — the wrong object, silently.
            condition = _rescope_to_trigger_subject(condition, "previous_target")
        if condition is not None and reading.self_subject and not reading.previous_subject and not reading.group_subject:
            # PAR-142: "when ~ dies, if it was a creature / wasn't a Demon, …" — "it" is the source, but these
            # pronoun rows read ``previous_target`` (a pick an earlier clause made), which no clause made here.
            condition = _rescope_self_pronoun_condition(
                condition, past=re.search(r"\b(?:was|wasn'?t|were|weren'?t)\b", match.groupdict().get("cond") or "") is not None,
            )
        if condition is None:
            # A row whose ``build`` couldn't resolve its condition phrase (the
            # generic rows below hand the phrase to the shared vocabulary, and
            # it isn't total). Claiming the body here would emit the effect
            # with no gate at all, which is the one outcome worse than leaving
            # the card unmodeled.
            return True, None
        gated: list[EffectSpec] = []
        for spec in inner:
            params = dict(spec.params)
            if (
                spec.type == "return_self_to_battlefield" and "target_kind" not in params
                and reading.previous_subject and not reading.self_subject and not reading.group_subject
            ):
                params["target_kind"] = "previous_target"  # "return it" after a clause that chose the pick
            if row.rewrite_params is not None:
                row.rewrite_params(params, match)
            gated.append(EffectSpec(spec.type, params, condition=condition))
        trailing = (match.groupdict().get("trailing") or "").strip().lstrip(". ").strip()
        if not trailing:
            return True, gated
        # A second sentence this match swallowed, with a gate of its own —
        # re-fold it through `parse_effect_body` so it gets that gate rather
        # than silently inheriting this one.
        more = parse_effect_body(
            trailing, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        return True, (gated + more if more is not None else None)
    return False, None


def _with_after_tail(
    specs: list[EffectSpec], after_group: Optional[str], *,
    reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """The repeated tail shape across `parse_effect_body`'s two-sentence
    wrapper blocks below (look_top_select/no_regen/gain_control_tail/
    sac_when_you_do): a trailing "after" sentence, if any, recurses back
    into `parse_effect_body` and its specs are appended; with none, ``specs``
    is returned as-is. Fails closed (``None``) if the "after" sentence itself
    doesn't parse. ``group_subject`` carries forward unchanged (MEC-28) —
    unlike ``previous_subject``, the trigger's own group-subject scope
    doesn't shift between an ability's clauses."""
    after_text = (after_group or "").strip()
    if not after_text:
        return specs
    after_specs = parse_effect_body(
        after_text, reading=ClauseReading(referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if after_specs is None:
        return None
    if specs and _OTHER_TARGET_PART_RE.search(after_text):
        after_specs, _ = _stamp_distinct_from_others(after_specs)  # ENG-52, as in the clause loop
    return specs + after_specs


#: MEC-118, RULE 115.1 / 601.2c: "target `<X>` **of an opponent's choice**" [+ "they control"].  The phrase only moves
#: *who picks* the target, so it is lifted out of the clause (the rest reads like the ordinary clause an existing row
#: already claims) and re-attached as ``target_chooser`` params on the specs that clause produced.
_OPPONENT_CHOICE_RE = re.compile(r" of an opponent's choice(?P<they> they control)?")
#: "target creature **of your choice**, then destroy target creature of an opponent's choice" (Diaochan): redundant
#: wording of the controller's own pick, dropped only next to an opponent's-choice phrase.
_OF_YOUR_CHOICE_RE = re.compile(r" of your choice(?=[,. ]|$)")
_TARGET_WORD_RE = re.compile(r"\btarget\b")
#: Effect types that announce exactly one target per spec (the chooser phrase is matched to a spec by order of the
#: "target" words, so a type that may announce several -- or none -- would mis-assign it; anything else fails closed).
_ONE_TARGET_EFFECT_TYPES = frozenset({"damage", "destroy", "gain_control_until_eot", "return_from_graveyard"})
#: The wording that replaces "they control" once the chooser phrase is lifted out (the opponent-controlled pool).
_OPPONENT_CONTROLS_TAIL = " an opponent controls"


def _lift_opponent_choice(body: str) -> Optional[tuple[str, list[tuple[int, bool]]]]:
    """``body`` without its "of an opponent's choice" phrases, plus ``(target ordinal, they-control)`` for each.

    ``None`` when ``body`` has no such phrase.  The ordinal counts the "target" words before the phrase (0-based)."""
    if not _OPPONENT_CHOICE_RE.search(body):
        return None
    body = _OF_YOUR_CHOICE_RE.sub("", body)
    lifted: list[tuple[int, bool]] = []
    out: list[str] = []
    cursor = 0
    for match in _OPPONENT_CHOICE_RE.finditer(body):
        out.append(body[cursor:match.start()])
        ordinal = len(_TARGET_WORD_RE.findall("".join(out))) - 1
        if ordinal < 0:
            return None
        lifted.append((ordinal, match.group("they") is not None))
        out.append(_OPPONENT_CONTROLS_TAIL if match.group("they") else "")
        cursor = match.end()
    out.append(body[cursor:])
    return "".join(out), lifted


def parse_effect_body(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """`_parse_effect_body_unstamped`, then PAR-175's created-pronoun pass over the finished spec list (so a row that
    emits a whole multi-sentence sequence is covered exactly like the sentence-by-sentence loop)."""
    specs = _parse_effect_body_unstamped(body, reading=reading)
    return _stamp_created_pronouns(specs) if specs else specs


def _parse_effect_body_unstamped(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """`_parse_effect_body_inner`, plus MEC-118's "target `<X>` of an opponent's choice": the phrase is lifted out,
    the plain clause parsed, and ``target_chooser`` stamped on the spec whose target it described (fail closed when
    the targets cannot be matched to specs one to one)."""
    designation = re.fullmatch(r"it becomes (?P<designation>day|night)\.?", body.strip())
    if designation is not None:
        return [EffectSpec("set_day_night", {"designation": designation.group("designation")})]
    flicker_sequence = flicker_sequence_specs(body, reading=ClauseReading(self_subject=reading.self_subject)) or linked_pool_return_specs(body) or source_return_specs(body)
    if flicker_sequence is not None:
        return flicker_sequence
    exile_grant = exile_grant_specs(body)
    if exile_grant is not None:
        return exile_grant
    physical_fight = physical_fight_specs(body)
    if physical_fight is not None:
        return physical_fight
    target_group = target_group_specs(body, lambda text: parse_effect_body(
        text, reading=reading.unattached(),
    ))
    if target_group is not None:
        return target_group
    # (PAR-175 M4b: the body-level `fight_sequence_specs` / `source_counter_fight_specs` call was retired -- the clause-level
    # call in `catalogue/handlers.match_clause` claims every one of those bodies, with the identical specs, for the whole
    # cache.)
    if reading.attached_subject:
        # RULE 400.7e: keep a dying host's conditional return riders atomic
        # before sentence/connector splitting can lose their shared referent.
        host_return = dying_host_return_specs(body)
        if host_return is not None:
            return host_return
    as_printed = _parse_effect_body_inner(
        body, reading=reading,
    )
    lifted = _lift_opponent_choice(body)
    if as_printed is not None or lifted is None:
        # Resolve-time "of an opponent's choice" wordings ("a nonland card of an opponent's choice", Tasigur) are
        # claimed by their own rows and keep their meaning; only a body nothing else claims is lifted.
        return _fold_placement_tails(as_printed)
    plain, choosers = lifted
    specs = _parse_effect_body_inner(
        plain, reading=reading,
    )
    if specs is None:
        return None
    mentions = len(_TARGET_WORD_RE.findall(plain))
    # One entry per announced target, in printed order: (carrier spec, that target's slot within the spec).
    slots: list[tuple[EffectSpec, int]] = []
    for spec in specs:
        if spec.type in _ONE_TARGET_EFFECT_TYPES:
            if spec.params.get("count", 1) != 1:
                return None
            slots.append((spec, 0))
        elif spec.type == "fight" and spec.params.get("fighter_kind") and spec.params.get("other_kind"):
            slots.extend([(spec, 0), (spec, 1)])
    if len(slots) != mentions:
        return None
    stamped = list(specs)
    for ordinal, controls in choosers:
        carrier, slot = slots[ordinal]
        index = next(i for i, spec in enumerate(stamped) if spec is carrier)
        params = dict(stamped[index].params)
        params["target_chooser"] = TARGET_CHOOSER_OPPONENT
        if slot or carrier.type == "fight":
            params["target_chooser_slots"] = sorted({*params.get("target_chooser_slots", []), slot})
        if controls:
            params["target_chooser_controls"] = True
        stamped[index] = replace(stamped[index], params=params)
    return _fold_placement_tails(stamped)


#: PAR-152: a placement that waits on its controller's pick ("you may put a creature card from your hand onto the
#: battlefield tapped and attacking") parks the rest of the body until the pick is answered, so a following
#: "it"/"that creature" clause would resolve with no referent (and a delayed trigger would capture the source).
#: These specs about the placed card are carried *inside* the placement instead, as `placed_effects`, run once a
#: card was placed with that card as their referent. `{type: [params that make the spec a placed-card rider]}`.
_PLACED_CARD_RIDERS: dict[str, tuple[tuple[str, tuple[object, ...]], ...]] = {
    "pump": (("previous_subject", (True,)),),
    "add_counters": (("previous_subject", (True,)),),
    "grant_until": (("previous_subject", (True,)),),
    # ``self``: "if you do, convert ~ at end of combat" (Ultra Magnus) only happens when a card was placed.
    "create_delayed_trigger": (("capture", ("previous_or_self", "self")),),
}


def _fold_rider_dicts(effects: list[dict]) -> list[dict]:
    """`_fold_placement_tails` over serialized ``{"type", "params"}`` effects (an ``optional`` wrapper's body)."""
    folded: list[dict] = []
    index = 0
    while index < len(effects):
        effect = effects[index]
        riders: list[dict] = []
        if effect.get("type") in PLACEMENT_WITH_RIDERS:
            for later in effects[index + 1:]:
                needs = _PLACED_CARD_RIDERS.get(later.get("type"))
                params = later.get("params") or {}
                if needs is None or not all(params.get(key) in values for key, values in needs):
                    break
                riders.append(later)
        if riders:
            params = dict(effect.get("params") or {})
            params["placed_effects"] = [*params.get("placed_effects", []), *riders]
            folded.append({**effect, "params": params})
            index += 1 + len(riders)
        else:
            folded.append(effect)
            index += 1
    return folded


def _fold_placement_tails(specs: Optional[list[EffectSpec]]) -> Optional[list[EffectSpec]]:
    if not specs:
        return specs
    as_dicts = [spec.to_dict() for spec in specs]
    # "You may put …. If you do, convert ~ at end of combat." is one ``optional`` whose body carries both.
    folded_dicts = []
    for d in _fold_rider_dicts(as_dicts):
        if d["type"] == "optional" and isinstance(d["params"].get("effects"), list):
            inner = _fold_rider_dicts(d["params"]["effects"])
            # The pick is itself optional (the player may place nothing), so a lone placement needs no second
            # "do you want to?" wrapper; "if you do" is carried by its ``placed_effects``.
            d = inner[0] if len(inner) == 1 and inner[0]["type"] in PLACEMENT_WITH_RIDERS else {
                **d, "params": {**d["params"], "effects": inner},
            }
        folded_dicts.append(d)
    if folded_dicts == as_dicts:
        return specs
    return [EffectSpec.from_dict(d) for d in folded_dicts]


def _parse_effect_body_inner(
    body: str, *, reading: ClauseReading = STANDALONE,
) -> Optional[list[EffectSpec]]:
    """A normalised effect ``body`` → its `EffectSpec`s, or ``None`` if unclaimed.

    Tries the whole body as one clause first (so a target phrase containing
    "or"/"and" isn't split), then falls back to splitting on effect connectors
    and parsing each part. Any unclaimed part fails the whole body (fail-closed:
    a partially-modeled ability is never emitted).

    ``self_subject`` says a bare "it" in ``body`` means the ability's own
    source — true of a trigger whose *subject* is the source ("when ~ enters,
    it fights …"), which is what unlocks `effect_rows.shared.EffectHandler.
    self_subject_only` rows. It is deliberately **not** passed down into the
    connector-split parse below: once a body chains clauses, an earlier one
    may have introduced a new referent ("put a +1/+1 counter on target
    creature you control, then it fights …") — that reading is
    ``previous_subject``'s job instead, handed to each split part whose
    predecessor actually chose a creature (`announces_creature_target`), and
    unlocking `effect_rows.shared.EffectHandler.previous_subject_only` rows. The two
    flags are therefore never both set: a pronoun means the source or the
    last pick, never either-or.

    ``group_subject`` (MEC-28) says "it"/"that creature" means whichever
    object matched this ability's own RULE 603.1 group-subject trigger
    condition ("whenever a creature you control attacks alone, … untap
    **that creature**.") — unlocking `effect_rows.shared.EffectHandler.
    group_subject_only` rows. Unlike ``self_subject``, it *is* carried into
    every recursive call, including the connector-split parse below: the
    trigger's own subject scope is a fact about the whole ability, not a
    local referent that shifts clause to clause, so there's no equivalent
    of ``previous_subject`` recomputing it.

    A mass *selector* clause ("untap all attacking creatures") introduces a
    different kind of referent — "they" in a following clause ("**They**
    gain first strike until end of turn.", unlocking `handlers.
    EffectHandler.previous_selector_only` rows) — tracked by the
    connector-split loop below the same way ``previous_subject`` is
    (`_announces_group_selector`, resolved at runtime off `effects.
    GameContext.previous_selector` rather than a specific object list).

    ``attached_subject`` (PAR-117) says "its" means RULE 303.4/301.5's
    attached host — this ability's own trigger condition is ``{"subject":
    "attached_permanent"}`` ("whenever enchanted creature attacks or
    blocks, its controller loses N life."), unlocking `handlers.
    EffectHandler.attached_subject_only` rows. Like ``self_subject``, and for
    the same reason, it is **not** carried into the connector-split parse
    below: every cached card printing this shape is a single clause, so
    there is nothing yet to say what the pronoun should mean two clauses
    into a split body — left narrow rather than guessed.
    """
    body = body.strip().rstrip(".").strip()
    if not body:
        return []
    # Preserve the existing hand-cheat package before placement-tail folding.
    # Its choice already owns haste and the delayed sacrifice (MEC-73).
    if "that creature gains haste until end of turn" in body:
        packaged = match_clause(body, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET)), )
        if packaged and len(packaged) == 1 and packaged[0].type == "cheat_creature_from_hand":
            return packaged
    # "you may **have** target creature get -2/-2 until end of turn" (Blightcaster, Battle-Rattle Shaman, the
    # cycling trio, Painsmith, …): "have … get" is only how the optional wording carries the verb — the effect is
    # "target creature gets -2/-2", which every pump / keyword-grant row already reads.
    body = _MAY_HAVE_TARGET_GET_RE.sub(r"\g<1>\g<2> \g<3>s ", body)

    # "destroy target nonbasic land you don't control and target nonbasic land you don't control." (Volcanic Offering):
    # one verb over two target phrases is two destroy instructions, in printed order (RULE 115.1).  One sentence only:
    # a rider after it ("They can't be regenerated.", Plague Spores) would attach to just the second instruction.
    destroy_pair = re.fullmatch(r"destroy (?P<a>target [^.]+?) and (?P<b>target [^.]+)", body, re.IGNORECASE)
    if destroy_pair is not None:
        first = parse_effect_body(f"destroy {destroy_pair.group('a')}")
        second = parse_effect_body(f"destroy {destroy_pair.group('b')}")
        if first and second and len(first) == len(second) == 1:
            return first + second
        return None

    # PAR-130: a per-player target announcement followed by the clause(s)
    # acting on "that/those/the chosen" objects. The generic connector split
    # cannot discover the first half because the per-player wrapper used to
    # expect the whole body to be one effect; split this printed boundary,
    # retain the announced targets as the following clause's referent, and
    # fail closed unless both halves independently parse.
    per_player_choose = re.fullmatch(
        r"(?P<choose>for each (?:opponent|player), choose (?:up to 1 )?"
        r"(?:another |other )?target .+? that player controls)"
        r"(?:\.|,\s*then)\s*(?P<after>.+)",
        body, re.IGNORECASE | re.DOTALL,
    )
    if per_player_choose is not None:
        before_specs = parse_effect_body(per_player_choose.group("choose"))
        if not before_specs or not all(spec.type == "choose_targets" for spec in before_specs):
            return None
        after_specs = parse_effect_body(
            per_player_choose.group("after"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if after_specs is None:
            return None
        return before_specs + after_specs

    # "…, whenever `<event>` this turn, `<effect>`" as one sentence of a larger body — after an
    # "if C," gate or a first sentence — creates the same turn-long trigger a whole line does.
    if _TURN_TRIGGER_RE.match(body):
        turn_trigger = _turn_trigger_segment(
            body, provenance=ParserProvenance(), reading=ClauseReading(referents=reading.referents_of(TARGET)),
        )
        if turn_trigger is not None and turn_trigger.claimed and turn_trigger.spec is not None:
            return list(turn_trigger.spec.effects)

    return_then = re.fullmatch(r"(?P<before>return .+?)\. if you do, (?P<after>.+)", body, re.I | re.S)
    if return_then is not None:
        before_specs = parse_effect_body(return_then.group("before"), reading=ClauseReading(self_subject=reading.self_subject))
        after_specs = parse_effect_body(return_then.group("after"), reading=ClauseReading(self_subject=reading.self_subject))
        if (before_specs is None or after_specs is None or len(before_specs) != 1
                or before_specs[0].type != "return_to_hand"):
            return None
        params = dict(before_specs[0].params)
        params["then_specs"] = [spec.to_dict() for spec in after_specs]
        return [EffectSpec("return_to_hand", params)]

    # An activated ability's sacrifice cost is paid before its effects resolve
    # (RULE 602.2b).  Keep both mutually-exclusive draw counts explicit: the
    # card does not draw one and then a further two when the sacrificed
    # creature was suspected.
    if re.fullmatch(
        r"draw a card\. if the sacrificed creature was suspected, draw 2 cards instead",
        body,
        re.IGNORECASE,
    ):
        return [
            EffectSpec("draw", {"count": 1}, condition={"sacrificed_cost_was_suspected": False}),
            EffectSpec("draw", {"count": 2}, condition={"sacrificed_cost_was_suspected": True}),
        ]

    # Lamplight Phoenix — the whole optional reflexive sequence is one
    # atomic action.  It cannot be split at "and"/"if you do": exile and
    # collect evidence must both happen before the card returns.
    lamplight = re.fullmatch(
        r"exile (?:it|~) and collect evidence (?P<n>\d+)\. if you do, "
        r"return this card to the battlefield(?P<tapped> tapped)?",
        body,
        re.IGNORECASE,
    )
    if lamplight is not None:
        return [EffectSpec("exile_self_collect_evidence_return", {
            "amount": int(lamplight.group("n")), "tapped": bool(lamplight.group("tapped")),
        })]

    # Primetime Suspect — both branches are the same optional library search,
    # but the Aura host's suspected state changes its cardinality.  This is
    # deliberately kept to the complete printed search sentence; a general
    # "instead" rewrite would be unsafe around asynchronous searches.
    if re.fullmatch(
        r"search your library for a land card, put that card onto the battlefield tapped, "
        r"then shuffle\. if enchanted creature is suspected, you search for 2 lands instead",
        body,
        re.IGNORECASE,
    ):
        return [
            EffectSpec(
                "search", {"criteria": {"type": "land"}, "destination": "battlefield_tapped"},
                condition={"attached_is_suspected": False},
            ),
            EffectSpec(
                "search", {"criteria": {"type": "land"}, "destination": "battlefield_tapped", "count": 2},
                condition={"attached_is_suspected": True},
            ),
        ]

    # RULE 603.4 intervening-ifs, and RULE 601.2b's optional-additional-cost
    # gates: one rule over `_CONDITION_PREFIXES` (ENG-36), where each of these
    # was its own ten-line block. They run before `match_clause` / the
    # connector split so a base `<effect>` handler can never claim the clause
    # *without* its gate — a wrong-but-modeled unconditional card is worse
    # than an unclaimed one.
    matched, peeled = _peel_condition(
        body, _CONDITION_PREFIXES, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if matched:
        return peeled

    clash_repeat = _CLASH_REPEAT_PROCESS_RE.match(body)
    if clash_repeat is not None:
        process = parse_effect_body(clash_repeat.group("process"), reading=ClauseReading(self_subject=reading.self_subject))
        if process is None:
            return None
        inner = [e.to_dict() for e in process] + [{"type": "clash", "params": {}}]
        return [EffectSpec("repeat_process", {"effects": inner, "repeat_while": "clash_won"})]

    clash_bounce_lib = _CLASH_BOUNCE_OR_LIBRARY_RE.match(body)
    if clash_bounce_lib is not None:
        return [
            EffectSpec("clash", {}),
            EffectSpec("return_to_hand", {
                "target_kind": "creature", "to_library_top_if_clash_won": True,
            }),
        ]

    if _CHOOSE_TARGET_IF_SUSPECTED_RE.match(body) is not None:
        # PAR-30 (Agrus Kos, Spirit of Justice) — RULE 701.60c if/else over
        # the chosen creature's suspected state. The exile branch carries the
        # RULE 115 target; the "otherwise" branch reads it back as the
        # previous subject (`effects.ConditionalEffect._condition_holds`'s
        # ``previous_target_is_suspected`` key). Exile leaves ``is_suspected``
        # set on the old object reference (RULE 400.7), so the complementary
        # branch still evaluates `True` and stays skipped.
        return [
            EffectSpec(
                "exile", {"target_kind": "creature", "count": 1, "optional": True},
                condition={"previous_target_is_suspected": True},
            ),
            EffectSpec(
                "suspect", {"previous_subject": True},
                condition={"previous_target_is_suspected": False},
            ),
        ]

    look_top_select = _LOOK_TOP_SELECT_RE.match(body)
    if look_top_select is not None:
        if look_top_select.group("removed") and look_top_select.group("n") != "x":
            return None
        rest_destination, rest_order = _LOOK_TOP_SELECT_DESTINATIONS[
            look_top_select.group("dest").lower()
        ]
        spec = EffectSpec(
            "look_top_select",
            {
                "count": ({"kind": "counters_removed_as_cost", "of": "source", "counter": look_top_select.group("removed")}
                          if look_top_select.group("removed") else
                          "x" if look_top_select.group("n") == "x" else int(look_top_select.group("n"))),
                "select_count": int(look_top_select.group("m")),
                "rest_destination": rest_destination,
                "rest_order": rest_order,
            },
        )
        return _with_after_tail([spec], look_top_select.group("after"), reading=ClauseReading(group_subject=reading.group_subject))

    look_put_atk = _LOOK_TOP_PUT_ATTACKING_RE.match(body)
    if look_put_atk is not None:
        words = look_put_atk.group("filter").split()
        criteria: Optional[dict] = None
        if words == ["creature"]:
            criteria = {"type": "creature"}
        elif len(words) == 2 and words[1] == "creature":
            # "human creature card" / "cat creature card" — a creature
            # subtype filter (a substring match on the type line).
            criteria = {"type": words[0]}
        if criteria is not None:
            params: dict[str, Any] = {
                "count": int(look_put_atk.group("n")),
                "criteria": criteria,
                "hit_destination": "battlefield_attacking",
                "miss_destination": "library_bottom_random",
                "optional": True,
            }
            hitkw_raw = (look_put_atk.group("hitkw") or "").strip()
            if hitkw_raw:
                slugs: list[str] = []
                for tok in re.split(r",|\band\b", hitkw_raw):
                    tok = tok.strip()
                    if not tok:
                        continue
                    if tok not in _LOOK_TOP_HIT_GRANT_KEYWORDS:
                        return None  # unknown keyword — fail closed
                    slugs.append(_LOOK_TOP_HIT_GRANT_KEYWORDS[tok])
                if not slugs:
                    return None
                params["hit_grant_keywords"] = slugs
            elsebody = (look_put_atk.group("elsebody") or "").strip()
            if elsebody:
                else_specs = parse_effect_body(elsebody)
                if else_specs is None:
                    return None  # else-branch didn't parse — fail closed
                params["miss_effect_specs"] = [s.to_dict() for s in else_specs]
            spec = EffectSpec("impulsive_look", params)
            return _with_after_tail(
                [spec], look_put_atk.group("after"), reading=ClauseReading(group_subject=reading.group_subject)
            )

    enters_atk = _CREATED_ENTERS_ATTACKING_RE.match(body)
    if enters_atk is not None:
        before_specs = parse_effect_body(
            enters_atk.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        name_subj = (enters_atk.group("name_subj") or "").strip().lower()
        # ``create_named_legendary_token`` emits a plain ``create_token``
        # spec (with ``token_name``/``legendary``), so it's covered here too.
        _STAMPABLE = ("create_token", "copy_permanent", "populate")
        if before_specs is not None:
            for i in range(len(before_specs) - 1, -1, -1):
                if before_specs[i].type not in _STAMPABLE:
                    continue
                # A bare-name subject only binds the spec that actually made
                # a token by that name (RULE 700 — no other referent). A
                # pronoun subject binds the last token-maker, as before.
                if name_subj:
                    tok_name = str(before_specs[i].params.get("token_name") or "").lower()
                    if tok_name != name_subj:
                        continue
                flagged = dict(before_specs[i].params)
                flagged["tapped"] = True
                flagged["attacking"] = True
                before_specs[i] = EffectSpec(
                    before_specs[i].type, flagged, condition=before_specs[i].condition
                )
                return _with_after_tail(
                    before_specs, enters_atk.group("after"), reading=ClauseReading(group_subject=reading.group_subject)
                )
        # regex matched but nothing stampable — fall through, fail closed

    spend_mana = _SPEND_MANA_SENTENCE_RE.match(body)
    if spend_mana is not None:
        restriction = _spend_mana_restriction(spend_mana.group("what"))
        before_specs = parse_effect_body(
            spend_mana.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        ) if restriction is not None else None
        if before_specs is None or not any(spec.type == "add_mana" for spec in before_specs):
            return None
        before_specs = [
            EffectSpec(spec.type, {**spec.params, "restriction": dict(restriction)}, condition=spec.condition)
            if spec.type == "add_mana" else spec
            for spec in before_specs
        ]
        return _with_after_tail(
            before_specs, spend_mana.group("after"), reading=ClauseReading(referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )

    keep_mana = _KEEP_MANA_SENTENCE_RE.match(body)
    if keep_mana is not None:
        before_specs = parse_effect_body(
            keep_mana.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(spec.type == "add_mana" for spec in before_specs):
            return None
        keep = _KEEP_MANA_UNTIL[keep_mana.group("until").lower()]
        before_specs = [
            EffectSpec(spec.type, {**spec.params, "keep_until": keep}, condition=spec.condition)
            if spec.type == "add_mana" else spec
            for spec in before_specs
        ]
        return _with_after_tail(
            before_specs, keep_mana.group("after"), reading=ClauseReading(referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )

    no_regen = _NO_REGEN_SENTENCE_RE.match(body)
    if no_regen is not None:
        before_specs = parse_effect_body(
            no_regen.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        plural_regen = bool(re.search(r"\.\s*they can'?t be regenerated", body, re.IGNORECASE))
        plural_flagged = False
        for i in range(len(before_specs) - 1, -1, -1):
            if before_specs[i].type == "destroy":
                flagged = dict(before_specs[i].params)
                flagged["can_be_regenerated"] = False
                before_specs[i] = EffectSpec(
                    before_specs[i].type, flagged, condition=before_specs[i].condition
                )
                if plural_regen:
                    plural_flagged = True
                    continue  # "They can't be regenerated." covers every creature the sentence before destroyed
                break
            wrapped = before_specs[i].params.get("effects") if (
                before_specs[i].type == "trigger_subject_referent") else None
            if wrapped and wrapped[-1].get("type") == "destroy":
                # "destroy it. It can't be regenerated." under a group trigger: the destroy sits in
                # the firing-object wrapper's body.
                nested = dict(wrapped[-1])
                nested["params"] = {**(nested.get("params") or {}), "can_be_regenerated": False}
                before_specs[i] = EffectSpec(
                    before_specs[i].type, {**before_specs[i].params, "effects": [*wrapped[:-1], nested]},
                    condition=before_specs[i].condition,
                )
                break
        else:
            if not plural_flagged:
                return None  # nothing to deny regeneration to — fail closed
        return _with_after_tail(
            before_specs, no_regen.group("after"),
            reading=ClauseReading(previous_subject=announces_creature_target(before_specs), group_subject=reading.group_subject),
        )

    regen_exile = _REGEN_EXILE_RIDER_RE.match(body.strip())
    if regen_exile is not None:
        before_specs = parse_effect_body(
            regen_exile.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if not before_specs or not any(spec.type == "damage" for spec in before_specs):
            return None
        creature_gate = regen_exile.group("gate").lower().startswith("it")
        gate = None if creature_gate else static_condition(regen_exile.group("gate"))
        if not creature_gate and gate is None:
            return None
        riders = [
            EffectSpec("cant_be_regenerated", {"damaged_this_way": True}, condition=gate),
            EffectSpec("grant_die_to_exile_this_turn", {
                "damaged_this_way": True, "creature_only": True,
            }, condition=gate),
        ]
        return before_specs + riders
    die_to_exile = _DIE_TO_EXILE_SENTENCE_RE.match(body)
    if die_to_exile is not None:
        before_specs = parse_effect_body(
            die_to_exile.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        # MEC-81: a "before" clause that *dealt damage* — single target, "any
        # target", or mass ("to each creature") — arms the rider on the
        # actual hit set (`GameContext.damaged_this_way`), the referent that
        # covers the mass/multi-hit case `previous_subject` could not name.
        # Otherwise the rider only qualifies a creature/permanent the "before"
        # clause already *targeted* (Bleed Dry's "-13/-13", the fight forms) —
        # `previous_subject` off `previous_targets`; anything else fails closed.
        if any(s.type == "damage" for s in before_specs):
            rider = EffectSpec("grant_die_to_exile_this_turn", {"damaged_this_way": True})
        elif announces_creature_target(before_specs):
            rider = EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})
        else:
            return None
        return _with_after_tail(
            before_specs + [rider],
            die_to_exile.group("after"),
            reading=ClauseReading(previous_subject=announces_creature_target(before_specs), group_subject=reading.group_subject),
        )

    kicked_mag = _KICKED_MAGNITUDE_OVERRIDE_RE.match(body)
    if kicked_mag is not None:
        before_specs = parse_effect_body(
            kicked_mag.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        bargained = kicked_mag.group("cost").lower() == "bargained"
        key_p = "power_if_bargained" if bargained else "power_if_kicked"
        key_t = "toughness_if_bargained" if bargained else "toughness_if_kicked"
        p2, t2 = int(kicked_mag.group("p")), int(kicked_mag.group("t"))
        for i in range(len(before_specs) - 1, -1, -1):
            spec = before_specs[i]
            if spec.type == "pump" and ("power" in spec.params or "toughness" in spec.params):
                flagged = dict(spec.params)
                flagged[key_p] = p2
                flagged[key_t] = t2
                before_specs[i] = EffectSpec("pump", flagged, condition=spec.condition)
                return before_specs
        return None  # no pump magnitude to override — fail closed

    gain_control_tail = _GAIN_CONTROL_HASTE_TAIL_RE.match(body)
    if gain_control_tail is not None:
        before_specs = parse_effect_body(
            gain_control_tail.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(
            spec.type == "gain_control_until_eot" for spec in before_specs
        ):
            return None  # fail closed — the tail only makes sense after that clause
        prev = announces_creature_target(before_specs)
        grant_text = (gain_control_tail.group("grant") or "").strip()
        grant_specs: list[EffectSpec] = []
        if grant_text and not _GAIN_CONTROL_BARE_HASTE_RE.match(grant_text):
            # A *richer* restatement than bare haste ("it gains trample and
            # haste until end of turn") — model the extra grant against the
            # just-controlled creature (`previous_subject`), fail closed if
            # it isn't something we can represent.
            grant_specs = parse_effect_body(grant_text, reading=ClauseReading(previous_subject=prev)) or []
            if not grant_specs:
                return None
        return _with_after_tail(
            before_specs + grant_specs, gain_control_tail.group("after"),
            reading=ClauseReading(previous_subject=prev, group_subject=reading.group_subject),
        )

    for certain_re, antecedent_type in _CERTAIN_ANTECEDENT_ROWS:
        certain = certain_re.match(body)
        if certain is None:
            continue
        before_specs = parse_effect_body(
            certain.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(spec.type == antecedent_type for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return _with_after_tail(before_specs, certain.group("after"), reading=ClauseReading(group_subject=reading.group_subject))

    exile_self_delayed_return = _EXILE_SELF_THEN_DELAYED_RETURN_RE.match(body)
    if exile_self_delayed_return is not None:
        before_specs = parse_effect_body(
            exile_self_delayed_return.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None or not any(spec.type == "exile" for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return [
            EffectSpec("exile", {**before_specs[0].params, "remember": True}),
            EffectSpec("create_delayed_trigger", {
                "step": "end", "scope": "any",
                "effects": [{"type": "return_linked_exile", "params": {"destination": "battlefield"}}],
            }),
        ]

    action_then = _ACTION_THEN_WHEN_YOU_DO_RE.match(body)
    if action_then is not None:
        before_text = action_then.group("before")
        if before_text.startswith("exile ") and not re.search(r"\btarget\b", before_text):
            return None  # nontargeted exile choices must be made during resolution
        before_specs = parse_effect_body(
            before_text, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        after_text = action_then.group("after")
        condition = None
        if after_text.lower().startswith("if "):
            gate = _GENERIC_IF_PREFIX_RE.match(after_text)
            condition = static_condition(gate.group("cond")) if gate else None
            if condition is None:
                return None
            after_text = gate.group("rest")
        after_specs = parse_effect_body(after_text)
        if not before_specs or len(before_specs) != 1 or before_specs[0].type not in {"exile", "create_token"} or not after_specs:
            return None
        params = dict(before_specs[0].params)
        # One action; multi-event/mass antecedents need
        # explicit batching semantics before exposing a reflexive body.
        if (params.get("count", 1) != 1 or params.get("count_selector")
                or params.get("selector") or params.get("group") or params.get("spell_or_permanent")
                or params.get("per_opponent") or params.get("creators", "you") not in {"you", "target"}):
            return None
        params["then_trigger"] = [spec.to_dict() for spec in after_specs]
        if condition is not None:
            params["then_trigger_condition"] = condition
        return [EffectSpec(before_specs[0].type, params)]

    may_exile_self_then = _MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE.match(body)
    if may_exile_self_then is not None:
        if not reading.self_subject:
            return None  # "it" is the source only when the body's subject is ~ (a dies trigger)
        after_specs = parse_effect_body(may_exile_self_then.group("after"), reading=ClauseReading(self_subject=reading.self_subject))
        if not after_specs:
            return None
        return [EffectSpec("may_exile_source_then", {"then_trigger": [s.to_dict() for s in after_specs]})]

    roll_when_you_do = _ROLL_DIE_THEN_WHEN_YOU_DO_RE.match(body)
    if roll_when_you_do is not None:
        before_specs = parse_effect_body(
            roll_when_you_do.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        after_specs = parse_effect_body(
            roll_when_you_do.group("after"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if (before_specs is None or len(before_specs) != 1
                or before_specs[0].type != "roll_die" or after_specs is None):
            return None
        params = dict(before_specs[0].params)
        params["then_trigger"] = [spec.to_dict() for spec in after_specs]
        return [EffectSpec("roll_die", params)]

    # PAR-79 eighth increment: a delayed sacrifice/exile/return clause
    # (`effect_rows.pump_stats._DELAYED_SAC_EXILE_WHEN_FIRST_RE`) preceded by an unrelated
    # earlier sentence of the *same* ability — the Alora, Cheerful `<X>`
    # cycle's own "whenever you attack, up to 1 target attacking creature
    # can't be blocked this turn. at the beginning of the next end step,
    # return that creature to its owner's hand[. if you do, `<effect>`]."
    # Every existing "certain antecedent" collapse above (`_SACRIFICE_THEN_
    # WHEN_YOU_DO_RE` et al.) is anchored at the *start* of ``body`` because
    # every real card using those shapes prints the collapse as the whole
    # ability body — Alora's own first sentence (an ordinary RULE 115
    # target pick, already claimed fine by `unblockable`) breaks that
    # assumption, so this dispatch instead finds the delayed clause
    # wherever it sits and recursively parses the leading sentence(s) in
    # front of it, rather than widening any of the anchored checks above to
    # a shape they were never meant to match.
    prefixed_delayed = _PREFIXED_DELAYED_SAC_EXILE_RE.match(body)
    if prefixed_delayed is not None:
        before_specs = parse_effect_body(
            prefixed_delayed.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is None:
            return None
        delayed_specs = match_clause(prefixed_delayed.group("delayed"))
        if delayed_specs is None:
            return None
        return before_specs + delayed_specs

    prefixed_delayed_tail = _PREFIXED_DELAYED_TAIL_RE.match(body)
    if prefixed_delayed_tail is not None:
        before_specs = parse_effect_body(
            prefixed_delayed_tail.group("before"), reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        delayed_specs = match_clause(prefixed_delayed_tail.group("delayed"))
        # Fall through (rather than fail closed) when this split doesn't
        # parse: the shape is loose enough to catch a multi-sentence body
        # another row owns whole (Incandescent Soulstoke's "…onto the
        # battlefield. That creature gains haste until end of turn. Sacrifice
        # it at the beginning of the next end step.").
        if before_specs is not None and delayed_specs is not None:
            return before_specs + delayed_specs

    mill_land_this_way = _MILL_LAND_THIS_WAY_RE.match(body)
    if mill_land_this_way is not None:
        before_specs = parse_effect_body(mill_land_this_way.group("before"))
        branches = re.split(r"\.\s*otherwise,?\s+", mill_land_this_way.group("after"), maxsplit=1)
        after_specs = parse_effect_body(branches[0], reading=ClauseReading(self_subject=reading.self_subject))
        if before_specs is None or after_specs is None or not any(s.type == "mill" for s in before_specs):
            return None
        if len(branches) > 1:
            otherwise = parse_effect_body(branches[1], reading=ClauseReading(self_subject=reading.self_subject))
            if otherwise is None:
                return None
            return before_specs + [EffectSpec("if_else", {
                "condition": {"kind": "milled_land_this_way"},
                "then": [s.to_dict() for s in after_specs],
                "else": [s.to_dict() for s in otherwise],
            })]
        return before_specs + [
            EffectSpec(s.type, dict(s.params), condition={"kind": "milled_land_this_way"})
            for s in after_specs
        ]

    counter_when_you_do = _COUNTER_THEN_WHEN_YOU_DO_RE.match(body)
    if counter_when_you_do is not None:
        before_specs = parse_effect_body(counter_when_you_do.group("before"), reading=ClauseReading(self_subject=True))
        after_specs = parse_effect_body(counter_when_you_do.group("after"), reading=ClauseReading(self_subject=True))
        if before_specs is None or after_specs is None:
            return None
        return before_specs + after_specs

    tap_when_you_do = _TAP_THEN_WHEN_YOU_DO_RE.match(body)
    if tap_when_you_do is not None:
        before_specs = parse_effect_body(tap_when_you_do.group("before"))
        after_specs = parse_effect_body(tap_when_you_do.group("after"))
        if before_specs is None or after_specs is None:
            return None
        # RULE 603.12: "When you do" is a *reflexive trigger* — it exists only
        # if the tap actually happened, and its graveyard target is chosen when
        # it goes on the stack. `choose_objects`' ``then`` runs only once a pick
        # was made, so the trigger rides there instead of following the tap as
        # an unconditional sibling effect.
        if len(before_specs) != 1 or before_specs[0].type != "choose_objects":
            return None
        return [EffectSpec("choose_objects", {
            **before_specs[0].params,
            "then": [EffectSpec("reflexive_trigger", {
                "then_trigger": [s.to_dict() for s in after_specs],
            }).to_dict()],
        })]

    exile_then_copy = _EXILE_THEN_COPY_SENTENCE_RE.match(body)
    if exile_then_copy is not None:
        before_text = exile_then_copy.group("before").strip()
        # "You may exile …" (God-Pharaoh's Gift, Séance) — the optionality
        # lives on the exile; peel it and re-fold it as ``optional`` so the
        # inner clause reaches `_exile_from_graveyard` (which has no "you
        # may" grammar of its own).
        optional_exile = bool(re.match(r"(?i)^you may ", before_text))
        if optional_exile:
            before_text = before_text[len("you may "):]
        before_specs = parse_effect_body(
            before_text, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
        )
        if before_specs is not None and optional_exile:
            before_specs = [
                EffectSpec(s.type, {**s.params, "optional": True}, condition=s.condition)
                for s in before_specs
            ]
        # Fail closed unless the "before" half genuinely chose a graveyard
        # card (`announces_creature_target` recognises the `graveyard_*`
        # target-kind prefix) — that pick is the pronoun `CopyPermanentEffect
        # (referent="previous")` reads back (RULE 608.2).
        if before_specs is None or not announces_creature_target(before_specs):
            return None
        after_specs = parse_effect_body(
            exile_then_copy.group("after"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if after_specs is None or not any(s.type == "copy_permanent" for s in after_specs):
            return None
        return before_specs + after_specs

    pooled_this_way = _this_way_sequences(
        body, verbs=frozenset({"exiled", "destroyed", "milled"}),
        reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if pooled_this_way is not None:
        return pooled_this_way

    any_number_this_way = _any_number_this_way_specs(body, reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject), )
    if any_number_this_way is not None:
        return any_number_this_way

    windowed_this_way = _this_way_sequences(
        body, verbs=frozenset({"discarded", "sacrificed"}),
        reading=ClauseReading(self_subject=reading.self_subject, group_subject=reading.group_subject),
    )
    if windowed_this_way is not None:
        return windowed_this_way

    exile_x_for_each = _EXILE_X_GY_FOR_EACH_CREATE_RE.match(body)
    if exile_x_for_each is not None:
        create_specs = parse_effect_body(
            exile_x_for_each.group("create"), reading=ClauseReading(previous_subject=True, group_subject=reading.group_subject),
        )
        if not create_specs or len(create_specs) != 1:
            return None
        follow = create_specs[0]
        if follow.type == "copy_permanent":
            # "…create a token that's a copy of that card…" (Hour of Eternity)
            # — one copy of *each* exiled card, RULE 608.2 `previous_targets`.
            follow = EffectSpec(
                "copy_permanent", {**follow.params, "referent": "previous_each"},
            )
        elif follow.type == "create_token":
            # "…create a 2/2 black Zombie creature token." (Midnight Ritual) —
            # N inline tokens, N = how many cards this resolution exiled.
            follow = EffectSpec(
                "create_token",
                {**follow.params, "count_from_context": "objects_exiled_this_way"},
            )
        else:
            return None  # fail closed — only the two known follow-up shapes
        return [
            EffectSpec("exile", {
                "target_kind": "graveyard_creature", "count_selector": "source_x_paid",
            }),
            follow,
        ]

    quoted_token_ability = _created_tokens_have_ability_specs(body)
    if quoted_token_ability is not None:
        return quoted_token_ability

    distributed_cda = _created_tokens_have_cda_specs(body)
    if distributed_cda is not None:
        return distributed_cda

    destroyed_counter_token = _destroy_target_counter_token_specs(body)
    if destroyed_counter_token is not None:
        return destroyed_counter_token

    direct = match_clause(
        body, reading=reading,
    )
    if direct is not None:
        return direct

    if re.match(r"you may pay (?:\{e\})+\.\s*(?:if|when) you do\b", body, re.I):
        # RULE 608.2/603.12: the payment and its continuation are atomic.
        # A declined wrapper must not fall through to splitting ", then"
        # and turn an unsupported paid/reflexive payoff into a free effect.
        return None

    timed = _for_as_long_as_counter_specs(body, reading=ClauseReading(referents=reading.referents_of(TARGET)))
    if timed is not None:
        return timed

    both_counters = _DOUBLE_COUNTERS_RE.match(body)
    if both_counters is not None:
        # "put a +1/+1 counter on that creature and a +1/+1 counter on ~" — two placements in one
        # sentence, each read on its own (the second half has no verb of its own to split on).
        halves = [
            parse_effect_body(
                f"put {both_counters.group(part)}", reading=reading,
            )
            for part in ("first", "second")
        ]
        if all(halves):
            return [spec for half in halves for spec in half]
        return None

    # PAR-62: "if `<cond>`, `<A>`. otherwise, `<B>`." must be claimed as one
    # `if_else` *before* the connector split, not after it. The split hands
    # "otherwise, `<B>`" over as its own part, and a standing
    # `_CONDITION_PREFIXES` row reads a bare leading "otherwise," as RULE
    # 701.30d's **clash** "otherwise" — the only place that word had a
    # modeled meaning before this. That gate is right for a clash card and
    # unrelated here, so leaving the split to win would attach
    # "you didn't win the clash" to this card's else branch: a wrong reading,
    # and one this ticket's own `if` gate would newly expose by making the
    # *then* half parse. Anchored on a leading "if", so a real clash body
    # ("clash with an opponent. if you win, …") never reaches this and keeps
    # its own grammar.
    if_else = _if_else_specs(
        body, reading=reading.unattached(),
    )
    if if_else is not None:
        return if_else

    override = _instead_override_specs(body, reading=reading.unattached())
    if override is not None:
        return override

    # "If `<cond>`, `<A>` and|, then `<B>`." — one sentence, one gate over *both* effects. The
    # connector split below would hand `<B>` over on its own, ungated (Unholy Annex: "If you
    # control a Demon, each opponent loses 2 life and you gain 2 life" gained the life
    # whether or not you did). A body with a period is several sentences and keeps its
    # per-clause gating.
    one_gate = _GENERIC_IF_PREFIX_RE.match(body)
    if one_gate is not None and "." not in one_gate.group("rest") and re.search(
        r"\s+and\s+|,?\s+then\s+", one_gate.group("rest")
    ):
        gate = static_condition(one_gate.group("cond"))
        gated_inner = (
            parse_effect_body(
                one_gate.group("rest"), reading=reading.unattached(),
            )
            if gate is not None else None
        )
        if gated_inner and all(spec.condition is None for spec in gated_inner):
            return [EffectSpec(spec.type, dict(spec.params), condition=gate) for spec in gated_inner]

    # "`<A>` and `<B>`, where X is the number of …" — one X for the whole sentence. The
    # connector split below would hand the tail to `<B>` alone and leave `<A>`'s X as
    # the (unpaid) spell X (Tendrils of Corruption dealt 0 damage and gained the life).
    one_x_text = body.strip().rstrip(".").strip()
    one_x = (_WHERE_X_RE.match(one_x_text) or _WHERE_X_AMOUNT_RE.match(one_x_text)
             or _WHERE_X_DIE_RE.match(one_x_text) or _WHERE_X_HALF_COUNT_RE.match(one_x_text))
    if one_x is not None and "." not in one_x.group("rest") and re.search(
        r"\s+and\s+", one_x.group("rest")
    ):
        shared_x = _where_x_specs(
            body, reading=reading.unattached(),
            several=True,
        )
        if shared_x is not None:
            return shared_x

    for sep in _CONNECTORS:
        # PAR-141: the pronoun comma is only a boundary *within* a gated body's own effect text. Split
        # across "…, if you do, X, it gains …" it would leave the later clauses outside the gate.
        if sep is _PRONOUN_COMMA_CONNECTOR and re.search(r"\b(?:if|when) you (?:do|don't),", body, re.I):
            continue
        parts = _split_effect_connector(body, sep)
        if len(parts) > 1:
            collected: list[EffectSpec] = []
            ok = True
            # Seed the pronoun chain from the caller: a two-sentence wrapper
            # (`_EXILE_THEN_COPY_SENTENCE_RE`, `_with_after_tail`) passes
            # ``previous_subject=True`` for a span it already knows opens
            # with a referent ("create a token that's a copy of that card.
            # It gains haste …") — the *first* sub-part must inherit that,
            # not restart from nothing. ``self_subject`` still isn't passed
            # down (see this function's docstring).
            referents = reading.referents
            referent = any(r.kind == TARGET for r in referents)
            referent_selector = any(r.kind == SELECTOR for r in referents)
            # PAR-32: a self-subject trigger body ("whenever ~ attacks, put a
            # +1/+1 counter on ~. it gains deathtouch until end of turn." —
            # Agent of the Shadow Thieves) — "it" in every sub-clause still
            # means the source, until a clause introduces a *different*
            # targeted creature (`announces_creature_target` flips
            # ``carry_self`` off). Unlike the source-less `previous_subject`
            # chain, this survives a clause that only re-references the
            # source (a counter on "~").
            carry_self = reading.self_subject
            last_len = 0
            # "Otherwise, you may pay {X}. When you do, …" (Rose Room
            # Treasurer): the reflexive sentence belongs to the else branch
            # (RULE 603.12), not to the clauses after the if_else.
            merged: list[str] = []
            for part in parts:
                if (merged and _OTHERWISE_RE.match(merged[-1].strip())
                        and re.match(r"^\s*(?:when|if) you do,", part, re.I)):
                    merged[-1] = f"{merged[-1].rstrip()}. {part.strip()}"
                else:
                    merged.append(part)
            parts = merged
            skip_until = 0
            conjunct_player_scope = None
            for idx, part in enumerate(parts):
                if idx < skip_until:
                    continue  # consumed by a multi-sentence window
                # A period split retains the leading "then" from a printed
                # "… . Then <effect>" sentence, unlike the explicit
                # `, then` connector. It is sequencing, not effect grammar.
                part = re.sub(r"^then\s+", "", part.strip(), flags=re.IGNORECASE)
                part = _created_noun_to_pronoun(part, referents)
                if sep == _AND_CONNECTOR:
                    part = part.rstrip(",").strip()  # "…if {g} was spent to cast this spell**,** and …"
                    # A repeated third-person verb keeps the current group
                    # subject: "each opponent sacrifices ... and loses ...".
                    # A newly stated subject ends that inheritance.
                    player_head = _PLAYER_SCOPE_SUBJECT_RE.match(part)
                    if player_head is not None:
                        who = player_head['who'].lower()
                        conjunct_player_scope = who if who in _PLAYER_SCOPE_ITERATION else None
                    elif conjunct_player_scope and _ELIDED_PLAYER_VERB_RE.match(part):
                        part = f"{conjunct_player_scope} {part}"
                    else:
                        conjunct_player_scope = None
                otherwise = _OTHERWISE_RE.match(part)
                if otherwise is not None:
                    sub = _otherwise_specs(
                        otherwise.group("rest"), collected[len(collected) - last_len:] if last_len else [],
                        reading=_sequel_reading(reading, carry_self, referents),
                    )
                    if sub is not None:
                        del collected[len(collected) - last_len:]  # the if_else replaces them
                else:
                    sub = None
                    if sep == _CONNECTORS[0]:
                        # A row written for several consecutive sentences (`_MAX_SENTENCE_WINDOW`),
                        # longest first, before the sentence alone: splitting would hand it only
                        # its first sentence.
                        for end in range(min(len(parts), idx + _MAX_SENTENCE_WINDOW), idx + 1, -1):
                            window = re.sub(r"^then\s+", "", ". ".join(p.strip() for p in parts[idx:end]), flags=re.I)
                            sub = match_clause(
                                window, reading=_sequel_reading(reading, carry_self, referents),
                            )
                            if sub is not None:
                                skip_until = end
                                break
                    if sub is None:
                        sub = parse_effect_body(
                            part,
                            reading=_sequel_reading(reading, carry_self, referents),
                        )
                if sub is None and sep == _AND_CONNECTOR and idx:
                    # "~ deals 3 damage to X if … **and 3 damage to Y** if …" / "you gain X life if … **and X life**
                    # if …": the second conjunct repeats only the amount noun, the verb is the first one's.
                    for verb_head, elided in _ELIDED_AMOUNT_VERBS:
                        if (
                            parts[idx - 1].lstrip().lower().startswith(verb_head) and elided.match(part)
                        ):
                            sub = parse_effect_body(
                                f"{verb_head}{part}", reading=_sequel_reading(reading, carry_self, referents),
                            )
                            # "any other target" / "another …" is only kept distinct by the stamp (ENG-52); an
                            # effect that cannot carry it leaves the compound unclaimed.
                            if sub is not None and _ELIDED_TARGET_LOSS_RE.search(part):
                                sub, distinct = _stamp_distinct_from_others(sub)
                                if not distinct:
                                    sub = None
                            break
                if sub is None:
                    ok = False
                    break
                if sep == _AND_CONNECTOR and idx and _elides_player_subject(parts[0], part):
                    # "target player draws a card **and loses 2 life**": the second verb has no subject of
                    # its own, so it acts on the player the first clause chose, not on the controller.
                    sub = _stamp_previous_player(sub)
                    if sub is None:
                        ok = False
                        break
                if referent:
                    sub = stamp_counters_on_referent(part, sub)
                if collected and _OTHER_TARGET_PART_RE.search(part):
                    # ENG-52: "…. ~ deals 2 damage to any other target": not the target an earlier clause chose.
                    sub, _ = _stamp_distinct_from_others(sub)
                sub = _fold_counter_destination(sub, collected)
                if sub is None:
                    ok = False
                    break
                last_len = len(sub)
                collected.extend(sub)
                prev_referent, prev_referent_selector = referent, referent_selector
                prev_referents = referents
                # RULE 601.2c: what the clause just parsed *chose* is what
                # the next one's "it"/"that creature"/"those creatures" can
                # point at (`effect_rows.shared.EffectHandler.previous_subject_only`,
                # `effects.GameContext.previous_targets`). A clause that
                # chose no creature leaves the pronoun unbound — and so
                # unclaimed — rather than letting it drift onto some earlier
                # clause's pick, which is the ambiguity this gate exists for.
                referent = TARGET in {r.kind for r in produces(sub)}
                # PAR-32: once a clause picks a *different* targeted creature,
                # the self-subject carry is broken (a later "it" now means
                # that pick, via ``referent``, not the source).
                if referent:
                    carry_self = False
                # PAR-30: "clash with an opponent" is a *referent-transparent*
                # interstitial — it neither targets nor creates, so a card
                # like Gilt-Leaf Ambush ("create 2 tokens. clash with an
                # opponent. if you win, those creatures gain deathtouch …")
                # must carry the pronoun chain across the clash sentence
                # rather than have it cleared here.
                if not referent and sub and all(s.type in _REFERENT_TRANSPARENT_TYPES for s in sub):
                    referent, referent_selector = prev_referent, prev_referent_selector
                # PAR-141: "put a +1/+1 counter on ~. It becomes a Spirit in addition to …" — a
                # counter put on the source leaves "it" meaning the source (a counter spec with no
                # target of its own is the ability's own permanent), so the next clause may read
                # the pronoun as `self_subject` even outside a self-subject trigger.
                if not referent and sub and _puts_counter_on_source(sub[-1]):
                    carry_self = True
                # PAR-30: a clause that itself *consumed* the pronoun ("untap
                # that creature", "it gains haste until end of turn") keeps the
                # referent chain alive for the clause after it rather than
                # clearing it — real cards run several such restatement clauses
                # in series off one "gain control of target creature" antecedent
                # (the threaten family; RULE 701.30d clash "if you win, …"
                # payoffs). Only extends an existing chain, never starts one.
                # PAR-123: the *input* referent had to exist. A clause a group trigger's own
                # firing object satisfied (`match_clause`'s group fallback) consumes a previous
                # -subject row without any earlier clause having chosen anything, and must not
                # turn that into a chain a later "it" would read as a real target.
                if not referent and prev_referent and any(
                    s.params.get("previous_subject") or s.params.get("bake_previous_objects") for s in sub
                ):
                    referent = True
                # MEC-28: the mass-selector sibling — "untap all attacking
                # creatures. They gain …" — tracked independently since a
                # selector clause never sets ``referent`` above (it targets
                # nothing at all, RULE 601.2c).
                referent_selector = SELECTOR in {r.kind for r in produces(sub)}
                # What was just *made* stays the referent while later clauses keep consuming it ("... It has "...".
                # It gains haste ..."), and only then.
                made = tuple(r for r in produces(sub) if r.kind in (CREATED, COUNTERED)) or (
                    tuple(r for r in prev_referents if r.kind == CREATED)
                    if any(s.params.get("referent") == CREATED for s in sub) else ()
                )
                referents = _referents_from(referent, referent_selector, made)
            if ok:
                return collected

    # The same rule again, at the *other* end of the pipeline: these gates
    # are checked **after** the connector split so each binds to only its own
    # clause. In "draw a card, then discard a card unless her additional cost
    # was paid" the split hands this just "discard a card unless …", where a
    # pre-split peel would have gated the draw too. Two call sites, not two
    # implementations — where in the pipeline a gate binds is a real property
    # of the gate, and the only thing that separates the two tables.
    matched, peeled = _peel_condition(
        body, _CONDITION_SUFFIXES, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if matched and peeled is not None:
        return peeled

    # PAR-62 (`14_` S4), the first connective routed to an ENG-37 composition
    # node rather than to a fused effect type or a per-effect ``optional``
    # boolean: RULE 601.2b's "you may `<effect>`" appearing **mid-body**.
    #
    # `peel_optional` handles only a *leading* "you may", at the whole-ability
    # level (`segment_line`), which is why "…, then you may `<effect>`" — the
    # connector split hands this function "you may `<effect>`" as its own
    # part — had no reading at all. A named standing gap in `09_`.
    #
    # Deliberately placed **after** everything above, including the connector
    # cascade: `_CONNECTORS` returns on the first separator that yields a
    # *complete* parse, so a body with a reading today keeps it and this can
    # only fire where the pipeline already returned ``None``. That is what
    # makes S4 landable in increments instead of as one re-derivation of every
    # MODELED card.
    for_each = _for_each_specs(
        body, reading=reading.unattached(),
    )
    if for_each is not None:
        return for_each

    where_x = _where_x_specs(
        body, reading=reading.unattached(),
    )
    if where_x is not None:
        return where_x

    referent_x = _referent_characteristic_specs(
        body, reading=reading.unattached(),
    )
    if referent_x is not None:
        return referent_x

    player_scope = _player_scope_specs(
        body, reading=reading.unattached(),
    )
    if player_scope is not None:
        return player_scope

    each_flip = _leading_for_each_flip_specs(
        body, reading=reading.unattached(),
    )
    if each_flip is not None:
        return each_flip

    each_object = _leading_for_each_object_specs(body)
    if each_object is not None:
        return each_object

    matched, peeled = _peel_condition(
        body, _GENERIC_CONDITION_ROWS, reading=ClauseReading(self_subject=reading.self_subject, referents=reading.referents_of(TARGET), group_subject=reading.group_subject),
    )
    if matched and peeled is not None:
        return peeled

    optional_body = _MID_BODY_OPTIONAL_RE.match(body)
    if optional_body is not None and not _PAY_ENERGY_THEN_PEEL_GUARD_RE.match(body):
        rest = optional_body.group("rest").strip()
        # One "you may" per node. A second one inside ``rest`` would make the
        # outer node wrap clauses the card never made optional (the printed
        # "you may A. you may B" is two independent choices, not one), so it
        # fails closed here rather than guessing a nesting.
        #
        # The same refusal for RULE 603.3's *reflexive* trigger, "you may A.
        # when you do, B." / "…if you do, B." — B is a separate triggered
        # ability that fires because A happened and uses the stack, not a
        # second half of one choice. Wrapping both in this node would collapse
        # the trigger into a plain sequence, which is a wrong reading rather
        # than a missing one; those shapes have their own grammar above
        # (`_EARTHBEND_THEN_WHEN_YOU_DO_RE` and its siblings) and must reach
        # it. Pinned by `tests/test_par30_earthbend_when_you_do.py`.
        if not _MID_BODY_OPTIONAL_RE.match(rest) and not _REFLEXIVE_TRIGGER_RE.search(rest):
            inner = parse_effect_body(
                rest, reading=reading.unattached(),
            )
            if inner:
                return [EffectSpec("optional", {
                    "effects": [spec.to_dict() for spec in inner],
                })]

    # PAR-117: "its controller may `<effect>`" — same composition as
    # `_MID_BODY_OPTIONAL_RE` just above, but the chooser is a referent
    # rather than "you". Only meaningful under exactly one of the three
    # pronoun-referent modes `parse_effect_body`'s own docstring documents
    # (never `self_subject`: "its controller" when the subject already *is*
    # the source would just mean "you", which the plain "you may" row above
    # already claims) — resolved to the identical `{"of": …, "as":
    # "controller"}` dict `_its_controller_*`/`_group_its_controller_*`/
    # `_attached_its_controller_*` already read via `_operand_player`.
    its_controller_may = _MID_BODY_ITS_CONTROLLER_MAY_RE.match(body)
    if its_controller_may is not None:
        referent = (
            {"of": "previous_target", "as": "controller"} if reading.previous_subject
            else {"of": "entering", "as": "controller"} if reading.group_subject
            else {"of": "attached", "as": "controller"} if reading.attached_subject
            else None
        )
        if referent is not None:
            rest = its_controller_may.group("rest").strip()
            if not _MID_BODY_OPTIONAL_RE.match(rest) and not _REFLEXIVE_TRIGGER_RE.search(rest):
                inner = parse_effect_body(
                    rest, reading=ClauseReading(group_subject=reading.group_subject, referents=reading.referents),
                )
                if inner:
                    inner_dicts = [
                        _rewrite_optional_referent_actor(spec.to_dict(), referent)
                        for spec in inner
                    ]
                    return [EffectSpec("optional", {
                        "effects": inner_dicts,
                        "player": referent,
                    })]
    return None


#: PAR-117: the referent that answers "its controller may `<effect>`"'s own
#: question ("do they?") is also who *performs* the body once they say yes —
#: RULE 603.1's "its controller" is one pronoun, not two independent
#: resolutions of "whoever that is". `OptionalEffect`'s own pause (the
#: player has to actually answer before the body runs) already re-resolves
#: this referent at that later point (`_resume_composite_optional`), so the
#: inner effect just needs to *ask* for it explicitly instead of falling
#: back to its usual "this ability's own controller" default, which would
#: silently be the wrong player whenever the referent differs (Edric,
#: Spymaster of Trest: Edric's own controller vs. the damaging creature's).
#: A closed, narrow map — only the two inner effect shapes real cards in
#: this cluster actually use (`draw`'s own referent-dict ``player`` field;
#: `create_token`'s closed-string ``creators`` enum, needing the
#: referent's own ``of`` translated rather than passed through raw).
#: Anything else stays unrewritten rather than guessing a field name that
#: might not exist on that effect type.
_OPTIONAL_REFERENT_CREATORS_BY_OF: dict[str, str] = {
    "entering": "trigger_subject_controller",
    "previous_target": "previous_target_controller",
}


def _rewrite_optional_referent_actor(spec_dict: dict, referent: dict) -> dict:
    if spec_dict.get("type") == "draw" and "player" not in (spec_dict.get("params") or {}):
        spec_dict = {**spec_dict, "params": {**spec_dict.get("params", {}), "player": referent}}
    elif spec_dict.get("type") == "create_token" and "creators" not in (spec_dict.get("params") or {}):
        creators = _OPTIONAL_REFERENT_CREATORS_BY_OF.get(str(referent.get("of")))
        if creators is not None:
            spec_dict = {
                **spec_dict, "params": {**spec_dict.get("params", {}), "creators": creators},
            }
    return spec_dict


#: PAR-142: "… for as long as it/that `<noun>` has a `<kind>` counter on it" (Aquitect's Will, Minas Morgul,
#: Aven Mimeomancer) — RULE 611.2b's condition-bounded duration over the pick an earlier clause just put the
#: counter on. Not a clause of its own: the body before (or after) it is an ordinary duration-less effect, and
#: this only re-times the `grant_until` it produced (`game/durations.py`, ``for_as_long_as``, its condition
#: read off the locked permanent — ``of="affected"``).
_FOR_AS_LONG_AS_WHO = r"(?:it|that [a-z]+)"
_FOR_AS_LONG_AS_COUNTER = (
    rf"for as long as (?P<who>{_FOR_AS_LONG_AS_WHO}) has an? (?P<kind>[a-z0-9+/\- ]+?) counters? on it"
)
_FOR_AS_LONG_AS_TRAILING_RE = re.compile(
    rf"^(?P<body>.+?),?\s+{_FOR_AS_LONG_AS_COUNTER}$", re.IGNORECASE | re.DOTALL,
)
_FOR_AS_LONG_AS_LEADING_RE = re.compile(
    rf"^{_FOR_AS_LONG_AS_COUNTER},\s+(?P<body>.+)$", re.IGNORECASE | re.DOTALL,
)


def _for_as_long_as_counter_specs(body: str, *, reading: ClauseReading = STANDALONE, ) -> Optional[list[EffectSpec]]:
    m = _FOR_AS_LONG_AS_TRAILING_RE.match(body) or _FOR_AS_LONG_AS_LEADING_RE.match(body)
    if m is None or not reading.previous_subject:
        return None  # the pronoun needs a pick an earlier clause made
    inner = parse_effect_body(m.group("body").strip(), reading=ClauseReading(previous_subject=True))
    if not inner or any(spec.type != "grant_until" for spec in inner):
        return None  # only a duration effect can be re-timed; anything else fails closed
    condition = {"kind": "source_counters", "counter": m.group("kind").strip().lower(), "min": 1, "of": "affected"}
    return [
        EffectSpec(spec.type, {**spec.params, "duration": "for_as_long_as", "condition": dict(condition)},
                   condition=spec.condition)
        for spec in inner
    ]


def _puts_counter_on_source(spec: EffectSpec) -> bool:
    """A plain ``add_counters`` naming no target, recipient or group — the counter went on ``~``."""
    return spec.type == "add_counters" and not any(
        key in spec.params for key in ("target_kind", "group", "selector", "choose_one", "recipient")
    )


#: MEC-28: recognised mass-selector values `effect_rows.shared.EffectHandler.
#: previous_selector_only` rows may read back as "they" (`effects.
#: GameContext.previous_selector`, `game/binding/core.py`'s narrow
#: ``TapEffect``-only tracking whitelist) — deliberately just the one real
#: card (Karlach, Fury of Avernus) needs today, widened only as another
#: card actually prints a different mass selector before this same "they"
#: tail, matching this file's usual narrow-whitelist convention.
#:
#: PAR-120 (PARSER_VERSION 474): "attacking creatures"/"creatures your
#: opponents control" now reach `group_selector_objects` as a *structured*
#: selector (`catalogue.effect_rows.shared._group_selector`) rather than always the
#: named string here — a plain ``in`` check against this frozenset would
#: both crash (a dict isn't hashable) and, even fixed to avoid that, still
#: miss the structured spelling. `_is_group_selector_value` recognizes
#: either form of the same two selectors.
_GROUP_SELECTOR_VALUES: frozenset[str] = frozenset({"attacking_creatures", "creatures_opponents_control"})
_GROUP_SELECTOR_STRUCTURED_FILTERS: tuple[dict, ...] = (
    {"zone": "battlefield", "of": "any", "filter": {"attacking": True, "card_type": "creature"}},
    {"zone": "battlefield", "of": "opponents", "filter": {"card_type": "creature"}},
)


#: PAR-128: the named tap groups a following "those creatures" may replay —
#: each is its whole group by name (no subtype/colour suffix riding on a
#: separate param).
_SELF_DESCRIBING_TAP_SELECTORS: frozenset[str] = frozenset(
    {"creatures_you_control", "other_creatures_you_control", "attacking_creatures"}
)
#: The params a tap / pump spec may carry and still be replayable by its
#: selector alone (anything else narrows the group past what
#: `GameContext.previous_selector` records).
#: `DealDamageEffect.selector` values naming creatures only — mirrored by
#: `effects.attachments_transforms.PREVIOUS_GROUP_DAMAGE_SELECTORS` (the parser
#: can't import `game/`).
_CREATURE_MASS_DAMAGE_SELECTORS: frozenset[str] = frozenset(
    {"each_creature", "each_other_creature", "each_creature_opponents_control"}
)
#: `AddCountersEffect.selector` creature groups (mirrors `counters_tokens.
#: ADD_COUNTERS_GROUP_AFFECTS`) and the params such a spec may carry.
_CREATURE_MASS_COUNTER_SELECTORS: frozenset[str] = frozenset(
    {"each_creature_you_control", "each_other_creature_you_control", "each_creature",
     "each_other_creature", "each_creature_opponents_control"}
)
_BARE_COUNTER_PARAMS: frozenset[str] = frozenset({"kind", "selector", "count"})
_BARE_COUNTER_GROUP_PARAMS: frozenset[str] = frozenset({"kind", "group", "count", "group_other"})


#: "each creature" / "each other creature": the filters that name a group by type and self-exclusion alone.
_BARE_CREATURE_GROUP_FILTERS = ({"card_type": "creature"}, {"card_type": "creature", "not_reference": True})


def _is_creature_only_group(group: object) -> bool:
    """A structured battlefield group whose members are all creatures."""
    return (
        isinstance(group, dict) and group.get("zone", "battlefield") == "battlefield"
        and isinstance(group.get("filter"), dict) and group["filter"].get("card_type") == "creature"
    )


def _is_bare_creature_group(group: object) -> bool:
    """An unnarrowed creature group: replaying it later names the same objects (no counter/state filter)."""
    return _is_creature_only_group(group) and group["filter"] in _BARE_CREATURE_GROUP_FILTERS
_BARE_TAP_PARAMS: frozenset[str] = frozenset({"selector", "untap", "selector_player"})
_BARE_PUMP_PARAMS: frozenset[str] = frozenset({"selector", "power", "toughness", "keywords"})


def _is_group_selector_value(value: object) -> bool:
    if isinstance(value, dict):
        return value in _GROUP_SELECTOR_STRUCTURED_FILTERS
    return value in _GROUP_SELECTOR_VALUES


#: Effects that leave what they made in `GameContext.created_objects` for the next clause.
_CREATING_TYPES: frozenset[str] = frozenset({"create_token"})
# (``copy_permanent`` is not listed: `CopyPermanentEffect.created_objects_are_referent` already hands its copies on
# as the next clause's `previous_targets`, so "Create a token that's a copy of that card. It gains haste." is right.)


def produces(specs: list[EffectSpec]) -> tuple[Referent, ...]:
    """What a just-parsed clause leaves for the next one to name (the referent environment's one producer): the
    object it chose (``it`` / ``that creature``) and/or the group it acted on (``they`` / ``those creatures``)."""
    out: list[Referent] = []
    if announces_creature_target(specs):
        out.append(TARGET_REFERENT)
    if _announces_group_selector(specs):
        out.append(SELECTOR_REFERENT)
    if specs and specs[-1].type == "counter" and not specs[-1].params.get("destination"):
        out.append(COUNTERED_REFERENT)
    # The creation may be followed, inside the same clause, by riders that already consumed it ("create a token that's a
    # copy of …, except it has "…"" is a copy plus a grant on the copy): the last spec that is not such a rider decides.
    core = list(specs)
    while len(core) > 1 and core[-1].params.get("previous_subject") and core[-1].params.get("target_kind") is None:
        core.pop()
    if core and core[-1].type in _CREATING_TYPES | {"copy_permanent"}:
        out.append(CREATED_GROUP_REFERENT if core[-1].params.get("count", 1) != 1 else CREATED_REFERENT)
        if not any(r.kind == TARGET for r in out):
            out.append(TARGET_REFERENT)
    return tuple(out)


#: Pronoun consumers whose engine effect reads ``referent="created"`` (PumpEffect, GrantUntilEffect); a delayed
#: trigger's ``capture`` is switched to ``created_objects`` instead.
_CREATED_AWARE_TYPES: frozenset[str] = frozenset({"pump", "grant_until"})


_CREATED_DELAYED_BODIES: frozenset[str] = frozenset({"sacrifice_specific", "exile_specific", "destroy_specific"})


_CREATED_SUBJECT_RE = re.compile(r"^(?:those|the) tokens\b|^that token\b", re.IGNORECASE)
_CREATED_OBJECT_RE = re.compile(
    r"^(?P<verb>sacrifice|exile|destroy|untap|tap|return) (?:those|the) tokens\b|^(?P<verb1>sacrifice|exile|destroy|untap|tap|return) that token\b",
    re.IGNORECASE,
)


def _created_noun_to_pronoun(part: str, referents: tuple[Referent, ...]) -> str:
    """"Create two tokens. **Those tokens** gain haste. Sacrifice **those tokens** at the beginning of the next end step."
    -- right after a creating clause the noun names exactly what was made, so it reads as the pronoun the pronoun rows
    already take (they / them / it). Without a CREATED referent the text is left alone (and stays unclaimed)."""
    if not any(r.kind == CREATED for r in referents):
        return part
    group = next(r for r in referents if r.kind == CREATED).group
    obj = _CREATED_OBJECT_RE.match(part)
    if obj is not None:
        verb = obj.group("verb") or obj.group("verb1")
        return f"{verb} {'them' if group or obj.group('verb') else 'it'}" + part[obj.end():]
    if _CREATED_SUBJECT_RE.match(part):
        return ("they" if group else "it") + part[_CREATED_SUBJECT_RE.match(part).end():]
    return part


def _fold_counter_destination(sub: list[EffectSpec], collected: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    """"Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's
    graveyard." -- the consumer row (offered only right after a counter) emits a ``counter_destination`` marker; it
    becomes the ``destination`` of the counter already collected. ``None`` when it has no counter to join."""
    if not any(s.type == "counter_destination" for s in sub):
        return sub
    if len(sub) != 1 or not collected or collected[-1].type != "counter" or collected[-1].params.get("destination"):
        return None
    collected[-1] = replace(collected[-1], params={**collected[-1].params, "destination": sub[0].params["destination"]})
    return []


def _stamp_created_pronouns(specs: list[EffectSpec]) -> list[EffectSpec]:
    """"Tap up to 2 target creatures. Create a token. It gains haste." / "Exile target creature card from your
    graveyard. Create a token that's a copy of that card. It gains haste. Exile it at the beginning of the next end
    step." -- ``previous_targets`` still holds what an earlier clause picked, so a pronoun clause that follows a
    *creating* clause says so explicitly (`referent="created"`; a delayed trigger bakes ``capture="created_objects"``)
    when something was picked before the creation. Without an earlier pick the engine's own fallback to
    `created_objects` is already right, and the spec stays as it was. Idempotent."""
    picked = False  # an earlier clause chose something (`previous_targets` is not empty at the creation)
    stale = False  # ... and the most recent creating clause came after it
    out: list[EffectSpec] = []
    for spec in specs:
        if spec.type in _CREATING_TYPES:
            stale = picked
            out.append(spec)
            continue
        if stale and spec.type in _CREATED_AWARE_TYPES and spec.params.get("previous_subject") and "referent" not in spec.params:
            spec = replace(spec, params={**spec.params, "referent": CREATED})
        elif (
            stale and spec.type == "create_delayed_trigger" and spec.params.get("capture") == "previous_or_self"
            # "Sacrifice/exile/destroy it/them" names the creation; "return the exiled cards" (Disorder in the Court)
            # names the earlier pick even when a Clue was made in between.
            and all(e.get("type") in _CREATED_DELAYED_BODIES for e in spec.params.get("effects", []))
        ):
            spec = replace(spec, params={**spec.params, "capture": "created_objects"})
        elif spec.params.get("target_kind") or spec.params.get("selector") or spec.params.get("group"):
            picked, stale = True, False  # a new pick is what the next pronoun names
        out.append(spec)
    return out


def _referents_from(target: bool, selector: bool, created: tuple[Referent, ...] = ()) -> tuple[Referent, ...]:
    """The environment for the next clause, after the sequencing loop has applied its carry-over rules."""
    return tuple(ref for ref, on in ((TARGET_REFERENT, target), (SELECTOR_REFERENT, selector)) if on) + created


def _sequel_reading(reading: ClauseReading, carry_self: bool, referents: tuple[Referent, ...]) -> ClauseReading:
    """The reading of the next clause of a sequence: the source keeps "it" until a clause chose something else, the
    group-trigger subject carries over, and the environment is what the clauses so far produced."""
    chose = any(r.kind == TARGET for r in referents)
    return ClauseReading(
        self_subject=carry_self and not chose, group_subject=reading.group_subject, referents=referents,
    )


def _announces_group_selector(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` is an untargeted mass-selector effect
    ("untap all attacking creatures") the next clause's "they" can point at —
    `announces_creature_target`'s sibling for RULE 601.2c selectors rather
    than RULE 115 targets, since a selector clause has no target of its own
    to be caught by that check."""
    if not specs:
        return False
    last = specs[-1]
    if last.type == "exile" and (last.params.get("group") or last.params.get("selector")):
        # PAR-136: "Exile each creature you control. Return those cards …" (Ghostway) — a mass exile
        # leaves exactly what it exiled in `GameContext.previous_targets` (`ExileEffect`).
        return True
    if last.type == "tap":
        selector = last.params.get("selector")
        if isinstance(selector, dict) and selector.get("zone", "battlefield") == "battlefield":
            # PAR-128: a structured selector states its whole group (filter and
            # controller scope included), so replaying it names the same objects.
            return set(last.params) <= _BARE_TAP_PARAMS
        return _is_group_selector_value(last.params.get("selector")) or (
            # PAR-128: "untap all creatures you control. They gain …" — any
            # *unnarrowed* named group; `GameContext.previous_selector`
            # carries only the selector, so a subtype/filter rider layered on
            # top of it would be lost by the pronoun (Valley Floodcaller).
            last.params.get("selector") in _SELF_DESCRIBING_TAP_SELECTORS
            and set(last.params) <= _BARE_TAP_PARAMS
        )
    if last.type == "add_counters":
        # PAR-128: "put a +1/+1 counter on each creature you control. Untap
        # those creatures." — an unnarrowed creature group, replayable by name.
        return (
            last.params.get("selector") in _CREATURE_MASS_COUNTER_SELECTORS
            and set(last.params) <= _BARE_COUNTER_PARAMS
        ) or (
            # PAR-169: the structured form (`add_pt_counter_group`) of the same unnarrowed creature group.
            _is_bare_creature_group(last.params.get("group"))
            and set(last.params) <= _BARE_COUNTER_GROUP_PARAMS
        )
    if last.type == "damage":
        # PAR-128: "deals 1 damage to each creature with flying your opponents
        # control. Tap those creatures." — creature-only mass damage; the group
        # is the set the hit landed on (`GameContext.damaged_this_way`).
        return last.params.get("selector") in _CREATURE_MASS_DAMAGE_SELECTORS or (
            # PAR-169: the structured form (`damage_group`) — any creature-only group, since the
            # replayed set is the one the hit landed on, not a re-run of the filter.
            _is_creature_only_group(last.params.get("group"))
            and "group_and_players" not in last.params and "group_player" not in last.params
        )
    if last.type == "pump":
        selector = last.params.get("selector")
        return _is_group_selector_value(selector) or (
            # PAR-128: "creatures you control get +2/+1 until end of turn.
            # Untap those creatures." (War Flare) — a structured selector
            # (PARSER_VERSION 473) states its whole group, filter included,
            # so replaying it for "those creatures" names the same objects —
            # provided the pump adds no narrowing param of its own.
            isinstance(selector, dict)
            and selector.get("zone", "battlefield") == "battlefield"
            and set(last.params) <= _BARE_PUMP_PARAMS
        )
    if last.type == "grant_until":
        return _is_group_selector_value(
            last.params.get("static", {}).get("params", {}).get("affects")
        )
    return False


#: RULE 702.6: an "Equip …" line that is more than the bare cost — the "Equip abilities you activate" static family, or a sentence
#: after the cost ("Equip {3}. This ability costs {1} less …"). "Equip legendary creature {3}" and "Equip—<cost>" stay bare.
_EQUIP_RIDER_RE = re.compile(r"^equip(?:\s+abilities\b|\b[^.]*\.\s*\S)", re.IGNORECASE)


def is_keyword_line(line: str) -> bool:
    """Whether ``line`` is only keyword abilities, for the gate.

    Two or more keywords can share one line, comma-separated ("Flying,
    vigilance"). A comma-separated continuation only rejoins the token before
    it when that token starts one of the closed `_COMPOUND_PARAM_START_RE`
    keywords *and* doesn't already stand as a keyword token on its own — so
    an unrelated trailing clause ("Flying, then draw a card") still fails
    instead of being swallowed by a keyword's own greedy `.*$` match.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if _is_compound_keyword_line(stripped):
        return True
    raw_tokens = [t.strip() for t in stripped.split(",") if t.strip()]
    if not raw_tokens:
        return False
    tokens: list[str] = []
    for tok in raw_tokens:
        if tokens and not _is_keyword_token(tok) and _COMPOUND_PARAM_START_RE.match(tokens[-1]):
            tokens[-1] = f"{tokens[-1]}, {tok}"
        else:
            tokens.append(tok)
    return all(_is_keyword_token(t) for t in tokens)


# --- PAR-28: "Keyword — [ability]" labelled abilities -----------------------
# RULE 702.142 Boast / 702.177 Exhaust / 702.57 Forecast / Power-up (Marvel) /
# 702.169 Solved / 702.178 Max Speed. Each is a real activated / triggered /
# static ability behind an em-dash label, with the keyword adding a fixed
# restriction to it (a timing/legality gate, a once-per-game cap, a
# solved/speed condition). The label is stripped, the body is parsed by the
# ordinary `segment_line` machinery, and the restriction is applied to the
# resulting spec — never claiming the body alone (which would model a
# working but unrestricted ability).
_KEYWORD_LABELED_ABILITY_RE = re.compile(
    r"^(?P<kw>boast|exhaust|power-up|forecast|solved|max speed)\s*[—-]\s*(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)
#: RULE 702.57b: revealing the card from hand is bookkeeping, not a cost
#: component — peeled off Forecast's cost text before the colon.
_FORECAST_REVEAL_RE = re.compile(
    r",?\s*reveal\s+.+?\s+from your hand\s*:", re.IGNORECASE | re.DOTALL
)


def _apply_keyword_restriction(spec: AbilitySpec, kw: str) -> bool:
    """Fold ``kw``'s fixed rules-restriction onto an already-parsed ability
    ``spec`` (RULE 702.142a/702.177a/702.57a/702.169b-d/702.178a). Returns
    ``False`` if the spec's shape can't carry the restriction (fail-closed)."""
    if kw == "boast":  # RULE 702.142a
        if spec.ability_kind != "activated":
            return False
        spec.effects.append(
            EffectSpec(ACTIVATION_CONDITION_MARKER,
                       {"condition": {"kind": "source_attacked_this_turn"}})
        )
        spec.effects.append(EffectSpec(ONCE_PER_TURN_MARKER, {}))
        return True
    if kw in ("exhaust", "power-up"):  # RULE 702.177a / Power-up
        if spec.ability_kind != "activated":
            return False
        spec.effects.append(EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {}))
        if kw == "power-up":
            spec.effects.append(EffectSpec(POWERUP_COST_REDUCTION_MARKER, {}))
        return True
    if kw == "forecast":  # RULE 702.57
        if spec.ability_kind != "activated":
            return False
        spec.effects.append(EffectSpec(FROM_HAND_MARKER, {}))
        spec.effects.append(
            EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": {"kind": "your_upkeep"}})
        )
        spec.effects.append(EffectSpec(ONCE_PER_TURN_MARKER, {}))
        return True
    # RULE 702.169b-d Solved / 702.178a Max Speed — the same condition on
    # whichever of the three ability shapes the body turned out to be.
    cond = {"kind": "source_solved"} if kw == "solved" else {"kind": "your_speed_is_max"}
    # A replacement is gated the same way (``binding.core.build_replacements`` reads ``active_if`` off each effect):
    # "Solved — If one or more tokens would be created under your control, …" (Case of the Pilfered Proof).
    if spec.ability_kind in ("static", "replacement"):
        for eff in spec.effects:
            eff.params.setdefault("active_if", cond)
        return True
    if spec.ability_kind == "triggered":
        spec.trigger = {**(spec.trigger or {}), "active_if": cond}
        return True
    spec.effects.append(EffectSpec(ACTIVATION_CONDITION_MARKER, {"condition": cond}))
    return True


#: RULE 719.3a: "To solve — [Condition]" means "At the beginning of your end
#: step, if [condition] and this Case is not solved, this Case becomes
#: solved." Modeled as an ordinary phase-triggered ability with the
#: condition as an intervening-if. Only the ``[condition]`` phrasings that
#: map onto the whitelisted `game/static_conditions.py` vocabulary are
#: claimed (fail-closed for the rest — a Case whose solve condition needs an
#: unbuilt per-turn tracker stays UNMODELED, exactly like a battle whose
#: body grammar isn't covered yet).
_TO_SOLVE_RE = re.compile(r"^to solve\s*[—-]\s*(?P<cond>.+?)\.?$", re.IGNORECASE | re.DOTALL)
_TO_SOLVE_CONDITION_RES: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"you'?ve cast (?P<n>\d+) or more instant and sorcery spells this turn", re.I),
     lambda m: {"kind": "control_count",
                "selector": "instant_and_sorcery_spells_cast_this_turn", "min": int(m.group("n"))}),
    (re.compile(r"you have no cards in hand", re.I),
     lambda m: {"kind": "cards_in_hand_at_most", "amount": 0}),
    (re.compile(r"you control (?P<n>\d+) or more (?P<what>artifacts|lands|creatures|"
                r"enchantments|detectives)", re.I),
     lambda m: {"kind": "control_count",
                "selector": f"{m.group('what')}_you_control", "min": int(m.group("n"))}),
    (re.compile(r"there are (?P<n>\d+|fifteen) or more cards in your graveyard", re.I),
     lambda m: {"kind": "control_count", "selector": "cards_in_your_graveyard",
                "min": 15 if m.group("n") == "fifteen" else int(m.group("n"))}),
]


def _to_solve_condition_dict(text: str) -> Optional[dict[str, Any]]:
    stripped = text.strip().rstrip(".").strip()
    for pattern, build in _TO_SOLVE_CONDITION_RES:
        m = pattern.fullmatch(stripped)
        if m is not None:
            return build(m)
    return None


def _segment_to_solve(raw: str, *, provenance: ParserProvenance) -> Optional["Segment"]:
    m = _TO_SOLVE_RE.match(raw)
    if m is None:
        return None
    cond = _to_solve_condition_dict(m.group("cond"))
    if cond is None:
        return Segment(raw=raw)  # fail-closed: unrecognised solve condition
    spec = AbilitySpec(
        "triggered",
        effects=[EffectSpec("become_solved", {})],
        trigger={
            "event": "STEP_BEGIN",
            "filter": {"step": "end"},
            "phase_relation": "you",
            "active_if": cond,
        },
        raw_text=raw,
        parser=provenance,
    )
    return Segment(raw=raw, spec=spec, claimed=True)


def _segment_keyword_labeled_ability(
    raw: str, *, allow_spell_effect: bool, provenance: ParserProvenance, is_saga: bool
) -> Optional["Segment"]:
    to_solve = _segment_to_solve(raw, provenance=provenance)
    if to_solve is not None:
        return to_solve
    m = _KEYWORD_LABELED_ABILITY_RE.match(raw)
    if m is None:
        return None
    kw = m.group("kw").lower()
    body = m.group("body").strip()
    if kw == "forecast":
        body = _FORECAST_REVEAL_RE.sub(":", body, count=1).strip()
    inner = segment_line(
        body, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if inner.claimed and inner.spec is None:
        # The body parsed but yields no effect spec — a mana ability
        # ("Exhaust — {G}, {T}: Add three mana of any one color." — Loot, the
        # Pathfinder, the very card RULE 702.177b's example is about) or an
        # informational-only clause. Claimed, but there's no `ActivatedAbility`
        # to fold the once-per-game cap onto — a mana ability gets its cap from
        # `game/mana_abilities.py`'s own "Exhaust —"/"Power-up —" label
        # handling (`ActivationCost.once_per_game`), which reads the same line.
        return Segment(raw=raw, claimed=True)
    if not inner.claimed or inner.spec is None or not _apply_keyword_restriction(
        inner.spec, kw
    ):
        # Body didn't fully parse, or the spec can't carry the restriction:
        # fail closed. This used to fall back to an inert keyword-line claim
        # (the pre-PAR-28 behaviour of `_KEYWORD_TOKEN_RE`'s greedy `.*$`),
        # which made the card MODELED with the whole labelled ability silently
        # missing — PAR-129, 23 cards across Exhaust/Power-up/Boast/Max speed.
        # UNMODELED is correct and recoverable (the body is an ordinary
        # unclaimed clause the ranking can see); a half-model is not.
        return Segment(raw=raw)
    inner.spec.raw_text = raw
    for extra in inner.extra_specs:
        _apply_keyword_restriction(extra, kw)
        extra.raw_text = raw
    return Segment(raw=raw, spec=inner.spec, extra_specs=inner.extra_specs, claimed=True)


#: A bare pronoun in a trigger body ("return **it**", "exile **that creature**").
_BARE_PRONOUN_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT})\b(?!')")

#: An explicit naming of the ability's own source in a normalised body ("~", or the
#: "this card"/"this spell" phrasings `normalize` leaves alone).
_EXPLICIT_SOURCE_RE = re.compile(r"~|\bthis (?:card|spell|creature|permanent|artifact|enchantment|land)\b")

#: Effect types whose untargeted form ("it") has a ``"trigger_subject"`` mode — the
#: object that fired a group trigger, read off the event at resolution.
_GROUP_IT_RETARGETED: frozenset[str] = frozenset({"tap", "return_to_hand", "exile"})


_IT_DEALS_RE = re.compile(rf"\b(?:it|that {PRONOUN_NOUN_ALT}) deals?\b")


def _deals_damage(effect: "EffectSpec") -> bool:
    """A ``damage`` effect, or a ``bind`` whose body is one."""
    if effect.type == "damage":
        return True
    return effect.type == "bind" and any(
        isinstance(e, dict) and e.get("type") == "damage" for e in effect.params.get("effects", [])
    )


def _reads_blocked_attacker(effect: "EffectSpec") -> bool:
    """Whether ``effect`` carries a "creatures blocking it" group (`blocking_source`), which the
    engine reads off the effect's *source* — the blocked attacker."""
    return '"blocking_source"' in json.dumps(effect.to_dict(), default=str)


def _stamped_dealer(effect: "EffectSpec") -> bool:
    return GROUP_SUBJECT_KEY_SENTINEL in json.dumps(effect.to_dict(), default=str)


def _stamped_dealer_any(effects: "list[EffectSpec]") -> bool:
    """Whether any of ``effects`` reads the group trigger's firing object."""
    return any(_stamped_dealer(e) for e in effects)


def _stamp_damage_dealer(effect: "EffectSpec") -> "EffectSpec":
    """``effect`` with each ``damage`` in it dealt by the group trigger's firing object."""
    if effect.type == "damage":
        return EffectSpec(
            "damage", {**effect.params, "dealer_event_key": GROUP_SUBJECT_KEY_SENTINEL},
            condition=effect.condition,
        )
    inner = [
        {**e, "params": {**e["params"], "dealer_event_key": GROUP_SUBJECT_KEY_SENTINEL}}
        if e.get("type") == "damage" else e
        for e in effect.params["effects"]
    ]
    return EffectSpec("bind", {**effect.params, "effects": inner}, condition=effect.condition)


#: Words that put another card in play for a later "that card" to name ("exile the top card of your
#: library. You may play that card"), so it is *not* the object a trigger fired for.
_CARD_INTRODUCER_RE = re.compile(
    r"\b(?:top card|top \d+ cards|reveal|look at|from among|search your|cards? from|revealed|exile target|"
    r"target [a-z ]*card|the first card)\b"
)

#: A bare "it" (not "it's", not "its").
_BARE_IT_RE = re.compile(r"\bit\b(?!')")

#: A boundary between one clause and the next in a normalised trigger body.
_CLAUSE_BOUNDARY_RE = re.compile(r"[.;,]| then | and ")


def _pronoun_continues_source(lowered: str) -> bool:
    """Whether a bare pronoun in ``lowered`` sits in a later clause than an explicit "~" and so
    most likely continues it ("put a +1/+1 counter on ~. **it** gains haste"), rather than
    naming the firing object. A pronoun in the *same* clause as the "~" is that clause's other
    participant ("attach ~ to **it**", "~ deals 2 damage to **that creature**")."""
    for source in _EXPLICIT_SOURCE_RE.finditer(lowered):
        for pronoun in _BARE_PRONOUN_RE.finditer(lowered, source.end()):
            if _CLAUSE_BOUNDARY_RE.search(lowered, source.end(), pronoun.start()) is not None:
                return True
    return False


def _is_bare_referent_seed(node: Any) -> bool:
    """A `trigger_subject_referent` that only seeds the referent (no body to run, no acting player)."""
    if isinstance(node, EffectSpec):
        return (
            node.type == "trigger_subject_referent" and not node.params.get("effects")
            and node.params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL
        )
    if not isinstance(node, dict) or node.get("type") != "trigger_subject_referent":
        return False
    params = node.get("params") or {}
    return not params.get("effects") and params.get("event_key") == GROUP_SUBJECT_KEY_SENTINEL


def _strip_bare_seeds(node: Any) -> Any:
    if isinstance(node, list):
        return [_strip_bare_seeds(item) for item in node if not _is_bare_referent_seed(item)]
    if isinstance(node, dict):
        return {key: _strip_bare_seeds(value) for key, value in node.items()}
    return node


def _hoist_referent_seed(effects: "list[EffectSpec]") -> "list[EffectSpec]":
    """PAR-123: one seed of the group trigger's referent, first in the list.

    A clause read through a previous-subject row brings its own seed, but a gate on it ("if it
    has flying, …") is evaluated *before* the gated effect runs, so a seed nested inside would come
    too late for the condition that names the referent. The seeds are lifted out and one is put at
    the front, where every clause and every gate after it can read it. A gate that names the
    referent with nothing chosen anywhere in the body ("if it's a creature, tap it") needs it too."""
    dumped = [e.to_dict() for e in effects]
    text = json.dumps(dumped, default=str)
    chosen_something = re.search(r'"target_kind": "(?!trigger_subject|source")', text) is not None
    if not any(_has_bare_seed_deep(d) for d in dumped) and not (
        '"of": "previous_target"' in text and not chosen_something
    ):
        return effects
    kept: list[EffectSpec] = []
    for data in dumped:
        if _is_bare_referent_seed(data):
            continue
        data = _strip_bare_seeds(data)
        kept.append(EffectSpec(data["type"], data.get("params") or {}, condition=data.get("condition")))
    return [EffectSpec("trigger_subject_referent", {"event_key": GROUP_SUBJECT_KEY_SENTINEL}), *kept]


def _has_bare_seed_deep(node: Any) -> bool:
    if _is_bare_referent_seed(node):
        return True
    if isinstance(node, list):
        return any(_has_bare_seed_deep(item) for item in node)
    if isinstance(node, dict):
        return any(_has_bare_seed_deep(value) for value in node.values())
    return False


#: Player-event heads whose body speaks of "that attacking player" / "that player" / "they" (RULE 506.4).
_ATTACKING_PLAYER_EVENTS = frozenset({"PLAYER_ATTACKED", "ATTACKERS_DECLARED"})
#: "that attacking player [may] <verb>" / "they <verb>" — the acting player named by the event.
_ATTACKING_PLAYER_SUBJECT_RE = re.compile(r"\b(?:that (?:attacking )?player|they)\b(?!')")
#: The effect types that read "you" through `GameContext.acting_player_id` *and* keep it across a pause
#: ("you may …", "if you do …"); anything else would quietly act for the ability's controller.
_ACTING_EVENT_PLAYER_TYPES = frozenset({
    "draw", "create_token", "pay_cost_then", "optional", "lose_life", "gain_life", "discard",
})


def _effect_types(node: Any) -> set[str]:
    """Every effect ``type`` named anywhere inside a spec dict (nested bodies included)."""
    found: set[str] = set()
    if isinstance(node, dict):
        if isinstance(node.get("type"), str) and "params" in node:
            found.add(node["type"])
        for value in node.values():
            found |= _effect_types(value)
    elif isinstance(node, list):
        for value in node:
            found |= _effect_types(value)
    return found


#: "…creates a tapped `<token>` that's attacking that opponent" — the token joins the combat attacking the
#: defender the `PLAYER_ATTACKED` event names (RULE 508.4; `attacker_creates_attacking_token`).
_ATTACKING_THAT_OPPONENT_RE = re.compile(
    r"^that (?:attacking )?player creates an? tapped (?P<token>.+?) that's attacking that opponent$"
)
#: The `create_token` params `attacker_creates_attacking_token` carries over.
_ATTACKING_TOKEN_PARAMS = ("power", "toughness", "colors", "subtypes", "keywords", "token_name")


def _attacking_token_body(body: str) -> Optional[list[EffectSpec]]:
    """Combat Calligrapher's / Ellie, Brick Master's "that attacking player creates a tapped `<token>`
    that's attacking that opponent": the token read by the ordinary create-token grammar, then handed to
    the attacker (not this ability's controller) already attacking the defender."""
    m = _ATTACKING_THAT_OPPONENT_RE.fullmatch(body.strip().lower().rstrip("."))
    if m is None:
        return None
    token_text, _, name = m.group("token").partition(" named ")
    effects = parse_effect_body(f"create a {token_text}", reading=ClauseReading(self_subject=True))
    if not effects or len(effects) != 1 or effects[0].type != "create_token":
        return None
    params = dict(effects[0].params)
    if name:
        params["token_name"] = name.title()
    if params.get("count", 1) != 1 or any(k not in (*_ATTACKING_TOKEN_PARAMS, "count", "tapped") for k in params):
        return None
    return [EffectSpec("attacker_creates_attacking_token", {
        k: params[k] for k in _ATTACKING_TOKEN_PARAMS if k in params
    })]


#: RULE 603.4: "When ~ enters, if `<condition>`, `<effect>`" — the condition is checked when the trigger event occurs
#: (the ability does not trigger at all otherwise: no stack object, no target to choose) and again as it resolves.
#: The per-effect gate every body keeps is the resolution check; this is the trigger-time one (`trigger["active_if"]`).
#: These leading-if conditions are also checked at the trigger event (RULE 603.4);
#: the effect retains its resolution-time check. Extend only with verified live predicates.
_INTERVENING_IF_AT_TRIGGER_KINDS = frozenset({"mana_color_spent_to_cast_at_least", "card_types_in_graveyard_at_least"})
_ETB_INTERVENING_IF_RE = re.compile(r"^if (?P<cond>[^,]{2,160}),\s+.+$", re.IGNORECASE | re.S)


def _etb_intervening_if(event: Any, condition: Optional[dict[str, Any]], body: str) -> Optional[dict[str, Any]]:
    if event != "ENTERS_BATTLEFIELD" or (condition or {}).get("subject") != "self":
        return None
    lead = _ETB_INTERVENING_IF_RE.match(body.strip())
    gated = static_condition(lead.group("cond")) if lead is not None else None
    return gated if gated is not None and gated.get("kind") in _INTERVENING_IF_AT_TRIGGER_KINDS else None


def _event_player_body(body: str) -> Optional[list[EffectSpec]]:
    """"Whenever a player attacks …, **that attacking player** creates a Treasure token" — the body as
    that player's own second-person clause, run *as* them (`trigger_subject_referent` ``acting``
    ``"event_player"``, RULE 109.5). Refused when the body also names "you"/a target, or when an effect
    in it does not honour the acting player."""
    attacking_token = _attacking_token_body(body)
    if attacking_token is not None:
        return attacking_token
    text = body.lower()
    if re.search(r"\b(?:you|your|target|opponent)\b", text) or _ATTACKING_PLAYER_SUBJECT_RE.search(text) is None:
        return None
    text = re.sub(r"\bif (?:the player|they) does?\b", "if you do", text)
    text = re.sub(
        r"\bthat (?:attacking )?player (may )?([a-z]+)\b",
        lambda m: f"you {m.group(1) or ''}{m.group(2) if m.group(1) else base_verb(m.group(2))}", text,
    )
    text = re.sub(r"\bthey\b", "you", text)
    if _ATTACKING_PLAYER_SUBJECT_RE.search(text) or "their" in text:
        return None
    effects = parse_effect_body(text, reading=ClauseReading(self_subject=True))
    if not effects or not all(_effect_types(e.to_dict()) <= _ACTING_EVENT_PLAYER_TYPES for e in effects):
        return None
    return [EffectSpec("trigger_subject_referent", {
        "acting": "event_player", "effects": [e.to_dict() for e in effects],
    })]


#: PAR-164: under a player-recipient DAMAGE head ("whenever an opponent is dealt 3 or more damage by a single
#: source, **that player** discards a card"), "that player" is the player who was dealt the damage (RULE 120.3),
#: not the controller of the damage source that the group-subject dispatch reads it as ("its controller", the same
#: printed pronoun family). The group dispatch's player operand is swapped for the `damaged_player` referent.
_GROUP_SUBJECT_CONTROLLER_OPERAND = {"of": "entering", "as": "controller"}
_DAMAGED_PLAYER_OPERAND = {"of": "damaged_player"}
_THAT_PLAYER_BODY_RE = re.compile(r"^that player\b", re.IGNORECASE)


def _swap_operand(value: Any) -> Any:
    if value == _GROUP_SUBJECT_CONTROLLER_OPERAND:
        return dict(_DAMAGED_PLAYER_OPERAND)
    if isinstance(value, dict):
        return {k: _swap_operand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap_operand(v) for v in value]
    return value


def _retarget_that_player_to_damaged(effects: list[EffectSpec]) -> Optional[list[EffectSpec]]:
    """``effects`` with the group dispatch's controller operand read as the damaged player; ``None`` when a shape
    keyed to the source's controller by another route (a selector name) is present, so it fails closed."""
    if "trigger_subject_controller" in repr(effects):
        return None
    return [EffectSpec(e.type, _swap_operand(e.params), condition=e.condition) for e in effects]


def _stamp_group_pronoun(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> "Optional[list[EffectSpec]]":
    stamped = _stamp_group_pronoun_once(condition, body, effects)
    if stamped is not None and (condition or {}).get("subject") in ("group", "self_or_group"):
        stamped = _hoist_referent_seed(stamped)
    return stamped


def _stamp_group_pronoun_once(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> "Optional[list[EffectSpec]]":
    """PAR-123: under a group-subject trigger a bare "it"/"that creature" is the
    object that fired the trigger, whereas "~" is the source. Both parse to the
    same untargeted spec (``target_kind: None``, which acts on the source), so the
    parser — the only place the words are visible — stamps the pronoun reading
    onto each effect that has a trigger-subject mode; the binder resolves which
    event field names the object (`GROUP_SUBJECT_KEY_SENTINEL`).

    A body that also names the source explicitly is left as parsed ("exile ~, then
    return it" is the source both times). ``None`` means the body is a pronoun
    reading no effect here can honour, so the line stays unclaimed."""
    subject = (condition or {}).get("subject")
    if subject not in (None, "self", "group", "self_or_group") and any(_reads_blocked_attacker(e) for e in effects):
        return None  # "equipped creature becomes blocked, it deals …": "it" isn't the source
    if subject not in ("group", "self_or_group"):
        return effects
    lowered = body.lower()
    if _stamped_dealer_any(effects) and _pronoun_continues_source(lowered):
        return None  # "put a counter on ~. it gains haste": that "it" is the source, not the firing object
    if _BARE_PRONOUN_RE.search(lowered) is None or _EXPLICIT_SOURCE_RE.search(lowered):
        return effects
    stamped: list[EffectSpec] = []
    index = 0
    while index < len(effects):
        effect = effects[index]
        following = effects[index + 1] if index + 1 < len(effects) else None
        if (effect.type == "exile" and effect.params.get("target_kind", "unset") is None
                and following is not None and following.type == "return_self_to_battlefield"):
            # "exile it, then return it to the battlefield under its owner's control"
            if following.params != {"tapped": False}:
                return None
            stamped.append(EffectSpec(
                "blink", {"target_kind": "trigger_subject",
                          "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            ))
            index += 2
            continue
        if _IT_DEALS_RE.search(lowered) and _deals_damage(effect):
            # "Whenever a Dragon you control enters, it deals X damage to any target" — the
            # entering Dragon is the damage source (lifelink, deathtouch, protection), not the
            # Enchantment that carries the ability (PAR-123).
            effect = _stamp_damage_dealer(effect)
        elif effect.type == "sacrifice_self" and not effect.params:
            # "Whenever another Goblin you control becomes blocked, sacrifice it." — the firing
            # creature, not the permanent carrying the ability.
            effect = EffectSpec(
                "sacrifice_self",
                {"target_kind": "trigger_subject", "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            )
        elif effect.type == "return_self_to_battlefield" and "target_kind" not in effect.params:
            # "Whenever a creature you control dies, return it to the battlefield under its
            # owner's control" — the dead creature, not the permanent carrying the ability.
            effect = EffectSpec(
                "return_self_to_battlefield",
                {**effect.params, "target_kind": "trigger_subject",
                 "trigger_event_key": GROUP_SUBJECT_KEY_SENTINEL},
                condition=effect.condition,
            )
        elif effect.type in _GROUP_IT_RETARGETED and effect.params.get("target_kind", "unset") is None:
            params = dict(effect.params)
            params["target_kind"] = "trigger_subject"
            params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
            effect = EffectSpec(effect.type, params, condition=effect.condition)
        elif effect.type == "create_delayed_trigger" and effect.params.get("capture") == "previous_or_self":
            # "Whenever a Minotaur attacks this turn, it gets +2/+0 … Destroy that creature at
            # end of combat." (Consuming Rage) — the delayed clause's own "that creature" parsed
            # to the default ``previous_or_self`` fallback (PAR-30), which has nothing to fall
            # back *to* here (this resolution's earlier effect is itself untargeted) and would
            # silently capture this ability's own source instead. Under a confirmed group
            # subject a bare pronoun is always RULE 603.1's firing object, never that fallback
            # chain — an explicit "~" would have failed the ``_EXPLICIT_SOURCE_RE`` guard above
            # before reaching here, so this can only be the pronoun.
            params = dict(effect.params)
            params["capture"] = "trigger_subject"
            params["trigger_event_key"] = GROUP_SUBJECT_KEY_SENTINEL
            effect = EffectSpec(effect.type, params, condition=effect.condition)
        if _reads_blocked_attacker(effect) and not _stamped_dealer(effect):
            return None  # the blocked attacker is the firing object; nothing here names it
        stamped.append(effect)
        index += 1
    return stamped


#: Effect params that read a number or object off the firing event. An `ATTACKERS_DECLARED`
#: event names the whole declaration, not "that many"/"that creature": the count a body means
#: depends on the head's own filter, which the shared event cannot carry.
_EVENT_READS = (
    "amount_from_trigger_event", "count_from_trigger_event", "pt_from_trigger_event", "any_amount_from_trigger_event",
)


def _retarget_block_relation(
    event: "str | list[str]", head_trigger: dict[str, Any], effects: "list[EffectSpec]"
) -> "list[EffectSpec]":
    """Under a block-relation head ("~ blocks or becomes blocked by a non-Wall creature")
    "that creature" is the creature on the other side of the block. A delayed effect built
    from it captured the source when nothing preceded it; it now captures the event's
    related creatures, filtered as the head is."""
    events = event if isinstance(event, list) else [event]
    if not events or not set(events) <= {"BLOCKS", "BECOMES_BLOCKED"}:
        return effects
    out: "list[EffectSpec]" = []
    for e in effects:
        if e.params.get("trigger_related") and "related_filter" not in e.params:
            e = EffectSpec(
                e.type, {**e.params, "related_filter": dict(head_trigger.get("related_filter") or {})},
                condition=e.condition,
            )
        if e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self":
            params = dict(e.params)
            params["capture"] = "trigger_related"
            params["related_filter"] = dict(head_trigger.get("related_filter") or {})
            e = EffectSpec(e.type, params, condition=e.condition)
        out.append(e)
    return out


#: What "that many" measures for a counting head: the attack batch (RULE 508.3a, captured
#: by `trigger_quantities.capture_attackers`) or an object batch (RULE 603.2c, captured by
#: `binding.core`'s batch capture as the event's ``matching_count``).
_ATTACK_COUNT_AMOUNT: dict[str, Any] = {"kind": "attackers_declared"}
_BATCH_COUNT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "matching_count"}
#: "that much"/"that many" after a damage head is the damage that event dealt (its ``amount``).
_DAMAGE_EVENT_AMOUNT: dict[str, Any] = {"kind": "trigger_event", "field": "amount"}
_HEAD_COUNT_AMOUNTS: dict[str, dict[str, Any]] = {
    "ATTACKERS_DECLARED": _ATTACK_COUNT_AMOUNT, "EVENT_BATCH": _BATCH_COUNT_AMOUNT,
    "DAMAGE": _DAMAGE_EVENT_AMOUNT,
}
_THAT_MANY_RE = re.compile(r"\bthat (?:many|much)\b", re.IGNORECASE)


def _reads_event_amount(effects: "list[EffectSpec]") -> bool:
    """Whether any effect (nested compositions included) reads a number off the firing event (`_EVENT_READS`)."""
    return any(key in repr(effect.to_dict()) for effect in effects for key in _EVENT_READS)


def _bind_attack_count(
    effects: "list[EffectSpec]", amount: Optional[dict[str, Any]] = None,
) -> "Optional[list[EffectSpec]]":
    """Bind 'that many/much' to this head's own count (RULE 508.3a / 603.2c).

    Walk compositions too: an optional/conditional draw has the same referent.
    Other event fields and an unresolved 'that creature' still fail closed.
    """
    # An adjacent library choice supplies 'that creature'; run the delayed
    # instruction only for the selected hit, including after an interactive pause.
    linked = []
    for effect in effects:
        if (effect.type == "create_delayed_trigger"
                and effect.params.get("capture") == "previous_or_self"
                and linked and linked[-1].type == "impulsive_look"
                and linked[-1].params.get("hit_destination", "").startswith("battlefield")
                and effect.condition is None):
            look = linked.pop()
            delayed = EffectSpec(effect.type, {**effect.params, "capture": "created_objects"})
            linked.append(EffectSpec(look.type, {
                **look.params,
                "hit_effect_specs": [*look.params.get("hit_effect_specs", []), delayed.to_dict()],
            }, condition=look.condition))
        else:
            linked.append(effect)
    effects = linked
    reads_count = False

    def rewrite(value):
        nonlocal reads_count
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("type") == "create_delayed_trigger" and (
            value.get("params", {}).get("capture") == "previous_or_self"
        ):
            raise ValueError("No creature referent in an attack count")
        result = {}
        for key, item in value.items():
            if key in _EVENT_READS:
                if item not in ("amount", "that_much") or key == "pt_from_trigger_event":
                    raise ValueError("Not an attacker count")
                reads_count = True
                result[key.removesuffix("_from_trigger_event")] = "$attack_count"
            else:
                result[key] = rewrite(item)
        return result

    try:
        rewritten = rewrite([effect.to_dict() for effect in effects])
    except ValueError:
        return None
    if not reads_count:
        return effects
    return [EffectSpec("bind", {"name": "attack_count",
                               "amount": dict(amount or _ATTACK_COUNT_AMOUNT),
                               "effects": rewritten})]


def _group_it_would_hit_source(
    condition: Optional[dict[str, Any]], body: str, effects: "list[EffectSpec]"
) -> bool:
    """Whether a group-subject trigger body's bare "it" would still resolve to the
    wrong permanent after `_stamp_group_pronoun`. With a group subject "it" is the
    object that fired the trigger, but an effect parsed with no target
    (``target_kind: None``), or a delayed capture that falls back to the source,
    acts on *this ability's own source* — wrong, yet claimed."""
    if (condition or {}).get("subject") not in ("group", "self_or_group"):
        return False
    if _BARE_PRONOUN_RE.search(body.lower()) is None:
        return False
    return any(
        (
            e.params.get("target_kind", "unset") is None
            # PAR-124: `copy_permanent`'s own ``referent="trigger_event"``
            # (Theoretical Duplication's "create a token that's a copy of
            # **that creature**.") already reads the *firing object*, not
            # the source, via `_COPY_PERMANENT_GROUP_RE`'s own group-
            # subject-gated row — a correct resolution this guard would
            # otherwise reject on the same ``target_kind: None`` shape a
            # plain (wrongly source-falling-back) reading uses.
            and not (e.type == "copy_permanent" and e.params.get("referent") == "trigger_event")
        )
        or (e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self")
        for e in effects
    )


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


def _compound_candidates(line: str) -> "list[tuple[str, str]]":
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
_TURN_TRIGGER_RE = re.compile(
    r"^(?:until end of turn,\s*(?P<kw1>whenever|when)\s+(?P<cond1>[^,]+?)"
    r"|(?P<kw2>whenever|when)\s+(?P<cond2>[^,]+?)\s+this turn),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: "when you next cast an instant or sorcery spell this turn" — the one-shot variant.
_NEXT_CAST_RE = re.compile(r"\byou next cast\b")


#: PAR-124: "When **target creature** dies this turn, return that card to
#: the battlefield under its owner's control." (Graceful Reprieve) — the
#: chosen RULE 115 target, not a group condition, is the trigger's own
#: subject: `_turn_trigger_segment` rewrites this to the ordinary
#: self-subject phrasing ("~ `<verb>`") before the inner `segment_line`
#: call, and stamps `target_kind="creature"` on the outer `create_turn_
#: trigger` spec so `CreateTurnTriggerEffect` binds the ability with the
#: chosen object itself as its source (see that class's own docstring).
_TARGET_CREATURE_SUBJECT_RE = re.compile(r"^target creature (?P<verb>.+)$", re.IGNORECASE)

#: PAR-102: "Target creature gets +2/+0 until end of turn. When **that creature** dies this turn, …" — the
#: subject is the creature the *preceding clause* chose, so it is only read as such when the caller says
#: a previous clause did (`previous_subject`); otherwise "that creature" names nothing and stays unclaimed.
#: PAR-160: "the creature" is the same referent when worded that way (Phantasmal Mount's second rider).
_THAT_CREATURE_SUBJECT_RE = re.compile(
    r"^(?:that creature|the creature|it) (?P<verb>(?:dies|leaves the battlefield))$", re.IGNORECASE,
)
#: PAR-160: "When **~** leaves the battlefield this turn, sacrifice **that creature**." — the trigger is the
#: source's own and the body names the creature an earlier clause chose (`previous_subject`), baked in at creation.
_SOURCE_LEAVES_RE = re.compile(r"^~ (?:dies|leaves the battlefield)$", re.IGNORECASE)


def _turn_trigger_segment(
    line: str, *, provenance: ParserProvenance, reading: ClauseReading = STANDALONE,
) -> "Optional[Segment]":
    """A spell line that creates a turn-long trigger → its `create_turn_trigger` segment;
    an unclaimed `Segment` when the trigger inside is not one the grammar reads; ``None``
    when the line is not this shape at all."""
    m = _TURN_TRIGGER_RE.match(line.strip())
    if m is None:
        return None
    keyword = (m.group("kw1") or m.group("kw2")).lower()
    condition = m.group("cond1") or m.group("cond2")
    once = _NEXT_CAST_RE.search(condition.lower()) is not None
    if once:
        condition = _NEXT_CAST_RE.sub("you cast", condition.lower())
    target_creature = _TARGET_CREATURE_SUBJECT_RE.match(condition.strip())
    target_kind = None
    if target_creature is not None:
        target_kind = "creature"
        condition = f"~ {target_creature.group('verb')}"
    that_creature = _THAT_CREATURE_SUBJECT_RE.match(condition.strip())
    if that_creature is not None:
        if not reading.previous_subject:
            return Segment(raw=line.strip())
        condition = f"~ {that_creature.group('verb')}"
    unclaimed = Segment(raw=line.strip())
    if (
        _SOURCE_LEAVES_RE.match(condition.strip()) and reading.previous_subject and target_kind is None
        and m.group("body").strip().lower() == "sacrifice that creature"
    ):
        # The shell supplies the trigger dict; the body is the baked `sacrifice_specific` (no re-parse of "that creature").
        shell = segment_line(
            f"{keyword} {condition}, draw a card.", allow_spell_effect=False, provenance=provenance,
        )
        if not shell.claimed or shell.spec is None or isinstance(shell.spec.trigger.get("event"), list):
            return unclaimed
        return Segment(
            raw=line.strip(),
            spec=AbilitySpec(
                "spell_effect",
                effects=[EffectSpec("create_turn_trigger", {
                    "trigger": shell.spec.trigger,
                    "effects": [{"type": "sacrifice_specific", "params": {}}],
                    "optional": False,
                    "bake_previous_objects": True,
                    "description": line.strip(),
                })],
                raw_text=line.strip(), parser=provenance,
            ),
            claimed=True,
        )
    inner = segment_line(
        f"{keyword} {condition}, {m.group('body')}",
        allow_spell_effect=False, provenance=provenance,
    )
    pinned = target_kind is not None or that_creature is not None
    if pinned and (not inner.claimed or inner.spec is None) and condition == "~ dies":
        # The body names the dying creature's controller/owner ("its controller gets a poison counter"): a self
        # subject can't say that, but the same body under a group head can — its effects carry the group-subject
        # referent, which the binder resolves for a chosen-object trigger too. The trigger shell stays the self one.
        group = segment_line(
            f"{keyword} a creature dies, {m.group('body')}",
            allow_spell_effect=False, provenance=provenance,
        )
        shell = segment_line(f"{keyword} {condition}, draw a card.", allow_spell_effect=False, provenance=provenance)
        if group.claimed and group.spec is not None and shell.claimed and shell.spec is not None:
            group.spec.trigger = shell.spec.trigger
            inner = group
    if not inner.claimed or inner.spec is None or inner.extra_specs:
        return unclaimed
    spec = inner.spec
    if spec.ability_kind != "triggered" or not spec.effects or isinstance(spec.trigger.get("event"), list):
        return unclaimed
    effect_dicts = [e.to_dict() for e in spec.effects]
    if pinned:
        # "…, return **it** to the battlefield": the pinned trigger is bound to the spell/ability, so a bare "it" must
        # name the creature that died (the trigger's subject), not the source — as "return that card" already does.
        for effect in effect_dicts:
            if effect.get("type") == "return_self_to_battlefield" and "target_kind" not in effect["params"]:
                effect["params"] = {**effect["params"], "target_kind": "trigger_subject"}
    return Segment(
        raw=line.strip(),
        spec=AbilitySpec(
            "spell_effect",
            effects=[EffectSpec("create_turn_trigger", {
                "trigger": spec.trigger,
                "effects": effect_dicts,
                "optional": bool(spec.optional),
                **({"once": True} if once else {}),
                **({"target_kind": target_kind} if target_kind else {}),
                **({"previous_subject": True} if that_creature is not None else {}),
                "description": line.strip(),
            })],
            raw_text=line.strip(), parser=provenance,
        ),
        claimed=True,
    )


def _stamp_group_pronoun_segment(segment: "Segment") -> "Segment":
    """`_stamp_group_pronoun` over a finished triggered segment — every dispatch that
    builds a group-subject trigger (damage, batch, object-head, …) is covered here
    instead of at each of its call sites."""
    if not segment.claimed or segment.spec is None:
        return segment
    trigger_line = TRIGGER_RE.match(segment.raw.strip().lower())
    for spec in [segment.spec, *segment.extra_specs]:
        if spec.ability_kind != "triggered" or trigger_line is None:
            continue
        stamped = _stamp_group_pronoun(
            (spec.trigger or {}).get("condition"), trigger_line.group("body"), spec.effects
        )
        if stamped is None:
            return Segment(raw=segment.raw)
        spec.effects = stamped
    return segment


#: "Whenever ~ attacks **while `<state>`**, `<effect>`" — the state is a condition on the
#: ability (RULE 603.4's intervening if), so it is read as "…attacks, **if `<state>`**, …"
#: through the condition grammar every leading "if" already uses.
_WHILE_TAIL_RE = re.compile(
    r"^(?P<kw>when|whenever) (?P<head>[^,]+?) while (?P<state>[^,]+),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def _while_condition_segment(
    line: str, *, allow_spell_effect: bool, provenance: ParserProvenance, is_saga: bool
) -> "Optional[Segment]":
    """A trigger with a "while `<state>`" tail → the segment of the "if `<state>`" reading,
    ``"while saddled"`` → the source's own ``requires_saddled`` gate; ``None`` when the line
    has no such tail."""
    m = _WHILE_TAIL_RE.match(line.strip())
    if m is None:
        return None
    saddled = m.group("state").strip() == "saddled"
    rewritten = (
        f"{m.group('kw')} {m.group('head')}, {m.group('body')}" if saddled
        else f"{m.group('kw')} {m.group('head')}, if {m.group('state')}, {m.group('body')}"
    )
    inner = segment_line(
        rewritten, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if not saddled or not inner.claimed or inner.spec is None:
        return inner
    # `requires_saddled` reads the *source's* stamp, so it is only right for a self subject.
    if inner.extra_specs or (inner.spec.trigger or {}).get("condition", {}).get("subject") != "self":
        return Segment(raw=line.strip())
    inner.spec.trigger = {**inner.spec.trigger, "requires_saddled": True}
    return inner


#: "if `<state>`, `<effect>`" at the head of a phase trigger's body — the state is read by
#: `static_condition`, so anything that vocabulary says is an intervening if.
_PHASE_INTERVENING_IF_RE = re.compile(r"^if (?P<cond>[^,]+), (?P<rest>.+)$", re.IGNORECASE | re.S)
#: A second sentence after the first one — what makes a leading phase-trigger "if"
#: an ability-wide gate rather than one effect's (see its use in `segment_line`).
_NEXT_SENTENCE_RE = re.compile(r"\.\s+\S")


#: "Flashback {8}{G}{G}. This spell costs {X} less to cast this way, where X is …" (the Visions flashback cycle): a
#: keyword line carrying a sentence about its own cost, read as the keyword plus a graveyard-gated cost reduction.
FLASHBACK_DISCOUNT_LINE_RE = re.compile(
    r"(?P<keyword>flashback (?:\{[^{}]+\})+)\.\s+(?P<discount>this spell costs \{x\} less to cast this way, where x is .+)",
    re.IGNORECASE,
)


def segment_line(
    line: str,
    *,
    allow_spell_effect: bool,
    provenance: ParserProvenance,
    is_saga: bool = False,
) -> Segment:
    """Parse one normalised ability ``line`` into a `Segment` — whole first,
    then, if unclaimed, as two independent triggers sharing one body."""
    if allow_spell_effect:
        turn_trigger = _turn_trigger_segment(line, provenance=provenance)
        if turn_trigger is not None:
            return turn_trigger
    while_reading = _while_condition_segment(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if while_reading is not None and while_reading.claimed:
        return while_reading
    whole = _stamp_group_pronoun_segment(_segment_line_unsplit(
        line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    ))
    if whole.claimed:
        return whole
    for first, second in _compound_candidates(line):
        halves = [
            segment_line(
                half, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
            )
            for half in (first, second)
        ]
        if any(h.spec is None or not h.claimed for h in halves):
            continue
        specs = [h.spec for h in halves] + [x for h in halves for x in h.extra_specs]
        return Segment(raw=line.strip(), spec=specs[0], extra_specs=specs[1:], claimed=True)
    return whole


@dataclass(frozen=True)
class LineContext:
    """What every `LINE_MATCHERS` row sees: the stripped line plus the three gates `segment_line` was given."""

    raw: str
    line: str
    allow_spell_effect: bool
    provenance: ParserProvenance
    is_saga: bool


@dataclass(frozen=True)
class LineMatcher:
    """One ordered row of `LINE_MATCHERS`: a named matcher returning a `Segment` to claim (or refuse) the line, or
    ``None`` to fall through to the next row. ORDER IS SEMANTICS: the first row to return a `Segment` wins, and a row
    that returns an unclaimed `Segment` ends the search (it recognised the shape but could not model it)."""

    name: str
    match: Callable[[LineContext], Optional[Segment]]


def _line_neither_day_nor_night(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if re.fullmatch(
        r"if it'?s neither day nor night, it becomes day as (?:~|this (?:creature|artifact|enchantment)|[a-z][a-z' -]+) enters\.?",
        raw,
        re.I,
    ):
        return Segment(
            raw=raw,
            spec=AbilitySpec(
                "enter_replacement", [EffectSpec("establish_day_on_entry", {})],
                raw_text=raw, parser=provenance,
            ),
            claimed=True,
        )
    return None


# PAR-28: "Boast/Exhaust/Forecast/Power-up/Solved/Max speed — [ability]".
# Checked *before* `is_keyword_line`, since `_KEYWORD_TOKEN_RE`'s greedy
# `.*$` would otherwise claim the whole "<keyword> — <cost>: <effect>"
# line as a bare keyword line (producing no ability at all).
def _line_kw_labeled(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    kw_labeled = _segment_keyword_labeled_ability(
        raw, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if kw_labeled is not None:
        return kw_labeled
    return None


# BUG-1: "Equip—<non-mana cost>[. Activate only once each turn.]" is a keyword line only when the cost grammar fully represents
# the cost (RULE 602.1, `costs.parse_activation_cost`); a choice cost ("Pay {3} or discard a card") stays unclaimed, never free.
def _line_equip_dash(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    equip_dash = EQUIP_DASH_COST_RE.fullmatch(raw.strip())
    if equip_dash is not None:
        if scan_cost_text(equip_dash.group("cost").strip()).leftover is None:
            return Segment(raw=raw, claimed=True, keyword_line=True)
        return Segment(raw=raw, claimed=False)
    return None


# BUG-1: an "Equip abilities you activate …" static, or an "Equip {N}. <rider>" sentence, is not a bare equip cost. The keyword
# token's greedy `.*$` would claim it whole and drop the rider, so it falls through to the static handlers instead.
def _line_equip_once_each_turn(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if is_keyword_line(raw) and (_EQUIP_RIDER_RE.match(raw) is None or EQUIP_ONCE_EACH_TURN_RE.fullmatch(raw)):
        return Segment(raw=raw, claimed=True, keyword_line=True)
    return None


# PAR-79 fifth increment: see `_ETB_AND_CAST_TRIGGER_RE`'s own docstring
# — split before any single-trigger regex gets a look, so a compound
# "enters and whenever you cast" line always goes through this path
# rather than falling through to the composed cast head (whose own
# ``^(?:whenever|when) <actor>`` anchor wouldn't match this line's leading
# "when ~ enters and " anyway, but the ordering is deliberate).
def _line_etb_and_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    etb_and_cast = _ETB_AND_CAST_TRIGGER_RE.match(raw)
    if etb_and_cast is not None:
        body = etb_and_cast.group("body").strip()
        cast_clause = etb_and_cast.group("cast_clause").strip()
        etb_seg = segment_line(
            f"when ~ enters, {body}",
            allow_spell_effect=allow_spell_effect, provenance=provenance,
        )
        cast_seg = segment_line(
            f"whenever {cast_clause}, {body}",
            allow_spell_effect=allow_spell_effect, provenance=provenance,
        )
        if etb_seg.spec is not None and cast_seg.spec is not None:
            return Segment(raw=raw, spec=etb_seg.spec, extra_specs=[cast_seg.spec], claimed=True)
        return Segment(raw=raw)
    return None


def _line_play_with_top_revealed(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if _PLAY_WITH_TOP_REVEALED_RE.match(raw):
        return Segment(raw=raw, claimed=True)  # informational-only, no spec (see docstring)
    return None


def _line_meld_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    meld_trig = _MELD_TRIGGER_RE.match(raw)
    if meld_trig is not None:
        step = _PHASE_STEP_WORDS.get(meld_trig.group("step").lower(), meld_trig.group("step").lower())
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec("meld", {
                "partner_name": meld_trig.group("partner").strip(),
                "result_name": meld_trig.group("result").strip(),
            })],
            trigger={"event": "STEP_BEGIN", "filter": {"step": step}, "phase_relation": "you"},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_attack_meld(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    attack_meld = _ATTACK_MELD_TRIGGER_RE.match(raw)
    if attack_meld is not None:
        before = parse_effect_body(attack_meld.group("before"))
        if before is None:
            return Segment(raw=raw)
        before.append(EffectSpec("meld", {
            "partner_name": attack_meld.group("partner").strip(),
            "result_name": attack_meld.group("result").strip(),
            "tapped_attacking": True,
        }))
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=before,
            trigger={"event": "PLAYER_ATTACKED", "condition": {"subject": "you"}},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_wordy(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    wordy = re.fullmatch(r"whenever you cast a wordy spell, (.+)", raw)
    if wordy is not None:
        effects = parse_effect_body(wordy[1])
        if effects is None:
            return Segment(raw=raw)
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=effects,
            trigger={"event": "SPELL_CAST", "condition": {"subject": "group", "controller": "you", "type": "permanent"},
                     "printed_rules_lines_at_least": 4},
            raw_text=raw, parser=provenance), claimed=True)
    return None


def _line_magecraft(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    magecraft = _MAGECRAFT_RE.match(raw)
    if magecraft is not None:
        effects = parse_effect_body(magecraft.group("body"))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group", "type": "permanent", "controller": "you", "other": False},
                "spell_subtype_any": ["instant", "sorcery"],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_counter_free_spell(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if _COUNTER_FREE_SPELL_RE.match(raw):
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec("counter", {"target_from_trigger_event": "instance_id"})],
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "spell_no_mana_spent": True,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_enters_if_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    enters_if_cast = _ENTERS_IF_CAST_RE.match(raw)
    if enters_if_cast is not None:
        body, optional = peel_optional(enters_if_cast.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        for e in effects:
            e.condition = {**(e.condition or {}), "source_was_cast": True}
            # "…for a creature card with mana value X or less…" (Rocco,
            # Cabaretti Caterer) — this whole row is *always* a triggered
            # ability firing after its own casting resolution ended, so the
            # generic bare ``"x"`` sentinel (tied to the *current* stack
            # item's announced X, which is 0 for a trigger) is always wrong
            # here; rewrite to `GameObject.x_paid`'s own ``"source_x_paid"``
            # sentinel (Invasion of Ikoria's existing idiom) instead.
            for key, value in list(e.params.items()):
                if value == "x":
                    e.params[key] = "source_x_paid"
                elif isinstance(value, dict):
                    for inner_key, inner_value in list(value.items()):
                        if inner_value == "x":
                            value[inner_key] = "source_x_paid"
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_enters_if_madness(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    enters_if_madness = _ENTERS_IF_MADNESS_PAID_RE.match(raw)
    if enters_if_madness is not None:
        body, optional = peel_optional(enters_if_madness.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        for e in effects:
            e.condition = {
                **(e.condition or {}), f"{enters_if_madness.group('cost').lower()}_cost_paid": True,
            }
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_spell_not_their_turn_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_not_their_turn_trig = _CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE.match(raw)
    if cast_spell_not_their_turn_trig is not None:
        body, optional = peel_optional(cast_spell_not_their_turn_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "not_controllers_turn": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_spell_no_mana_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_no_mana_trig = _CAST_SPELL_NO_MANA_TRIGGER_RE.match(raw)
    if cast_spell_no_mana_trig is not None:
        body, optional = peel_optional(cast_spell_no_mana_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "group"},
                "spell_no_mana_spent": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_spell_targets_src(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_targets_src = _CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_targets_src is not None:
        body, optional = peel_optional(cast_spell_targets_src.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition("you"),
                "requires_spell_targets_source": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_spell_shares_type(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_shares_type = _CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_shares_type is not None:
        body, optional = peel_optional(cast_spell_shares_type.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition("you"),
                "spell_shares_creature_type_with_source": True,
                **({"limit": True} if body_limit else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_spell_targets_perm(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_spell_targets_perm = _CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE.match(raw)
    if cast_spell_targets_perm is not None:
        subj = cast_spell_targets_perm.group("subj").lower()
        body, optional = peel_optional(cast_spell_targets_perm.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "requires_spell_targets_permanent": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_two_color_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    two_color_cast = _CAST_TWO_COLOR_SPELL_TRIGGER_RE.match(raw)
    if two_color_cast is not None:
        body, optional = peel_optional(two_color_cast.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        mimic_body = re.fullmatch(
            r"~ has base power and toughness (?P<p>\d+)/(?P<t>\d+) until end of turn and "
            r"(?P<tail>gains? [a-z ]+|can'?t be blocked this turn)\.", body.strip(), re.I,
        )
        if effects is None and mimic_body is not None:
            effects = [EffectSpec("grant_until", {
                "static": {"type": "pt_set", "params": {
                    "power": int(mimic_body.group("p")), "toughness": int(mimic_body.group("t")),
                }}, "duration": "end_of_turn", "target_kind": None,
            })]
            tail = mimic_body.group("tail").lower()
            if tail.startswith("gains "):
                effects.append(EffectSpec("pump", {"keywords": [tail.removeprefix("gains ")]}))
            else:
                effects.append(EffectSpec("pump", {"unblockable": True}))
        if effects is None:
            return Segment(raw=raw)
        colors = [
            _CAST_SPELL_COLOR_WORDS[two_color_cast.group("c1").lower()],
            _CAST_SPELL_COLOR_WORDS[two_color_cast.group("c2").lower()],
        ]
        spec = AbilitySpec("triggered", effects=effects, trigger={
            "event": "SPELL_CAST",
            "condition": _cast_spell_trigger_condition(two_color_cast.group("subj")),
            "cast_of_all_colors": colors,
        }, optional=optional, raw_text=raw, parser=provenance)
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_this_spell_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_this_spell_trig = _CAST_THIS_SPELL_TRIGGER_RE.match(raw)
    if cast_this_spell_trig is not None:
        body, optional = peel_optional(cast_this_spell_trig.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "SPELL_CAST", "condition": {"subject": "self"}},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_draw_trig_plain(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    draw_trig_plain = _DRAW_TRIGGER_PLAIN_RE.match(raw)
    if draw_trig_plain is not None:
        subj = draw_trig_plain.group("subj").lower()
        body, optional = peel_optional(draw_trig_plain.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "DRAW", "condition": _cast_spell_trigger_condition(subj)},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_reveal_first(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    reveal_first = _REVEAL_FIRST_DRAW_RE.match(raw)
    if reveal_first is not None:
        body, optional = peel_optional(reveal_first.group("body"))
        effects = parse_effect_body(body)
        if effects is None or any(effect.condition for effect in effects):
            return Segment(raw=raw)
        gate: dict[str, Any] = {"kind": "is_card_type", "of": "first_drawn_this_turn",
                                "card_type": reveal_first.group("type").lower()}
        if reveal_first.group("basic"):
            gate = {"kind": "all", "conditions": [
                gate, {"kind": "is_basic", "of": "first_drawn_this_turn"}]}
        spec = AbilitySpec(
            "triggered",
            effects=[EffectSpec(e.type, e.params, condition=gate) for e in effects],
            trigger={"event": "DRAW", "condition": _cast_spell_trigger_condition("you"),
                     "is_nth_draw_this_turn": 1},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_draw_trig_nth(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    draw_trig_nth = _DRAW_CARD_TRIGGER_NTH_RE.match(raw)
    if draw_trig_nth is not None:
        subj = draw_trig_nth.group("subj").lower()
        n = _CAST_SPELL_ORDINAL_WORDS[draw_trig_nth.group("ordinal").lower()]
        body, optional = peel_optional(draw_trig_nth.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DRAW",
                "condition": _cast_spell_trigger_condition(subj),
                "is_nth_draw_this_turn": n,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_tap_mana_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    tap_mana_trig = _TAP_FOR_MANA_TRIGGER_RE.match(raw)
    if tap_mana_trig is not None:
        subj = tap_mana_trig.group("subj").lower()
        land = tap_mana_trig.group("land").lower()
        body, optional = peel_optional(tap_mana_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        condition: dict[str, Any] = {"subject": "group", "type": "land"}
        if land != "land":
            condition["subtypes"] = [land]
        if subj == "you":
            condition["controller"] = "you"
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "TAPPED_FOR_MANA", "condition": condition, "mana_ability": True},
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_doctor_or_companion_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    doctor_or_companion_trig = _DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE.match(raw)
    if doctor_or_companion_trig is not None:
        body, optional = peel_optional(doctor_or_companion_trig.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        doctor_spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_subtype_any": ["doctor"],
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        companion_spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": ["creature"],
                "spell_has_keyword": "Doctor's Companion",
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=doctor_spec, extra_specs=[companion_spec], claimed=True)
    return None


def _line_composed_cast(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    composed_cast = _CAST_TRIGGER_COMPOSED_RE.match(raw)
    if composed_cast is not None:
        composed_keys = parse_spell_phrase(composed_cast.group("phrase"))
        if composed_keys is not None:
            if composed_cast.group("copies"):
                composed_keys["event"] = ["SPELL_CAST", "SPELL_COPIED"]
            return _cast_trigger_segment(
                raw, composed_cast.group("subj"), composed_keys, composed_cast.group("body"), provenance
            )
    return None


def _line_cycle_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cycle_trig = _CYCLE_TRIGGER_RE.match(raw)
    if cycle_trig is not None:
        body = cycle_trig.group("body")
        # RULE 702.28c's X (Shark Typhoon's "create an X/X ... token"): the
        # Cycling cost's own paid {X}, ambiguous to any *generic* "create an
        # X/X ... token" handler outside this wrapper (see `_cycling_xx_
        # token`'s own docstring) — checked directly, here, rather than
        # through the ordinary HANDLERS table this body would otherwise go
        # through via `parse_effect_body`.
        xx_token_match = CYCLING_XX_TOKEN_RE.fullmatch(body.strip().rstrip(".").strip())
        if xx_token_match is not None:
            effects = cycling_xx_token(xx_token_match)
        else:
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "CYCLED", "condition": {"subject": "self"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_caused_discard_replacement(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if _CAUSED_DISCARD_REPLACEMENT_RE.match(raw) is not None:
        return Segment(raw=raw, claimed=True, spec=AbilitySpec(
            "replacement", [EffectSpec("discard_to_battlefield", {})],
            raw_text=raw, parser=provenance,
        ))
    return None


def _line_caused_discard(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    caused_discard = _OPPONENT_CAUSED_DISCARD_TRIGGER_RE.match(raw)
    if caused_discard is not None:
        is_self = caused_discard.group("what").lower() != "a card"
        effects = _caused_discard_effects(caused_discard.group("body"), is_self)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DISCARD_CARD",
                "condition": {"subject": "self" if is_self else "you"},
                "requires_opponent_caused_discard": True,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_exert_bare(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    if _EXERT_BARE_RE.match(raw) is not None:
        return Segment(raw=raw, claimed=True, keyword_line=True)
    return None


def _line_exert_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    exert_trig = _EXERT_TRIGGER_RE.match(raw)
    if exert_trig is not None:
        # "…as he attacks. When you do, he gains flying" (Themberchaud): the effect grammar
        # knows the self-pronoun as "it".
        body = re.sub(r"\b(?:he|she)\b", "it", exert_trig.group("body"))
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "EXERTED", "condition": {"subject": "self"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_exert_player_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    exert_player_trig = _EXERT_PLAYER_TRIGGER_RE.match(raw)
    if exert_player_trig is not None:
        effects = parse_effect_body(exert_player_trig.group("body"))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={"event": "EXERTED", "condition": {"subject": "you"}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_sacrifice_trig(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sacrifice_trig = _SACRIFICE_TYPE_TRIGGER_RE.match(raw)
    if sacrifice_trig is not None:
        effects = parse_effect_body(sacrifice_trig.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SACRIFICE",
                "condition": {"subject": "you"},
                "sacrifice_type": [
                    t.lower() for t in (sacrifice_trig.group("type"), sacrifice_trig.group("type2")) if t
                ],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_control_none_matching(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    control_none_matching = _CONTROL_NONE_MATCHING_RE.match(raw)
    if control_none_matching is not None:
        effects = parse_effect_body(control_none_matching.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        quality: dict[str, Any] = {"subtype": control_none_matching.group("sub").lower()}
        if control_none_matching.group("leg"):
            quality["legendary"] = True
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered", effects=effects,
            trigger={"event": "STATE_CHECK", "controls_none_matching": quality},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_control_none_sac(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    control_none_sac = _CONTROL_NONE_SACRIFICE_RE.match(raw)
    if control_none_sac is not None:
        effects = parse_effect_body(control_none_sac.group("body"), reading=ClauseReading(self_subject=True))
        if effects is None:
            return Segment(raw=raw)
        land_type = _BASIC_LAND_TYPE_SINGULAR[control_none_sac.group("type").lower()]
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "LEAVES_BATTLEFIELD",
                "controls_none_of_type": land_type,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# RULE 118.9 alternative costs — checked regardless of card type
# (unlike every other row `allow_spell_effect` gates below): a spell's
# mana cost doesn't care what it becomes once it resolves, so the
# Bringer cycle prints "You may pay <mana> rather than pay this
# spell's mana cost." on an ordinary creature spell exactly the same
# way Force of Will prints it on an instant. Widening `_is_spell`
# itself to include creatures was tried and reverted — it also gates
# unrelated bare-imperative rows below (Strive, free-cast conditions, …)
# that broke real creature static/replacement-clause tests when creature
# cards started reaching them, so only this alt_cost family is pulled
# out and made unconditional instead.
def _line_alt_cost_exile_hand_color(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch = _ALT_COST_EXILE_HAND_COLOR_RE.match(raw)
    if pitch is not None:
        color = resolve_color_word(pitch.group("color"))
        if color is None:
            return Segment(raw=raw)  # unrecognised colour word → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"exile_hand_card_color": color},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_sacrifice_filter(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_filter = _ALT_COST_SACRIFICE_NONTOKEN_COLOR_CREATURE_RE.match(raw)
    if sac_filter is not None:
        color = resolve_color_word(sac_filter.group("color"))
        if color is None:
            return Segment(raw=raw)  # unrecognised colour word → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"sacrifice_filter": {"card_type": "creature", "color": color, "nontoken": True}},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_sacrifice_type(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_type = _ALT_COST_SACRIFICE_TYPE_RE.match(raw)
    if sac_type is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"sacrifice": sac_type.group("what").lower()},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_return_two(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    ret_two = _ALT_COST_RETURN_TWO_RE.match(raw)
    if ret_two is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"return_to_hand_count": [2, ret_two.group("subtype").lower()]},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_life_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_if = _ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE.match(raw)
    if pay_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "pay_life": int(pay_if.group("n")),
                "condition": {"control_land_type": pay_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_mana_if_attacking(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_attacking = _ALT_COST_PAY_MANA_IF_ATTACKING_RE.match(raw)
    if pay_mana_if_attacking is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_attacking.group("mana")),
                "condition": {
                    "creatures_attacking_at_least": int(pay_mana_if_attacking.group("n")),
                },
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_mana_if_you_attacked(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_you_attacked = _ALT_COST_PAY_MANA_IF_YOU_ATTACKED_RE.match(raw)
    if pay_mana_if_you_attacked is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_you_attacked.group("mana")),
                "condition": {"you_attacked_this_turn": True},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_mana(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana = _ALT_COST_PAY_MANA_RE.match(raw)
    if pay_mana is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"mana": re.sub(r"\s+", "", pay_mana.group("mana"))},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_sacrifice_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_if = _ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE.match(raw)
    if sac_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "sacrifice": sac_if.group("what").lower(),
                "condition": {"control_land_type": sac_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_tap_creature_if_control_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    tap_if = _ALT_COST_TAP_CREATURE_IF_CONTROL_LAND_RE.match(raw)
    if tap_if is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "tap_others": [1, "creature"],
                "condition": {"control_land_type": tap_if.group("land").lower()},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_mana_and_return_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_and_return = _ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE.match(raw)
    if pay_and_return is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_and_return.group("mana")),
                "return_to_hand_count": [1, "basic land"],
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_sacrifice_count(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    sac_count = _ALT_COST_SACRIFICE_COUNT_RE.match(raw)
    if sac_count is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"sacrifice_count": [int(sac_count.group("n")), sac_count.group("subtype").lower()]},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_exile_hand_color_count(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_color_count = _ALT_COST_EXILE_HAND_COLOR_COUNT_RE.match(raw)
    if pitch_color_count is not None:
        color = resolve_color_word(pitch_color_count.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"exile_hand_card_color_count": [2, color]},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_exile_hand_if_not_your_turn(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_if_not_your_turn = _ALT_COST_EXILE_HAND_COLOR_IF_NOT_YOUR_TURN_RE.match(raw)
    if pitch_if_not_your_turn is not None:
        color = resolve_color_word(pitch_if_not_your_turn.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "exile_hand_card_color": color,
                "condition": {"not_your_turn": True},
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_life_and_exile_hand(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pitch_pay_life = _ALT_COST_PAY_LIFE_AND_EXILE_HAND_COLOR_RE.match(raw)
    if pitch_pay_life is not None:
        color = resolve_color_word(pitch_pay_life.group("color"))
        if color is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "pay_life": int(pitch_pay_life.group("n")),
                "exile_hand_card_color": color,
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_discard_land(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    discard_land = _ALT_COST_DISCARD_LAND_TYPE_RE.match(raw)
    if discard_land is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={"discard_land_type": discard_land.group("land").lower()},
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_alt_cost_pay_mana_if_treasure(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    pay_mana_if_treasure = _ALT_COST_PAY_MANA_IF_TREASURE_RE.match(raw)
    if pay_mana_if_treasure is not None:
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            alt_cost={
                "mana": re.sub(r"\s+", "", pay_mana_if_treasure.group("mana")),
                "mana_source_kind": "treasure",
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _line_cast_mana_source_restriction(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    cast_mana_source = _CAST_MANA_SOURCE_RESTRICTION_RE.match(raw)
    if cast_mana_source is not None:
        kind = {"basic lands": "basic_land", "creatures": "creature"}[
            cast_mana_source.group("kind").lower()
        ]
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            cast_mana_source_restriction=kind,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# RULE 601.2b/604.3 additional cost — checked before every other wrapper
# since it has neither a trigger word nor a colon (so it can't be
# mistaken for one of those shapes below). Not gated by
# ``allow_spell_effect``: the "as an additional cost to cast this spell,"
# wrapper is unambiguous and applies to a creature/other permanent spell
# just as much as an instant/sorcery (Kinsbaile Aspirant/Lys Alana
# Dignitary/Silvergill Mentor — Behold, PAR-29), and the spec it emits
# carries no bare imperative for the gate to guard against.
def _line_collect_evidence_discount(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    evidence_discount = _COLLECT_EVIDENCE_COST_REDUCTION_RE.match(raw)
    if evidence_discount is not None:
        cost = {"collect_evidence": int(evidence_discount.group("evidence"))}
        cost_spec = AbilitySpec(
            "spell_effect", effects=[], additional_cost=cost,
            additional_cost_optional=True, raw_text=raw, parser=provenance,
        )
        reduction_spec = AbilitySpec(
            "static",
            effects=[EffectSpec("cost_reduction", {
                "affects": "self", "generic": int(evidence_discount.group("reduction")),
                "active_if": {"kind": "flag", "flag": "additional_cost_paid"},
            })],
            raw_text=raw, parser=provenance,
        )
        return Segment(raw=raw, spec=cost_spec, extra_specs=[reduction_spec], claimed=True)
    return None


def _line_additional_cost_line(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    add_cost = _ADDITIONAL_COST_LINE_RE.match(raw)
    if add_cost is not None:
        cost_text = add_cost.group("cost")
        # PAR-30 / RULE 601.2b: "you may <cost>" → an *optional* additional
        # cost, offered as its own cast variant and recorded on
        # `GameObject.additional_cost_paid`.
        optional_m = _ADDITIONAL_COST_OPTIONAL_PREFIX_RE.match(cost_text.strip())
        is_optional = optional_m is not None
        if is_optional:
            cost_text = optional_m.group("cost")
        cost = _additional_cost_dict(cost_text)
        if cost is None:
            return Segment(raw=raw)  # unrecognised cost shape → unclaimed
        spec = AbilitySpec(
            "spell_effect",
            effects=[],
            additional_cost=cost,
            additional_cost_optional=is_optional or "sacrifice_or_mana" in cost or "or_mana" in cost,  # "either": both branches mandatory
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# PAR-35's casting clauses are unambiguous spell metadata, so like an
# additional cost they apply to permanent spells too (Harbinger of the
# Tides / Armor of Thorns), not only bare instant/sorcery effects.
def _line_declare_attackers_if_attacked(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if _DECLARE_ATTACKERS_IF_ATTACKED_RE.match(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_timing_restriction={"step": "declare_attackers", "controller_attacked": True},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_combat_cast_only(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    combat_cast = _COMBAT_CAST_ONLY_RE.fullmatch(raw)
    if combat_cast:
        groups = combat_cast.groupdict()
        restriction = {"phase": "combat"} if groups["window"].lower() == "during combat" else {"step": "declare_blockers"}
        if groups["turn"]:
            restriction["your_turn" if groups["turn"].lower() == "your" else "opponents_turn"] = True
        if groups["point"]:
            if "step" in restriction:
                return Segment(raw=raw)  # contradictory or unsupported composite
            restriction[groups["point"].lower() + "_blockers"] = True
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], cast_timing_restriction=restriction,
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_before_blockers_cast_only(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if _BEFORE_BLOCKERS_CAST_ONLY_RE.fullmatch(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_timing_restriction={"before_blockers": True, "first_combat": True},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_cast_only_if_another_color(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    another_cast = _CAST_ONLY_IF_ANOTHER_COLOR_RE.match(raw)
    if another_cast is not None:
        color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[
            another_cast.group("color").lower()
        ]
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_condition={"another_spell_cast_this_turn": {"color": color}},
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_conditional_flash_for_mana(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    flash_for_mana = _CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE.match(raw)
    if flash_for_mana is not None:
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], conditional_flash={"unconditional": True},
            flash_extra_cost=re.sub(r"\s+", "", flash_for_mana.group("cost")),
            raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_flash_then_cleanup_sac(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    if _FLASH_THEN_CLEANUP_SAC_RE.match(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "triggered",
            [EffectSpec("create_delayed_trigger", {
                "step": "cleanup", "scope": "controller",
                "effects": [{"type": "sacrifice_self", "params": {}}],
                "description": "Instant-speed cast: sacrifice at next cleanup",
            }, condition={"cast_outside_sorcery_speed": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            conditional_flash={"unconditional": True}, raw_text=raw, parser=provenance,
        ), claimed=True)
    return None


def _line_spell_free_cast_conditions(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if allow_spell_effect:
        # RULE 601.2f-adjacent condition-gated free-cast alternative cost —
        # "If you control a commander, you may cast this spell without
        # paying its mana cost." — its own standalone line, same treatment.
        if _FREE_CAST_IF_COMMANDER_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={"control_commander": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        another_color = _FREE_CAST_IF_ANOTHER_COLOR_RE.match(raw)
        if another_color is not None:
            color = {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G"}[
                another_color.group("color").lower()
            ]
            return Segment(raw=raw, spec=AbilitySpec(
                "spell_effect", effects=[],
                free_cast_condition={"another_spell_cast_this_turn": {"color": color}},
                raw_text=raw, parser=provenance,
            ), claimed=True)

        opp_spells = _FREE_CAST_IF_OPPONENT_SPELLS_RE.match(raw)
        if opp_spells is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={
                    "opponent_spells_cast_this_turn_at_least": int(opp_spells.group("n"))
                },
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        if _FREE_CAST_IF_OPPONENT_FOREST_YOU_ISLAND_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                free_cast_condition={"opponent_controls_forest_and_you_control_island": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        # RULE 702.8b: "You may cast this spell as though it had flash if it
        # targets a commander." (Timely Ward-shaped, MEC-7) — same standalone-
        # line treatment as the free-cast condition just above.
        if _CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE.match(raw):
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                conditional_flash={"targets_a_commander": True},
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        behold_flash = _CONDITIONAL_FLASH_IF_BEHOLD_RE.match(raw)
        if behold_flash is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                conditional_flash={
                    "controller_beholds_subtype": behold_flash.group("q").strip().lower()
                },
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        # "Strive — This spell costs <cost> more to cast for each target
        # beyond the first." (MEC-4) — same standalone-line treatment; the
        # cost run is whitespace-collapsed the way `_additional_cost_dict`'s
        # neighbours already do, so ``{2} {u}`` and ``{2}{u}`` both parse.
        strive = _STRIVE_LINE_RE.match(raw)
        if strive is not None:
            spec = AbilitySpec(
                "spell_effect",
                effects=[],
                strive_cost=re.sub(r"\s+", "", strive.group("cost")),
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
    return None


# Saga chapter ability "i, ii — <effect>" (RULE 714.2d) — checked before
# every other wrapper since it has neither a trigger word nor a colon.
def _line_saga_chapter(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    if is_saga:
        chap = CHAPTER_LINE_RE.match(raw)
        if chap is not None:
            chapters = parse_chapter_token(chap.group("chapters"))
            if chapters is None:
                return Segment(raw=raw)  # unrecognised numeral → unclaimed
            body, optional = peel_optional(chap.group("body"))
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
    return None


# Planeswalker loyalty ability "[±N]: <effect>" (RULE 606.5c) — its cost is
# the bracket, so it's recognised before the generic activated case (whose
# cost sniff wouldn't accept a bare "[+1]").
def _line_loyalty_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    loy = _LOYALTY_LINE_RE.match(raw)
    if loy is not None:
        if loy.group(2) == "x":
            # RULE 107.3a / 606.6: the shared cost model already supports
            # announced negative X; positive/unsigned X is not represented.
            if loy.group(1) not in ("-", "−"):
                return Segment(raw=raw)
            delta = "-x"
        else:
            magnitude = int(loy.group(2))
            delta = -magnitude if loy.group(1) in ("-", "−") else magnitude
        body, optional = peel_optional(loy.group("effect").strip())
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
    return None


# Activated ability "<cost>: <effect>" — checked before the trigger/spell
# cases since a colon unambiguously marks it (RULE 602.1). A trigger has no
# colon, so this never steals one.
def _line_activated_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    is_saga = ctx.is_saga
    act = _ACTIVATED_RE.match(raw)
    if act is not None and _is_activation_cost(act.group("cost")):
        alternative = _ALTERNATIVE_COST_RE.fullmatch(act.group("cost").strip())
        if alternative is not None:
            # ENG-51: "{3}, {T} or {U}, {T}: …" (the Shards) — two costs for
            # one ability; either pays it. Modeled as two activated abilities
            # sharing the effect, the Pemmin's Aura idiom (`extra_specs`):
            # picking which to activate *is* picking the cost.
            halves = [
                _segment_line_unsplit(
                    f"{alternative.group(half)}: {act.group('effect')}",
                    allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga,
                )
                for half in ("a", "b")
            ]
            if not all(half.claimed and half.spec is not None for half in halves):
                return Segment(raw=raw)
            return Segment(
                raw=raw, spec=halves[0].spec, claimed=True,
                extra_specs=[*halves[0].extra_specs, halves[1].spec, *halves[1].extra_specs],
            )
        if scan_cost_text(act.group("cost")).leftover is not None:
            # ENG-49: a cost fragment no recognizer reads would never be
            # charged, so the ability would be claimed cheaper than printed
            # ("{G}, {T}, Discard a historic card"). Unclaimed instead — the
            # same grammar `game/costs.parse_activation_cost` charges from.
            return Segment(raw=raw)
        effect_text = act.group("effect").strip()
        if (
            _MANA_EFFECT_RE.match(effect_text)
            or _COLORS_AMONG_PERMANENTS_MANA_RE.match(effect_text)
            or _DEVOTION_CHOSEN_COLOR_MANA_RE.match(effect_text)
        ):
            if _MANA_ABILITY_SACRIFICE_X_RE.search(act.group("cost")) and not (
                _MANA_ABILITY_X_SUPPORTED_RE.fullmatch(effect_text)
            ):
                # A mana ability announces X only for "Add X mana of any one
                # color[. You gain X life.]" (ENG-51, Springjack Pasture —
                # `ManaAbility.x_scaled`); any other X-sized mana effect would
                # neither scale its sacrifice nor its amount, so stays unclaimed.
                return Segment(raw=raw)
            # Mana ability — covered by the engine's mana model, no spec here.
            return Segment(raw=raw, claimed=True)
        cost_dict: dict[str, Any] = {"text": act.group("cost").strip()}
        # Throne of Eldraine-shaped colour-lock on this ability's own cost —
        # a trailing "Spend only mana of the chosen color to activate this
        # ability." sentence, peeled off the effect body and recorded as a
        # cost flag (`ActivationCost.spend_only_chosen_color`) rather than a
        # (non-existent) effect.
        if _SPEND_ONLY_CHOSEN_COLOR_RE.search(effect_text):
            effect_text = _SPEND_ONLY_CHOSEN_COLOR_RE.sub("", effect_text).strip()
            cost_dict["spend_only_chosen_color"] = True
        party_reduction = _ACTIVATION_COST_REDUCTION_PARTY_RE.search(effect_text)
        if party_reduction is not None:
            effect_text = _ACTIVATION_COST_REDUCTION_PARTY_RE.sub("", effect_text).strip()
            cost_dict["dynamic_reduction"] = {
                "count_selector": "creatures_in_your_party",
                "generic_per": int(party_reduction.group("n")),
            }
        else:
            per_reduction = _ACTIVATION_COST_REDUCTION_FOR_EACH_RE.search(effect_text)
            if per_reduction is not None:
                selector = _activation_cost_reduction_selector(per_reduction.group("what"))
                if selector is not None:
                    effect_text = _ACTIVATION_COST_REDUCTION_FOR_EACH_RE.sub("", effect_text).strip()
                    cost_dict["dynamic_reduction"] = {
                        "count_selector": selector,
                        "generic_per": int(per_reduction.group("n")),
                    }
            conditional_reduction = _ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE.search(effect_text)
            if conditional_reduction is not None:
                effect_text = _ACTIVATION_COST_REDUCTION_GRAVEYARD_MV_RE.sub("", effect_text).strip()
                cost_dict["dynamic_reduction"] = {
                    "generic_per": int(conditional_reduction.group("n")),
                    "active_if": {
                        "kind": "distinct_mana_values_in_graveyard_at_least",
                        "min": int(conditional_reduction.group("minimum")),
                    },
                }
            else:
                colored_reduction = _ACTIVATION_COST_REDUCTION_COLORED_RE.search(effect_text)
                if colored_reduction is not None:
                    active_if = static_condition(colored_reduction.group("condition"))
                    symbols = re.findall(r"\{([WUBRG])\}", colored_reduction.group("symbols"), re.I)
                    colors = {symbol.upper() for symbol in symbols}
                    if active_if is not None and len(colors) == 1:
                        effect_text = _ACTIVATION_COST_REDUCTION_COLORED_RE.sub("", effect_text).strip()
                        cost_dict["dynamic_reduction"] = {
                            "generic_per": int((colored_reduction.group("generic") or "{0}")[1:-1]),
                            "colored": {colors.pop(): len(symbols)},
                            "active_if": active_if,
                        }
                conditional_reduction = _ACTIVATION_COST_REDUCTION_CONDITIONAL_RE.search(effect_text)
                if conditional_reduction is not None:
                    active_if = static_condition(conditional_reduction.group("condition"))
                    if active_if is not None:
                        effect_text = _ACTIVATION_COST_REDUCTION_CONDITIONAL_RE.sub("", effect_text).strip()
                        cost_dict["dynamic_reduction"] = {
                            "generic_per": int(conditional_reduction.group("n")),
                            "active_if": active_if,
                        }
        tail_markers: list[EffectSpec] = []
        # RULE 602.5d: activation timing qualifies the whole ability, even
        # when the effect body ends in an otherwise branch.
        sorcery_tail = re.search(r"\.\s*activate only as a sorcery\.?$", effect_text, re.I)
        if sorcery_tail is not None:
            effect_text = effect_text[:sorcery_tail.start()].strip()
            tail_markers.extend(parse_effect_body("activate only as a sorcery") or [])
        # RULE 602.2: "Any player may activate this ability [but only as a
        # sorcery]" (Fan Favorite, Feral Hydra, Excavation, the Flailing cycle) —
        # `ActivationCost.any_player_may_activate`, the primitive Mercenaries and
        # Nullhide Ferox were hand-authored on.
        any_player = _ANY_PLAYER_MAY_ACTIVATE_RE.search(effect_text)
        if any_player is not None:
            effect_text = effect_text[:any_player.start()].strip()
            cost_dict["any_player_may_activate"] = True
            if any_player.group("sorcery"):
                sorcery = parse_effect_body("activate only as a sorcery")
                if sorcery is None:
                    return Segment(raw=raw)
                tail_markers.extend(sorcery)
        activation_tail = _ACTIVATE_ONLY_IF_TRAILING_RE.search(effect_text)
        if activation_tail is not None:
            conds = [
                f"it's the {activation_tail.group('step').lower()} step" if activation_tail.group("step") else None,
                (activation_tail.group("cond") or activation_tail.group("cond2") or "").strip() or None,
            ]
            tail = "activate only if " + " and ".join(c for c in conds if c)
            parsed_tail = parse_effect_body(tail)
            if parsed_tail is None:
                return Segment(raw=raw)
            tail_markers.extend(parsed_tail)
            if activation_tail.group("once"):
                tail_markers.append(EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {}))
            effect_text = effect_text[:activation_tail.start()].strip()
        if re.search(r"\b(?:exile|sacrifice) ~(?:,|$)", raw.split(":", 1)[0].strip(), re.I):
            # RULE 608.2h: with ~ paid as the cost, "it had N counters on it"
            # is ~'s last-known count, captured for its departed visit
            # rather than retained on the exiled card (Lost Isle Calling).
            effect_text = _COST_PAID_SOURCE_HAD_RE.sub(r"if ~ has \g<n> or more \g<kind> counters on it,",
                                                       effect_text)
        body, optional = peel_optional(effect_text)
        effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
        if effects is None:
            # RULE 700.2's *compact* inline modal ("gets +1/-1 or -1/+1
            # until end of turn" — Pemmin's Aura), which the bulleted
            # modal-block grammar can't see. Only tried once the ordinary
            # parse has already failed, so it can never steal a line that
            # already had a reading.
            split = _inline_pt_modal_bodies(body)
            if split is None:
                return Segment(raw=raw)
            parsed = [parse_effect_body(half) for half in split]
            if any(half is None for half in parsed):
                return Segment(raw=raw)
            specs = [
                AbilitySpec(
                    "activated",
                    effects=half,
                    cost=dict(cost_dict),
                    optional=optional,
                    raw_text=raw,
                    parser=provenance,
                )
                for half in parsed
            ]
            return Segment(
                raw=raw, spec=specs[0], extra_specs=specs[1:], claimed=True
            )
        effects.extend(tail_markers)
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost=cost_dict,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


def _phase_damage_referents(effects: list[EffectSpec]) -> list[EffectSpec]:
    """RULE 603.2b: a step body's "that player" is the active player.

    Amount wrappers (Festering Wound) can hide damage below ``bind``. Only
    descend into immediate composition, never future granted abilities.
    """
    rewritten = []
    for effect in effects:
        params = dict(effect.params)
        if effect.type == "damage" and params.get("selector") == "event_player":
            params["selector"] = "active_player"
        fields = {"seq": ("effects",), "bind": ("effects",), "if_else": ("then", "else")}.get(effect.type, ())
        for field in fields:
            if isinstance(params.get(field), list):
                children = [EffectSpec.from_dict(child) for child in params[field]]
                params[field] = [child.to_dict() for child in _phase_damage_referents(children)]
        rewritten.append(EffectSpec(effect.type, params, condition=effect.condition))
    return rewritten


def _line_phase_trigger(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    phase_trig = _PHASE_TRIGGER_RE.match(raw)
    if phase_trig is not None:
        step_word = (
            phase_trig.group("step_any")
            or phase_trig.group("step_you")
            or phase_trig.group("step_you_each")
            or phase_trig.group("step_both_mains")
            or phase_trig.group("step_combat_you")
            or phase_trig.group("step_combat_opp")
            or phase_trig.group("step_opp")
            or phase_trig.group("step_other")
            or phase_trig.group("step_attached")
        )
        both_mains = bool(phase_trig.group("step_both_mains"))
        step = "main1" if both_mains else _PHASE_STEP_WORDS.get((step_word or "").lower())
        if step is None:
            return Segment(raw=raw)
        if (
            phase_trig.group("step_you")
            or phase_trig.group("step_you_each")
            or both_mains
            or phase_trig.group("step_combat_you")
        ):
            relation = "you"
        elif phase_trig.group("step_opp") or phase_trig.group("step_other") or phase_trig.group("step_combat_opp"):
            relation = "not_you"
        elif phase_trig.group("step_attached"):
            relation = "attached_permanent"
        else:
            relation = None
        body, optional = peel_optional(phase_trig.group("body"))
        # MEC-46: peel a leading "if another <subtype> entered … this turn,"
        # RULE 603.4 intervening-if into the trigger's own `active_if`.
        phase_active_if: Optional[dict[str, Any]] = None
        phase_self_subject = False
        entered_if = _ANOTHER_SUBTYPE_ENTERED_IF_RE.match(body)
        gy_if = _CREATURE_CARD_TO_GY_IF_RE.match(body)
        dmg_if = _YOU_DEALT_DAMAGE_IF_RE.match(body)
        no_subtype_if = _YOU_CONTROL_NO_SUBTYPE_IF_RE.match(body)
        harnessed_if = _SOURCE_HARNESSED_IF_RE.match(body)
        noncreature_if = re.match(
            r"^if you'?ve cast a noncreature spell this turn,\s*(?P<rest>.+)$", body, re.I | re.S,
        )
        that_player_hand_if = _THAT_PLAYER_HAND_IF_RE.match(body)
        if harnessed_if is not None:  # MEC-79 / RULE 701.64b
            phase_active_if = {"kind": "source_harnessed"}
            body = harnessed_if.group("rest").strip()
        elif noncreature_if is not None:
            phase_active_if = {"kind": "cast_noncreature_spell_this_turn"}
            body = noncreature_if.group("rest").strip()
        elif entered_if is not None:
            phase_active_if = {
                "kind": "another_subtype_entered_this_turn",
                "subtype": entered_if.group("sub").lower(),
            }
            body = entered_if.group("rest").strip()
        elif gy_if is not None:
            phase_active_if = {"kind": "creature_card_to_graveyard_this_turn"}
            body = gy_if.group("rest").strip()
        elif dmg_if is not None:
            phase_active_if = {
                "kind": "you_dealt_damage_this_turn_at_least",
                "amount": int(dmg_if.group("n")),
            }
            body = dmg_if.group("rest").strip()
        elif no_subtype_if is not None and (
            (no_subtype_if.group("sub1") or no_subtype_if.group("sub2") or "").lower()
            in _CONTROL_NO_SUBTYPE_WORDS
        ):
            sub = (no_subtype_if.group("sub1") or no_subtype_if.group("sub2")).lower()
            phase_active_if = {
                "kind": "control_count",
                "selector": f"creatures_you_control_of_type_{sub}",
                "max": 0,
            }
            body = no_subtype_if.group("rest").strip()
        elif that_player_hand_if is not None:
            n = that_player_hand_if.group("n")
            phase_active_if = {
                "kind": "active_player_cards_in_hand_at_most",
                "amount": int(n) if n else 0,
            }
            body = that_player_hand_if.group("rest").strip()
        if phase_active_if is None:
            # RULE 603.4: every recognized leading condition gates both
            # triggering and the complete resolving body, even one sentence.
            gate = _PHASE_INTERVENING_IF_RE.match(body)
            gated = static_condition(gate.group("cond")) if gate is not None else None
            if gated is not None:
                phase_active_if = gated
                phase_self_subject = "~" in gate.group("cond")
                body = gate.group("rest").strip()
        phase_reading = ClauseReading(
            self_subject=phase_self_subject,
            attached_subject=relation == "attached_permanent",
        )
        if relation is None:
            them_damage = _PHASE_DAMAGE_TO_THEM_RE.match(body)
            if them_damage is not None:
                effects = [EffectSpec("damage", {
                    "amount": int(them_damage.group("n")), "selector": "active_player",
                })]
            else:
                effects = _active_player_phase_body(body) or parse_effect_body(body, reading=phase_reading)
        else:
            effects = _active_player_phase_body(body) or parse_effect_body(body, reading=phase_reading)
        if effects is None and phase_active_if is None:
            # RULE 603.4: any other leading "if `<state>`," of a phase trigger is an intervening
            # if too — read through the shared state-predicate vocabulary (`static_condition`)
            # rather than one regex per phrase. Only tried once the body failed as it stands, so
            # a body some other row already reads (as a per-effect gate) is left as it was.
            gate = _PHASE_INTERVENING_IF_RE.match(body)
            gated = static_condition(gate.group("cond")) if gate is not None else None
            if gated is not None:
                phase_active_if = gated
                # A condition that names ``~`` ("if …and ~ isn't a creature, it becomes …", Emergent
                # Haunting) gives a bare "it" in the body its only antecedent: the source.
                active_effects = _active_player_phase_body(gate.group("rest").strip())
                # RULE 603.4: this newly recognized body must also test the
                # intervening-if when it resolves (Howling Mine can be tapped
                # in response). The trigger's active_if handles trigger time.
                effects = ([EffectSpec("if_else", {
                    "condition": gated, "then": [e.to_dict() for e in active_effects],
                })] if active_effects is not None else None) or parse_effect_body(
                    gate.group("rest").strip(), reading=phase_reading.but(self_subject="~" in gate.group("cond")),
                )
        if effects is None:
            return Segment(raw=raw)
        effects = _phase_damage_referents(effects)
        if phase_active_if is not None:
            if len(effects) == 1 and effects[0].condition is None:
                # An atomic body already has a single resolution boundary.
                effect = effects[0]
                effects = [EffectSpec(effect.type, effect.params, condition=phase_active_if)]
            else:
                effects = [EffectSpec("seq", {"effects": [effect.to_dict() for effect in effects]}, condition=phase_active_if)]
        steps = _EACH_MAIN_PHASE_STEPS if both_mains else (step,)
        phase_specs: list[AbilitySpec] = []
        for one_step in steps:
            trigger: dict[str, Any] = {"event": "STEP_BEGIN", "filter": {"step": one_step}}
            if relation is not None:
                trigger["phase_relation"] = relation
            if phase_active_if is not None:
                trigger["active_if"] = phase_active_if
            phase_specs.append(AbilitySpec(
                "triggered",
                effects=copy.deepcopy(effects) if len(steps) > 1 else effects,
                trigger=trigger,
                optional=optional,
                raw_text=raw,
                parser=provenance,
            ))
        return Segment(raw=raw, spec=phase_specs[0], claimed=True, extra_specs=phase_specs[1:])
    return None


def _line_triggered_ability(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    trig = TRIGGER_RE.match(raw)
    if trig is not None:
        cond_text = trig.group("cond")
        # PAR-14: "…for the first time each turn" (Whispering Snitch-shaped)
        # — stripped once here, before any subject-family dispatch below, so
        # every family picks up `AbilitySpec.trigger["limit"]` for free.
        limit_suffix_m = _ONCE_PER_TURN_CONDITION_SUFFIX_RE.match(cond_text.strip())
        limit = limit_suffix_m is not None
        if limit_suffix_m is not None:
            cond_text = limit_suffix_m.group("base")

        creature_explores = _CREATURE_EXPLORES_TRIGGER_RE.match(cond_text.strip())
        if creature_explores is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(group_subject=True))
            if effects is None:
                return Segment(raw=raw)
            condition = {"subject": "group", "type": "creature", "controller": "you"}
            result = creature_explores.group("result")
            if result is not None:
                condition["explore_found_land"] = result.lower() == "land"
            spec = AbilitySpec("triggered", effects=effects, trigger={
                "event": "EXPLORED", "condition": condition,
            }, optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        milled_cards = _CARDS_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if milled_cards is not None:
            body, optional = peel_optional(trig.group("body"))
            milled_type = milled_cards.group("type")
            normalized_body = body.strip().rstrip(".").lower()
            if milled_type and normalized_body == "put them onto the battlefield tapped":
                effects = [EffectSpec("return_milled_cards", {
                    "card_type": milled_type.lower(), "tapped": True,
                })]
            elif milled_type and normalized_body == "put 1 of them onto the battlefield":
                effects = [EffectSpec("return_milled_cards", {
                    "card_type": milled_type.lower(), "choose_one": True,
                })]
            elif normalized_body == "each opponent loses 1 life for each card type among those cards":
                effects = [EffectSpec("lose_life_for_milled_card_types", {})]
            else:
                effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            trigger: dict[str, Any] = {
                "event": "CARDS_MILLED", "condition": {"subject": "you"},
            }
            if milled_type:
                trigger["milled_card_type"] = milled_type.lower()
            spec = AbilitySpec("triggered", effects=effects, trigger=trigger,
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        if _LAST_TIME_COUNTER_REMOVED_COND_RE.match(cond_text.strip()):
            # RULE 702.62a: a suspended card's own trigger, fired from exile.
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "LAST_TIME_COUNTER_REMOVED", "condition": {"subject": "self"}},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        self_milled = _SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if self_milled is not None:
            body, optional = peel_optional(trig.group("body"))
            # Narcomoeba's "put it onto the battlefield" is an untargeted
            # self-return, not a fresh RULE 115 target.
            if body.strip().rstrip(".").lower() == "put it onto the battlefield":
                effects = [EffectSpec("return_self_from_graveyard", {})]
            else:
                effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
                # Creeping Chill's optionality encloses its reflexive
                # exile-and-damage sequence; retain that composition instead
                # of peeling the leading ``you may`` into ability-level
                # optionality (which loses the pronoun's antecedent).
                if effects is None:
                    effects = parse_effect_body(trig.group("body"), reading=ClauseReading(self_subject=True))
                    optional = False
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "CARDS_MILLED", "milled_source": True},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        one_milled_card = _ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if one_milled_card is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects, trigger={
                "event": "MILLED_CARD", "condition": {"subject": "you"},
                "milled_card_type": one_milled_card.group("type").lower(),
            }, optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        graveyard_exit = _CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if graveyard_exit is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            # RULE 603.2: "This ability triggers only once each turn." (Fang, Fearless l'Cie) is the trigger's limit.
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            if not effects:
                return Segment(raw=raw)
            trigger: dict[str, Any] = {
                "event": "CARDS_LEFT_GRAVEYARD",
                "graveyard_owner": "you",
            }
            if limit or body_limit:
                trigger["limit"] = True
            if graveyard_exit.group("types"):
                types = re.split(r" and/or | or ", graveyard_exit.group("types"))
                if not set(types) <= _GRAVEYARD_EXIT_TYPES:
                    return Segment(raw=raw)
                trigger["left_graveyard_types"] = types
            if graveyard_exit.group("during"):
                trigger["during_your_turn"] = True
            spec = AbilitySpec(
                "triggered", effects=effects, trigger=trigger, optional=optional,
                raw_text=raw, parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        enters_and_phase = _ENTERS_AND_MAIN_PHASE_RE.match(cond_text.strip())
        if enters_and_phase is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            eap_limit = limit or body_limit
            eap_specs: list[AbilitySpec] = []
            for trig_dict in (
                {"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
                {"event": "STEP_BEGIN", "filter": {"step": "main1"},
                 "phase_relation": "you"},
            ):
                if eap_limit:
                    trig_dict["limit"] = True
                eap_specs.append(AbilitySpec(
                    "triggered",
                    effects=[EffectSpec(e.type, dict(e.params), condition=e.condition)
                             for e in effects],
                    trigger=trig_dict,
                    optional=optional,
                    raw_text=raw,
                    parser=provenance,
                ))
            return Segment(
                raw=raw, spec=eap_specs[0], extra_specs=eap_specs[1:], claimed=True,
            )

        variant_event = _variant_trigger_event(cond_text)
        if variant_event is not None:
            body, optional = peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            limit = limit or body_limit
            # One `AbilitySpec` **per firing condition**, rather than the
            # single list-valued ``event`` `_SELF_MULTI_EVENT_RE` emits: the
            # compound plane template's two halves need *different* triggers,
            # since only the upkeep half carries a step filter, and a filter
            # is AND-ed onto the event payload (a `PLANESWALKED_TO` event has
            # no ``step`` key, so a shared filter would fail closed and that
            # half would never fire).
            variant_specs: list[AbilitySpec] = []
            for event_name in (
                variant_event if isinstance(variant_event, list) else [variant_event]
            ):
                trigger = {"event": event_name}
                if event_name == "STEP_BEGIN":
                    trigger["filter"] = {"step": "upkeep"}
                if limit:
                    trigger["limit"] = True
                variant_specs.append(
                    AbilitySpec(
                        "triggered",
                        effects=[EffectSpec(e.type, dict(e.params)) for e in effects],
                        trigger=trigger,
                        optional=optional,
                        raw_text=raw,
                        parser=provenance,
                    )
                )
            return Segment(
                raw=raw,
                spec=variant_specs[0],
                extra_specs=variant_specs[1:],
                claimed=True,
            )
        defender_lands_min: Optional[int] = None
        head_trigger: dict[str, Any] = {}
        composed_head = False
        atk_lands = _ATTACKS_DEFENDER_LANDS_RE.match(cond_text.strip())
        atk_most_life = _ATTACKS_DEFENDER_MOST_LIFE_RE.match(cond_text.strip())
        multi = _SELF_MULTI_EVENT_RE.match(cond_text.strip())
        attached_multi = _ATTACHED_MULTI_EVENT_RE.match(cond_text.strip())
        defender_most_life = False
        day_night = re.fullmatch(
            r"(?P<first>day becomes night|night becomes day)(?: or (?P<second>day becomes night|night becomes day))?",
            cond_text.strip(),
        )
        if day_night is not None:
            # RULE 731.1a: this is a global designation, with no object subject.
            event = "DAY_NIGHT_CHANGED"
            condition = {"subject": "global"}
            if day_night.group("second") != {
                "day becomes night": "night becomes day",
                "night becomes day": "day becomes night",
            }[day_night.group("first")]:
                head_trigger = {"filter": {
                    "previous": day_night.group("first").split()[0],
                    "current": day_night.group("first").split()[-1],
                }}
        elif atk_lands is not None:
            event: "str | list[str]" = "ATTACKS"
            condition: Optional[dict[str, Any]] = {"subject": "self"}
            defender_lands_min = int(atk_lands.group("n"))
        elif atk_most_life is not None:
            event = "ATTACKS"
            condition = {"subject": "self"}
            defender_most_life = True
        elif multi is not None:
            event = [_multi_event_name(multi.group("v1")), _multi_event_name(multi.group("v2"))]
            if not all(event):
                return Segment(raw=raw)  # an unrecognised verb → fail closed
            condition = {"subject": "self"}
        elif attached_multi is not None:
            # "whenever enchanted creature attacks or blocks, …" (RULE
            # 303.4c) — one trigger, two firing events, on the Aura's host.
            event = [
                _multi_event_name(attached_multi.group("v1")),
                _multi_event_name(attached_multi.group("v2")),
            ]
            if not all(event):
                return Segment(raw=raw)
            condition = {"subject": "attached_permanent"}
        else:
            event = _trigger_event(cond_text)
            condition = _trigger_condition(cond_text) if event is not None else None
            if event is None or condition is None:
                # PAR-119: the composed object head — subject noun phrase ×
                # verb(s) × tails — for whatever the per-adjective regexes
                # above did not name. Only reached when they declined, so no
                # line they already claim changes.
                head = parse_object_trigger_head(cond_text)
                if head is None:
                    compound = (
                        None if limit else _compound_trigger_segment(
                            raw, cond_text, trig.group("body"),
                            allow_spell_effect=allow_spell_effect, provenance=provenance,
                        )
                    )
                    # unrecognised trigger/scope → unclaimed (fail-closed)
                    return compound if compound is not None else Segment(raw=raw)
                event, condition, head_trigger = head.event, head.condition, head.trigger
                composed_head = True
        body, optional = peel_optional(trig.group("body"))
        if event == "DIES":
            delayed_return = delayed_dying_return_specs(body)
            if delayed_return is not None:
                return Segment(raw=raw, spec=AbilitySpec(
                    "triggered", effects=delayed_return,
                    trigger={"event": event, "condition": condition,
                             **({"limit": True} if limit else {}),
                             **head_trigger},
                    optional=optional, raw_text=raw, parser=provenance,
                ), claimed=True)
        # A group DAMAGE head aimed at a creature introduces two object
        # referents: the dealer and the recipient.  The delayed-sacrifice
        # body's bare "it"/"that creature" means the recipient on cards such
        # as Sosuke, but the current referent model can only capture the firing
        # subject.  Preserve the legacy row's fail-closed guard during the
        # PAR-131 migration rather than silently destroying the dealer.
        damage_pronoun = (
            DELAYED_SAC_EXILE_TAIL_RE.fullmatch(body.strip().rstrip(".").strip())
            if composed_head and event == "DAMAGE"
            and (condition or {}).get("subject") == "group"
            and head_trigger.get("filter", {}).get("is_player") is False
            else None
        )
        if damage_pronoun is not None and damage_pronoun.group("obj"):
            return Segment(raw=raw)
        death_counter_branch = (
            _LEAVING_COUNTER_IF_ELSE_RE.fullmatch(body)
            if event == "DIES" and (condition or {}).get("subject") == "self"
            else None
        )
        if death_counter_branch is not None:
            kind = death_counter_branch.group("kind").lower()
            effects = [EffectSpec("if_else", {
                "condition": {"kind": "trigger_event_counters", "counter": kind, "min": 1},
                "then": [EffectSpec("exile", {"target_kind": None}).to_dict()],
                "else": [EffectSpec("return_self_to_battlefield", {
                    "under_your_control": True,
                    "extra_counters": {"kind": kind, "count": 1},
                }).to_dict()],
            })]
            return Segment(raw=raw, spec=AbilitySpec(
                "triggered", effects=effects,
                trigger={"event": event, "condition": condition},
                raw_text=raw, parser=provenance,
            ), claimed=True)
        event_counter_gate: Optional[dict[str, Any]] = None
        if event in ("DIES", "LEAVES_BATTLEFIELD"):
            counter_if = _LEAVING_COUNTER_INTERVENING_RE.match(body)
            if counter_if is not None:
                kind = counter_if.group("kind")
                if kind in (None, "+1/+1", "-1/-1", "time", "loyalty", "lore", "finality"):
                    event_counter_gate = {
                        **({"kind": kind} if kind else {}),
                        "max" if counter_if.group("no") else "min": (
                            0 if counter_if.group("no") else int(counter_if.group("count") or 1)
                        ),
                    }
                    body = counter_if.group("rest").strip()
        # PAR-120: "that many"/"where x is the number of counters on that
        # creature" behind the gate — see `_LEAVING_COUNTER_THAT_MANY_RE`.
        event_counter_amount: Optional[dict[str, Any]] = None
        if event_counter_gate is not None:
            # The measured body is bound as one effect (`_bind_x`), so a
            # "you may" behind the gate becomes the ability's own optional —
            # only then; an unmeasured body keeps its parse unchanged.
            measured, measured_optional = (
                peel_optional(body) if not optional else (body, optional)
            )
            where_x = _LEAVING_COUNTER_WHERE_X_RE.match(measured)
            if where_x is not None:
                counter = where_x.group("kind") or ""
                body, optional = where_x.group("rest").strip(), measured_optional
                event_counter_amount = {"kind": "trigger_event_counter",
                                        **({"counter": counter} if counter else {})}
            elif _LEAVING_COUNTER_THAT_MANY_RE.search(measured):
                body = _LEAVING_COUNTER_THAT_MANY_RE.sub("x", measured, count=1)
                optional = measured_optional
                # "that many" names what the gate counted: its own kind, or all.
                counter = event_counter_gate.get("kind") or ""
                event_counter_amount = {"kind": "trigger_event_counter",
                                        **({"counter": counter} if counter else {})}
        # PAR-98: Meanders Guide's optional tap is the antecedent for a
        # following "When you do" trigger.  Keep the pair together before
        # the ordinary optional wrapper can turn it into two unrelated
        # clauses.
        # `peel_optional` deliberately leaves this "you may" in place (its
        # guard protects `MAY_EFFECT_THEN_ANTECEDENT_PHRASES` shapes), so
        # peel it here — the optionality wraps the whole tap-then-return pair.
        reflexive_tap = _REFLEXIVE_TAP_PEEL_RE.match(body)
        if cond_text.strip() == "~ attacks" and reflexive_tap is not None:
            body = reflexive_tap.group("rest")
            optional = True
            effects = parse_effect_body(body, reading=ClauseReading(self_subject=True))
            if effects is None:
                return Segment(raw=raw)
            return Segment(raw=raw, spec=AbilitySpec(
                "triggered", effects=effects,
                trigger={"event": "ATTACKS", "condition": {"subject": "self"}},
                optional=optional, raw_text=raw, parser=provenance,
            ), claimed=True)
        # RULE 603.4 intervening-if prefix on an "~ attacks a player"
        # trigger — "…, if no opponent has more life than that player, …"
        # (Guild Artisan &c). Only for a self-subject ATTACKS trigger;
        # strip it, parse the rest, and gate the trigger on the attacked
        # player's life via `attacked_player_has_lowest_life`.
        attacked_lowest_life = False
        if event == "ATTACKS" and condition == {"subject": "self"}:
            low_m = _ATTACKED_PLAYER_LOWEST_LIFE_IF_RE.match(body.strip())
            if low_m is not None:
                attacked_lowest_life = True
                body = low_m.group("rest")
        # PAR-120: "whenever a creature attacks 1 of your opponents, **that
        # player** loses/gains N life." (Calculating Lich). Caught here,
        # before the generic group-subject dispatch below: that dispatch's
        # own "its controller"/"that player" family (`_group_its_
        # controller_loses_life`) means the *attacking* creature's
        # controller (RULE 603.1's own group referent, "entering"), which
        # is the wrong side of this attack — RULE 506.4's defending player
        # is a distinct event field, so this shape needs its own referent
        # rather than reusing that one under the same printed pronoun.
        if (condition or {}).get("attacks_opponent"):
            attacked_player_life = _ATTACKS_OPPONENT_THAT_PLAYER_LIFE_RE.match(body.strip())
            if attacked_player_life is not None:
                verb = attacked_player_life.group("verb")
                effect_type = "lose_life" if verb == "loses" else "gain_life"
                effects = [EffectSpec(effect_type, {
                    "amount": int(attacked_player_life.group("n")),
                    "player": {"of": "attacked_player"},
                })]
                return Segment(raw=raw, spec=AbilitySpec(
                    "triggered", effects=effects, trigger={"event": event, "condition": condition},
                    raw_text=raw, parser=provenance,
                ), claimed=True)
        # "When ~ enters, **it** fights …": with the source as the trigger's
        # own subject, a bare "it" in the body is the source — anything else
        # (a group subject, an attached permanent) leaves the pronoun
        # ambiguous, so only this scope unlocks it. MEC-28: "whenever a
        # creature you control attacks alone, … that creature …" is the
        # `{"subject": "group"}` sibling — `condition` may carry extra keys
        # (``controller``/``type``/…) alongside it, so this reads the key
        # rather than requiring an exact dict match the way ``self_subject``
        # does above.
        copy_departed = (
            _LEAVING_COUNTER_COPY_RE.fullmatch(body)
            if event_counter_gate is not None else None
        )
        delayed_copy = (
            _LEAVING_COUNTER_DELAYED_COPY_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        create_transfer = (
            _LEAVING_COUNTER_CREATE_TRANSFER_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        return_without_abilities = (
            _LEAVING_COUNTER_RETURN_LOSE_RE.fullmatch(body)
            if event_counter_gate is not None and (condition or {}).get("subject") == "self"
            else None
        )
        if create_transfer is not None:
            created = parse_effect_body(create_transfer.group("create"))
            if not created or len(created) != 1 or created[0].type != "create_token":
                return Segment(raw=raw)
            effects = [*created, EffectSpec("transfer_event_counters", {
                "target_kind": "created",
            })]
        elif return_without_abilities is not None:
            effects = [EffectSpec("return_self_to_battlefield", {
                "lose_all_abilities": True,
            })]
        elif delayed_copy is not None:
            # The end-step trigger no longer sees the DIES event, so this
            # ability pins the departed object and half its counters now
            # (RULE 603.7c, RULE 107.2 rounding down) for the delayed copy.
            kind = delayed_copy.group("kind")
            effects = [EffectSpec("bind", {
                "name": "id", "amount": {"kind": "trigger_event", "field": "instance_id"},
                "effects": [EffectSpec("bind", {
                    "name": "half",
                    "amount": {"kind": "trigger_event_counter", "counter": kind, "divide": 2},
                    "effects": [EffectSpec("create_delayed_trigger", {
                        "step": "end", "scope": "any",
                        "effects": [EffectSpec("copy_permanent", {
                            "count": 1, "target_kind": None, "target_instance_id": "$id",
                            "enter_counters": {kind: "$half"},
                        }).to_dict()],
                    }).to_dict()],
                }).to_dict()],
            })]
            event_counter_amount = None  # measured here, not by `_bind_x`
        elif copy_departed is not None:
            # RULE 400.7: a dying object's snapshot is the copy referent;
            # the ability source may have changed zones before resolution.
            effects = [EffectSpec("copy_permanent", {
                "count": int(copy_departed.group("count")), "target_kind": None,
                "referent": "trigger_event",
            })]
        else:
            # A batch (RULE 603.2c) has no one firing object, so its body gets no
            # single-object pronoun reading at all ("it" stays unclaimed).
            if (condition or {}).get("subject") == "group" and not _CARD_INTRODUCER_RE.search(body):
                # "whenever a creature you control dies, return **that card** to its owner's
                # hand": the card is the object that fired the trigger, the same referent "it" is.
                body = re.sub(r"\bthat card\b(?!')", "it", body)
            group_pronoun_names_source = (
                (condition or {}).get("subject") == "group" and _pronoun_continues_source(body.lower())
            )
            # "~ or another creature you control enters, **that creature** gets +2/+2": whichever of
            # the two fired it, a *named* pronoun is that object; a bare "it" could as well be "~", so
            # the composed head still refuses it.
            composed_names_firing = (
                (condition or {}).get("subject") == "self_or_group"
                and _BARE_IT_RE.search(body.lower()) is None
                and not _pronoun_continues_source(body.lower())
            )
            body_reading = ClauseReading(
                # "put a +1/+1 counter on ~. It gains flying": the "it" is the source the
                # sentence just named, so the body reads as a self-subject one.
                self_subject=(condition or {}).get("subject") in ("self", "you", "player")
                or group_pronoun_names_source,
                group_subject=bool(
                    ((condition or {}).get("subject") == "group" or composed_names_firing)
                    and event != "EVENT_BATCH" and "contributors" not in head_trigger
                    and not group_pronoun_names_source
                ),
                attached_subject=(condition or {}).get("subject") == "attached_permanent",
            )
            effects = (
                _event_player_body(body)
                if isinstance(event, str) and event in _ATTACKING_PLAYER_EVENTS
                and (condition or {}).get("subject") == "player" else None
            ) or parse_effect_body(body, reading=body_reading)
            count_amount = _HEAD_COUNT_AMOUNTS.get(event) if isinstance(event, str) else None
            if effects is None and count_amount is not None and _THAT_MANY_RE.search(body):
                # "put that many +1/+1 counters on ~" off a counting head: the body read
                # with a literal X (every X-capable verb already takes one), X bound to
                # the head's own count — not one "that many" row per verb.
                x_effects = parse_effect_body(_THAT_MANY_RE.sub("x", body), reading=body_reading)
                effects = _bind_x(x_effects, count_amount) if x_effects else None
        if effects is None:
            return Segment(raw=raw)
        if event_counter_amount is not None:
            effects = _bind_x(effects, event_counter_amount)
            if effects is None:
                return Segment(raw=raw)
        if (composed_head and event == "DAMAGE" and (condition or {}).get("subject") == "group"
                and head_trigger.get("filter", {}).get("is_player") is True
                and _THAT_PLAYER_BODY_RE.match(body.strip())):
            effects = _retarget_that_player_to_damaged(effects)
            if effects is None:
                return Segment(raw=raw)
        stamped = _stamp_group_pronoun(condition, body, effects)
        if stamped is None:
            return Segment(raw=raw)
        effects = stamped
        if composed_head and _group_it_would_hit_source(condition, body, effects):
            return Segment(raw=raw)
        if event == "PLAYER_ATTACKED" and _reads_event_amount(effects):
            # "Whenever one or more creatures you control attack, … that much/many" (Grand Warlord Radha, Ohran
            # Viper-shaped): `PLAYER_ATTACKED` fires once per defender and carries no amount, so the count is read off
            # the whole declaration instead (`ATTACKERS_DECLARED`). A group-filtered head has no equivalent: fail closed.
            if condition.get("group_filter"):
                return Segment(raw=raw)
            event = "ATTACKERS_DECLARED"
            head_trigger = {"attackers_declared": {"filter": {"card_type": "creature"}, "min": 1}}
        if event == "ATTACKERS_DECLARED":
            effects = _bind_attack_count(effects)
            if effects is None:
                return Segment(raw=raw)
        if event != "EVENT_BATCH" and "'batch_members'" in repr(effects):
            return Segment(raw=raw)  # "them" names a batch only under a batch head
        if event == "EVENT_BATCH":
            if "trigger_subject" in repr(effects) or "__group_subject__" in repr(effects):
                return Segment(raw=raw)  # no single firing object to name
            effects = _bind_attack_count(effects, _BATCH_COUNT_AMOUNT)
            if effects is None:
                return Segment(raw=raw)
        if composed_head:
            effects = _retarget_block_relation(event, head_trigger, effects)
        if "'trigger_related': True" in repr(effects) and "'related_filter'" not in repr(effects):
            return Segment(raw=raw)  # "that creature" of a block relation, under a head that has no other side
        effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
        limit = limit or body_limit
        intervening = _etb_intervening_if(event, condition, body)
        if intervening is not None:
            head_trigger = {**head_trigger, "active_if": intervening}
            # What was spent to cast the permanent is history: it cannot change between the trigger event and the
            # resolution, so the second RULE 603.4 check can only agree with the first — and, read off a source that
            # has since left the battlefield (a new object, RULE 400.7, with nothing spent), it would wrongly
            # disagree where last-known information (RULE 608.2h) says it was spent. One check, at trigger time.
            if intervening.get("kind") == "mana_color_spent_to_cast_at_least":
                effects = [
                    EffectSpec(e.type, e.params, condition=None if e.condition == intervening else e.condition)
                    for e in effects
                ]
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": event,
                "condition": condition,
                **({"limit": True} if limit else {}),
                **({"defender_controls_lands_at_least": defender_lands_min}
                   if defender_lands_min else {}),
                **({"attacked_player_has_lowest_life": True}
                   if attacked_lowest_life else {}),
                **({"attacked_player_has_most_life": True}
                   if defender_most_life else {}),
                **({"event_counter_gate": event_counter_gate}
                   if event_counter_gate is not None else {}),
                **head_trigger,
                # RULE 605.1b: a trigger off a mana ability whose body only adds mana is
                # itself a mana ability — it resolves at once, never on the stack.
                **({"mana_ability": True}
                   if event == "TAPPED_FOR_MANA" and effects
                   and all(e.type in _MANA_ADDING_EFFECTS for e in effects) else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)
    return None


# No trigger wrapper. On a *permanent*, "As ~ enters, choose a creature
# type/color" (RULE 601.2b) is a characteristic-defining choice made as
# part of entering — an ``enter_replacement`` ability (RULE 614.1c/
# 614.12's family, not a triggered ability and not `static_effect_specs`'
# standing-continuous-ability shape either), tried first since it's a
# narrower, closed pair of clauses.
def _line_permanent_standing_line(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if not allow_spell_effect:
        enter_choice = enter_choice_specs(raw)
        if enter_choice is not None:
            spec = AbilitySpec(
                "enter_replacement", effects=enter_choice, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        # A standing "Creatures you control get +1/+1" / "Goblins you
        # control have haste" is a static continuous ability (RULE 613), not
        # a resolve-time effect — try that before giving up.
        static = static_effect_specs(raw)
        if static is not None:
            spec = AbilitySpec(
                standing_ability_kind(static), effects=static, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        # A standing "if X would Y, Z instead" line (RULE 614/616) is a
        # replacement effect, not a static continuous ability — tried after
        # `static_effect_specs` (the two never overlap in shape) before
        # giving up.
        replacement = replacement_clause_specs(raw)
        if replacement is not None:
            spec = AbilitySpec(
                "replacement", effects=replacement, raw_text=raw, parser=provenance
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        return Segment(raw=raw)  # permanent bare imperative → unclaimed
    return None


# RULE 601.2f "This spell costs {N} less to cast if `<condition>`."/
# "…for each attacking creature [you control]." — a spell's own self
# cost reduction, printed on an instant/sorcery rather than a
# permanent. `continuous.self_cost_reduction_for` already reads this
# off *any* object's `static_effects` regardless of zone (Ghostfire
# Slice's own hand-authored entry proves the engine side works) — the
# only missing piece was ever reaching `static_effect_specs` at all
# for a card where `allow_spell_effect` is true, since every clause
# below this point is otherwise routed to the resolve-time
# `spell_effect` parse instead. Scoped to a pure ``cost_reduction``
# result so an unrelated static-shaped false match can't misfile a
# genuine resolve-time clause here.
def _line_spell_cost_static(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    allow_spell_effect = ctx.allow_spell_effect
    provenance = ctx.provenance
    if allow_spell_effect:
        cost_static = static_effect_specs(raw)
        if cost_static is not None and (
            all(spec.type == "cost_reduction" and spec.params.get("affects") == "self" for spec in cost_static)
            or all(spec.type == "grant_graveyard_to_library_replacement" for spec in cost_static)
        ):
            spec = AbilitySpec("static", effects=cost_static, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)
    return None


# A resolve-time effect (instant/sorcery only).
def _line_spell_effect_imperative(ctx: LineContext) -> Optional[Segment]:
    raw = ctx.raw
    provenance = ctx.provenance
    body, optional = peel_optional(raw)
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


LINE_MATCHERS: tuple[LineMatcher, ...] = (
    LineMatcher("neither_day_nor_night", _line_neither_day_nor_night),
    LineMatcher("kw_labeled", _line_kw_labeled),
    LineMatcher("equip_dash", _line_equip_dash),
    LineMatcher("equip_once_each_turn", _line_equip_once_each_turn),
    LineMatcher("etb_and_cast", _line_etb_and_cast),
    LineMatcher("play_with_top_revealed", _line_play_with_top_revealed),
    LineMatcher("meld_trig", _line_meld_trig),
    LineMatcher("attack_meld", _line_attack_meld),
    LineMatcher("wordy", _line_wordy),
    LineMatcher("magecraft", _line_magecraft),
    LineMatcher("counter_free_spell", _line_counter_free_spell),
    LineMatcher("enters_if_cast", _line_enters_if_cast),
    LineMatcher("enters_if_madness", _line_enters_if_madness),
    LineMatcher("cast_spell_not_their_turn_trig", _line_cast_spell_not_their_turn_trig),
    LineMatcher("cast_spell_no_mana_trig", _line_cast_spell_no_mana_trig),
    LineMatcher("cast_spell_targets_src", _line_cast_spell_targets_src),
    LineMatcher("cast_spell_shares_type", _line_cast_spell_shares_type),
    LineMatcher("cast_spell_targets_perm", _line_cast_spell_targets_perm),
    LineMatcher("two_color_cast", _line_two_color_cast),
    LineMatcher("cast_this_spell_trig", _line_cast_this_spell_trig),
    LineMatcher("draw_trig_plain", _line_draw_trig_plain),
    LineMatcher("reveal_first", _line_reveal_first),
    LineMatcher("draw_trig_nth", _line_draw_trig_nth),
    LineMatcher("tap_mana_trig", _line_tap_mana_trig),
    LineMatcher("doctor_or_companion_trig", _line_doctor_or_companion_trig),
    LineMatcher("composed_cast", _line_composed_cast),
    LineMatcher("cycle_trig", _line_cycle_trig),
    LineMatcher("caused_discard_replacement", _line_caused_discard_replacement),
    LineMatcher("caused_discard", _line_caused_discard),
    LineMatcher("exert_bare", _line_exert_bare),
    LineMatcher("exert_trig", _line_exert_trig),
    LineMatcher("exert_player_trig", _line_exert_player_trig),
    LineMatcher("sacrifice_trig", _line_sacrifice_trig),
    LineMatcher("control_none_matching", _line_control_none_matching),
    LineMatcher("control_none_sac", _line_control_none_sac),
    LineMatcher("alt_cost_exile_hand_color", _line_alt_cost_exile_hand_color),
    LineMatcher("alt_cost_sacrifice_filter", _line_alt_cost_sacrifice_filter),
    LineMatcher("alt_cost_sacrifice_type", _line_alt_cost_sacrifice_type),
    LineMatcher("alt_cost_return_two", _line_alt_cost_return_two),
    LineMatcher("alt_cost_pay_life_if_control_land", _line_alt_cost_pay_life_if_control_land),
    LineMatcher("alt_cost_pay_mana_if_attacking", _line_alt_cost_pay_mana_if_attacking),
    LineMatcher("alt_cost_pay_mana_if_you_attacked", _line_alt_cost_pay_mana_if_you_attacked),
    LineMatcher("alt_cost_pay_mana", _line_alt_cost_pay_mana),
    LineMatcher("alt_cost_sacrifice_if_control_land", _line_alt_cost_sacrifice_if_control_land),
    LineMatcher("alt_cost_tap_creature_if_control_land", _line_alt_cost_tap_creature_if_control_land),
    LineMatcher("alt_cost_pay_mana_and_return_land", _line_alt_cost_pay_mana_and_return_land),
    LineMatcher("alt_cost_sacrifice_count", _line_alt_cost_sacrifice_count),
    LineMatcher("alt_cost_exile_hand_color_count", _line_alt_cost_exile_hand_color_count),
    LineMatcher("alt_cost_exile_hand_if_not_your_turn", _line_alt_cost_exile_hand_if_not_your_turn),
    LineMatcher("alt_cost_pay_life_and_exile_hand", _line_alt_cost_pay_life_and_exile_hand),
    LineMatcher("alt_cost_discard_land", _line_alt_cost_discard_land),
    LineMatcher("alt_cost_pay_mana_if_treasure", _line_alt_cost_pay_mana_if_treasure),
    LineMatcher("cast_mana_source_restriction", _line_cast_mana_source_restriction),
    LineMatcher("collect_evidence_discount", _line_collect_evidence_discount),
    LineMatcher("additional_cost_line", _line_additional_cost_line),
    LineMatcher("declare_attackers_if_attacked", _line_declare_attackers_if_attacked),
    LineMatcher("combat_cast_only", _line_combat_cast_only),
    LineMatcher("before_blockers_cast_only", _line_before_blockers_cast_only),
    LineMatcher("cast_only_if_another_color", _line_cast_only_if_another_color),
    LineMatcher("conditional_flash_for_mana", _line_conditional_flash_for_mana),
    LineMatcher("flash_then_cleanup_sac", _line_flash_then_cleanup_sac),
    LineMatcher("spell_free_cast_conditions", _line_spell_free_cast_conditions),
    LineMatcher("saga_chapter", _line_saga_chapter),
    LineMatcher("loyalty_ability", _line_loyalty_ability),
    LineMatcher("activated_ability", _line_activated_ability),
    LineMatcher("phase_trigger", _line_phase_trigger),
    LineMatcher("triggered_ability", _line_triggered_ability),
    LineMatcher("permanent_standing_line", _line_permanent_standing_line),
    LineMatcher("spell_cost_static", _line_spell_cost_static),
    LineMatcher("spell_effect_imperative", _line_spell_effect_imperative),
)


def _segment_line_unsplit(
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
    ctx = LineContext(
        raw=raw, line=line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    for matcher in LINE_MATCHERS:
        segment = matcher.match(ctx)
        if segment is not None:
            return segment
    return Segment(raw=raw)  # unreachable: the last matcher always returns; unclaimed is the fail-closed fallback


#: "you may pay {E}… . If/When you do, <effect>." (Aether Chaser) / "you
#: may pay {1}. If you do, draw a card." (RULE 118.3's general
#: `pay_cost_then` idiom, Spellbomb-cycle-shaped) / MEC-18's wider "you may
#: sacrifice/discard/pay life `<X>`. When you do, `<effect>`." family / PAR-79
#: seventh increment's "you may return/tap another `<permanent>` you
#: control. If you do, `<effect>`." (`effect_rows.costs_mana_limits._may_effect_then`, via
#: `effect_rows.costs_mana_limits.MAY_EFFECT_THEN_ANTECEDENT_PHRASES`) — every one of these is a
#: *conditioned-on-success* choice `pay_energy_then`/`pay_cost_then`/
#: `optional`(`_may_effect_then`) model with their own interactive
#: machinery, not a whole-ability "you may". Left un-peeled so the full
#: clause reaches `parse_effect_body`'s own handler for whichever shape it
#: is intact (otherwise the ability would be marked doubly-optional *and*
#: the "if you do" gate lost outright — the trailing fragment "`<effect2>`"
#: alone, with no antecedent in front of it, generally can't parse as a
#: sensible effect on its own, so the whole clause silently fails instead
#: of half-modeling it).
#:
#: Deliberately does **not** cover every "you may `<X>`. if/when you do,
#: `<Y>`." shape — `_SACRIFICE_THEN_WHEN_YOU_DO_RE`/
#: `_EXILE_SELF_THEN_DELAYED_RETURN_RE`/`_EARTHBEND_THEN_WHEN_YOU_DO_RE`/
#: `_DISCARD_THEN_IF_YOU_DO_RE` (below) are the mirror-image case: a bare,
#: *certain* self-referential antecedent ("sacrifice ~"/"exile it"/
#: "earthbend N"/"discard a card") that RULE 603.3's "if you do" reduces to
#: an unconditional sequence, and those handlers' own docstrings say so
#: explicitly — they run only *after* `peel_optional` has already stripped
#: the leading "you may " and need that peel, not this guard, so widening
#: this regex to catch every antecedent (tried and reverted) broke all four
#: families (Chaos Spewer/Hikari, Twilight Guardian/Sunfire Torch/Yawgmoth
#: Demon &c.) by preventing the very peel they depend on. This antecedent
#: list must therefore only ever grow to cover a **new interactive**
#: `pay_energy_then`/`pay_cost_then`/`_may_effect_then`-shaped handler, never
#: widen to "any antecedent" — the two families are deliberately disjoint by
#: design (`_pay_cost_then_general`'s own docstring on why its cost
#: vocabulary excludes bare self-sacrifice).
_PAY_ENERGY_THEN_PEEL_GUARD_RE = re.compile(
    r"^you may (?:pay (?:\{e\})+|" + MAY_COST_THEN_CLAUSE + r"|"
    + MAY_EFFECT_THEN_ANTECEDENT_PHRASES + r")\.\s*(?:if|when) you do"
    # PAR-164: "you may exile it. When you do, …" keeps its "may" (`_MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE`).
    r"|^you may exile (?:it|that card|~)\.\s*when you do",
    re.IGNORECASE,
)


#: RULE 603.3's reflexive trigger tail — "…, when you do, `<effect>`" /
#: "…, if you do, `<effect>`". A "you may" body containing one is a choice
#: *plus a trigger*, not a single optional block; see `_MID_BODY_OPTIONAL_RE`'s
#: use site.
_REFLEXIVE_TRIGGER_RE = re.compile(r"\b(?:when|if) you do\b", re.IGNORECASE)


#: PAR-62: RULE 601.2b's "you may `<effect>`" as a *clause* rather than as an
#: ability-level prefix — what `peel_optional` sees only when it leads the
#: whole body. Same shape, read at the other end of the pipeline.
_MID_BODY_OPTIONAL_RE = re.compile(r"^you may\s+(?P<rest>.+)$", re.IGNORECASE | re.S)

#: PAR-117: "its controller may `<effect>`" — the referent-scoped sibling of
#: `_MID_BODY_OPTIONAL_RE` above: the chooser is whichever pronoun referent
#: this body's own subject mode names (RULE 603.1's group-subject firing
#: object, the previous clause's target, or an Aura/Equipment's attached
#: host — never "you", so it can't reuse that row), not this ability's own
#: controller (Edric, Spymaster of Trest/Brood Sliver/Synapse Sliver:
#: "whenever a creature [you control] deals combat damage to a player, its
#: controller may `<effect>`."). Composes the identical ``"optional"`` node
#: `_MID_BODY_OPTIONAL_RE`'s own dispatch does — any effect body "you may"
#: can wrap, "its controller may" can too — just with `OptionalEffect.
#: player` pointed at the active referent instead of defaulting to "you".
_MID_BODY_ITS_CONTROLLER_MAY_RE = re.compile(
    r"^(?:its|that (?:creature|permanent|land|artifact)'s) controller may\s+(?P<rest>.+)$",
    re.IGNORECASE | re.S
)


#: A sentence that opens with the outcome test of an optional/cost clause before it (RULE 608.2c / 603.12).
_IF_YOU_DO_SENTENCE_RE = re.compile(r"\.\s+(?:if|when) you do\b", re.I)


def peel_optional(body: str) -> tuple[str, bool]:
    """Strip a leading "you may " and report whether it was present (RULE 601.2)."""
    body = body.strip()
    if _PAY_ENERGY_THEN_PEEL_GUARD_RE.match(body):
        return body, False
    # PAR-152 (Jocasta): "…, if this card is in your graveyard, you may return it to the battlefield tapped and
    # attacking." — the intervening-if just says where the trigger functions (a graveyard-zone trigger, like
    # Bloodghast's), so it folds into the self-return clause the graveyard rows already read.
    in_graveyard = re.match(
        rf"^if (?:this card|~) is in your graveyard,\s+you may return it to the battlefield(?P<rest>.*)$",
        body, re.S,
    )
    if in_graveyard is not None:
        return f"return this card from your graveyard to the battlefield{in_graveyard.group('rest')}", True
    m = re.match(r"^you may\s+(?P<rest>.+)$", body, re.S)
    if m is not None:
        rest = m.group("rest")
        # PAR-130: the causative spelling "you may **have it deal** N/that
        # much damage …" (Mordant Dragon / Skirk Commando family) changes
        # neither source nor effect. Once the optional wrapper is recorded,
        # fold it to the ordinary self-subject "it deal…" body every damage
        # handler already understands. Narrow to this verb so an unrelated
        # "have <player/object> <do something>" choice stays fail-closed.
        causative_damage = re.match(
            r"^have\s+(?P<subject>it|~|this creature|this permanent)\s+"
            r"(?P<deal>deals?\s+.+)$", rest, re.S,
        )
        if causative_damage is not None:
            rest = f"{causative_damage.group('subject')} {causative_damage.group('deal')}"
        # PAR-175: "you may X. If you do, Y." -- "if you do" is the outcome of the optional X (RULE 608.2c,
        # 603.12), and the peel hands it a body whose first clause no longer says it was optional. When the peeled
        # body cannot be read, the whole sentence pair is the unit (`may_effect_then`); a body the peel already
        # reads keeps its meaning untouched.
        if _IF_YOU_DO_SENTENCE_RE.search(rest) and parse_effect_body(rest) is None and parse_effect_body(body) is not None:
            return body, False
        return rest, True
    return body, False


# The handlers, static handlers and sequence grammars recurse into these entry points through
# `catalogue.clause_hooks` (PAR-172: the one real cycle, broken by late binding, not by imports).
register_segmenter(
    parse_effect_body=parse_effect_body,
    segment_line=segment_line,
    trigger_condition_dict=trigger_condition_dict,
)
