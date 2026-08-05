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

from .catalogue.handlers import TRIGGER_ONCE_PER_TURN_MARKER, match_clause
from .catalogue.keywords import ALIAS_DISPLAYS, KEYWORDS
from .catalogue.replacements import replacement_clause_specs
from .catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from .catalogue.static_handlers import enter_choice_specs, static_effect_specs
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
#: stays out and its cards stay `UNMODELED` (fail-closed). Deliberately
#: absent for exactly that reason: "becomes untapped" (`EventType.UNTAP` is
#: fired once per untap *step*, keyed by player, never per permanent),
#: "becomes monstrous"/"specializes" (mechanics with no engine primitive at
#: all — see the `MEC` tickets in `BACKLOG.md`).
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
_SELF_MULTI_EVENT_RE = re.compile(
    r"^(?:~|this (?:creature|artifact|enchantment|land|permanent|equipment))\s+"
    rf"(?P<v1>{_VERB_ALT})(?:\s+the\s+battlefield)?"
    r"\s+or\s+"
    rf"(?P<v2>{_VERB_ALT})(?:\s+the\s+battlefield)?$"
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
    # "Whenever the Ring tempts you, …" (RULE 701.51a, Tales of Middle-earth
    # — Aragorn, Company Leader/Galadriel of Lothlórien/Sméagol, Helpful
    # Guide-shaped). `EventType.RING_TEMPTED` fires from `RulesEngine.
    # the_ring_tempts_you` once the Ring-bearer choice is settled.
    (re.compile(r"^the ring tempts you$"), "RING_TEMPTED"),
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
#: far most common printed scope for this template); "an opponent casts"/
#: "a player casts" are a different subject grammar `_subject_condition`
#: doesn't support yet, left unclaimed rather than silently misreading
#: "opponent" as "you". Creature *subtypes* ("wizard spell", "elf spell")
#: aren't in `_SPELL_CAST_TYPE_WORDS` — `GameObject.type_words` only ever
#: carries main card types — so a compound naming one fails closed
#: correctly rather than silently dropping the subtype qualifier.
_SPELL_CAST_TYPE_WORDS: frozenset[str] = frozenset(
    {"creature", "artifact", "enchantment", "instant", "sorcery", "planeswalker", "land", "battle"}
)
_CAST_SPELL_TRIGGER_RE = re.compile(
    r"^whenever you cast (?:an?|another) (?P<types>[a-z][a-z,\s]*?) spell,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
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
    r") deals (?P<combat>combat )?damage to (?:an?|1 of your) (?P<recipient>player|opponent|creature)s?,"
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
    rf"(?:{_VERB_ALT})(?:\s+the\s+battlefield)?(?:\s+alone)?$"
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

#: RULE 603.1's condition subject — a *group* of objects, not just the
#: source itself: "a"/"another" <type> [you control], then the trigger verb,
#: optionally "the battlefield" (enters) and/or "under your control" (the
#: older enters-battlefield templating). Examples this claims: "a creature
#: enters the battlefield under your control", "another creature you control
#: enters", "a creature dies", "another creature you control dies", "a
#: creature you control attacks".
_GROUP_SUBJECT_RE = re.compile(
    r"^(?P<article>another|an|a)\s+(?P<type>" + "|".join(_GROUP_TYPE_WORDS) + r")"
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
    r"tap .+ untapped .+ you control|remove .+ counters?|"
    r"return an? [a-z]+ you control to (?:its|your) owner'?s?\s*hand",
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

#: "You may look at the top card of your library any time." (Elsha of the
#: Infinite/Bolas's Citadel) — purely informational, no separate game-state
#: effect at this engine's fidelity: the *actual* play/cast-from-top
#: permission is a different clause (`game/top_library.py`, already
#: standing/battlefield-sourced), and this one only lets a player see what's
#: already implied by having that permission. Claimed as a documented no-op
#: (mirroring how a mana-ability's own effect line is "covered but no spec"
#: above) rather than wired into new behaviour — the goldfish UI has no
#: hidden-information model where "may look any time" would change anything
#: observable.
_LOOK_AT_TOP_ANY_TIME_RE = re.compile(
    r"^you may look at the top card of your library any time\.?$", re.IGNORECASE
)

#: "Play with the top card of your library revealed." (Oracle of Mul
#: Daya/Future Sight-shaped) — the same "purely informational, no separate
#: game-state effect" no-op as `_LOOK_AT_TOP_ANY_TIME_RE` just above, printed
#: as its own line right next to the actual play/cast-from-top permission
#: (`catalogue.static_handlers._TOP_LIBRARY_PERMISSION_RE`) rather than
#: combined with it.
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

#: "Strive — This spell costs `<cost>` more to cast for each target beyond
#: the first." (MEC-4) — not a RULE 702 keyword (no CR entry defines it, see
#: `AbilitySpec.strive_cost`'s docstring), so it's recognized as its own
#: standalone-line template here rather than through `keywords.py`'s
#: numbered catalogue. ``<cost>`` is a run of brace-delimited symbols, same
#: shape `_STRIVE_COST_RE` (`parser/oracle/spec.py`) validates.
_STRIVE_LINE_RE = re.compile(
    r"^strive\s*[—-]\s*this spell costs (?P<cost>(?:\{[^{}]+\})+) more to cast "
    r"for each target beyond the first\.?\s*$",
    re.IGNORECASE,
)


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
    r"^(?:" + "|".join(re.escape(d) for d in _KEYWORD_DISPLAYS) + r")\b.*$"
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


def _is_keyword_token(tok: str) -> bool:
    return bool(_KEYWORD_TOKEN_RE.match(tok) or _CYCLING_TOKEN_RE.match(tok) or re.match(r"^[a-z]+walk\b", tok))


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
        return {
            "subject": "group",
            "type": m.group("type"),
            "controller": "you" if (m.group("you_a") or m.group("you_b")) else "any",
            "other": m.group("article") == "another",
        }
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


def parse_effect_body(
    body: str, *, self_subject: bool = False, previous_subject: bool = False
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
    """
    body = body.strip().rstrip(".").strip()
    if not body:
        return []

    kicked = _KICKED_CONDITION_RE.match(body)
    if kicked is not None:
        inner = parse_effect_body(
            kicked.group("rest"), self_subject=self_subject, previous_subject=previous_subject
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

    target_is_you = _TARGET_IS_CONTROLLER_RE.match(body)
    if target_is_you is not None:
        inner = parse_effect_body(
            target_is_you.group("rest"),
            self_subject=self_subject,
            previous_subject=previous_subject,
        )
        if inner is None:
            return None
        wants_controller = not target_is_you.group("neg")
        return [
            EffectSpec(e.type, dict(e.params), condition={"target_is_controller": wants_controller})
            for e in inner
        ]

    life_gained = _LIFE_GAINED_THIS_TURN_CONDITION_RE.match(body)
    if life_gained is not None:
        inner = parse_effect_body(
            life_gained.group("rest"), self_subject=self_subject, previous_subject=previous_subject
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
            )
            if more is None:
                return None
            return conditioned + more
        return conditioned

    ring_bearer_other = _RING_BEARER_OTHER_CONDITION_RE.match(body)
    if ring_bearer_other is not None:
        inner = parse_effect_body(
            ring_bearer_other.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject,
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
            previous_subject=previous_subject,
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

    direct = match_clause(body, self_subject=self_subject, previous_subject=previous_subject)
    if direct is not None:
        return direct

    for sep in _CONNECTORS:
        parts = [p for p in re.split(sep, body) if p.strip()]
        if len(parts) > 1:
            collected: list[EffectSpec] = []
            ok = True
            referent = False
            for part in parts:
                sub = parse_effect_body(part, previous_subject=referent)
                if sub is None:
                    ok = False
                    break
                collected.extend(sub)
                # RULE 601.2c: what the clause just parsed *chose* is what
                # the next one's "it"/"that creature"/"those creatures" can
                # point at (`handlers.EffectHandler.previous_subject_only`,
                # `effects.GameContext.previous_targets`). A clause that
                # chose no creature leaves the pronoun unbound — and so
                # unclaimed — rather than letting it drift onto some earlier
                # clause's pick, which is the ambiguity this gate exists for.
                referent = _announces_creature_target(sub)
            if ok:
                return collected
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
    """Whether the last of ``specs`` picks a permanent the next clause can
    refer back to as "it"/"that creature"/"those creatures"."""
    if not specs:
        return False
    values: list[Any] = []
    for value in specs[-1].params.values():
        values.extend(value if isinstance(value, list) else [value])
    return any(isinstance(v, str) and v in _CREATURE_TARGET_KINDS for v in values)


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

    if _LOOK_AT_TOP_ANY_TIME_RE.match(raw) or _PLAY_WITH_TOP_REVEALED_RE.match(raw):
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

    cast_spell_trig = _CAST_SPELL_TRIGGER_RE.match(raw)
    if cast_spell_trig is not None:
        types = _parse_cast_spell_types(cast_spell_trig.group("types"))
        if types is None:
            return Segment(raw=raw)
        effects = parse_effect_body(cast_spell_trig.group("body"))
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": {"subject": "you"},
                "spell_card_types": types,
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
        damage_filter: dict[str, Any] = {
            "is_player": damage_trig.group("recipient") in ("player", "opponent")
        }
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
        if _MANA_EFFECT_RE.match(effect_text):
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
        effects = parse_effect_body(body)
        if effects is None:
            return Segment(raw=raw)
        trigger: dict[str, Any] = {"event": "STEP_BEGIN", "filter": {"step": step}}
        if relation is not None:
            trigger["phase_relation"] = relation
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
            effects = parse_effect_body(body)
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
        multi = _SELF_MULTI_EVENT_RE.match(cond_text.strip())
        if multi is not None:
            event: "str | list[str]" = [_VERB_EVENTS[multi.group("v1")], _VERB_EVENTS[multi.group("v2")]]
            condition: Optional[dict[str, Any]] = {"subject": "self"}
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
        # ambiguous, so only this scope unlocks it.
        effects = parse_effect_body(body, self_subject=condition == {"subject": "self"})
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
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

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


#: "you may pay {E}… . If/When you do, <effect>." (Aether Chaser) — the
#: "you may" here is the *energy-payment* decision the `pay_energy_then`
#: effect models with its own interactive choice, not a whole-ability "you
#: may". Left un-peeled so the full clause reaches `parse_effect_body`'s
#: `pay_energy_then` handler intact (otherwise the ability would be marked
#: doubly-optional and the "if you do" gate would be lost).
_PAY_ENERGY_THEN_PEEL_GUARD_RE = re.compile(
    r"^you may pay (?:\{e\})+\.\s*(?:if|when) you do", re.IGNORECASE
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
