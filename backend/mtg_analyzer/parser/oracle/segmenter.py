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
from dataclasses import dataclass, field
from typing import Any, Optional

from .catalogue.handlers import (
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    FROM_HAND_MARKER,
    ONCE_PER_TURN_MARKER,
    POWERUP_COST_REDUCTION_MARKER,
    TRIGGER_ONCE_PER_TURN_MARKER,
    _CYCLING_XX_TOKEN_RE,
    _cycling_xx_token,
    _MAY_COST_THEN_CLAUSE,
    match_clause,
)
from .catalogue.keywords import ALIAS_DISPLAYS, KEYWORDS, KeywordShape
from .catalogue.replacements import replacement_clause_specs
from .catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from .catalogue.static_handlers import enter_choice_specs, static_effect_specs
from .catalogue.subgrammars import COLOR_WORD_ALT, resolve_color_word
from .spec import AbilitySpec, EffectSpec, ParserProvenance

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
#: Still deliberately absent: "specializes" (a mechanic with no engine
#: primitive at all — see the `MEC` tickets in `BACKLOG.md`). ("Becomes
#: monstrous" is *not* absent — RULE 701.37a's own `BECAME_MONSTROUS` row
#: sits below with the rest of this table; an earlier version of this
#: comment listed it here by mistake.)
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
    ("enters", "ENTERS_BATTLEFIELD"),
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
#: Matched against the *condition* text `_TRIGGER_RE` peels out — i.e. with
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

#: RULE 603.1 trigger conditions whose subject is **the controller**, not an
#: object: "whenever *you* scry", "whenever *you* surveil". No object-verb
#: grammar above can express these — `_TRIGGER_VERBS` is a table of things a
#: *permanent* does, and its whole scoping discipline (a verb earns a row
#: only if the engine fires an event carrying an `instance_id` for it) is
#: about matching the acting object. These events carry a ``player_id``
#: instead, and the scoping question is "was it *me* who scried?".
#:
#: So they get their own table, emitting ``{"subject": "you"}`` for
#: `effect_binder._subject_condition` — which is real scoping, unlike
#: `_VARIANT_TRIGGER_CONDITIONS` (a plane's abilities are only ever
#: collected for the face-up plane, so those need none). Without it, Dimir
#: Spybug would grow a counter when an *opponent* surveiled.
#:
#: Matched against the *condition* text `_TRIGGER_RE` peels out — the
#: leading "when"/"whenever" already stripped. Anchored end-to-end on
#: purpose: "whenever you surveil **for the first time each turn**"
#: (Whispering Snitch) is a once-per-turn qualifier the engine can't
#: express, so it must fail to match and leave the card `UNMODELED` rather
#: than bind an over-firing trigger.
#:
#: The compound "whenever you scry **or** surveil" (Matoya, Archon Elder;
#: Planetarium of Wan Shi Tong) maps to a *list* of two events, handled the
#: same way `_SELF_MULTI_EVENT_RE` and the compound plane template are: one
#: `AbilitySpec` per event, each with its own freshly-bound effects.
_PLAYER_TRIGGER_CONDITIONS: tuple[tuple[re.Pattern[str], Any], ...] = (
    (re.compile(r"^you scry or surveil$"), ["SCRY", "SURVEIL"]),
    (re.compile(r"^you surveil or scry$"), ["SURVEIL", "SCRY"]),
    (re.compile(r"^you scry$"), "SCRY"),
    (re.compile(r"^you surveil$"), "SURVEIL"),
    # "Whenever you gain life, …" (RULE 119.3 — Ajani's Pridemate/Archangel
    # of Thune-shaped lifegain payoffs). `EventType.LIFE_GAINED` already
    # exists as the post-replacement trigger source (`LIFE_GAIN` is the
    # pre-emptive, replaceable half — see its own docstring); only this
    # oracle-text recognition and the matching `effect_binder`
    # `_GROUP_CONTROLLER_EVENT_KEYS` entry were missing.
    (re.compile(r"^you gain life$"), "LIFE_GAINED"),
    # "Whenever you lose life, …" (RULE 118/119, Vilis, Broker of Blood-
    # shaped, MEC-43) — `LIFE_GAINED`'s own loss-side sibling; `LIFE_LOST`
    # already exists as the post-replacement trigger source (`RulesEngine.
    # lose_life`'s single choke point for every cause of life loss,
    # including combat/noncombat damage), so only this oracle-text
    # recognition and the matching `effect_binder` `_GROUP_CONTROLLER_
    # EVENT_KEYS` entry were missing.
    (re.compile(r"^you lose life$"), "LIFE_LOST"),
    # "Whenever the Ring tempts you, …" (RULE 701.51a, Tales of Middle-earth
    # — Aragorn, Company Leader/Galadriel of Lothlórien/Sméagol, Helpful
    # Guide-shaped). `EventType.RING_TEMPTED` fires from `RulesEngine.
    # the_ring_tempts_you` once the Ring-bearer choice is settled.
    (re.compile(r"^the ring tempts you$"), "RING_TEMPTED"),
    # RULE 506.4's "whenever you attack, …" (MEC-28, Karlach, Fury of
    # Avernus-shaped) — the bare form and "whenever you attack **a player**"
    # (Soaring Lightbringer), which only names the defender kind the
    # PLAYER_ATTACKED event doesn't refine (RULE 508.1 — an attack is always
    # at a player or their planeswalker). "whenever you attack with
    # `<qualifier>`" (a much bigger, still-unbuilt family —
    # `parser_probe.py blocked "^whenever you attack\\b"`, 97+ SOLO cards)
    # needs its own count/filter grammar and is out of scope.
    (re.compile(r"^you attack(?: a player)?$"), "PLAYER_ATTACKED"),
    # RULE 603.1's "whenever one or more creatures you control deal combat
    # damage to a player, …" (Professional Face-Breaker-shaped Treasure
    # payoffs) — the bare (no power-threshold) sibling of the hand-
    # authored ``contributor_power_at_least`` cards (Tifa/Kediss); MEC-29's
    # `EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER` already fires for
    # this exact shape, only the oracle-text recognition was missing.
    (re.compile(r"^1 or more creatures you control deal combat damage to a player$"),
     "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"),
    # RULE 701.30: "Whenever you clash, …" (Entangling Trap/Rebellion of the
    # Flamekin) and its favourable-outcome sibling "Whenever you win a
    # clash, …" (Marvo, Deep Operative) / "Whenever you clash and win, …"
    # (Sylvan Echoes — the same WON_CLASH condition, just phrased as the
    # procedure plus its result). `EventType.CLASHED` / `EventType.WON_CLASH`
    # fire from `RulesEngine.clash`; the `CLASHED`/`WON_CLASH` split
    # (mirroring `LIFE_GAIN`/`LIFE_GAINED`) means "win a clash" needs no
    # event ``filter``.
    (re.compile(r"^you clash$"), "CLASHED"),
    (re.compile(r"^you (?:win a clash|clash and win)$"), "WON_CLASH"),
    # RULE 701.59b: "Whenever you collect evidence, …" (Evidence Examiner/
    # Surveillance Monitor). `RulesEngine.collect_evidence` fires
    # `EventType.COLLECTED_EVIDENCE` per-player, same `player_id` convention.
    (re.compile(r"^you collect evidence$"), "COLLECTED_EVIDENCE"),
    # RULE 701.61b: "Whenever you forage, …" (Corpseberry Cultivator/Euru,
    # Acorn Scrounger). `RulesEngine.forage` fires `EventType.FORAGED`
    # per-player.
    (re.compile(r"^you forage$"), "FORAGED"),
    # RULE 701.4b: "Whenever you behold …". No card in the current pool
    # triggers on beholding, but the row keeps the keyword-action family's
    # per-player `player_id` convention ready for one that does.
    (re.compile(r"^you behold(?: an?\s+\w+)?$"), "BEHELD"),
)

#: A triggered-ability wrapper: "When/Whenever/At <condition>, <body>".
_TRIGGER_RE = re.compile(r"^(?:when|whenever|at)\b(?P<cond>[^,]*),\s*(?P<body>.+)$", re.S)

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
    return remaining, len(remaining) != len(effects)

#: RULE ~702.156-ish "ability word" Magecraft — "Magecraft — Whenever you
#: cast or copy an instant or sorcery spell, <effect>." (Professor Onyx/
#: Witherbloom Apprentice-shaped). A dedicated whole-line recognizer rather
#: than the generic `_TRIGGER_RE`/`_trigger_event`/`_trigger_condition`
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

#: RULE 603.1's "Whenever you cast a/an <type>[, <type>, or <type>] spell,
#: <effect>." (Baral, Chief of Compliance/Archmage of Runes/Young Pyromancer-
#: adjacent spellslinger payoffs) — a player-subject trigger whose event
#: needs a card-type filter, so — like `_MAGECRAFT_RE`/`_DAMAGE_TRIGGER_RE`
#: — it gets its own dedicated whole-line recognizer rather than
#: `_PLAYER_TRIGGER_CONDITIONS`'s bare event-name table. `effect_binder`'s
#: ``spell_card_types`` predicate already exists (built for the hand-
#: authored Wandering Archaic) — only the oracle-text recognition was
#: missing. Deliberately narrow to ``you`` as the subject (RULE 603.1's by
#: far most common printed scope for a *typed* filter) — extending it to
#: "an opponent"/"a player" too would need `effect_binder`'s existing group
#: scoping *plus* a card-type filter on a non-permanent event, which no
#: card in scope has needed yet; `_CAST_SPELL_TRIGGER_PLAIN_RE` below is the
#: sibling that already covers all three subjects for the untyped case.
#: Creature *subtypes* ("wizard spell", "elf spell")
#: aren't in `_SPELL_CAST_TYPE_WORDS` — `GameObject.type_words` only ever
#: carries main card types — so a compound naming one fails closed
#: correctly rather than silently dropping the subtype qualifier.
_SPELL_CAST_TYPE_WORDS: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "instant", "sorcery", "planeswalker", "land", "battle"}
)
#: ``subj`` alternation added 2026-08-10 (Bonus Round/Hive Mind's own
#: "whenever **a player** casts an instant or sorcery spell, …" needed it
#: — 354 SOLO cards on this widening alone, `parser_probe.py blocked`,
#: the single biggest template blocker found to date): the untyped sibling
#: (`_CAST_SPELL_TRIGGER_PLAIN_RE`) already proved the "an opponent"/"a
#: player" subjects need no new engine primitive (`effect_binder`'s
#: existing group/controller scoping over `SPELL_CAST`), so this is purely
#: widening the *typed* row's own subject the same way.
_CAST_SPELL_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? (?:an?|another) "
    r"(?P<types>[a-z][a-z,\s]*?) spell,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def _cast_spell_trigger_condition(subj: str) -> dict[str, Any]:
    """``{"subject": …}`` for a cast-spell/draw-card trigger's ``you``/``an
    opponent``/``a player`` subject — shared by every widened row below so
    the three-way mapping (`_CAST_SPELL_TRIGGER_RE`/`_CAST_SPELL_TRIGGER_NEG_RE`/
    `_CAST_SPELL_TRIGGER_PLAIN_RE`/`_CAST_SPELL_TRIGGER_MV_RE`/
    `_DRAW_TRIGGER_PLAIN_RE`) lives in exactly one place."""
    subj = subj.lower()
    if subj == "you":
        return {"subject": "you"}
    if subj == "an opponent":
        return {"subject": "group", "controller": "not_you"}
    return {"subject": "group"}

#: The negated sibling — "Whenever you cast a **noncreature** spell, …"
#: (Young Pyromancer/Shark Typhoon/dozens of "spells matter" payoffs —
#: found to be the single biggest ranked template blocker in the cache,
#: ~92 cards on this shape alone). RULE 603.1 excludes one main card type
#: rather than naming several to include, so it's `effect_binder`'s own
#: predicate (``spell_exclude_card_types``, the mirror of the existing
#: ``spell_card_types`` OR-match) rather than reusing that key with a
#: "negate" flag — the two would otherwise need a third param just to tell
#: them apart. Only ever one excluded type on a real card so far (a
#: compound "noncreature, nonland spell" hasn't been seen) — extend the
#: capture group to a list the day one is.
#: ``subj`` alternation added alongside `_CAST_SPELL_TRIGGER_RE`'s own
#: widening (Cindervines/Kambal, Consul of Allocation-shaped — 67 more SOLO
#: cards): same reasoning, same shared `_cast_spell_trigger_condition`.
_CAST_SPELL_TRIGGER_NEG_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? an? non(?P<type>[a-z]+) spell,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: The *untyped* sibling of `_CAST_SPELL_TRIGGER_RE` — "Whenever you/an
#: opponent/a player casts a spell, <effect>." with no card-type filter at
#: all (Spellshock/Eidolon of the Great Revel-shaped punishers). Doesn't
#: overlap with the typed regex above: that one requires a real word between
#: "a" and "spell" (`(?P<types>[a-z][a-z,\s]*?) spell`), which "a spell"
#: alone never supplies. Unlike the two regexes above, this one also covers
#: the "an opponent"/"a player" subjects — `effect_binder`'s existing
#: ``{"subject": "group", "controller": "not_you"/None}`` scoping already
#: handles any player-keyed event (`_GROUP_CONTROLLER_EVENT_KEYS` maps
#: `SPELL_CAST` to ``"player_id"``, proven working by Smothering Tithe's own
#: `DRAW`-event use of the identical shape), so no new engine primitive is
#: needed here — purely a missing recognizer.
_CAST_SPELL_TRIGGER_PLAIN_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell"
    # "…during an opponent's turn" (Fire Nation Occupation) — the caster
    # isn't the active player, i.e. the trigger's own ``not_controllers_
    # turn`` gate (`effect_binder`, RULE 603.4). "during your turn" has no
    # matching engine gate, so it's deliberately left out (fail-closed).
    r"(?P<opp_turn> during an opponent'?s turn)?,\s*(?P<body>.+)$",
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
#: the trigger's own ``spell_no_mana_spent`` gate (`effect_binder.py`) and
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
_CAST_SPELL_ORDINAL_WORDS: dict[str, int] = {"second": 2, "third": 3, "fourth": 4}
_CAST_SPELL_TRIGGER_NTH_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? (?:your|their) "
    rf"(?P<ordinal>{'|'.join(_CAST_SPELL_ORDINAL_WORDS)}) spell each turn,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

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

#: The mana-value-filtered sibling — "Whenever a player casts a spell with
#: mana value N or less, <effect>." (Eidolon of the Great Revel/Pyrostatic
#: Pillar-shaped). `SPELL_CAST` already carries ``mana_value`` on the event
#: (`_track_spell_cast`'s own read), so `effect_binder`'s
#: ``spell_mana_value_at_most`` predicate is the only new piece.
_CAST_SPELL_TRIGGER_MV_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell with "
    r"mana value (?P<n>\d+) or less,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: A curated whitelist of real creature subtypes for "Whenever you cast an
#: Elf spell, …"-shaped triggers (Lys Alana Huntmaster/Leaf-Crowned
#: Visionary, tribal "spells matter" payoffs — ranked the single biggest
#: template blocker in the whole cache at ~181 cards on the wider "cast a
#: `<word>` spell" shape; this is the safe creature-subtype slice of it).
#: Deliberately a fixed list rather than "any word": `effect_binder`'s
#: `spell_subtype_any` predicate is a bare substring check against the
#: cast object's printed type line, which would *silently* misfire on a
#: non-subtype adjective that happens to appear in some other card's type
#: line ("legendary") or simply never fire on one that never does
#: ("historic"/"kicked"/"multicolored"/"party") — both wrong, and neither
#: caught by the coverage gate, so only genuine creature types go in this
#: list (extend it as a real card needs one, rather than trying to
#: enumerate the ~300-entry official creature-type list up front — no
#: canonical list of those exists in this codebase, per
#: `catalogue.handlers._creature_type_options`'s own docstring).
_CAST_SPELL_SUBTYPE_WORDS: frozenset[str] = frozenset({
    "elf", "goblin", "zombie", "human", "wizard", "merfolk", "vampire",
    "dragon", "angel", "demon", "spirit", "soldier", "knight", "warrior",
    "elemental", "giant", "dwarf", "faerie", "sliver", "rogue", "cleric",
    "shaman", "druid", "beast", "bird", "cat", "dog", "insect", "snake",
    "treefolk", "wolf",
})

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

#: RULE 701.17/603.1's "Whenever you sacrifice a Food, …" (Experimental
#: Confectioner/Trail of Crumbs-shaped Food-matters payoffs) — a player-
#: subject trigger like `_PLAYER_TRIGGER_CONDITIONS`'s bare event-name
#: table, but that table has no way to carry a type filter, and RULE 122.1a
#: "sacrifice a `<type>`" always means *some* type. Scoped to the same
#: closed named-token vocabulary `catalogue.handlers._NAMED_TOKEN_WORDS`
#: already trusts (Treasure/Clue/Food) rather than any noun — a fail-closed
#: choice, not a card-count one: `EventType.SACRIFICE`'s own `object_types`
#: payload (`RulesEngine.put_into_graveyard`) is the *card's printed type
#: line*, so "a permanent" or an arbitrary creature type would need its own
#: (much wider, unverified) matching rules this narrow vocabulary sidesteps.
_SACRIFICE_TYPE_TRIGGER_RE = re.compile(
    r"^whenever you sacrifice an? (?P<type>treasure|clue|food),\s*(?P<body>.+)$",
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


def _parse_cast_spell_types(text: str) -> Optional[list[str]]:
    """``text`` (e.g. "instant or sorcery", "creature, artifact, or
    enchantment") → its card-type word list, or ``None`` if any token isn't
    a recognised main card type (fail-closed)."""
    tokens = [t for t in re.split(r"[,\s]+", text.strip().lower()) if t and t != "or"]
    if not tokens or any(t not in _SPELL_CAST_TYPE_WORDS for t in tokens):
        return None
    return tokens

#: The card-type words a "group" trigger condition can scope to (RULE 613.6-
#: adjacent vocabulary shared with `catalogue.static_handlers`'s anthem
#: selectors) — deliberately small: only what `models/game_object.py`'s
#: `type_words` can check without a subtype grammar. Used by both
#: `_GROUP_SUBJECT_RE` (the object-subject events) and `_DAMAGE_TRIGGER_RE`
#: (RULE 120.3's damage shape) below.
_GROUP_TYPE_WORDS = ("creature", "artifact", "enchantment", "land", "permanent")

#: RULE 120.3's "deals combat damage to a player" (Sword-cycle/Bloodforged
#: Battle-Axe-shaped self-subject trigger) and its "deals combat damage to a
#: creature" (Kaldra Compleat-shaped) sibling — `EventType.DAMAGE` filtered to
#: ``{"combat": bool, "is_player": bool}``, mirroring exactly what
#: `effect_binder._trigger_condition`'s ``"filter"`` docstring already
#: documents for the hand-authored Sword-cycle entries; only the parser
#: recognition was missing. A dedicated bypass (checked before the generic
#: `_TRIGGER_RE` dispatch, like `_MAGECRAFT_RE` above) since neither the
#: verb phrase nor its filter fit the single-word `_TRIGGER_EVENTS`/
#: `_trigger_condition` vocabulary. Two subject shapes:
#:
#: * ``~`` (folded from the card's own name/"this creature" by `normalize`)
#:   — an ordinary ``{"subject": "self"}`` condition.
#: * "a/an/another <type> [you control]" (Bident of Thassa/Deepfathom
#:   Skulker/Cazur-shaped) — RULE 603.1's ``{"subject": "group"}``, the same
#:   closed `_GROUP_TYPE_WORDS` vocabulary `_GROUP_SUBJECT_RE` uses, with
#:   "you control" optional exactly as it is there. Every *qualified*
#:   variant ("a **modified**/**renowned**/**historic** creature you
#:   control", "a creature you control **with deathtouch**") stays
#:   unclaimed — the type word is a closed list and the regex is anchored,
#:   so the qualifier simply fails to match (fail-closed).
#: * "enchanted/equipped <noun>" (the Sword-of-X-and-Y cycle) — RULE
#:   303.4/301.5's ``{"subject": "attached_permanent"}``, the same subject
#:   `_ATTACHED_SUBJECT_RE` maps for the enters/dies/attacks/blocks verbs.
#:   Previously these cards reached the engine only through the
#:   hand-authored catalogue.
#:
#: DAMAGE's subject key is ``source_id`` and its group-controller key is
#: ``source_controller_id`` (`effect_binder._SUBJECT_EVENT_KEYS`/
#: `_GROUP_CONTROLLER_EVENT_KEYS`) — the damage event names its *source*, not
#: an `instance_id`/`controller_id` the way the RULE 603.1 object-subject
#: events do.
_DAMAGE_TRIGGER_RE = re.compile(
    r"^whenever (?:"
    r"(?P<self>~)"
    r"|(?P<attached>(?:enchanted|equipped) (?:creature|permanent|land|artifact))"
    r"|(?P<article>another|an|a) (?P<goaded>goaded )?(?P<type>"
    + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<yours> you control)?"
    # RULE 310: "…to a player or battle" (Furnace Reins-shaped) — the battle
    # case rides the same ``{"is_player": true}`` DAMAGE filter (a documented
    # simplification: the far commoner player-damage firing is exact; battle
    # damage as an extra trigger source isn't separately modelled). The whole
    # "to <recipient>" is optional: a bare "deals damage" (Shackles of
    # Treachery's granted trigger) matches *any* damage instance, so the
    # dispatch below omits the ``is_player`` key entirely in that case.
    r") deals (?P<combat>combat )?damage"
    r"(?: to (?:an?|1 of your) (?P<recipient>player|opponent|creature)s?(?: or battle)?)?,"
    r"\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 603.1's *recipient* side of a damage trigger (MEC-11, Enrage-shaped:
#: "Enrage — Whenever ~ is dealt damage, …", the ability-word label already
#: stripped by `normalize._strip_ability_words` before this ever runs) —
#: `_DAMAGE_TRIGGER_RE`'s mirror image, same subject grammar (self/attached/
#: group over `_GROUP_TYPE_WORDS`), opposite direction: the object *taking*
#: the damage, not dealing it. Far more cards use this shape than print the
#: "Enrage —" label (Boros Reckoner/Brash Taunter/Fungusaur-shaped self
#: triggers, Rite of Passage's "a creature you control", a Sword-cycle-
#: adjacent "equipped creature" family) — the grammar is general RULE 603.1
#: recognition, not an Enrage-specific carve-out, so it's not gated on the
#: label at all. No recipient-side "to a player/opponent" analogue exists
#: (nothing prints "whenever a player is dealt damage" — that would be a
#: player-subject condition, a different, unbuilt vocabulary — so unlike
#: `_DAMAGE_TRIGGER_RE` there is no ``recipient`` group here to parse).
#: The ``condition["recipient"] = True`` marker is what tells
#: `effect_binder._subject_event_key`/`_group_controller_event_key` to read
#: `target_id`/`target_controller_id` off the `DAMAGE` event instead of the
#: `source_id`/`source_controller_id` the "deals damage" family above reads.
_DAMAGE_RECIPIENT_TRIGGER_RE = re.compile(
    r"^whenever (?:"
    r"(?P<self>~)"
    r"|(?P<attached>(?:enchanted|equipped) (?:creature|permanent|land|artifact))"
    r"|(?P<article>another|an|a) (?P<type>"
    + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<yours> you control)?"
    r") is dealt (?P<combat>combat )?damage,\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: MEC-19/RULE 115/601.2c's "becomes the target of a spell/ability" trigger
#: condition (`EventType.BECOMES_TARGET`) — Goldspan Dragon/Tectonic Giant's
#: own "attacks or becomes the target of a spell", and, far more numerously,
#: a ~150-card cycle that prints Ward's exact RULE 702.21a outcome
#: ("counter it unless that player pays `<cost>`") as an ordinary triggered
#: ability instead of the Ward keyword — those cards have no "Ward" word
#: anywhere in their text, so the keyword catalogue can never reach them.
#: Same self/attached/group subject grammar as `_DAMAGE_TRIGGER_RE` above,
#: plus two qualifiers this family always prints and that shape never needs:
#:
#: * ``item_kind`` — "of a spell"/"of a spell or ability"/"of an ability",
#:   fed straight to the ordinary ``"filter"`` exact-match mechanism
#:   (`BECOMES_TARGET`'s own ``item_kind`` payload) rather than a bespoke
#:   predicate. A more specific object ("of an Aura spell", "of an instant
#:   or sorcery spell", "of a backup ability") isn't in this closed
#:   alternation on purpose — matching it here would require re-deriving
#:   the *cast* object's own card-type/subtype at `BECOMES_TARGET`-fire
#:   time, a genuinely separate lookup `cast_of_color`/`spell_card_types`
#:   need a live `state.find_object` for; those clauses stay unclaimed
#:   (fail-closed) rather than guessed at.
#: * ``caster_relation`` — "an opponent controls"/"you control", optional
#:   (unscoped when absent) — `effect_binder._trigger_condition`'s new
#:   ``caster_relation`` predicate, comparing `BECOMES_TARGET`'s
#:   ``controller_id`` (the *caster*, not the target) against the ability's
#:   own source.
#:
#: A trailing "**for the first time each turn**" (Angelic Cub/Heartfire
#: Hero-shaped) is RULE 603.2's per-source once-a-turn cap — the exact
#: primitive `TRIGGER_ONCE_PER_TURN_MARKER` already folds into
#: `TriggeredAbility.once_per_turn` for a *trailing-sentence* phrasing;
#: here the qualifier is embedded in the condition clause itself, so it's
#: set directly as ``trigger["limit"]`` rather than round-tripped through
#: that marker.
#:
#: Deliberately excludes the player-subject/compound "you or a permanent
#: you control becomes the target…" shape (Leovold, Rayne, Surrak, Unsettled
#: Mariner, Parnesse) — a genuinely different, unbuilt compound-subject
#: grammar (BACKLOG.md) — and any group subject qualified by a *subtype*
#: word rather than `_GROUP_TYPE_WORDS`'s closed main-type list ("a Dragon
#: you control becomes the target…", Thunderbreak Regent/Dragon's
#: Disciple/Scalelord Reckoner/Svyelun-shaped): those stay unclaimed.
_BECOMES_TARGET_TRIGGER_RE = re.compile(
    # "When" and "whenever" are interchangeable here — the ~19-card
    # Illusion cycle (Phantasmal Bear, Frost Walker, Skulking Ghost, …)
    # prints "When ~ becomes the target …, sacrifice it.", and a
    # self-sacrifice on becoming a target behaves identically either way
    # (the permanent is gone after the first firing).
    r"^when(?:ever)? (?:"
    r"(?P<self>~)"
    r"|(?P<attached>(?:enchanted|equipped) (?:creature|permanent|land|artifact))"
    r"|(?P<article>another|an|a) (?P<type>"
    + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<yours> you control)?"
    r") becomes the target of an? (?P<item_kind>spell or ability|spell|ability)"
    r"(?P<caster_rel> an opponent controls| you control)?"
    r"(?P<once> for the first time each turn)?"
    r",\s*(?P<body>.+)$",
    re.IGNORECASE,
)

#: RULE 500.7's "at the beginning of the [upkeep/draw/end/…] step" turn-
#: structure trigger family — a genuinely common template distinct from
#: RULE 603.1's object-subject "when/whenever X enters/dies/attacks/blocks"
#: shape `_trigger_condition` handles above, so it's a separate, dedicated
#: recognizer (checked before the generic `_TRIGGER_RE` dispatch, which
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
    r"^(?:~|it) deals (?P<n>\d+) damage to them\.?\s*$", re.IGNORECASE,
)

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

_PHASE_TRIGGER_RE = re.compile(
    r"^at the beginning of (?:"
    # "each player's upkeep" reads exactly like "each upkeep" to this engine
    # — every player's turn has one — so it shares the unscoped branch.
    rf"(?:the|each)(?: player'?s)? (?P<step_any>{_PHASE_STEP_ALT})(?:\s+step)?"
    rf"|your (?P<step_you>{_PHASE_STEP_ALT})(?:\s+step)?"
    # "at the beginning of each of your postcombat main phases" — the plural
    # form of the "your <phase>" row above, same meaning.
    rf"|each of your (?P<step_you_each>{_PHASE_STEP_ALT})s?(?:\s+steps?)?"
    # RULE 507's own idiom: the phase is named, the scope trails it.
    r"|(?P<step_combat_you>combat) on your turn"
    rf"|each opponent'?s (?P<step_opp>{_PHASE_STEP_ALT})(?:\s+step)?"
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

#: RULE 508.3a's batch attack trigger: "whenever **one or more** [<filter>]
#: creatures you control attack[ a player], …" (Winota / A-Winota, Angelic
#: Guardian, Ancestor Dragon, Alibou, …). Fires once per combat, not per
#: attacker — the engine's `EventType.PLAYER_ATTACKED` aggregate already has
#: exactly that shape (one firing per (attacking player, defender) group),
#: so this maps onto ``{"subject": "you"}`` with an optional ``group_filter``
#: the binder checks against the live attacking group (`effect_binder.
#: _subject_condition`). The ``<filter>`` is parsed by
#: `_batch_attack_group_filter` — bare, a negated creature subtype
#: ("non-Human"/"non-Toy"), or a main type ("artifact") — anything else
#: (RULE 701.48 "modified", "suspected") fails the match closed.
_BATCH_ATTACK_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more (?P<filt>[a-z][a-z-]*(?:\s[a-z][a-z-]*)?\s)?"
    r"creatures you control attack(?: a player)?$"
)


def _batch_attack_group_filter(filt: Optional[str]) -> Optional[dict[str, Any]]:
    """The optional ``<filter>`` before "creatures you control attack" in a
    `_BATCH_ATTACK_TRIGGER_RE` match → a ``group_filter`` dict (empty for the
    bare form), or ``None`` to fail the whole trigger match closed for an
    un-modelled qualifier ("modified", "suspected")."""
    f = (filt or "").strip().lower()
    if not f:
        return {}
    if f.startswith("non-") and f[4:].isalpha():
        return {"excluded_subtypes": [f[4:]]}
    if f in _GROUP_TYPE_WORDS:
        return {"type": f}
    if f == "suspected":
        # RULE 701.60 (Clandestine Meddler) — "whenever one or more
        # suspected creatures you control attack, …". Checked against the
        # live attacking group by `effect_binder._any_attacking_matches`.
        return {"is_suspected": True}
    return None

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

#: RULE 603.1's condition subject — a *group* of objects, not just the
#: source itself: "a"/"another" <type> [you control], then the trigger verb,
#: optionally "the battlefield" (enters) and/or "under your control" (the
#: older enters-battlefield templating). Examples this claims: "a creature
#: enters the battlefield under your control", "another creature you control
#: enters", "a creature dies", "another creature you control dies", "a
#: creature you control attacks".
_GROUP_SUBJECT_RE = re.compile(
    r"^(?P<article>another|an|a)\s+(?P<nonland>nonland\s+)?"
    # "a **non-Human** creature you control attacks" (Winota) — a negated
    # creature subtype on the acting object, `effect_binder._build_group_ok`'s
    # ``excluded_subtypes`` (checked against the event's live subtypes).
    r"(?P<negsub>non-[a-z]+\s+)?"
    r"(?P<type>" + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<you_a> you control)?"
    rf"\s+(?:{_VERB_ALT})"
    r"(?:\s+the\s+battlefield)?(?:\s+alone)?"
    r"(?P<you_b> under your control)?$"
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

#: RULE 603.1's condition subject, scoped by a **creature subtype** instead
#: of `_GROUP_TYPE_WORDS`'s closed main-type vocabulary (The Ghoul,
#: Gunslinger: "another nontoken Zombie or Mutant you control dies" — a
#: real, broader gap: tribal "dies"/"enters"/"attacks" triggers are common
#: beyond this one card). One or more capitalized subtype words joined by
#: "or", an optional leading "nontoken" (RULE 111.9's "isn't a token"),
#: always "you control" in practice (no real card leaves this bare for a
#: subtype-scoped trigger) — checked against `EventType`'s own ``subtypes``/
#: ``is_token`` payload (`effect_binder._subject_condition`, since a DIES
#: event's object has already left the battlefield by the time a trigger
#: check runs — RULE 400.7 — so a live lookup can't see its subtypes).
_GROUP_SUBTYPE_SUBJECT_RE = re.compile(
    r"^(?P<article>another|an|a)\s+(?P<nontoken>nontoken\s+)?"
    r"(?P<subtypes>[a-z]+(?:\s+or\s+[a-z]+)*)\s+you control\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: The "~ or another <subject>" merge (The Ghoul, Gunslinger's own actual
#: printed condition: "The Ghoul or another nontoken Zombie or Mutant you
#: control dies") — this ability's own source *or* any matching battlefield
#: object, not either alone. A dedicated subject (``"self_or_group"``)
#: rather than composing "self"/"group" as two independent predicates,
#: since RULE 603.1 wants their **union** (either firing condition puts the
#: trigger on the stack) — a plain AND-composition (`_trigger_condition`'s
#: usual multi-predicate style) would wrongly require *both* at once.
_SELF_OR_GROUP_SUBTYPE_RE = re.compile(
    r"^~ or another\s+(?P<nontoken>nontoken\s+)?"
    r"(?P<subtypes>[a-z]+(?:\s+or\s+[a-z]+)*)\s+you control\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

#: The plain **main-type** sibling of `_SELF_OR_GROUP_SUBTYPE_RE` (Blood
#: Artist/Falkenrath Noble's own printed condition: "whenever ~ or another
#: creature dies, …") — no subtype filter, and "you control" is optional
#: rather than mandatory (Blood Artist's trigger fires on *any* creature
#: dying, not just the controller's own — the aristocrats payoff's whole
#: point). Tried before `_SELF_OR_GROUP_SUBTYPE_RE` for the same reason
#: `_GROUP_SUBJECT_RE` is tried before `_GROUP_SUBTYPE_SUBJECT_RE`: a bare
#: main-type word like "creature" would otherwise also match the subtype
#: grammar's permissive ``[a-z]+`` and be misread as a one-word tribal
#: filter.
_SELF_OR_GROUP_SUBJECT_RE = re.compile(
    r"^~ or another\s+(?P<type>" + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?P<you> you control)?\s+"
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
)

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
    r"^\s*\[?\s*([+\-−]?)\s*(\d+)\s*\]?\s*:\s*(?P<effect>.+)$", re.S
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
_CONNECTORS: tuple[str, ...] = (r"\.\s+", r";\s+", r",?\s+then\s+", r"\s+and\s+")

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
#: vocabulary `catalogue.handlers._NAMED_TOKEN_WORDS`/`segmenter._
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
_OTHERWISE_CLASH_RE = re.compile(
    r"^otherwise,\s*(?P<rest>.+)$", re.IGNORECASE,
)

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
    r"^look at the top (?P<n>\d+) cards? of your library\.\s*"
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
#: eot` effect (`catalogue.handlers._gain_control_eot`) already does — it's
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
#: when the clause immediately before "When you do," is exactly a bare
#: self-sacrifice, so it can never misfire onto one of those.
_SACRIFICE_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>sacrifice (?:it|this \w+|~))\.\s*when you do,\s*(?P<after>.+)$",
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
_ADDITIONAL_COST_SACRIFICE_RE = re.compile(
    r"^sacrifice an?\s+(creature|artifact|land)$", re.IGNORECASE
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
_ADDITIONAL_COST_DISCARD_RE = re.compile(r"^discard an?\s+card$", re.IGNORECASE)
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
#: Deliberately only the *unconditional* printing — a leading "Raid —
#: if you attacked this turn, "-shaped gate (Admiral's Order) would need a
#: `condition` key this row doesn't parse, so it's left unclaimed rather
#: than silently dropping the gate.
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


def _additional_cost_dict(text: str) -> Optional[dict[str, Any]]:
    """One additional-cost clause's closed vocabulary → its dict, or ``None``.

    Matches `AbilitySpec.additional_cost`'s shape exactly: ``{"sacrifice":
    "creature"|"artifact"|"land"|"artifact_or_creature"}``, ``{"discard": 1}``
    ("discard a card" is the only printed count in the pool), or
    ``{"pay_life": N|"x"}``.
    """
    text = text.strip().lower()
    if _ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE.match(text):
        return {"sacrifice": "artifact_or_creature"}
    sac = _ADDITIONAL_COST_SACRIFICE_RE.match(text)
    if sac is not None:
        return {"sacrifice": sac.group(1)}
    if _ADDITIONAL_COST_DISCARD_RE.match(text):
        return {"discard": 1}
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


def _is_keyword_token(tok: str) -> bool:
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


def _player_trigger_event(condition: str) -> Any:
    """A player-subject trigger condition ("whenever you scry/surveil") → its
    `EventType`, a *list* of two for the "scry or surveil" compound, or
    ``None`` for anything else (`_PLAYER_TRIGGER_CONDITIONS`)."""
    cond = condition.strip()
    for pattern, event in _PLAYER_TRIGGER_CONDITIONS:
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
    m = _SELF_OR_GROUP_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "self_or_group",
            "type": m.group("type"),
            "controller": "you" if m.group("you") else "any",
            "other": True,
        }
    m = _SELF_OR_GROUP_SUBTYPE_RE.match(cond)
    if m is not None:
        return {
            "subject": "self_or_group",
            "subtypes": [w.strip() for w in m.group("subtypes").split(" or ")],
            "nontoken": bool(m.group("nontoken")),
            "controller": "you",
            "other": True,
        }
    # MEC-49 — "a creature dealt damage by ~ / enchanted creature this turn
    # dies" (before `_GROUP_SUBJECT_RE`, which would stop at "creature" and
    # choke on the "dealt damage by …" tail).
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
    # Before `_GROUP_SUBJECT_RE`, which would otherwise fail on the "goaded"
    # word entirely (it isn't in `_GROUP_TYPE_WORDS`) and leave the clause
    # unclaimed.
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
    # Tried before the subtype variant below: a bare main-type word
    # ("creature"/"artifact"/…) matches *both* regexes (`[a-z]+` is
    # unavoidably as permissive as the closed `_GROUP_TYPE_WORDS` list it
    # overlaps with) — `_GROUP_SUBJECT_RE`'s exact-vocabulary match must win
    # so "a creature you control enters" keeps its ``"type"`` shape instead
    # of being misread as a one-word tribal filter with no real subtype.
    m = _GROUP_SUBJECT_RE.match(cond)
    if m is not None:
        out = {
            "subject": "group",
            "type": m.group("type"),
            "controller": "you" if (m.group("you_a") or m.group("you_b")) else "any",
            "other": m.group("article") == "another",
        }
        if m.group("nonland"):
            # RULE 111 / 205: "a **nonland** creature/permanent you control
            # dies" (Beifong's Bounty Hunters) — a negated main type on the
            # acting object, checked against the DIES event's snapshotted
            # ``object_types`` (`effect_binder._build_group_ok`'s
            # ``want_nonland``), the same shape ``nontoken`` already uses.
            out["nonland"] = True
        if m.group("negsub"):
            # "a **non-Human** creature you control attacks" (Winota) — a
            # negated creature subtype, `_build_group_ok`'s
            # ``excluded_subtypes`` (the mirror of the positive ``subtypes``
            # tribal filter below).
            out["excluded_subtypes"] = [m.group("negsub").strip()[4:]]
        return out
    # Only reached once the exact main-type vocabulary above has already
    # failed to match — a genuine tribal filter ("another nontoken Zombie
    # or Mutant you control dies", The Ghoul Gunslinger-shaped).
    m = _GROUP_SUBTYPE_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "group",
            "subtypes": [w.strip() for w in m.group("subtypes").split(" or ")],
            "nontoken": bool(m.group("nontoken")),
            "controller": "you",
            "other": m.group("article") == "another",
        }
    return None


def _with_after_tail(
    specs: list[EffectSpec], after_group: Optional[str], *,
    previous_subject: bool = False, group_subject: bool = False,
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
        after_text, previous_subject=previous_subject, group_subject=group_subject,
    )
    if after_specs is None:
        return None
    return specs + after_specs


def parse_effect_body(
    body: str, *, self_subject: bool = False, previous_subject: bool = False,
    group_subject: bool = False, previous_selector: bool = False,
) -> Optional[list[EffectSpec]]:
    """A normalised effect ``body`` → its `EffectSpec`s, or ``None`` if unclaimed.

    Tries the whole body as one clause first (so a target phrase containing
    "or"/"and" isn't split), then falls back to splitting on effect connectors
    and parsing each part. Any unclaimed part fails the whole body (fail-closed:
    a partially-modeled ability is never emitted).

    ``self_subject`` says a bare "it" in ``body`` means the ability's own
    source — true of a trigger whose *subject* is the source ("when ~ enters,
    it fights …"), which is what unlocks `handlers.EffectHandler.
    self_subject_only` rows. It is deliberately **not** passed down into the
    connector-split parse below: once a body chains clauses, an earlier one
    may have introduced a new referent ("put a +1/+1 counter on target
    creature you control, then it fights …") — that reading is
    ``previous_subject``'s job instead, handed to each split part whose
    predecessor actually chose a creature (`_announces_creature_target`), and
    unlocking `handlers.EffectHandler.previous_subject_only` rows. The two
    flags are therefore never both set: a pronoun means the source or the
    last pick, never either-or.

    ``group_subject`` (MEC-28) says "it"/"that creature" means whichever
    object matched this ability's own RULE 603.1 group-subject trigger
    condition ("whenever a creature you control attacks alone, … untap
    **that creature**.") — unlocking `handlers.EffectHandler.
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
    """
    body = body.strip().rstrip(".").strip()
    if not body:
        return []

    # RULE 603.4 suffix intervening-if — "`<effect>` if an opponent lost N
    # or more life this turn." (Davros) — checked before `match_clause` /
    # the connector split so the base `<effect>` handler can't claim the
    # clause *without* the gate (a wrong-but-modeled unconditional token).
    opp_lost = _OPPONENT_LOST_LIFE_SUFFIX_RE.match(body)
    if opp_lost is not None:
        inner = parse_effect_body(
            opp_lost.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner:
            n = int(opp_lost.group("n"))
            return [
                EffectSpec(
                    e.type, dict(e.params),
                    condition={"opponent_lost_life_this_turn_at_least": n},
                )
                for e in inner
            ]
        return None

    kicked = _KICKED_CONDITION_RE.match(body)
    if kicked is not None:
        inner = parse_effect_body(
            kicked.group("rest"), self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject,
        )
        if inner is None:
            return None
        kind = kicked.group("kind").lower()
        if kind == "bargained":
            condition: dict[str, Any] = {"bargained": True}
            rewrite_kicker_x = False
        elif "twice" in kind:
            condition = {"kicked_at_least": 2}
            rewrite_kicker_x = True
        else:
            condition = {"kicked": True}
            rewrite_kicker_x = True
        results = []
        for e in inner:
            params = dict(e.params)
            if rewrite_kicker_x:
                # RULE 702.33b/PAR-17: an "X" mentioned inside a "was
                # kicked" wrapper's own rest clause can only mean Kicker's
                # own announced {X} (PAR-7's `GameObject.kicker_x_paid`,
                # e.g. Kangee, Aerie Keeper's "put X feather counters on
                # it") — a *different* sentinel than the ordinary "x"
                # `RulesEngine._substitute_x` resolves against the spell's
                # own announced X, so it's rewritten here rather than left
                # ambiguous between the two.
                for key, value in list(params.items()):
                    if value == "x":
                        params[key] = "kicker_x"
            results.append(EffectSpec(e.type, params, condition=condition))
        return results

    add_paid = _ADDITIONAL_COST_PAID_CONDITION_RE.match(body)
    if add_paid is not None:
        inner = parse_effect_body(
            add_paid.group("rest"), self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(e.type, dict(e.params), condition={"additional_cost_paid": True})
            for e in inner
        ]

    target_is_you = _TARGET_IS_CONTROLLER_RE.match(body)
    if target_is_you is not None:
        inner = parse_effect_body(
            target_is_you.group("rest"),
            self_subject=self_subject,
            previous_subject=previous_subject,
            group_subject=group_subject,
        )
        if inner is None:
            return None
        wants_controller = not target_is_you.group("neg")
        return [
            EffectSpec(e.type, dict(e.params), condition={"target_is_controller": wants_controller})
            for e in inner
        ]

    clash_repeat = _CLASH_REPEAT_PROCESS_RE.match(body)
    if clash_repeat is not None:
        process = parse_effect_body(clash_repeat.group("process"), self_subject=self_subject)
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

    clash_branch = _IF_YOU_WIN_CLASH_RE.match(body) or _OTHERWISE_CLASH_RE.match(body)
    if clash_branch is not None:
        inner = parse_effect_body(
            clash_branch.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        won = _IF_YOU_WIN_CLASH_RE.match(body) is not None
        return [
            EffectSpec(e.type, dict(e.params), condition={"clash_won": won})
            for e in inner
        ]

    life_gained = _LIFE_GAINED_THIS_TURN_CONDITION_RE.match(body)
    if life_gained is not None:
        inner = parse_effect_body(
            life_gained.group("rest"), self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject,
        )
        if inner is None:
            return None
        conditioned = [
            EffectSpec(
                e.type, dict(e.params),
                condition={"life_gained_this_turn_at_least": int(life_gained.group("n"))},
            )
            for e in inner
        ]
        trailing = life_gained.group("trailing")
        if trailing:
            # Strip the leading ". Then " (and re-fold "Then" back onto the
            # start so the inner "if ~ is your Ring-bearer and…" wrapper's
            # own `(?:then )?` tolerance still matches, same as it does
            # after an ordinary connector-split).
            more = parse_effect_body(
                trailing.strip().lstrip(". ").strip(),
                self_subject=self_subject, previous_subject=previous_subject,
                group_subject=group_subject,
            )
            if more is None:
                return None
            return conditioned + more
        return conditioned

    controls_none = _CONTROLS_NONE_OF_TYPE_CONDITION_RE.match(body)
    if controls_none is not None:
        inner = parse_effect_body(
            controls_none.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(
                e.type, dict(e.params),
                condition={"controls_none_of_type": controls_none.group("type").lower()},
            )
            for e in inner
        ]

    gy_subtype = _GRAVEYARD_HAS_SUBTYPE_CONDITION_RE.match(body)
    if gy_subtype is not None:
        inner = parse_effect_body(
            gy_subtype.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(e.type, dict(e.params),
                       condition={"graveyard_has_type": gy_subtype.group("sub").lower()})
            for e in inner
        ]

    for _werewolf_re, _werewolf_key in (
        (_WEREWOLF_NO_SPELLS_CONDITION_RE, "no_spells_cast_last_turn"),
        (_WEREWOLF_TWO_SPELLS_CONDITION_RE, "two_or_more_spells_cast_last_turn"),
    ):
        _werewolf_m = _werewolf_re.match(body)
        if _werewolf_m is not None:
            inner = parse_effect_body(
                _werewolf_m.group("rest"), self_subject=self_subject,
                previous_subject=previous_subject, group_subject=group_subject,
            )
            if inner is None:
                return None
            return [
                EffectSpec(e.type, dict(e.params), condition={_werewolf_key: True})
                for e in inner
            ]

    first_combat_phase = _FIRST_COMBAT_PHASE_CONDITION_RE.match(body)
    if first_combat_phase is not None:
        inner = parse_effect_body(
            first_combat_phase.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(e.type, dict(e.params), condition={"is_first_combat_phase": True})
            for e in inner
        ]

    ring_bearer_other = _RING_BEARER_OTHER_CONDITION_RE.match(body)
    if ring_bearer_other is not None:
        inner = parse_effect_body(
            ring_bearer_other.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(e.type, dict(e.params), condition={"is_ring_bearer": False})
            for e in inner
        ]

    ring_bearer_and_tempted = _RING_BEARER_AND_TEMPTED_CONDITION_RE.match(body)
    if ring_bearer_and_tempted is not None:
        inner = parse_effect_body(
            ring_bearer_and_tempted.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return None
        return [
            EffectSpec(
                e.type, dict(e.params),
                condition={
                    "is_ring_bearer": True,
                    "ring_tempted_at_least": int(ring_bearer_and_tempted.group("n")),
                },
            )
            for e in inner
        ]

    look_top_select = _LOOK_TOP_SELECT_RE.match(body)
    if look_top_select is not None:
        rest_destination, rest_order = _LOOK_TOP_SELECT_DESTINATIONS[
            look_top_select.group("dest").lower()
        ]
        spec = EffectSpec(
            "look_top_select",
            {
                "count": int(look_top_select.group("n")),
                "select_count": int(look_top_select.group("m")),
                "rest_destination": rest_destination,
                "rest_order": rest_order,
            },
        )
        return _with_after_tail([spec], look_top_select.group("after"), group_subject=group_subject)

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
                [spec], look_put_atk.group("after"), group_subject=group_subject
            )

    enters_atk = _CREATED_ENTERS_ATTACKING_RE.match(body)
    if enters_atk is not None:
        before_specs = parse_effect_body(
            enters_atk.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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
                    before_specs, enters_atk.group("after"), group_subject=group_subject
                )
        # regex matched but nothing stampable — fall through, fail closed

    no_regen = _NO_REGEN_SENTENCE_RE.match(body)
    if no_regen is not None:
        before_specs = parse_effect_body(
            no_regen.group("before"), self_subject=self_subject, previous_subject=previous_subject,
            group_subject=group_subject,
        )
        if before_specs is None:
            return None
        for i in range(len(before_specs) - 1, -1, -1):
            if before_specs[i].type == "destroy":
                flagged = dict(before_specs[i].params)
                flagged["can_be_regenerated"] = False
                before_specs[i] = EffectSpec(
                    before_specs[i].type, flagged, condition=before_specs[i].condition
                )
                break
        else:
            return None  # nothing to deny regeneration to — fail closed
        return _with_after_tail(
            before_specs, no_regen.group("after"),
            previous_subject=_announces_creature_target(before_specs), group_subject=group_subject,
        )

    gain_control_tail = _GAIN_CONTROL_HASTE_TAIL_RE.match(body)
    if gain_control_tail is not None:
        before_specs = parse_effect_body(
            gain_control_tail.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if before_specs is None or not any(
            spec.type == "gain_control_until_eot" for spec in before_specs
        ):
            return None  # fail closed — the tail only makes sense after that clause
        prev = _announces_creature_target(before_specs)
        grant_text = (gain_control_tail.group("grant") or "").strip()
        grant_specs: list[EffectSpec] = []
        if grant_text and not _GAIN_CONTROL_BARE_HASTE_RE.match(grant_text):
            # A *richer* restatement than bare haste ("it gains trample and
            # haste until end of turn") — model the extra grant against the
            # just-controlled creature (`previous_subject`), fail closed if
            # it isn't something we can represent.
            grant_specs = parse_effect_body(grant_text, previous_subject=prev) or []
            if not grant_specs:
                return None
        return _with_after_tail(
            before_specs + grant_specs, gain_control_tail.group("after"),
            previous_subject=prev, group_subject=group_subject,
        )

    sac_when_you_do = _SACRIFICE_THEN_WHEN_YOU_DO_RE.match(body)
    if sac_when_you_do is not None:
        before_specs = parse_effect_body(
            sac_when_you_do.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if before_specs is None or not any(spec.type == "sacrifice_self" for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return _with_after_tail(before_specs, sac_when_you_do.group("after"), group_subject=group_subject)

    earthbend_when_you_do = _EARTHBEND_THEN_WHEN_YOU_DO_RE.match(body)
    if earthbend_when_you_do is not None:
        before_specs = parse_effect_body(
            earthbend_when_you_do.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if before_specs is None or not any(spec.type == "earthbend" for spec in before_specs):
            return None  # fail closed — only a certain, unconditional antecedent collapses
        return _with_after_tail(
            before_specs, earthbend_when_you_do.group("after"), group_subject=group_subject,
        )

    discard_then_if_you_do = _DISCARD_THEN_IF_YOU_DO_RE.match(body)
    if discard_then_if_you_do is not None:
        before_specs = parse_effect_body(
            discard_then_if_you_do.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if before_specs is None or not any(spec.type == "discard" for spec in before_specs):
            return None  # fail closed — only a bare mandatory discard collapses
        return _with_after_tail(
            before_specs, discard_then_if_you_do.group("after"), group_subject=group_subject,
        )

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
            before_text, self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if before_specs is not None and optional_exile:
            before_specs = [
                EffectSpec(s.type, {**s.params, "optional": True}, condition=s.condition)
                for s in before_specs
            ]
        # Fail closed unless the "before" half genuinely chose a graveyard
        # card (`_announces_creature_target` recognises the `graveyard_*`
        # target-kind prefix) — that pick is the pronoun `CopyPermanentEffect
        # (referent="previous")` reads back (RULE 608.2).
        if before_specs is None or not _announces_creature_target(before_specs):
            return None
        after_specs = parse_effect_body(
            exile_then_copy.group("after"), previous_subject=True, group_subject=group_subject,
        )
        if after_specs is None or not any(s.type == "copy_permanent" for s in after_specs):
            return None
        return before_specs + after_specs

    exile_x_for_each = _EXILE_X_GY_FOR_EACH_CREATE_RE.match(body)
    if exile_x_for_each is not None:
        create_specs = parse_effect_body(
            exile_x_for_each.group("create"), previous_subject=True, group_subject=group_subject,
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

    direct = match_clause(
        body, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )
    if direct is not None:
        return direct

    for sep in _CONNECTORS:
        parts = [p for p in re.split(sep, body) if p.strip()]
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
            referent = previous_subject
            referent_selector = previous_selector
            for part in parts:
                sub = parse_effect_body(
                    part, previous_subject=referent, previous_selector=referent_selector,
                    group_subject=group_subject,
                )
                if sub is None:
                    ok = False
                    break
                collected.extend(sub)
                prev_referent, prev_referent_selector = referent, referent_selector
                # RULE 601.2c: what the clause just parsed *chose* is what
                # the next one's "it"/"that creature"/"those creatures" can
                # point at (`handlers.EffectHandler.previous_subject_only`,
                # `effects.GameContext.previous_targets`). A clause that
                # chose no creature leaves the pronoun unbound — and so
                # unclaimed — rather than letting it drift onto some earlier
                # clause's pick, which is the ambiguity this gate exists for.
                referent = _announces_creature_target(sub)
                # PAR-30: "clash with an opponent" is a *referent-transparent*
                # interstitial — it neither targets nor creates, so a card
                # like Gilt-Leaf Ambush ("create 2 tokens. clash with an
                # opponent. if you win, those creatures gain deathtouch …")
                # must carry the pronoun chain across the clash sentence
                # rather than have it cleared here.
                if not referent and sub and all(s.type == "clash" for s in sub):
                    referent, referent_selector = prev_referent, prev_referent_selector
                # PAR-30: a clause that itself *consumed* the pronoun ("untap
                # that creature", "it gains haste until end of turn") keeps the
                # referent chain alive for the clause after it rather than
                # clearing it — real cards run several such restatement clauses
                # in series off one "gain control of target creature" antecedent
                # (the threaten family; RULE 701.30d clash "if you win, …"
                # payoffs). Only extends an existing chain, never starts one.
                if not referent and any(
                    s.params.get("previous_subject") for s in sub
                ):
                    referent = True
                # MEC-28: the mass-selector sibling — "untap all attacking
                # creatures. They gain …" — tracked independently since a
                # selector clause never sets ``referent`` above (it targets
                # nothing at all, RULE 601.2c).
                referent_selector = _announces_group_selector(sub)
            if ok:
                return collected

    # PAR-30: "`<effect>` unless `<its>` additional cost was paid." — checked
    # *after* the connector split so it binds to only its own clause (in
    # "draw a card, then discard a card unless her additional cost was
    # paid", the split hands this just "discard a card unless …"), not to
    # every clause of a compound body.
    add_not_paid = _ADDITIONAL_COST_NOT_PAID_SUFFIX_RE.match(body)
    if add_not_paid is not None:
        inner = parse_effect_body(
            add_not_paid.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is not None:
            return [
                EffectSpec(e.type, dict(e.params), condition={"additional_cost_paid": False})
                for e in inner
            ]
    return None


#: Target kinds that make a clause a legal antecedent for the next clause's
#: creature pronoun. `EffectSpec` params name their target kinds in a handful
#: of differently-named keys (``target_kind`` for the damage/tap/destroy
#: families, ``fighter_kind``/``other_kind``/``dealer_kind`` for the fight
#: ones, a ``kinds`` list for `effects.ChooseTargetsEffect`), so this scans
#: values rather than assuming one key.
_CREATURE_TARGET_KINDS: frozenset[str] = frozenset(
    {"creature", "creature_you_control", "creature_you_dont_control",
     "other_creature_you_control",
     # Not only creatures: the tap-then-lock family ("Tap target **land**. It
     # doesn't untap …") refers back to a land/artifact/permanent with the
     # same pronoun, and a permanent pronoun is no more ambiguous than a
     # creature one — the gate is about *whether the previous clause chose
     # something at all*, not about what type it chose.
     "land", "artifact", "permanent", "nonland_permanent",
     "artifact_creature_or_land", "artifact_or_creature"}
)


def _announces_creature_target(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` picks a permanent (or a graveyard card)
    the next clause can refer back to as "it"/"that creature"/"that card".

    A ``graveyard_*``/``any_graveyard_*``/``opponent_graveyard_*`` kind
    (PAR-18 — "exile up to 1 target creature card from a graveyard. Create a
    token that's a copy of **that card**.") is recognized by prefix rather
    than an enumerated set: this module has no `game/` import (the front-end
    security boundary), so it can't pull `game/targeting.py`'s
    `_GRAVEYARD_TARGET_KINDS` frozenset directly, and the prefix is the same
    one `catalogue.handlers._graveyard_target_kind` builds every such kind
    from.
    """
    if not specs:
        return False
    last = specs[-1]
    # "earthbend N, then untap **that land**." (Avatar Kyoshi — PAR-30): an
    # ``earthbend`` spec always picks a target land you control (the
    # `TargetSpec` is built inside `EarthbendEffect.__init__`, not surfaced
    # as a param), so it's recognised by type here rather than by scanning
    # params like every other kind below.
    if last.type == "earthbend" and not last.params.get("previous_subject"):
        return True
    # "Create a token …. **It** gains haste until end of turn." (PAR-30 —
    # God-Pharaoh's Gift, Harried Dronesmith, Molten Duplication, Mordor on
    # the March): a create/copy clause makes an object the next clause's
    # "it" points at, read at resolve time off `GameContext.created_objects`
    # rather than `previous_targets` (`PumpEffect.previous_subject`'s own
    # fallback). ``copy_permanent``/``become_copy`` included since the
    # reanimator-token grammar routes "a token that's a copy of that card"
    # through them.
    if last.type in ("create_token", "copy_permanent", "become_copy"):
        return True
    values: list[Any] = []
    for value in last.params.values():
        values.extend(value if isinstance(value, list) else [value])
    return any(
        isinstance(v, str) and (
            v in _CREATURE_TARGET_KINDS
            or v.startswith(("graveyard_", "any_graveyard_", "opponent_graveyard_"))
        )
        for v in values
    )


#: MEC-28: recognised mass-selector values `handlers.EffectHandler.
#: previous_selector_only` rows may read back as "they" (`effects.
#: GameContext.previous_selector`, `game/effect_binder.py`'s narrow
#: ``TapEffect``-only tracking whitelist) — deliberately just the one real
#: card (Karlach, Fury of Avernus) needs today, widened only as another
#: card actually prints a different mass selector before this same "they"
#: tail, matching this file's usual narrow-whitelist convention.
_GROUP_SELECTOR_VALUES: frozenset[str] = frozenset({"attacking_creatures"})


def _announces_group_selector(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` is an untargeted mass-selector effect
    ("untap all attacking creatures") the next clause's "they" can point at —
    `_announces_creature_target`'s sibling for RULE 601.2c selectors rather
    than RULE 115 targets, since a selector clause has no target of its own
    to be caught by that check."""
    if not specs:
        return False
    return specs[-1].type == "tap" and specs[-1].params.get("selector") in _GROUP_SELECTOR_VALUES


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
    if spec.ability_kind == "static":
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
        # to fold the once-per-game cap onto; a keyword *mana* ability's own
        # "activate only once" is left as a known simplification.
        return Segment(raw=raw, claimed=True)
    if not inner.claimed or inner.spec is None or not _apply_keyword_restriction(
        inner.spec, kw
    ):
        # Body didn't fully parse. Fall back to an inert keyword-line claim
        # *only* where `is_keyword_line` itself would already have made one
        # pre-PAR-28 (a comma-free `<keyword> — <body>` line, which
        # `_KEYWORD_TOKEN_RE`'s greedy `.*$` swallowed whole). That keeps the
        # handler a strict upgrade for those cards and avoids promoting a
        # card whose whole reason-for-being is an unparseable Boast/Solved/…
        # body to `MODELED` with that ability inert — a half-model.
        return (
            Segment(raw=raw, claimed=True, keyword_line=True)
            if is_keyword_line(raw)
            else Segment(raw=raw)
        )
    inner.spec.raw_text = raw
    for extra in inner.extra_specs:
        _apply_keyword_restriction(extra, kw)
        extra.raw_text = raw
    return Segment(raw=raw, spec=inner.spec, extra_specs=inner.extra_specs, claimed=True)


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

    # PAR-28: "Boast/Exhaust/Forecast/Power-up/Solved/Max speed — [ability]".
    # Checked *before* `is_keyword_line`, since `_KEYWORD_TOKEN_RE`'s greedy
    # `.*$` would otherwise claim the whole "<keyword> — <cost>: <effect>"
    # line as a bare keyword line (producing no ability at all).
    kw_labeled = _segment_keyword_labeled_ability(
        raw, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if kw_labeled is not None:
        return kw_labeled

    if is_keyword_line(raw):
        return Segment(raw=raw, claimed=True, keyword_line=True)

    if _PLAY_WITH_TOP_REVEALED_RE.match(raw):
        return Segment(raw=raw, claimed=True)  # informational-only, no spec (see docstring)

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

    cast_spell_trig_mv = _CAST_SPELL_TRIGGER_MV_RE.match(raw)
    if cast_spell_trig_mv is not None:
        subj = cast_spell_trig_mv.group("subj").lower()
        body, optional = _peel_optional(cast_spell_trig_mv.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        if subj == "you":
            mv_condition: dict[str, Any] = {"subject": "you"}
        elif subj == "an opponent":
            mv_condition = {"subject": "group", "controller": "not_you"}
        else:
            mv_condition = {"subject": "group"}
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": mv_condition,
                "spell_mana_value_at_most": int(cast_spell_trig_mv.group("n")),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

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

    cast_spell_trig_nth = _CAST_SPELL_TRIGGER_NTH_RE.match(raw)
    if cast_spell_trig_nth is not None:
        subj = cast_spell_trig_nth.group("subj").lower()
        n = _CAST_SPELL_ORDINAL_WORDS[cast_spell_trig_nth.group("ordinal").lower()]
        body, optional = _peel_optional(cast_spell_trig_nth.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "is_nth_spell_cast_this_turn": n,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    enters_if_cast = _ENTERS_IF_CAST_RE.match(raw)
    if enters_if_cast is not None:
        body, optional = _peel_optional(enters_if_cast.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    cast_spell_not_their_turn_trig = _CAST_SPELL_NOT_THEIR_TURN_TRIGGER_RE.match(raw)
    if cast_spell_not_their_turn_trig is not None:
        body, optional = _peel_optional(cast_spell_not_their_turn_trig.group("body"))
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

    cast_spell_no_mana_trig = _CAST_SPELL_NO_MANA_TRIGGER_RE.match(raw)
    if cast_spell_no_mana_trig is not None:
        body, optional = _peel_optional(cast_spell_no_mana_trig.group("body"))
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

    cast_spell_targets_perm = _CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE.match(raw)
    if cast_spell_targets_perm is not None:
        subj = cast_spell_targets_perm.group("subj").lower()
        body, optional = _peel_optional(cast_spell_targets_perm.group("body"))
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

    cast_spell_trig_plain = _CAST_SPELL_TRIGGER_PLAIN_RE.match(raw)
    if cast_spell_trig_plain is not None:
        subj = cast_spell_trig_plain.group("subj").lower()
        body, optional = _peel_optional(cast_spell_trig_plain.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        trig: dict[str, Any] = {
            "event": "SPELL_CAST", "condition": _cast_spell_trigger_condition(subj),
        }
        if cast_spell_trig_plain.group("opp_turn"):
            trig["not_controllers_turn"] = True
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger=trig,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cast_this_spell_trig = _CAST_THIS_SPELL_TRIGGER_RE.match(raw)
    if cast_this_spell_trig is not None:
        body, optional = _peel_optional(cast_this_spell_trig.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    draw_trig_plain = _DRAW_TRIGGER_PLAIN_RE.match(raw)
    if draw_trig_plain is not None:
        subj = draw_trig_plain.group("subj").lower()
        body, optional = _peel_optional(draw_trig_plain.group("body"))
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

    draw_trig_nth = _DRAW_CARD_TRIGGER_NTH_RE.match(raw)
    if draw_trig_nth is not None:
        subj = draw_trig_nth.group("subj").lower()
        n = _CAST_SPELL_ORDINAL_WORDS[draw_trig_nth.group("ordinal").lower()]
        body, optional = _peel_optional(draw_trig_nth.group("body"))
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

    # Tried before the positive `_CAST_SPELL_TRIGGER_RE` below: that
    # pattern's own ``types`` group (bare ``[a-z][a-z,\s]*?``) is generic
    # enough to also swallow "noncreature" as if it were a types list —
    # failing `_parse_cast_spell_types` and returning unclaimed *before*
    # this negated form ever got a chance to match the same line.
    cast_spell_trig_neg = _CAST_SPELL_TRIGGER_NEG_RE.match(raw)
    if cast_spell_trig_neg is not None:
        excluded = cast_spell_trig_neg.group("type").lower()
        if excluded not in _SPELL_CAST_TYPE_WORDS:
            return Segment(raw=raw)
        neg_subj = cast_spell_trig_neg.group("subj")
        body, optional = _peel_optional(cast_spell_trig_neg.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(neg_subj),
                "spell_exclude_card_types": [excluded],
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cast_spell_trig = _CAST_SPELL_TRIGGER_RE.match(raw)
    if cast_spell_trig is not None:
        pos_subj = cast_spell_trig.group("subj")
        raw_types = cast_spell_trig.group("types")
        types = _parse_cast_spell_types(raw_types)
        # "Whenever you cast an Elf spell, …" (Lys Alana Huntmaster-shaped) —
        # the same captured word list read as a *subtype* instead of a main
        # card type when it isn't one (`_CAST_SPELL_SUBTYPE_WORDS`'s curated
        # whitelist) — tried here, in the same branch, rather than a
        # separate regex row: `_CAST_SPELL_TRIGGER_RE`'s own generic
        # ``types`` group already matches "elf" just as happily as
        # "creature", so a standalone subtype row placed after this one
        # would never be reached, and placed before it would just invert
        # the same problem onto genuine main-type cards.
        single_word = raw_types.strip().lower()
        if types is None and single_word in _CAST_SPELL_SUBTYPE_WORDS:
            body, optional = _peel_optional(cast_spell_trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={
                    "event": "SPELL_CAST",
                    "condition": _cast_spell_trigger_condition(pos_subj),
                    "spell_subtype_any": [single_word],
                },
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        if types is None:
            return Segment(raw=raw)
        body, optional = _peel_optional(cast_spell_trig.group("body"))
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(pos_subj),
                "spell_card_types": types,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cycle_trig = _CYCLE_TRIGGER_RE.match(raw)
    if cycle_trig is not None:
        body = cycle_trig.group("body")
        # RULE 702.28c's X (Shark Typhoon's "create an X/X ... token"): the
        # Cycling cost's own paid {X}, ambiguous to any *generic* "create an
        # X/X ... token" handler outside this wrapper (see `_cycling_xx_
        # token`'s own docstring) — checked directly, here, rather than
        # through the ordinary HANDLERS table this body would otherwise go
        # through via `parse_effect_body`.
        xx_token_match = _CYCLING_XX_TOKEN_RE.fullmatch(body.strip().rstrip(".").strip())
        if xx_token_match is not None:
            effects = _cycling_xx_token(xx_token_match)
        else:
            effects = parse_effect_body(body, self_subject=True)
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

    if _EXERT_BARE_RE.match(raw) is not None:
        return Segment(raw=raw, claimed=True, keyword_line=True)

    exert_trig = _EXERT_TRIGGER_RE.match(raw)
    if exert_trig is not None:
        effects = parse_effect_body(exert_trig.group("body"), self_subject=True)
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

    sacrifice_trig = _SACRIFICE_TYPE_TRIGGER_RE.match(raw)
    if sacrifice_trig is not None:
        effects = parse_effect_body(sacrifice_trig.group("body"), self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SACRIFICE",
                "condition": {"subject": "you"},
                "sacrifice_type": sacrifice_trig.group("type").lower(),
            },
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    control_none_sac = _CONTROL_NONE_SACRIFICE_RE.match(raw)
    if control_none_sac is not None:
        effects = parse_effect_body(control_none_sac.group("body"), self_subject=True)
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

    damage_trig = _DAMAGE_TRIGGER_RE.match(raw)
    if damage_trig is not None:
        body, optional = _peel_optional(damage_trig.group("body"))
        # "Enrage — whenever ~ is dealt damage, **it** fights …": the source is
        # the trigger's own subject, so a bare "it" in the body is the source
        # (`parse_effect_body`'s ``self_subject``).
        effects = parse_effect_body(body, self_subject=bool(damage_trig.group("self")))
        if effects is None:
            return Segment(raw=raw)
        # "deals combat damage" requires the ``combat`` flag; a bare "deals
        # damage" (no "combat") is unqualified — it must match *any* damage
        # instance, combat or not, so the filter omits the key entirely
        # rather than pinning it to ``False`` (which would wrongly exclude
        # real combat damage from an unqualified trigger).
        # "…to **one of your opponents**" (The Rani) is the same recipient
        # kind as "…to a player" as far as the damage event is concerned —
        # the "yours" narrowing is a separate question this filter's
        # ``is_player`` key doesn't express, and no shipped card's behaviour
        # differs on it, so both spell it the same way.
        damage_filter: dict[str, Any] = {}
        if damage_trig.group("recipient"):
            damage_filter["is_player"] = (
                damage_trig.group("recipient") in ("player", "opponent")
            )
        if damage_trig.group("combat"):
            damage_filter["combat"] = True
        if damage_trig.group("self"):
            condition: dict[str, Any] = {"subject": "self"}
        elif damage_trig.group("attached"):
            condition = {"subject": "attached_permanent"}
        else:
            condition = {
                "subject": "group",
                "type": damage_trig.group("type").lower(),
                "other": damage_trig.group("article").lower() == "another",
            }
            if damage_trig.group("yours"):
                condition["controller"] = "you"
            if damage_trig.group("goaded"):  # RULE 701.15b — see `_GOADED_SUBJECT_RE`
                condition["goaded"] = True
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DAMAGE",
                "condition": condition,
                "filter": damage_filter,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    damage_recipient_trig = _DAMAGE_RECIPIENT_TRIGGER_RE.match(raw)
    if damage_recipient_trig is not None:
        body, optional = _peel_optional(damage_recipient_trig.group("body"))
        # "Enrage — whenever ~ is dealt damage, **it** fights …": the source
        # is the trigger's own subject, so a bare "it" in the body is the
        # source (`parse_effect_body`'s ``self_subject``) — same idiom as
        # the "deals damage" family above.
        is_self_subject = bool(damage_recipient_trig.group("self"))
        effects = parse_effect_body(body, self_subject=is_self_subject)
        if effects is None:
            return Segment(raw=raw)
        if not is_self_subject:
            # "…a creature you control is dealt damage, put a +1/+1 counter
            # on **it**." (Rite of Passage) — a bare "it" here means
            # whichever group member the event actually names, *not* this
            # ability's own source the way `self_subject` everywhere else
            # in this module means: Rite of Passage is an Enchantment, and
            # silently landing the counter on it instead of the damaged
            # creature would be a wrong-but-MODELED card, strictly worse
            # than leaving it unclaimed. `add_counters` with no explicit
            # `target_kind` is the one shape real cards actually print this
            # way (`AddCountersEffect.trigger_subject_key`, resolved
            # against the same event key `_subject_event_key` uses for this
            # trigger's own condition). Default-deny otherwise: an effect
            # with neither a real RULE 115 ``target_kind`` nor a mass
            # ``selector`` implicitly acts on "self" in every other
            # context this parser builds, and there's no cached card yet
            # to say what "self" should mean for a non-self subject here —
            # fail closed rather than guess.
            rewritten: list[EffectSpec] = []
            for effect_spec in effects:
                if effect_spec.type == "add_counters" and not effect_spec.params.get("target_kind"):
                    params = dict(effect_spec.params)
                    params["trigger_subject_key"] = "target_id"
                    rewritten.append(EffectSpec(effect_spec.type, params, condition=effect_spec.condition))
                elif effect_spec.params.get("target_kind") or effect_spec.params.get("selector"):
                    rewritten.append(effect_spec)
                else:
                    return Segment(raw=raw)
            effects = rewritten
        damage_filter = {}
        if damage_recipient_trig.group("combat"):
            damage_filter["combat"] = True
        if damage_recipient_trig.group("self"):
            condition = {"subject": "self", "recipient": True}
        elif damage_recipient_trig.group("attached"):
            condition = {"subject": "attached_permanent", "recipient": True}
        else:
            condition = {
                "subject": "group",
                "type": damage_recipient_trig.group("type").lower(),
                "other": damage_recipient_trig.group("article").lower() == "another",
                "recipient": True,
            }
            if damage_recipient_trig.group("yours"):
                condition["controller"] = "you"
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "DAMAGE",
                "condition": condition,
                "filter": damage_filter,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    becomes_target_trig = _BECOMES_TARGET_TRIGGER_RE.match(raw)
    if becomes_target_trig is not None:
        body, optional = _peel_optional(becomes_target_trig.group("body"))
        is_self_subject = bool(becomes_target_trig.group("self"))
        effects = parse_effect_body(body, self_subject=is_self_subject)
        if effects is None:
            return Segment(raw=raw)
        if becomes_target_trig.group("self"):
            condition = {"subject": "self"}
        elif becomes_target_trig.group("attached"):
            condition = {"subject": "attached_permanent"}
        else:
            condition = {
                "subject": "group",
                "type": becomes_target_trig.group("type").lower(),
                "other": becomes_target_trig.group("article").lower() == "another",
            }
            if becomes_target_trig.group("yours"):
                condition["controller"] = "you"
        trigger: dict[str, Any] = {
            "event": "BECOMES_TARGET",
            "condition": condition,
            "filter": {"item_kind": becomes_target_trig.group("item_kind").lower()},
        }
        caster_rel = (becomes_target_trig.group("caster_rel") or "").strip()
        if caster_rel == "an opponent controls":
            trigger["caster_relation"] = "opponent"
        elif caster_rel == "you control":
            trigger["caster_relation"] = "you"
        if becomes_target_trig.group("once"):
            trigger["limit"] = True
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger=trigger,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

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

    # RULE 601.2b/604.3 additional cost — checked before every other wrapper
    # since it has neither a trigger word nor a colon (so it can't be
    # mistaken for one of those shapes below). Not gated by
    # ``allow_spell_effect``: the "as an additional cost to cast this spell,"
    # wrapper is unambiguous and applies to a creature/other permanent spell
    # just as much as an instant/sorcery (Kinsbaile Aspirant/Lys Alana
    # Dignitary/Silvergill Mentor — Behold, PAR-29), and the spec it emits
    # carries no bare imperative for the gate to guard against.
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
            additional_cost_optional=is_optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

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
        if (
            _MANA_EFFECT_RE.match(effect_text)
            or _COLORS_AMONG_PERMANENTS_MANA_RE.match(effect_text)
            or _DEVOTION_CHOSEN_COLOR_MANA_RE.match(effect_text)
        ):
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
        body, optional = _peel_optional(effect_text)
        effects = parse_effect_body(body)
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
        spec = AbilitySpec(
            "activated",
            effects=effects,
            cost=cost_dict,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    phase_trig = _PHASE_TRIGGER_RE.match(raw)
    if phase_trig is not None:
        step_word = (
            phase_trig.group("step_any")
            or phase_trig.group("step_you")
            or phase_trig.group("step_you_each")
            or phase_trig.group("step_combat_you")
            or phase_trig.group("step_opp")
        )
        step = _PHASE_STEP_WORDS.get((step_word or "").lower())
        if step is None:
            return Segment(raw=raw)
        if (
            phase_trig.group("step_you")
            or phase_trig.group("step_you_each")
            or phase_trig.group("step_combat_you")
        ):
            relation = "you"
        elif phase_trig.group("step_opp"):
            relation = "not_you"
        else:
            relation = None
        body, optional = _peel_optional(phase_trig.group("body"))
        # MEC-46: peel a leading "if another <subtype> entered … this turn,"
        # RULE 603.4 intervening-if into the trigger's own `active_if`.
        phase_active_if: Optional[dict[str, Any]] = None
        entered_if = _ANOTHER_SUBTYPE_ENTERED_IF_RE.match(body)
        if entered_if is not None:
            phase_active_if = {
                "kind": "another_subtype_entered_this_turn",
                "subtype": entered_if.group("sub").lower(),
            }
            body = entered_if.group("rest").strip()
        if relation is None:
            them_damage = _PHASE_DAMAGE_TO_THEM_RE.match(body)
            if them_damage is not None:
                effects = [EffectSpec("damage", {
                    "amount": int(them_damage.group("n")), "selector": "active_player",
                })]
            else:
                effects = parse_effect_body(body)
        else:
            effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        trigger: dict[str, Any] = {"event": "STEP_BEGIN", "filter": {"step": step}}
        if relation is not None:
            trigger["phase_relation"] = relation
        if phase_active_if is not None:
            trigger["active_if"] = phase_active_if
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger=trigger,
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    trig = _TRIGGER_RE.match(raw)
    if trig is not None:
        cond_text = trig.group("cond")
        # PAR-14: "…for the first time each turn" (Whispering Snitch-shaped)
        # — stripped once here, before any subject-family dispatch below, so
        # every family picks up `AbilitySpec.trigger["limit"]` for free.
        limit_suffix_m = _ONCE_PER_TURN_CONDITION_SUFFIX_RE.match(cond_text.strip())
        limit = limit_suffix_m is not None
        if limit_suffix_m is not None:
            cond_text = limit_suffix_m.group("base")

        # RULE 508.3a batch attack: "one or more [<filter>] creatures you
        # control attack" → a single `PLAYER_ATTACKED` (once-per-combat)
        # trigger with an optional group filter (`_subject_condition`).
        batch_atk = _BATCH_ATTACK_TRIGGER_RE.match(cond_text.strip())
        if batch_atk is not None:
            group_filter = _batch_attack_group_filter(batch_atk.group("filt"))
            if group_filter is None:
                return Segment(raw=raw)  # un-modelled qualifier → unclaimed
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, group_subject=True)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            limit = limit or body_limit
            condition = {"subject": "you"}
            if group_filter:
                condition["group_filter"] = group_filter
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={
                    "event": "PLAYER_ATTACKED",
                    "condition": condition,
                    **({"limit": True} if limit else {}),
                },
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        enters_and_phase = _ENTERS_AND_MAIN_PHASE_RE.match(cond_text.strip())
        if enters_and_phase is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
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
            # O-Ring body ("exile … until ~ leaves") wants a companion
            # LEAVES_BATTLEFIELD return, exactly as the single-trigger path
            # below synthesizes it.
            if any(e.type == "exile" and e.params.get("until_source_leaves")
                   for e in effects):
                eap_specs.append(AbilitySpec(
                    "triggered",
                    effects=[EffectSpec("return_linked_exile", {})],
                    trigger={"event": "LEAVES_BATTLEFIELD", "condition": {"subject": "self"}},
                    raw_text=raw,
                    parser=provenance,
                ))
            return Segment(
                raw=raw, spec=eap_specs[0], extra_specs=eap_specs[1:], claimed=True,
            )

        variant_event = _variant_trigger_event(cond_text)
        if variant_event is not None:
            body, optional = _peel_optional(trig.group("body"))
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
        player_event = _player_trigger_event(cond_text)
        if player_event is not None:
            # RULE 603.1 with a *player* subject ("whenever you scry") — the
            # same one-spec-per-event shape as the compound above, but every
            # spec carries the ``{"subject": "you"}`` scoping that makes it
            # this controller's scry rather than anybody's.
            body, optional = _peel_optional(trig.group("body"))
            # "Whenever you gain life, **~** gets +X/+X …" (Field-Tested
            # Frying Pan's granted ability, Ageless Entity) — a player-
            # subject trigger introduces no group of objects, so a bare
            # "it"/"~" in the body is unambiguous: the ability's own source,
            # same reasoning as the object self-subject branch below.
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            limit = limit or body_limit
            player_specs = [
                AbilitySpec(
                    "triggered",
                    effects=[EffectSpec(e.type, dict(e.params)) for e in effects],
                    trigger={
                        "event": event_name,
                        "condition": {"subject": "you"},
                        **({"limit": True} if limit else {}),
                    },
                    optional=optional,
                    raw_text=raw,
                    parser=provenance,
                )
                for event_name in (
                    player_event if isinstance(player_event, list) else [player_event]
                )
            ]
            return Segment(
                raw=raw,
                spec=player_specs[0],
                extra_specs=player_specs[1:],
                claimed=True,
            )
        defender_lands_min: Optional[int] = None
        atk_lands = _ATTACKS_DEFENDER_LANDS_RE.match(cond_text.strip())
        multi = _SELF_MULTI_EVENT_RE.match(cond_text.strip())
        if atk_lands is not None:
            event: "str | list[str]" = "ATTACKS"
            condition: Optional[dict[str, Any]] = {"subject": "self"}
            defender_lands_min = int(atk_lands.group("n"))
        elif multi is not None:
            event = [_multi_event_name(multi.group("v1")), _multi_event_name(multi.group("v2"))]
            if not all(event):
                return Segment(raw=raw)  # an unrecognised verb → fail closed
            condition = {"subject": "self"}
        else:
            event = _trigger_event(cond_text)
            if event is None:
                return Segment(raw=raw)  # unrecognised trigger → unclaimed
            condition = _trigger_condition(cond_text)
            if condition is None:
                return Segment(raw=raw)  # unrecognised subject scope → unclaimed (fail-closed)
        body, optional = _peel_optional(trig.group("body"))
        # "When ~ enters, **it** fights …": with the source as the trigger's
        # own subject, a bare "it" in the body is the source — anything else
        # (a group subject, an attached permanent) leaves the pronoun
        # ambiguous, so only this scope unlocks it. MEC-28: "whenever a
        # creature you control attacks alone, … that creature …" is the
        # `{"subject": "group"}` sibling — `condition` may carry extra keys
        # (``controller``/``type``/…) alongside it, so this reads the key
        # rather than requiring an exact dict match the way ``self_subject``
        # does above.
        effects = parse_effect_body(
            body, self_subject=condition == {"subject": "self"},
            group_subject=(condition or {}).get("subject") == "group",
        )
        if effects is None:
            return Segment(raw=raw)
        effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
        limit = limit or body_limit
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": event,
                "condition": condition,
                **({"limit": True} if limit else {}),
                **({"defender_controls_lands_at_least": defender_lands_min}
                   if defender_lands_min else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        # O-Ring / Banisher Priest: "exile … until ~ leaves the battlefield"
        # (`handlers._exile_until_leaves`, `ExileEffect(remember=True)`) needs
        # a *second* ability — "When ~ leaves the battlefield, return the
        # exiled card." (`ReturnLinkedExileEffect`) — which a single body
        # parse can't emit. The ``until_source_leaves`` param on the exile
        # spec is that signal.
        extra_ltb: list[AbilitySpec] = []
        if any(
            e.type == "exile" and e.params.get("until_source_leaves") for e in effects
        ):
            extra_ltb.append(
                AbilitySpec(
                    "triggered",
                    effects=[EffectSpec("return_linked_exile", {})],
                    trigger={
                        "event": "LEAVES_BATTLEFIELD",
                        "condition": {"subject": "self"},
                    },
                    raw_text=raw,
                    parser=provenance,
                )
            )
        return Segment(raw=raw, spec=spec, extra_specs=extra_ltb, claimed=True)

    # No trigger wrapper. On a *permanent*, "As ~ enters, choose a creature
    # type/color" (RULE 601.2b) is a characteristic-defining choice made as
    # part of entering — an ``enter_replacement`` ability (RULE 614.1c/
    # 614.12's family, not a triggered ability and not `static_effect_specs`'
    # standing-continuous-ability shape either), tried first since it's a
    # narrower, closed pair of clauses.
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
                "static", effects=static, raw_text=raw, parser=provenance
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
    if allow_spell_effect:
        cost_static = static_effect_specs(raw)
        if cost_static is not None and all(
            spec.type == "cost_reduction" and spec.params.get("affects") == "self" for spec in cost_static
        ):
            spec = AbilitySpec("static", effects=cost_static, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

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


#: "you may pay {E}… . If/When you do, <effect>." (Aether Chaser) / "you
#: may pay {1}. If you do, draw a card." (RULE 118.3's general
#: `pay_cost_then` idiom, Spellbomb-cycle-shaped) / MEC-18's wider "you may
#: sacrifice/discard/pay life `<X>`. When you do, `<effect>`." family — the
#: "you may" here is the *cost-payment* decision `pay_energy_then`/
#: `pay_cost_then` model with their own interactive choice, not a
#: whole-ability "you may". Left un-peeled so the full clause reaches
#: `parse_effect_body`'s own handler for either shape intact (otherwise the
#: ability would be marked doubly-optional and the "if you do" gate lost).
#: The non-energy alternatives are `catalogue.handlers._MAY_COST_THEN_
#: CLAUSE` itself (not a hand-copied mirror of it) so this guard can never
#: drift out of sync with what `pay_cost_then_general` actually claims.
_PAY_ENERGY_THEN_PEEL_GUARD_RE = re.compile(
    r"^you may (?:pay (?:\{e\})+|" + _MAY_COST_THEN_CLAUSE + r")\.\s*(?:if|when) you do",
    re.IGNORECASE,
)


def _peel_optional(body: str) -> tuple[str, bool]:
    """Strip a leading "you may " and report whether it was present (RULE 601.2)."""
    body = body.strip()
    if _PAY_ENERGY_THEN_PEEL_GUARD_RE.match(body):
        return body, False
    m = re.match(r"^you may\s+(?P<rest>.+)$", body, re.S)
    if m is not None:
        return m.group("rest"), True
    return body, False
