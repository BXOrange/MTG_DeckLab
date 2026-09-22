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
from typing import Any, Callable, Optional

from .catalogue.object_trigger_head import parse_object_trigger_head
from .catalogue.count_phrase import parse_count_phrase
from .catalogue.spell_phrase import parse_spell_phrase
from .catalogue.subtype_vocabulary import SUBTYPES
from .catalogue.handlers import (
    ACTIVATE_ONLY_ONCE_MARKER,
    ACTIVATION_CONDITION_MARKER,
    FROM_HAND_MARKER,
    ONCE_PER_TURN_MARKER,
    POWERUP_COST_REDUCTION_MARKER,
    TRIGGER_ONCE_PER_TURN_MARKER,
    _CYCLING_XX_TOKEN_RE,
    _cycling_xx_token,
    _DELAYED_SAC_EXILE_TAIL_RE,
    _MAY_COST_THEN_CLAUSE,
    _MAY_EFFECT_THEN_ANTECEDENT_PHRASES,
    match_clause,
)
from .catalogue.keywords import ALIAS_DISPLAYS, KEYWORDS, KeywordShape
from .catalogue.replacements import replacement_clause_specs
from .catalogue.saga import CHAPTER_LINE_RE, parse_chapter_token
from .catalogue.static_handlers import (
    enter_choice_specs,
    static_condition,
    static_effect_specs,
)
from .catalogue.subgrammars import COLOR_WORD_ALT, resolve_color_word
from .spec import GROUP_SUBJECT_KEY_SENTINEL, AbilitySpec, EffectSpec, ParserProvenance

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
#: "specializes" joined the table in MEC-48 — `SpecializeEffect` fires
#: `EventType.SPECIALIZED` per-permanent, even though the digital keyword's
#: characteristic swap itself is a documented simplification (no face data).
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
    # MEC-48: "when ~ specializes" — the trigger half of the Specialize
    # digital keyword. `SpecializeEffect` fires `SPECIALIZED` with the
    # object's own `instance_id`, so this rides RULE 603.1 self-subject
    # scoping exactly like "becomes monstrous". "specializes from your
    # graveyard" / "specializes from any zone" carry a trailing zone phrase
    # the verb match ignores (the engine fires the same event regardless of
    # the from-zone), so the shorter "specializes" row claims them too.
    ("specializes", "SPECIALIZED"),
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
    # PAR-124: Forth Eorlingas! prints the recipient-side plural, "to 1 or
    # more players", instead of the singular "to a player" — the same
    # aggregate event either way (RULE 508.1's target is always exactly one
    # player, "1 or more" on that side is just a wording variant, not a
    # second qualifier to model).
    (re.compile(r"^1 or more creatures you control deal combat damage to"
                r" (?:a player|1 or more players)$"),
     "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"),
    # "…1 or more **nontoken** creatures you control…" (Feywild Visitor's
    # granted trigger) — same aggregate event, gated on the
    # ``contributor_any_nontoken`` flag the combat step now stamps (RULE
    # 111.9). Carried as a trailing filter marker `_player_trigger_event`'s
    # caller lifts onto the trigger dict.
    (re.compile(r"^1 or more nontoken creatures you control deal combat damage to"
                r" (?:a player|1 or more players)$"),
     ("CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER", {"contributor_any_nontoken": True})),
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
    # RULE 706: "Whenever you roll one or more dice, …" (Farideh, Devil's
    # Chosen / Vrondiss, Rage of Ancients / Barbarian Class level 2) —
    # `RulesEngine.roll_die` fires `EventType.DICE_ROLLED` once per roll
    # instruction (RULE 706.3b), keyed by ``player_id``, the same
    # per-player convention as SCRY/SURVEIL/CLASHED above. "one or more"
    # has already been normalised to "1 or more"; the bare "roll a die"
    # spelling is folded in for completeness though no cached card prints
    # a trigger on exactly one die yet.
    (re.compile(r"^you roll (?:a die|1 or more dice)$"), "DICE_ROLLED"),
    # PAR-79 residue: RULE 701.8's "Whenever you discard a card, …"
    # (All-Seeing Arbiter/Hobgoblin, Mantled Marauder-shaped) —
    # `EventType.DISCARD_CARD` already exists and already fires once per
    # discarded card, carrying `player_id` (its own docstring names this
    # exact trigger shape as the reason it's a per-card sibling of the
    # aggregate `DISCARD`); only the oracle-text recognition was missing.
    # "another" (Curator of Mysteries) is the identical event for a
    # battlefield permanent's own ability — it can never itself be the
    # discarded card — so both spellings collapse to one row.
    (re.compile(r"^you discard (?:a|another) card$"), "DISCARD_CARD"),
    # RULE 702.28c's *unscoped* form — "Whenever you cycle a card, …"
    # (Jo Grant/Crystalline Resonance) or "…another card" (Drannith
    # Healer/Benalish Partisan) — the sibling of `_CYCLE_TRIGGER_RE`
    # above, which only ever claims the *self*-scoped "When you cycle
    # this card,". `EventType.CYCLED` already fires with `controller_id`
    # for exactly this; same "another can't be this ability's own card"
    # collapse as the discard row just above.
    (re.compile(r"^you cycle (?:a|another) card$"), "CYCLED"),
    # The compound "Whenever you cycle or discard a[nother] card, …"
    # (Cunning Survivor/Flameblade Adept/Drake Haven-shaped — the single
    # highest-yield row in this whole addition) and its reverse ordering,
    # mirroring the "you scry or surveil"/"you surveil or scry" pair
    # above: one `AbilitySpec` per event, both already-shipped.
    (re.compile(r"^you cycle or discard (?:a|another) card$"), ["CYCLED", "DISCARD_CARD"]),
    (re.compile(r"^you discard or cycle (?:a|another) card$"), ["DISCARD_CARD", "CYCLED"]),
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
#:
#: ``(?:or copy )?`` (2026-09-07) folds in RULE ~702.153 **Magecraft** —
#: "Magecraft — Whenever you cast **or copy** an instant or sorcery spell,
#: …" (Archmage Emeritus / Veyran / Storm-Kiln Artist / Prismari Pianist-
#: adjacent). The old `_MAGECRAFT_RE` whole-line recognizer is unreachable
#: now that `normalize._strip_unregistered_keyword_labels` peels the
#: "Magecraft — " ability-word label (it isn't a registered RULE 702
#: keyword), leaving exactly this shape; the engine still has no spell-copy
#: event bus, so — as that recognizer's own docstring notes — only the
#: "cast" half binds (`EventType.SPELL_CAST`) and the "copy" branch is
#: unreachable by any state the engine can currently produce, not silently
#: wrong.
_CAST_SPELL_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? (?:or copy )?(?:an?|another) "
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

#: PAR-119: the composed cast-trigger head — actor + "cast" + a spell phrase
#: that `catalogue.spell_phrase.parse_spell_phrase` builds from shared word
#: tables (characteristic adjectives, ``with`` qualifiers, cast-from zone,
#: ownership, targets). One row for what used to be one regex *and* one ~25-line
#: dispatch block per adjective combination (`_CAST_SPELL_TRIGGER_MV_RE`,
#: `_..._HISTORIC_RE`, …). Tried only after every legacy row declined, so it
#: can only add coverage, never change a spec a legacy row already emits.
_CAST_TRIGGER_COMPOSED_RE = re.compile(
    r"^(?:whenever|when) (?P<subj>you|an opponent|a player) casts? "
    r"(?P<phrase>(?:an?|another) [^,]*?\bspell\b[^,]*),\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)


def _cast_trigger_segment(
    raw: str, subj: str, trigger_keys: dict[str, Any], body_text: str, provenance: ParserProvenance
) -> Segment:
    """The one dispatch for a `SPELL_CAST` trigger whose head is already parsed
    into ``trigger_keys``: optional peel, the two-rider mana-spent shape, the
    intervening "if at least N mana was spent", then the body."""
    body, optional = _peel_optional(body_text)
    trigger = {
        "event": "SPELL_CAST",
        "condition": _cast_spell_trigger_condition(subj),
        **trigger_keys,
    }
    two_rider_parts = _cast_mana_two_rider_parts(body, self_subject=True)
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
    body, mana_spent_at_least = _peel_spell_mana_spent_at_least(body)
    effects = parse_effect_body(body, self_subject=True)
    if effects is None:
        return Segment(raw=raw)
    if mana_spent_at_least is not None:
        trigger = {**trigger, "spell_mana_spent_at_least": mana_spent_at_least}
    spec = AbilitySpec("triggered", effects=effects, trigger=trigger,
        optional=optional, raw_text=raw, parser=provenance)
    return Segment(raw=raw, spec=spec, claimed=True)


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


def _cast_mana_rider_parts(body: str, *, self_subject: bool) -> Optional[tuple[list[EffectSpec], int, list[EffectSpec], bool]]:
    """Parse PAR-96's one-rider cast-trigger body without losing its gate."""
    m = _CAST_MANA_RIDER_RE.match(body.strip())
    if m is None:
        return None
    base = parse_effect_body(m.group("base"), self_subject=self_subject)
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
        else parse_effect_body(rider_text.removeprefix("also "), self_subject=self_subject)
    )
    if base is None or rider is None:
        return None
    return base, int(m.group("n")), rider, replaces


def _cast_mana_two_rider_parts(
    body: str, *, self_subject: bool,
) -> Optional[tuple[list[EffectSpec], list[tuple[int, list[EffectSpec]]]]]:
    """Parse PAR-96's additive two-threshold trigger body (Tellah)."""
    m = _CAST_MANA_TWO_RIDERS_RE.match(body.strip())
    if m is None:
        return None
    base = parse_effect_body(m.group("base"), self_subject=self_subject)
    first = parse_effect_body(m.group("rider1").strip().rstrip("."), self_subject=self_subject)
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
        second = parse_effect_body(second_text, self_subject=self_subject)
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
    # "…from exile" (Passionate Archaeologist's granted trigger) — RULE
    # 601.2a's cast zone, read off the `SPELL_CAST` event's ``from_exile``
    # key (`effect_binder`'s ``spell_from_exile`` predicate), the same
    # "gate the cast trigger on an event field" idiom as the mana-value /
    # ``from_hand`` rows.
    r"(?P<from_exile> from exile)?"
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

#: RULE 605.1: "Whenever you/a player taps a `<land type>`/land for mana,
#: <effect>." (Crypt Ghast/Wild Growth-shaped, hitherto only hand-authored
#: — Bubbling Muck/High Tide's own symmetric, unscoped "a player" form).
#: `EventType.TAPPED_FOR_MANA` already carries everything a RULE 603.1
#: group-subject condition over the tapped *land* needs (`type`/`subtypes`/
#: `controller`); "you" narrows to the ability's own controller the same
#: way `_cast_spell_trigger_condition` does for cast/draw triggers, "a
#: player" leaves it unscoped (any player's land).
_TAP_FOR_MANA_TRIGGER_RE = re.compile(
    r"^whenever (?P<subj>you|a player) taps? an? "
    r"(?P<land>swamp|island|mountain|forest|plains|land) for mana,\s*(?P<body>.+)$",
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

#: PAR-79 fifth increment: the ``>=`` mirror of `_CAST_SPELL_TRIGGER_MV_RE`
#: just above — "Whenever you cast a spell with mana value N or greater,
#: <effect>." (Angry Rabble/Enraged Flamecaster/Etherium Spinner-shaped).
#: `effect_binder`'s ``spell_mana_value_at_least`` predicate (built for
#: PAR-60's "…with mana value 5 or greater" *card-type-qualified* row —
#: `_CAST_SPELL_TRIGGER_RE`'s own ``types`` slot already threads it through
#: a *typed* cast trigger) already existed with **no bare, untyped
#: recognizer at all** — this row is exactly that missing piece, the same
#: gap `spell_has_x`/`first_x_spell` turned out to have below. Deliberately
#: narrow to the untyped "a spell" shape (like `_CAST_SPELL_TRIGGER_MV_RE`'s
#: own "or less" sibling); a typed "an instant or sorcery spell with mana
#: value N or greater" already reaches the threshold through
#: `_CAST_SPELL_TRIGGER_RE`'s own dispatch (see the mana-value branch added
#: there), not this row.
_CAST_SPELL_TRIGGER_MV_AT_LEAST_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell with "
    r"mana value (?P<n>\d+) or greater,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-79 fifth increment: "Whenever you cast a spell with {X} in its mana
#: cost, <effect>." (Matterbending Mage/Zaxara, the Exemplary/Geometer's
#: Arthropod-shaped) — `effect_binder`'s ``spell_has_x`` predicate already
#: existed (built for PAR-60's Elementalist's Palette/Quandrix {X}-first-
#: spell cluster) with no oracle-text recognizer reaching it at all; same
#: gap shape as the mana-value row above. The ordinal "your first spell
#: with {X} in its mana cost each turn" sibling reads the same-vintage
#: ``first_x_spell`` predicate and is recognized separately below.
_CAST_SPELL_TRIGGER_X_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a spell with "
    r"\{x\} in its mana cost,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)
_CAST_SPELL_TRIGGER_FIRST_X_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? (?:your|their) first "
    r"spell with \{x\} in its mana cost each turn,\s*(?P<body>.+)$",
    re.IGNORECASE | re.S,
)

#: PAR-79 fifth increment: "Whenever you cast a historic spell, <effect>."
#: (RULE 700.13 — an artifact, legendary, or Saga spell; Jhoira, Weatherlight
#: Captain/Cabal Paladin/Artificer's Assistant-shaped Kaladesh/Dominaria
#: payoffs) — same dead-primitive shape as the {X} rows just above:
#: `effect_binder`'s ``spell_is_historic`` predicate already existed with no
#: segmenter regex reaching it at all.
_CAST_SPELL_TRIGGER_HISTORIC_RE = re.compile(
    r"^whenever (?P<subj>you|an opponent|a player) casts? a historic spell,"
    r"\s*(?P<body>.+)$",
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
    r"|(?P<article>another|an|a) (?P<goaded>goaded )?(?:(?P<type>"
    + "|".join(_GROUP_TYPE_WORDS) + r")"
    # PAR-117 (group-subject residue, Essence/Brood/Synapse Sliver-shaped:
    # "whenever a **Sliver** deals [combat ]damage[ to a player], …") — a
    # creature *subtype* standing in for `_GROUP_TYPE_WORDS`'s closed main-
    # type list, the identical "any lowercase word, no whitelist" shape
    # `_GROUP_SUBTYPE_SUBJECT_RE` already accepts for the ENTERS/DIES/
    # ATTACKS/BLOCKS family (fail-safe: a non-subtype word just never
    # matches any real object, so this never over-fires). Tried only after
    # the closed `type` alternative above, so "a **creature** deals damage"
    # keeps matching that one first.
    r"|(?P<subtype>[a-z]+))"
    # "a creature **token** you control deals combat damage to a player"
    # (Curiosity Crafter / Reconnaissance Mission-for-tokens) — RULE 111.9's
    # is-a-token filter on the acting object.
    r"(?P<token> token)?"
    r"(?P<yours> you control)?"
    # RULE 310: "…to a player or battle" (Furnace Reins-shaped) — the battle
    # case rides the same ``{"is_player": true}`` DAMAGE filter (a documented
    # simplification: the far commoner player-damage firing is exact; battle
    # damage as an extra trigger source isn't separately modelled). The whole
    # "to <recipient>" is optional: a bare "deals damage" (Shackles of
    # Treachery's granted trigger) matches *any* damage instance, so the
    # dispatch below omits the ``is_player`` key entirely in that case.
    r") deals (?P<combat>combat )?damage"
    r"(?: to (?:an?|1 of your) (?P<recipient>player|opponent|creature)s?"
    r"(?P<or_planeswalker> or planeswalker)?(?: or battle)?)?,"
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

#: RULE 603.3f's "one or more <X> die" batch death trigger (Morbid
#: Opportunist / Sengir Connoisseur / Vraan / Dramatic Finale / Ghoulish
#: Procession / Homicide Investigator …). The engine fires a per-object
#: `DIES` event, not a per-batch aggregate, so this is modeled as an
#: ordinary `{"subject": "group", "type": "creature"}` DIES trigger — but
#: **only claimed when the body also carries "This ability triggers only
#: once each turn."** (`_TRIGGER_ONCE_PER_TURN_RE` → `limit`), which makes
#: the per-object firing collapse to the once-per-turn net behaviour the
#: real card has. The handful of un-limited "1 or more … die" cards (Great
#: Fierce Bee, Vengeful Townsfolk) stay unclaimed — a per-object model
#: would over-fire on a board wipe (that needs a real batch aggregate —
#: MEC, see PAR-60).
_BATCH_DIES_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more (?P<other>other )?(?P<nontoken>nontoken )?"
    r"creatures(?P<yours> you control)? die$"
)

#: "Whenever one or more other creatures you control enter, …" (Frantic
#: Scapegoat).  The event dispatcher exposes each entering object, so the
#: group predicate supplies the precise controller/type/other filter; a
#: simultaneous entry is still represented by its individual entry events.
_BATCH_ENTER_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more other creatures you control enter$"
)

_CREATURE_EXPLORES_TRIGGER_RE = re.compile(
    r"^a creature you control explores(?: a (?P<result>land|nonland) card)?$",
    re.IGNORECASE,
)

#: RULE 603.3f — Quintorius, Field Historian: one trigger for the complete
#: zone-change event, whether one card is flashback-cast or many are returned
#: together. The optional timing tail is an intervening trigger condition.
_CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE = re.compile(
    r"^(?:1|one) or more cards leave your graveyard(?P<during> during your turn)?$"
)

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
    # PAR-117 (group-subject residue, Bereavement-shaped: "whenever a
    # **green** creature dies"): a colour on the acting object, the RTR
    # "Denizen" cycle's own trigger shape ("whenever another `<color>`
    # creature you control enters"). `_build_group_ok`'s new ``color`` key,
    # read off the DIES/LEAVES_BATTLEFIELD event's snapshotted ``colors``
    # (RULE 400.7 — the object is gone by the time a DIES trigger checks)
    # with the same live-board fallback every other characteristic filter
    # here already uses for a verb that keeps the object around.
    r"(?:(?P<color>" + COLOR_WORD_ALT + r")\s+)?"
    # A single main type, or an "X or Y[ or Z]" list of them ("an artifact
    # or creature you control dies" — Agent of the Iron Throne). Each word
    # is from the closed `_GROUP_TYPE_WORDS` vocabulary; `_group_subject_
    # condition` splits the list and `effect_binder._build_group_ok`
    # already ORs a `type` list.
    r"(?P<type>(?:" + "|".join(_GROUP_TYPE_WORDS) + r")"
    r"(?:,? or (?:" + "|".join(_GROUP_TYPE_WORDS) + r"))*)"
    # "you control" or its mirror "an opponent controls" (Necroskitter /
    # The Reaper, King No More — `_build_group_ok` maps the latter to the
    # existing ``controller="not_you"`` scope).
    r"(?:(?P<you_a> you control)|(?P<opp> an opponent controls))?"
    # PAR-117 (group-subject residue, Kavu Lair-shaped: "whenever a creature
    # with power 4 or greater enters"/"whenever a creature you control with
    # power 2 or less attacks") — the same "with power `<n>` or `<less/
    # greater>`" fragment several one-shot handlers already share
    # (`handlers.py`'s target/damage-filter rows), reused here as a
    # qualifier on the acting object itself. `_build_group_ok`'s new
    # ``min_power``/``max_power`` keys read the event's live power (every
    # verb this can appear on — ENTERS_BATTLEFIELD, ATTACKS — keeps the
    # object on the battlefield when the condition is checked, RULE 508.3/
    # 508.1, unlike DIES's colour filter which needed a snapshot).
    r"(?:\s+with power (?P<power_n>\d+) or (?P<power_cmp>less|greater))?"
    # "…**with a -1/-1 counter on it**" / "…with a +1/+1 counter on it" /
    # the kindless "…with a counter on it" (the whole -1/-1 & +1/+1
    # aristocrats archetype — Skyclave Shadowcat, Gladehart Cavalry,
    # Necroskitter, The Scorpion God, …). Read off the DIES event's
    # snapshotted ``counters`` (RULE 400.7) / live for other verbs —
    # `effect_binder._build_group_ok`'s ``has_counter``/``has_counter_kind``.
    r"(?P<ctr>\s+with an?\s+(?:(?P<ctrkind>-1/-1|\+1/\+1)\s+)?counter on it)?"
    rf"\s+(?:{_VERB_ALT})"
    # "Whenever a creature blocks **this turn**" (Mage Hunters'
    # Onslaught) — on a trigger condition this is a tautological time tail,
    # not a duration the resulting ability has to remember: the BLOCKS event
    # necessarily occurred during the current turn. Consume it rather than
    # leaving an otherwise ordinary RULE 603.1 group condition unclaimed.
    r"(?:\s+this turn)?"
    r"(?:\s+the\s+battlefield)?(?:\s+alone)?"
    # PAR-117 (group-subject residue, Hissing Miasma/Blood Reckoning-shaped:
    # "whenever a creature attacks **you [or a planeswalker you control]**")
    # — RULE 508.1b's defending-player scope. The ATTACKS event's own
    # ``defending_player_id`` is the player directly attacked or, for a
    # planeswalker defender, that planeswalker's controller; `_build_group_ok`
    # compares it to this ability's controller. The longer spelling is kept
    # distinct: attacking a battle protected by that player does not satisfy
    # a printed "you or a planeswalker you control" condition.
    r"(?P<attacks_you_or_planeswalker>\s+you or a planeswalker you control)?"
    r"(?P<attacks_you>\s+you)?"
    # PAR-120: "whenever a creature attacks 1/one of your opponents, …"
    # (Calculating Lich) — RULE 506.4's *any*-opponent scope, distinct from
    # ``attacks_you`` (a specific player: the controller). The ATTACKS
    # event's ``defending_player_id`` just needs to be a living opponent of
    # this ability's controller, not equal to any one fixed player.
    r"(?P<attacks_opponent>\s+(?:1|one) of your opponents)?"
    # Curse of the Forsaken: the group subject is the attacking creature,
    # while "enchanted player" is this Aura's player attachment. Kept apart
    # from ``attached_permanent`` — a player has no GameObject identity.
    r"(?P<attacks_enchanted_player>\s+enchanted player)?"
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

_ACTIVATION_COST_REDUCTION_SELECTORS: dict[str, str] = {
    "basic land type among lands you control": "basic_land_types_among_lands_you_control",
    "creature card in your graveyard": "creature_cards_in_your_graveyard",
    "instant and sorcery card in your graveyard": "instant_or_sorcery_cards_in_your_graveyard",
    "legendary creature you control": "legendary_creatures_you_control",
    "legendary creature and planeswalker you control": "legendary_creatures_and_planeswalkers_you_control",
    "other artifact you control": "other_artifacts_you_control",
    "other equipment you control": "other_permanents_you_control_of_subtype_equipment",
    "equipment you control": "equipment_you_control",
    "other town you control": "other_permanents_you_control_of_subtype_town",
    "town you control": "permanents_you_control_of_subtype_town",
    "shrine you control": "permanents_you_control_of_subtype_shrine",
    "vampire you control": "creatures_you_control_of_type_vampire",
    "+1/+1 counter on creatures you control": "plus_one_counters_on_creatures_you_control",
    "modified creature you control": "modified_creatures_you_control",
}


def _activation_cost_reduction_selector(what: str) -> Optional[str]:
    """Map PAR-94's closed, per-unit discount vocabulary to live readers."""
    normalized = " ".join(what.lower().split())
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
    land = re.fullmatch(r"(?P<kind>[a-z]+) you control", normalized)
    if land is not None and land.group("kind") in {"island"}:
        return f"lands_you_control_of_type_{land.group('kind')}"
    return None

# An activated ability may end with its RULE 602 legality sentence rather
# than making it a separate oracle line: "{1}: Draw a card. Activate only if
# <condition> [and only once]."  Peel only this closed tail before parsing
# the actual body; the existing handler catalogue supplies the condition
# marker and the existing binder owns both activation limits.
_ACTIVATE_ONLY_IF_TRAILING_RE = re.compile(
    r"\.\s*activate (?:this ability )?only if (?P<cond>.+?)(?P<once> and only once)?\.?$",
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
_OTHERWISE_RE = re.compile(
    r"^otherwise,\s*(?P<rest>.+)$", re.IGNORECASE,
)


def _otherwise_specs(
    rest: str, preceding: "list[EffectSpec]", **flags: Any
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
    inner = parse_effect_body(rest, **flags)
    if not inner or any(spec.condition is not None for spec in inner):
        return None
    if gate == {"kind": "clash_won"}:
        # RULE 701.30d's clash outcome is a fact of the resolution that no branch changes, so
        # the two gated lists it always had are equivalent — and `clash` runs its own machinery.
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

#: PAR-79 eighth increment: a *preceding* sentence in front of
#: `catalogue.handlers._DELAYED_SAC_EXILE_WHEN_FIRST_RE`'s own "at the
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
    if _ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE.match(text):
        return {"sacrifice": "artifact_or_creature"}
    sac = _ADDITIONAL_COST_SACRIFICE_RE.match(text)
    if sac is not None:
        return {"sacrifice": sac.group(1)}
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

#: MEC-48: a "Specialize {cost}" line that carries a trailing rules rider on
#: the *same* line — "Specialize {5}. This ability costs {3} less to
#: activate if …", "Specialize {2}. Activate only if a player has 13 or less
#: life.", "Specialize {6}. You may also activate this ability if ~ is in
#: your graveyard." `_KEYWORD_TOKEN_RE`'s greedy `.*$` would claim the whole
#: line as a bare keyword line and silently drop the rider, so `segment_line`
#: matches this *before* `is_keyword_line` and returns the line UNMODELED
#: (fail-closed) — the bare "Specialize {cost}" line still claims normally.
#: The riders are their own follow-up (a cost-reduction / activation-
#: condition / alternate-zone rider on an activated ability).
_SPECIALIZE_WITH_RIDER_RE = re.compile(
    r"^specialize\s+\{[^}]+\}(?:\s*\{[^}]+\})*\s*[.:]\s*\S.*$", re.IGNORECASE | re.DOTALL
)
_SPECIALIZE_GRAVEYARD_DISCOUNT_RE = re.compile(
    r"^specialize\s+\{[^}]+\}\.\s*this ability costs \{\d+\} less to activate "
    r"if there are \d+ or more instant and/or sorcery cards in your graveyard\.?$", re.IGNORECASE,
)

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


def _all_subtypes(words: str) -> bool:
    """Whether every word of an "X or Y" list is a real card subtype. The tribal
    rows accept ``[a-z]+`` so they can name any creature type; without this check
    "a land or Bird you control" or "a planeswalker you control" became a
    *subtype* filter no object could ever match — claimed, but never firing."""
    return all(w.strip() in SUBTYPES for w in words.split(" or "))


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
    m = _SELF_OR_GROUP_SUBJECT_RE.match(cond)
    if m is not None:
        return {
            "subject": "self_or_group",
            "type": m.group("type"),
            "controller": "you" if m.group("you") else "any",
            "other": True,
        }
    m = _SELF_OR_GROUP_SUBTYPE_RE.match(cond)
    if m is not None and _all_subtypes(m.group("subtypes")):
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
        type_words = [w for w in re.split(r",?\s+or\s+", m.group("type")) if w]
        if m.group("you_a") or m.group("you_b"):
            controller = "you"
        elif m.group("opp"):
            controller = "not_you"  # "an opponent controls" — reuse the mirror scope
        else:
            controller = "any"
        out = {
            "subject": "group",
            "type": type_words if len(type_words) > 1 else type_words[0],
            "controller": controller,
            "other": m.group("article") == "another",
        }
        if m.group("ctr"):
            if m.group("ctrkind"):
                out["has_counter_kind"] = m.group("ctrkind")
            else:
                out["has_counter"] = True
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
        if m.group("color"):
            # "whenever a **green** creature dies" (Bereavement, the RTR
            # Denizen cycle) — `_build_group_ok`'s new ``color`` key.
            out["color"] = resolve_color_word(m.group("color"))
        if m.group("power_n"):
            # "whenever a creature with power `<n>` or `<less/greater>`
            # `<verb>`" (Kavu Lair) — `_build_group_ok`'s new
            # ``min_power``/``max_power`` keys.
            key = "min_power" if m.group("power_cmp") == "greater" else "max_power"
            out[key] = int(m.group("power_n"))
        if m.group("attacks_you"):
            # "whenever a creature attacks **you**" (Hissing Miasma) —
            # `_build_group_ok`'s new ``attacks_you`` key.
            out["attacks_you"] = True
        if m.group("attacks_you_or_planeswalker"):
            # "whenever a creature attacks you or a planeswalker you
            # control" (Blood Reckoning, Revenge of Ravens, …). The engine
            # stamps the planeswalker's controller in ATTACKS'
            # ``defending_player_id``; a separate key deliberately keeps
            # this wider printed scope distinct from bare "attacks you".
            out["attacks_you_or_planeswalker"] = True
        if m.group("attacks_enchanted_player"):
            out["attacks_enchanted_player"] = True
        if m.group("attacks_opponent"):
            # "whenever a creature attacks 1 of your opponents" (Calculating
            # Lich) — `_build_group_ok`'s new ``attacks_opponent`` key.
            out["attacks_opponent"] = True
        return out
    # Only reached once the exact main-type vocabulary above has already
    # failed to match — a genuine tribal filter ("another nontoken Zombie
    # or Mutant you control dies", The Ghoul Gunslinger-shaped).
    m = _GROUP_SUBTYPE_SUBJECT_RE.match(cond)
    if m is not None and _all_subtypes(m.group("subtypes")):
        return {
            "subject": "group",
            "subtypes": [w.strip() for w in m.group("subtypes").split(" or ")],
            "nontoken": bool(m.group("nontoken")),
            "controller": "you",
            "other": m.group("article") == "another",
        }
    return None


def trigger_condition_dict(cond_text: str) -> Optional[dict[str, Any]]:
    """A finite trigger *condition* phrase (no body) → the `AbilitySpec.trigger`-shaped
    dict it would produce (``event``, ``condition``, extra keys), or ``None``.

    For a caller that needs the condition on its own — a trigger doubler's cause
    ("a creature you control attacks") — through the same three recognisers
    `segment_line` uses for an ordinary trigger: player events, the per-adjective
    object subjects, then the composed object head.
    """
    cond = cond_text.strip()
    player_event = _player_trigger_event(cond)
    if player_event is not None:
        extra: dict[str, Any] = {}
        if isinstance(player_event, tuple):
            player_event, event_filter = player_event
            if event_filter:
                extra["filter"] = dict(event_filter)
        return {"event": player_event, "condition": {"subject": "you"}, **extra}
    event = _trigger_event(cond)
    if event is not None:
        condition = _trigger_condition(cond)
        if condition is not None:
            return {"event": event, "condition": condition}
    head = parse_object_trigger_head(cond)
    if head is not None:
        return {"event": head.event, "condition": head.condition, **head.trigger}
    return None


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
    r"^if (?P<cond>[^,]{2,80}),\s+(?P<then>.+?)[.]\s+otherwise,?\s+(?P<els>.+)$",
    re.IGNORECASE)


def _if_else_specs(
    body: str, *, self_subject: bool, previous_subject: bool,
    group_subject: bool, previous_selector: bool,
) -> "Optional[list[EffectSpec]]":
    """"if `<cond>`, `<A>`. otherwise, `<B>`." → an ``if_else`` node.

    Fails closed unless all three parts resolve: the condition through the
    shared whitelist, and both branches through the ordinary grammar.
    """
    match = _IF_OTHERWISE_RE.match(body)
    if match is None:
        return None
    condition = static_condition(match.group("cond"))
    if condition is None:
        return None
    branches = []
    for group in ("then", "els"):
        parsed = parse_effect_body(
            match.group(group).strip(), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
            previous_selector=previous_selector,
        )
        if not parsed:
            return None
        branches.append([spec.to_dict() for spec in parsed])
    return [EffectSpec("if_else", {
        "condition": condition, "then": branches[0], "else": branches[1],
    })]


#: The param keys an `EffectSpec` names a RULE 115 requirement under — the
#: same "differently-named keys" `_CREATURE_TARGET_KINDS` documents, read here
#: to answer "does this clause announce a target at all".
_TARGET_PARAM_KEYS: frozenset[str] = frozenset(
    {"target_kind", "fighter_kind", "other_kind", "dealer_kind", "kinds"}
)


def _names_a_target(spec: "EffectSpec") -> bool:
    return any(
        key in spec.params and spec.params[key] is not None
        for key in _TARGET_PARAM_KEYS
    )


#: The *quantity*-shaped "for each" operands — a number to multiply by, not a
#: group to iterate over. "for each card in your hand" is `effect_amounts`'
#: ``resource`` reading, and belongs on ENG-37's ``bind`` node (measure once,
#: hand the number to the body) rather than on ``for_each``, which would
#: iterate over objects that aren't on the battlefield at all.
_FOR_EACH_AMOUNTS: dict[str, dict[str, Any]] = {
    "card in your hand": {"kind": "resource", "resource": "hand_size"},
    "cards in your hand": {"kind": "resource", "resource": "hand_size"},
    "card in your graveyard": {"kind": "resource", "resource": "graveyard_size"},
    "cards in your graveyard": {"kind": "resource", "resource": "graveyard_size"},
    # MEC-83 / RULE 702.42a Domain — distinct basic land types (`effect_
    # amounts` ``domain`` kind, deferring to the one board-count selector).
    "basic land type among lands you control": {"kind": "domain"},
    "basic land types among lands you control": {"kind": "domain"},
}

#: The params an effect states its own magnitude in. A ``bind`` body has to
#: name exactly one of these for the measured number to land somewhere; a body
#: with none (or several) is refused rather than guessed at.
_MAGNITUDE_PARAM_KEYS: tuple[str, ...] = ("amount", "count")


def _count_amount(
    phrase: str, *, self_subject: bool, previous_subject: bool = True
) -> "Optional[dict[str, Any]]":
    """The quantity a "for each `<phrase>`" / "the number of `<phrase>`" measures, as an
    `effect_amounts` spec, or ``None`` for a phrase outside every reading."""
    phrase = phrase.strip().lower()
    amount = _FOR_EACH_AMOUNTS.get(phrase)
    if amount is not None:
        return amount
    cm = _FOR_EACH_COUNTER_RE.match(phrase)
    if cm is not None:
        who = cm.group("who").lower()
        # "~"/"this <type>" name the source; a bare "it" is the source under a
        # self-subject trigger ("when ~ dies, draw a card for each +1/+1 counter on
        # it") and an earlier clause's target only when one was announced — with
        # neither, nothing says which permanent it is, so the phrase is refused
        # rather than measured against an empty referent (which reads 0).
        if who == "~" or who.startswith("this ") or (who == "it" and self_subject):
            of = "source"
        elif previous_subject:
            of = "previous_target"
        else:
            return None
        return {"kind": "counters", "counter": cm.group("counter").lower(), "of": of}
    # PAR-120: any other count phrase — a structured selector over the shared
    # noun-phrase grammar, not a table row.
    selector = parse_count_phrase(phrase)
    if selector is None:
        return None
    return {"kind": "count_selector", "selector": selector}


def _for_each_amount_specs(
    match: "re.Match[str]", phrase: str, *, self_subject: bool,
    previous_subject: bool, group_subject: bool, previous_selector: bool,
) -> "Optional[list[EffectSpec]]":
    """"<effect> for each `<quantity>`" → a ``bind`` node, or ``None``.

    Fails closed on an unlisted quantity phrase, a body that doesn't parse, a
    body that announces a target, or a body whose magnitude isn't a single
    recognised param — in the last case there is nowhere unambiguous to put
    the measured number, and putting it in the wrong place would scale
    something the card never scaled.
    """
    amount = _count_amount(phrase, self_subject=self_subject, previous_subject=previous_subject)
    if amount is None:
        return None
    return _bound_for_each_amount(
        match, amount, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )


def _bound_for_each_amount(
    match: "re.Match[str]", amount: dict[str, Any], *, self_subject: bool,
    previous_subject: bool, group_subject: bool, previous_selector: bool,
) -> "Optional[list[EffectSpec]]":
    """The body of "<effect> for each `<quantity>`" bound to a measured ``amount``."""
    inner = parse_effect_body(
        match.group("rest").strip(), self_subject=self_subject,
        previous_subject=previous_subject, group_subject=group_subject,
        previous_selector=previous_selector,
    )
    if not inner or len(inner) != 1 or _names_a_target(inner[0]):
        return None
    keys = [k for k in _MAGNITUDE_PARAM_KEYS if k in inner[0].params]
    if len(keys) != 1:
        return None
    params = dict(inner[0].params)
    printed = params[keys[0]]
    if isinstance(printed, bool) or not isinstance(printed, int) or printed < 1:
        return None  # only a printed number can scale the count ("lose 2 life for each …")
    if printed > 1:
        amount = {**amount, "multiply": printed}
    params[keys[0]] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": inner[0].type, "params": params}],
    })]


#: PAR-62: "<effect> for each <group>" (`13_` 5.2's 5.9% connective) as an
#: ENG-37 ``for_each`` node over `continuous.group_selector_objects`.
#:
#: Deliberately narrow, for two reasons the measurement made concrete.
#: **(1)** Only *object-group* phrases belong on this node. The other frequent
#: "for each" operands are counts, not battlefield groups — "for each card in
#: your hand", "for each +1/+1 counter on it" — and those are an *amount*
#: (`game/effect_amounts.py`), not an iteration; routing them here would
#: iterate over nothing and silently do nothing at all.
#: **(2)** `parser/oracle/` may not import `game/` (docs/09), so nothing here
#: can check a selector name against the engine's vocabulary. An unknown name
#: fails closed *inside* the node — which reads as a MODELED card that does
#: nothing, the exact half-modeling the gate exists to stop. So the names are
#: a short hand-verified list, and `tests/test_par62_connectives.py` asserts
#: every one of them is a real `group_selector_objects` selector. Add a row
#: only with a test that crosses that boundary for you.
_FOR_EACH_SELECTORS: dict[str, str] = {
    "creature you control": "creatures_you_control",
    "creatures you control": "creatures_you_control",
    "artifact you control": "artifacts_you_control",
    "artifacts you control": "artifacts_you_control",
    "land you control": "lands_you_control",
    "lands you control": "lands_you_control",
    "permanent you control": "permanents_you_control",
    "permanents you control": "permanents_you_control",
    "legendary creature you control": "legendary_creatures_you_control",
    "attacking creature": "attacking_creatures",
    "attacking creatures": "attacking_creatures",
}

_FOR_EACH_SUFFIX_RE = re.compile(
    # MEC-83 widened the group class to admit "+1/+1 counter on it" — digits
    # and `+`/`/` — alongside the plain "creatures you control" phrasings.
    r"^(?P<rest>.+?),?\s+for each (?P<group>[a-z0-9+/ -]{3,45})$", re.IGNORECASE)

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
    body: str, *, self_subject: bool, previous_subject: bool,
    group_subject: bool, previous_selector: bool,
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
    selector = _FOR_EACH_SELECTORS.get(phrase)
    if selector is None:
        return _for_each_amount_specs(
            match, phrase, self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
            previous_selector=previous_selector,
        )
    inner = parse_effect_body(
        match.group("rest").strip(), self_subject=self_subject,
        previous_subject=previous_subject, group_subject=group_subject,
        previous_selector=previous_selector,
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
#: The params an X can sit in once an X-capable handler has parsed the body.
_X_PARAM_KEYS: tuple[str, ...] = ("amount", "count", "power", "toughness")


def _where_x_specs(
    body: str, *, self_subject: bool, previous_subject: bool,
    group_subject: bool, previous_selector: bool,
) -> "Optional[list[EffectSpec]]":
    """See `_WHERE_X_RE`; ``None`` unless exactly one recognised param holds the X."""
    text = body.strip().rstrip(".").strip()
    m = _WHERE_X_RE.match(text)
    if m is not None:
        rest = m.group("rest")
    else:
        m = _EQUAL_TO_RE.match(text)
        if m is None:
            return None
        rest = f"{m.group('verb')} x {m.group('noun')}{m.group('tail') or ''}"
    amount = _count_amount(
        m.group("phrase"), self_subject=self_subject, previous_subject=previous_subject
    )
    if amount is None:
        return None
    inner = parse_effect_body(
        rest.strip(), self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )
    if not inner or len(inner) != 1:
        return None
    params = dict(inner[0].params)
    holders = [k for k in _X_PARAM_KEYS if params.get(k) == "x"]
    if not holders or any(v == "-x" for v in params.values()):
        return None
    for key in holders:
        params[key] = "$n"
    return [EffectSpec("bind", {
        "name": "n",
        "amount": amount,
        "effects": [{"type": inner[0].type, "params": params}],
    })]


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
    r"^if (?P<cond>[^,]{2,80}),\s+(?P<rest>.+)$", re.IGNORECASE)
_GENERIC_IF_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?),?\s+if (?P<cond>[^,]{2,80})$", re.IGNORECASE)
#: "…unless `<x>`" is the same gate negated — ENG-36 added the ``not``
#: combinator to `static_conditions` for exactly this shape.
_GENERIC_UNLESS_PREFIX_RE = re.compile(
    r"^unless (?P<cond>[^,]{2,80}),\s+(?P<rest>.+)$", re.IGNORECASE)
_GENERIC_UNLESS_SUFFIX_RE = re.compile(
    r"^(?P<rest>.+?),?\s+unless (?P<cond>[^,]{2,80})$", re.IGNORECASE)


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


def _peel_condition(
    body: str,
    table: tuple[_ConditionPrefix, ...],
    *,
    self_subject: bool,
    previous_subject: bool,
    group_subject: bool,
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
        inner = parse_effect_body(
            match.group("rest"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if inner is None:
            return True, None
        condition = row.build(match)
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
            trailing, self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        return True, (gated + more if more is not None else None)
    return False, None


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
    attached_subject: bool = False,
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

    # "…, whenever `<event>` this turn, `<effect>`" as one sentence of a larger body — after an
    # "if C," gate or a first sentence — creates the same turn-long trigger a whole line does.
    if _TURN_TRIGGER_RE.match(body):
        turn_trigger = _turn_trigger_segment(body, provenance=ParserProvenance())
        if turn_trigger is not None and turn_trigger.claimed and turn_trigger.spec is not None:
            return list(turn_trigger.spec.effects)

    return_then = re.fullmatch(r"(?P<before>return .+?)\. if you do, (?P<after>.+)", body, re.I | re.S)
    if return_then is not None:
        before_specs = parse_effect_body(return_then.group("before"), self_subject=self_subject)
        after_specs = parse_effect_body(return_then.group("after"), self_subject=self_subject)
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
        body, _CONDITION_PREFIXES, self_subject=self_subject,
        previous_subject=previous_subject, group_subject=group_subject,
    )
    if matched:
        return peeled

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

    die_to_exile = _DIE_TO_EXILE_SENTENCE_RE.match(body)
    if die_to_exile is not None:
        before_specs = parse_effect_body(
            die_to_exile.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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
        elif _announces_creature_target(before_specs):
            rider = EffectSpec("grant_die_to_exile_this_turn", {"previous_subject": True})
        else:
            return None
        return _with_after_tail(
            before_specs + [rider],
            die_to_exile.group("after"),
            previous_subject=_announces_creature_target(before_specs), group_subject=group_subject,
        )

    kicked_mag = _KICKED_MAGNITUDE_OVERRIDE_RE.match(body)
    if kicked_mag is not None:
        before_specs = parse_effect_body(
            kicked_mag.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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

    exile_self_delayed_return = _EXILE_SELF_THEN_DELAYED_RETURN_RE.match(body)
    if exile_self_delayed_return is not None:
        before_specs = parse_effect_body(
            exile_self_delayed_return.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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

    roll_when_you_do = _ROLL_DIE_THEN_WHEN_YOU_DO_RE.match(body)
    if roll_when_you_do is not None:
        before_specs = parse_effect_body(
            roll_when_you_do.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        after_specs = parse_effect_body(
            roll_when_you_do.group("after"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
        )
        if (before_specs is None or len(before_specs) != 1
                or before_specs[0].type != "roll_die" or after_specs is None):
            return None
        params = dict(before_specs[0].params)
        params["then_trigger"] = [spec.to_dict() for spec in after_specs]
        return [EffectSpec("roll_die", params)]

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

    # PAR-79 eighth increment: a delayed sacrifice/exile/return clause
    # (`handlers._DELAYED_SAC_EXILE_WHEN_FIRST_RE`) preceded by an unrelated
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
            prefixed_delayed.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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
            prefixed_delayed_tail.group("before"), self_subject=self_subject,
            previous_subject=previous_subject, group_subject=group_subject,
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
        after_specs = parse_effect_body(mill_land_this_way.group("after"))
        if before_specs is None or after_specs is None or not any(s.type == "mill" for s in before_specs):
            return None
        return before_specs + [
            EffectSpec(s.type, dict(s.params), condition={"kind": "milled_land_this_way"})
            for s in after_specs
        ]

    counter_when_you_do = _COUNTER_THEN_WHEN_YOU_DO_RE.match(body)
    if counter_when_you_do is not None:
        before_specs = parse_effect_body(counter_when_you_do.group("before"), self_subject=True)
        after_specs = parse_effect_body(counter_when_you_do.group("after"), self_subject=True)
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
        attached_subject=attached_subject,
    )
    if direct is not None:
        return direct

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
        body, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )
    if if_else is not None:
        return if_else

    # "If `<cond>`, `<A>` and `<B>`." — one sentence, one gate over *both* effects. The
    # connector split below would hand `<B>` over on its own, ungated (Unholy Annex: "If you
    # control a Demon, each opponent loses 2 life and you gain 2 life" gained the life
    # whether or not you did). A body with a period is several sentences and keeps its
    # per-clause gating.
    one_gate = _GENERIC_IF_PREFIX_RE.match(body)
    if one_gate is not None and "." not in one_gate.group("rest") and re.search(
        r"\s+and\s+", one_gate.group("rest")
    ):
        gate = static_condition(one_gate.group("cond"))
        gated_inner = (
            parse_effect_body(
                one_gate.group("rest"), self_subject=self_subject,
                previous_subject=previous_subject, group_subject=group_subject,
                previous_selector=previous_selector,
            )
            if gate is not None else None
        )
        if gated_inner and all(spec.condition is None for spec in gated_inner):
            return [EffectSpec(spec.type, dict(spec.params), condition=gate) for spec in gated_inner]

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
            # PAR-32: a self-subject trigger body ("whenever ~ attacks, put a
            # +1/+1 counter on ~. it gains deathtouch until end of turn." —
            # Agent of the Shadow Thieves) — "it" in every sub-clause still
            # means the source, until a clause introduces a *different*
            # targeted creature (`_announces_creature_target` flips
            # ``carry_self`` off). Unlike the source-less `previous_subject`
            # chain, this survives a clause that only re-references the
            # source (a counter on "~").
            carry_self = self_subject
            last_len = 0
            for idx, part in enumerate(parts):
                # A period split retains the leading "then" from a printed
                # "… . Then <effect>" sentence, unlike the explicit
                # `, then` connector. It is sequencing, not effect grammar.
                part = re.sub(r"^then\s+", "", part.strip(), flags=re.IGNORECASE)
                otherwise = _OTHERWISE_RE.match(part)
                if otherwise is not None:
                    sub = _otherwise_specs(
                        otherwise.group("rest"), collected[len(collected) - last_len:] if last_len else [],
                        self_subject=carry_self and not referent, previous_subject=referent,
                        previous_selector=referent_selector, group_subject=group_subject,
                    )
                    if sub is not None:
                        del collected[len(collected) - last_len:]  # the if_else replaces them
                else:
                    sub = parse_effect_body(
                        part,
                        self_subject=carry_self and not referent,
                        previous_subject=referent, previous_selector=referent_selector,
                        group_subject=group_subject,
                    )
                if sub is None:
                    ok = False
                    break
                last_len = len(sub)
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

    # The same rule again, at the *other* end of the pipeline: these gates
    # are checked **after** the connector split so each binds to only its own
    # clause. In "draw a card, then discard a card unless her additional cost
    # was paid" the split hands this just "discard a card unless …", where a
    # pre-split peel would have gated the draw too. Two call sites, not two
    # implementations — where in the pipeline a gate binds is a real property
    # of the gate, and the only thing that separates the two tables.
    matched, peeled = _peel_condition(
        body, _CONDITION_SUFFIXES, self_subject=self_subject,
        previous_subject=previous_subject, group_subject=group_subject,
    )
    if matched and peeled is not None:
        return peeled

    # PAR-62 (`14_` S4), the first connective routed to an ENG-37 composition
    # node rather than to a fused effect type or a per-effect ``optional``
    # boolean: RULE 601.2b's "you may `<effect>`" appearing **mid-body**.
    #
    # `_peel_optional` handles only a *leading* "you may", at the whole-ability
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
        body, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )
    if for_each is not None:
        return for_each

    where_x = _where_x_specs(
        body, self_subject=self_subject, previous_subject=previous_subject,
        group_subject=group_subject, previous_selector=previous_selector,
    )
    if where_x is not None:
        return where_x

    matched, peeled = _peel_condition(
        body, _GENERIC_CONDITION_ROWS, self_subject=self_subject,
        previous_subject=previous_subject, group_subject=group_subject,
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
                rest, self_subject=self_subject, previous_subject=previous_subject,
                group_subject=group_subject, previous_selector=previous_selector,
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
            {"of": "previous_target", "as": "controller"} if previous_subject
            else {"of": "entering", "as": "controller"} if group_subject
            else {"of": "attached", "as": "controller"} if attached_subject
            else None
        )
        if referent is not None:
            rest = its_controller_may.group("rest").strip()
            if not _MID_BODY_OPTIONAL_RE.match(rest) and not _REFLEXIVE_TRIGGER_RE.search(rest):
                inner = parse_effect_body(
                    rest, previous_subject=previous_subject,
                    group_subject=group_subject, previous_selector=previous_selector,
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
     "artifact_creature_or_land", "artifact_or_creature",
     # PAR-124: "target land you control becomes a 4/4 … creature … **it**
     # must be blocked this turn if able." (Disturbed Slumber/Elemental
     # Uprising/Vengeant Earth) — the animate-land family's own target
     # kinds, referred back to the same "it" way a bare "land" already is.
     "land_you_control", "creature_or_land_you_control"}
)


def _announces_creature_target(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` picks a permanent (or a graveyard card,
    or — PAR-71 — a countered spell) the next clause can refer back to as
    "it"/"that creature"/"that card"/"that spell".

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
    # "Counter target spell. Discover X, where X is that spell's mana
    # value." (Hurl into History/Access Denied/Overwhelming Intellect/Spell
    # Swindle-shaped, PAR-71) — a ``counter`` spec's own RULE 115 target is
    # the countered spell, so a following clause's "that spell" refers back
    # to it the same way `MillEffect.selector="previous_subject_controller"`
    # (Broken Ambitions) already reads it via `GameContext.previous_targets`
    # (RULE 608.2h last-known info — the countered spell is in a graveyard,
    # with no controller, by the time a later clause asks).
    if last.type == "counter":
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
#: GameContext.previous_selector`, `game/binding/core.py`'s narrow
#: ``TapEffect``-only tracking whitelist) — deliberately just the one real
#: card (Karlach, Fury of Avernus) needs today, widened only as another
#: card actually prints a different mass selector before this same "they"
#: tail, matching this file's usual narrow-whitelist convention.
_GROUP_SELECTOR_VALUES: frozenset[str] = frozenset({"attacking_creatures", "creatures_opponents_control"})


def _announces_group_selector(specs: list[EffectSpec]) -> bool:
    """Whether the last of ``specs`` is an untargeted mass-selector effect
    ("untap all attacking creatures") the next clause's "they" can point at —
    `_announces_creature_target`'s sibling for RULE 601.2c selectors rather
    than RULE 115 targets, since a selector clause has no target of its own
    to be caught by that check."""
    if not specs:
        return False
    last = specs[-1]
    if last.type == "tap":
        return last.params.get("selector") in _GROUP_SELECTOR_VALUES
    if last.type == "pump":
        return last.params.get("selector") in _GROUP_SELECTOR_VALUES
    if last.type == "grant_until":
        return (last.params.get("static", {}).get("params", {}).get("affects")
                in _GROUP_SELECTOR_VALUES)
    return False


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


#: A bare pronoun in a trigger body ("return **it**", "exile **that creature**").
_BARE_PRONOUN_RE = re.compile(r"\b(?:it|that (?:creature|permanent|artifact|land|token))\b")

#: An explicit naming of the ability's own source in a normalised body ("~", or the
#: "this card"/"this spell" phrasings `normalize` leaves alone).
_EXPLICIT_SOURCE_RE = re.compile(r"~|\bthis (?:card|spell|creature|permanent|artifact|enchantment|land)\b")

#: Effect types whose untargeted form ("it") has a ``"trigger_subject"`` mode — the
#: object that fired a group trigger, read off the event at resolution.
_GROUP_IT_RETARGETED: frozenset[str] = frozenset({"tap", "return_to_hand", "exile"})


def _stamp_group_pronoun(
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
    if (condition or {}).get("subject") != "group":
        return effects
    lowered = body.lower()
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
        if effect.type in _GROUP_IT_RETARGETED and effect.params.get("target_kind", "unset") is None:
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
        stamped.append(effect)
        index += 1
    return stamped


#: Effect params that read a number or object off the firing event. An `ATTACKERS_DECLARED`
#: event names the whole declaration, not "that many"/"that creature": the count a body means
#: depends on the head's own filter, which the shared event cannot carry.
_EVENT_READS = ("amount_from_trigger_event", "count_from_trigger_event", "pt_from_trigger_event")


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
        if e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self":
            params = dict(e.params)
            params["capture"] = "trigger_related"
            params["related_filter"] = dict(head_trigger.get("related_filter") or {})
            e = EffectSpec(e.type, params, condition=e.condition)
        out.append(e)
    return out


def _batch_attack_body_unresolvable(effects: "list[EffectSpec]") -> bool:
    """Whether a batch-attack ("you attack with …" / "~ and at least N other creatures
    attack") body reads something the event cannot say: "that many" / "that much", or a
    delayed effect that falls back to the source for "that creature"."""
    return any(
        any(key in e.params for key in _EVENT_READS)
        or (e.type == "create_delayed_trigger" and e.params.get("capture") == "previous_or_self")
        for e in effects
    )


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


def _turn_trigger_segment(
    line: str, *, provenance: ParserProvenance
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
    inner = segment_line(
        f"{keyword} {condition}, {m.group('body')}",
        allow_spell_effect=False, provenance=provenance,
    )
    unclaimed = Segment(raw=line.strip())
    if not inner.claimed or inner.spec is None or inner.extra_specs:
        return unclaimed
    spec = inner.spec
    if spec.ability_kind != "triggered" or not spec.effects or isinstance(spec.trigger.get("event"), list):
        return unclaimed
    return Segment(
        raw=line.strip(),
        spec=AbilitySpec(
            "spell_effect",
            effects=[EffectSpec("create_turn_trigger", {
                "trigger": spec.trigger,
                "effects": [e.to_dict() for e in spec.effects],
                "optional": bool(spec.optional),
                **({"once": True} if once else {}),
                **({"target_kind": target_kind} if target_kind else {}),
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
    trigger_line = _TRIGGER_RE.match(segment.raw.strip().lower())
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

    # PAR-28: "Boast/Exhaust/Forecast/Power-up/Solved/Max speed — [ability]".
    # Checked *before* `is_keyword_line`, since `_KEYWORD_TOKEN_RE`'s greedy
    # `.*$` would otherwise claim the whole "<keyword> — <cost>: <effect>"
    # line as a bare keyword line (producing no ability at all).
    kw_labeled = _segment_keyword_labeled_ability(
        raw, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
    )
    if kw_labeled is not None:
        return kw_labeled

    # MEC-48: keep `_KEYWORD_TOKEN_RE`'s greedy `.*$` from swallowing a
    # "Specialize {cost}. <rider>" line whole and dropping the rider.
    if _SPECIALIZE_GRAVEYARD_DISCOUNT_RE.match(raw):
        return Segment(raw=raw, claimed=True, keyword_line=True)
    if _SPECIALIZE_WITH_RIDER_RE.match(raw):
        return Segment(raw=raw, claimed=False)

    if is_keyword_line(raw):
        return Segment(raw=raw, claimed=True, keyword_line=True)

    # PAR-79 fifth increment: see `_ETB_AND_CAST_TRIGGER_RE`'s own docstring
    # — split before any single-trigger regex gets a look, so a compound
    # "enters and whenever you cast" line always goes through this path
    # rather than falling through to `_CAST_SPELL_TRIGGER_RE` et al. (whose
    # own ``^whenever`` anchors wouldn't match this line's leading "when ~
    # enters and " anyway, but the ordering is deliberate for readability).
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

    if _PLAY_WITH_TOP_REVEALED_RE.match(raw):
        return Segment(raw=raw, claimed=True)  # informational-only, no spec (see docstring)

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
        effects = parse_effect_body(body, self_subject=True)
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

    cast_spell_trig_mv_at_least = _CAST_SPELL_TRIGGER_MV_AT_LEAST_RE.match(raw)
    if cast_spell_trig_mv_at_least is not None:
        subj = cast_spell_trig_mv_at_least.group("subj")
        body, optional = _peel_optional(cast_spell_trig_mv_at_least.group("body"))
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "spell_mana_value_at_least": int(cast_spell_trig_mv_at_least.group("n")),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cast_spell_trig_x = _CAST_SPELL_TRIGGER_X_RE.match(raw)
    if cast_spell_trig_x is not None:
        subj = cast_spell_trig_x.group("subj")
        body, optional = _peel_optional(cast_spell_trig_x.group("body"))
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "spell_has_x": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cast_spell_trig_first_x = _CAST_SPELL_TRIGGER_FIRST_X_RE.match(raw)
    if cast_spell_trig_first_x is not None:
        subj = cast_spell_trig_first_x.group("subj")
        body, optional = _peel_optional(cast_spell_trig_first_x.group("body"))
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "first_x_spell": True,
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    cast_spell_trig_historic = _CAST_SPELL_TRIGGER_HISTORIC_RE.match(raw)
    if cast_spell_trig_historic is not None:
        subj = cast_spell_trig_historic.group("subj")
        body, optional = _peel_optional(cast_spell_trig_historic.group("body"))
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                "event": "SPELL_CAST",
                "condition": _cast_spell_trigger_condition(subj),
                "spell_is_historic": True,
                **({"limit": True} if body_limit else {}),
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
        effects = _counter_triggering_spell_effects(body) or parse_effect_body(body)
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

    cast_spell_targets_src = _CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_targets_src is not None:
        body, optional = _peel_optional(cast_spell_targets_src.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    cast_spell_shares_type = _CAST_SPELL_SHARES_TYPE_SOURCE_TRIGGER_RE.match(raw)
    if cast_spell_shares_type is not None:
        body, optional = _peel_optional(cast_spell_shares_type.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    two_color_cast = _CAST_TWO_COLOR_SPELL_TRIGGER_RE.match(raw)
    if two_color_cast is not None:
        body, optional = _peel_optional(two_color_cast.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    cast_spell_trig_plain = _CAST_SPELL_TRIGGER_PLAIN_RE.match(raw)
    if cast_spell_trig_plain is not None:
        subj = cast_spell_trig_plain.group("subj").lower()
        body, optional = _peel_optional(cast_spell_trig_plain.group("body"))
        # "~ deals damage equal to that spell's mana value …" (Passionate
        # Archaeologist) — a bare "~" in the body is this ability's own
        # source, unambiguous for a player-subject cast trigger.
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        trig: dict[str, Any] = {
            "event": "SPELL_CAST", "condition": _cast_spell_trigger_condition(subj),
        }
        if cast_spell_trig_plain.group("opp_turn"):
            trig["not_controllers_turn"] = True
        if cast_spell_trig_plain.group("from_exile"):
            trig["spell_from_exile"] = True
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

    tap_mana_trig = _TAP_FOR_MANA_TRIGGER_RE.match(raw)
    if tap_mana_trig is not None:
        subj = tap_mana_trig.group("subj").lower()
        land = tap_mana_trig.group("land").lower()
        body, optional = _peel_optional(tap_mana_trig.group("body"))
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

    # Tried before the positive `_CAST_SPELL_TRIGGER_RE` below: that
    # pattern's own ``types`` group (bare ``[a-z][a-z,\s]*?``) is generic
    # enough to also swallow "noncreature" as if it were a types list —
    # failing `_parse_cast_spell_types` and returning unclaimed *before*
    # this negated form ever got a chance to match the same line.
    two_color_cast = _CAST_TWO_COLOR_SPELL_TRIGGER_RE.match(raw)
    if two_color_cast is not None:
        body, optional = _peel_optional(two_color_cast.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    cast_spell_trig_neg = _CAST_SPELL_TRIGGER_NEG_RE.match(raw)
    if cast_spell_trig_neg is not None:
        excluded = cast_spell_trig_neg.group("type").lower()
        if excluded not in _SPELL_CAST_TYPE_WORDS:
            return Segment(raw=raw)
        neg_subj = cast_spell_trig_neg.group("subj")
        body, optional = _peel_optional(cast_spell_trig_neg.group("body"))
        trigger = {
            "event": "SPELL_CAST",
            "condition": _cast_spell_trigger_condition(neg_subj),
            "spell_exclude_card_types": [excluded],
        }
        two_rider_parts = _cast_mana_two_rider_parts(body, self_subject=True)
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
        body, mana_spent_at_least = _peel_spell_mana_spent_at_least(body)
        effects = parse_effect_body(body, self_subject=True)
        if effects is None:
            return Segment(raw=raw)
        spec = AbilitySpec(
            "triggered",
            effects=effects,
            trigger={
                **trigger,
                **({"spell_mana_spent_at_least": mana_spent_at_least}
                   if mana_spent_at_least is not None else {}),
            },
            optional=optional,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    doctor_or_companion_trig = _DOCTOR_OR_COMPANION_CREATURE_CAST_TRIGGER_RE.match(raw)
    if doctor_or_companion_trig is not None:
        body, optional = _peel_optional(doctor_or_companion_trig.group("body"))
        effects = parse_effect_body(body, self_subject=True)
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

    # PAR-74: a bare "~" in the body is this ability's own source, the same
    # unambiguous reading `_CAST_SPELL_TRIGGER_PLAIN_RE`'s dispatch already
    # passes `self_subject=True` for (Passionate Archaeologist) — this typed
    # sibling was missing it, so any typed/color/subtype cast trigger whose
    # own source reacts ("~ gains protection …", "~ becomes a 4/4 …", "~
    # gains forestwalk …") failed closed on an otherwise-modelable body.
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
        if types is None and single_word in _CAST_SPELL_COLOR_WORDS:
            # "Whenever you cast a red spell, …" (Balefire Liege) — the
            # colour sibling of the subtype branch just below; reuses
            # `effect_binder`'s existing ``cast_of_color`` predicate.
            body, optional = _peel_optional(cast_spell_trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={
                    "event": "SPELL_CAST",
                    "condition": _cast_spell_trigger_condition(pos_subj),
                    "cast_of_color": _CAST_SPELL_COLOR_WORDS[single_word],
                },
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        subtype_words = [
            word for word in re.split(r"[,\s]+", raw_types.strip().lower())
            if word and word != "or"
        ]
        if types is None and subtype_words and all(
            word in _CAST_SPELL_SUBTYPE_WORDS or word == "arcane"
            for word in subtype_words
        ):
            body, optional = _peel_optional(cast_spell_trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={
                    "event": "SPELL_CAST",
                    "condition": _cast_spell_trigger_condition(pos_subj),
                    "spell_subtype_any": subtype_words,
                },
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)
        if types is None:
            # Not a bare type/colour/subtype list: decline (rather than fail
            # closed) so the composed cast-trigger row below can read the phrase.
            cast_spell_trig = None
    if cast_spell_trig is not None:
        body, optional = _peel_optional(cast_spell_trig.group("body"))
        two_rider_parts = _cast_mana_two_rider_parts(body, self_subject=True)
        if two_rider_parts is not None:
            base_effects, riders = two_rider_parts
            trigger = {
                "event": "SPELL_CAST", "condition": _cast_spell_trigger_condition(pos_subj),
                "spell_card_types": types,
            }
            base_spec = AbilitySpec("triggered", effects=base_effects, trigger=trigger,
                optional=optional, raw_text=raw, parser=provenance)
            rider_specs = [
                AbilitySpec("triggered", effects=effects,
                    trigger={**trigger, "spell_mana_spent_at_least": threshold}, optional=optional,
                    raw_text=raw, parser=provenance)
                for threshold, effects in riders
            ]
            return Segment(raw=raw, spec=base_spec, extra_specs=rider_specs, claimed=True)
        rider_parts = _cast_mana_rider_parts(body, self_subject=True)
        if rider_parts is not None:
            base_effects, threshold, rider_effects, replaces = rider_parts
            trigger = {
                "event": "SPELL_CAST", "condition": _cast_spell_trigger_condition(pos_subj),
                "spell_card_types": types,
            }
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
        effects = parse_effect_body(body, self_subject=True)
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

    composed_cast = _CAST_TRIGGER_COMPOSED_RE.match(raw)
    if composed_cast is not None:
        composed_keys = parse_spell_phrase(composed_cast.group("phrase"))
        if composed_keys is not None:
            return _cast_trigger_segment(
                raw, composed_cast.group("subj"), composed_keys, composed_cast.group("body"), provenance
            )

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
                "sacrifice_type": [
                    t.lower() for t in (sacrifice_trig.group("type"), sacrifice_trig.group("type2")) if t
                ],
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
        # (`parse_effect_body`'s ``self_subject``). "whenever enchanted
        # creature deals damage, its controller loses that much life."
        # (Visions of Brutality, PAR-117) is the attached sibling. A "group"
        # condition (Edric, Spymaster of Trest/Essence Sliver-shaped: "…, its
        # controller `<verb>` …") is the group-subject sibling PAR-117's own
        # `group_its_controller_*` handlers already model for every other
        # RULE 603.1 event — this dispatch had just never passed the flag
        # that unlocks them for `DAMAGE`.
        #
        # A group condition whose recipient is "a **creature**" (Sosuke, Son
        # of Seshiro/Toxin Sliver-shaped: "…deals combat damage to a
        # creature, destroy **that creature**.") introduces a *second*
        # antecedent object the body's own pronoun could mean — the one
        # damaged, not the one dealing it — which `delayed_sac_exile_tail`
        # (`_DELAYED_SAC_EXILE_TAIL_RE`'s bare "it"/"that creature"/"them"
        # alternative, ``capture="previous_or_self"``) can't tell apart from
        # the group subject; being ungated (it also answers a bare
        # self-subject "sacrifice it"), it would still match and fall back
        # to this ability's own source, silently destroying e.g. Sosuke
        # itself rather than the creature it just fought. Reading the
        # *recipient's* own object (RULE 603.1's real "that creature" here)
        # needs a referent this project doesn't have yet — a real gap, not
        # attempted here. Refused narrowly, by pre-checking this one
        # handler's own ambiguous-pronoun branch (not its ``obj_self``
        # "~" branch, which stays exactly as unambiguous as ever — Quest
        # for the Gemblades' "put a quest counter on **~**" keeps working)
        # rather than withholding the whole clause, so every other reading
        # of a creature-recipient group trigger is untouched.
        delayed_tail_pronoun = _DELAYED_SAC_EXILE_TAIL_RE.fullmatch(
            body.strip().rstrip(".").strip()
        )
        if (
            damage_trig.group("recipient") == "creature"
            and not (damage_trig.group("self") or damage_trig.group("attached"))
            and delayed_tail_pronoun is not None
            and delayed_tail_pronoun.group("obj")
        ):
            return Segment(raw=raw)
        effects = parse_effect_body(
            body, self_subject=bool(damage_trig.group("self")),
            attached_subject=bool(damage_trig.group("attached")),
            group_subject=bool(damage_trig.group("article")),
        )
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
        if damage_trig.group("or_planeswalker"):
            # ``is_player`` alone cannot express this union: planeswalker
            # damage uses the same False value as creature damage.  Binding
            # resolves the target's live type for this narrow printed form.
            damage_filter.pop("is_player", None)
            damage_filter["player_or_planeswalker"] = True
        if damage_trig.group("combat"):
            damage_filter["combat"] = True
        if damage_trig.group("self"):
            condition: dict[str, Any] = {"subject": "self"}
        elif damage_trig.group("attached"):
            condition = {"subject": "attached_permanent"}
        else:
            condition = {"subject": "group", "other": damage_trig.group("article").lower() == "another"}
            if damage_trig.group("type"):
                condition["type"] = damage_trig.group("type").lower()
            else:
                # PAR-117: "a **Sliver** deals damage" — the creature-
                # subtype sibling of the ``type`` branch above, same
                # ``subtypes`` list shape `_GROUP_SUBTYPE_SUBJECT_RE`'s own
                # dispatch uses (`_build_group_ok` doesn't care which event
                # supplied it).
                condition["subtypes"] = [damage_trig.group("subtype").lower()]
            if damage_trig.group("yours"):
                condition["controller"] = "you"
            if damage_trig.group("goaded"):  # RULE 701.15b — see `_GOADED_SUBJECT_RE`
                condition["goaded"] = True
            if damage_trig.group("token"):  # "a creature token you control …"
                condition["is_token"] = True
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
        is_attached_subject = bool(damage_recipient_trig.group("attached"))
        effects = parse_effect_body(
            body, self_subject=is_self_subject, attached_subject=is_attached_subject,
        )
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
                elif (
                    effect_spec.params.get("target_kind")
                    or effect_spec.params.get("selector")
                    # "its controller loses N/that much life" (PAR-117,
                    # Ragged Veins) — an ``attached_subject``-gated row
                    # already names a resolved referent via ``player``, so
                    # this isn't an ambiguous implicit-self "it" the rewrite
                    # above exists to catch; let it through unchanged.
                    or effect_spec.params.get("player")
                ):
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
            additional_cost_optional=is_optional or "sacrifice_or_mana" in cost,
            raw_text=raw,
            parser=provenance,
        )
        return Segment(raw=raw, spec=spec, claimed=True)

    # PAR-35's casting clauses are unambiguous spell metadata, so like an
    # additional cost they apply to permanent spells too (Harbinger of the
    # Tides / Armor of Thorns), not only bare instant/sorcery effects.
    if _DECLARE_ATTACKERS_IF_ATTACKED_RE.match(raw):
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[],
            cast_timing_restriction={"step": "declare_attackers", "controller_attacked": True},
            raw_text=raw, parser=provenance,
        ), claimed=True)

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

    flash_for_mana = _CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE.match(raw)
    if flash_for_mana is not None:
        return Segment(raw=raw, spec=AbilitySpec(
            "spell_effect", effects=[], conditional_flash={"unconditional": True},
            flash_extra_cost=re.sub(r"\s+", "", flash_for_mana.group("cost")),
            raw_text=raw, parser=provenance,
        ), claimed=True)

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
        activation_tail = _ACTIVATE_ONLY_IF_TRAILING_RE.search(effect_text)
        if activation_tail is not None:
            tail = "activate only if " + activation_tail.group("cond").strip()
            parsed_tail = parse_effect_body(tail)
            if parsed_tail is None:
                return Segment(raw=raw)
            tail_markers.extend(parsed_tail)
            if activation_tail.group("once"):
                tail_markers.append(EffectSpec(ACTIVATE_ONLY_ONCE_MARKER, {}))
            effect_text = effect_text[:activation_tail.start()].strip()
        body, optional = _peel_optional(effect_text)
        effects = parse_effect_body(body, self_subject=True)
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
        gy_if = _CREATURE_CARD_TO_GY_IF_RE.match(body)
        dmg_if = _YOU_DEALT_DAMAGE_IF_RE.match(body)
        no_subtype_if = _YOU_CONTROL_NO_SUBTYPE_IF_RE.match(body)
        harnessed_if = _SOURCE_HARNESSED_IF_RE.match(body)
        noncreature_if = re.match(
            r"^if you'?ve cast a noncreature spell this turn,\s*(?P<rest>.+)$", body, re.I | re.S,
        )
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
        if effects is None and phase_active_if is None:
            # RULE 603.4: any other leading "if `<state>`," of a phase trigger is an intervening
            # if too — read through the shared state-predicate vocabulary (`static_condition`)
            # rather than one regex per phrase. Only tried once the body failed as it stands, so
            # a body some other row already reads (as a per-effect gate) is left as it was.
            gate = _PHASE_INTERVENING_IF_RE.match(body)
            gated = static_condition(gate.group("cond")) if gate is not None else None
            if gated is not None:
                phase_active_if = gated
                effects = parse_effect_body(gate.group("rest").strip())
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

        # RULE 603.3f "1 or more [other] [nontoken] [artifact] creatures
        # [you control] die" — modeled as a per-object DIES group trigger,
        # claimed ONLY when the body's own "this ability triggers only once
        # each turn." marker makes that collapse to the correct net. See
        # `_BATCH_DIES_TRIGGER_RE`.
        batch_dies = _BATCH_DIES_TRIGGER_RE.match(cond_text.strip())
        if batch_dies is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, group_subject=True)
            if effects is None:
                return Segment(raw=raw)
            effects, body_limit = _strip_trigger_once_per_turn_marker(effects)
            if not (limit or body_limit):
                # No once-per-turn marker — a per-object model would
                # over-fire on simultaneous deaths. Fail closed.
                return Segment(raw=raw)
            condition = {"subject": "group", "type": "creature",
                         "other": bool(batch_dies.group("other"))}
            if batch_dies.group("yours"):
                condition["controller"] = "you"
            if batch_dies.group("nontoken"):
                condition["nontoken"] = True
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={"event": "DIES", "condition": condition, "limit": True},
                optional=optional,
                raw_text=raw,
                parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        batch_enters = _BATCH_ENTER_TRIGGER_RE.match(cond_text.strip())
        if batch_enters is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec(
                "triggered", effects=effects,
                trigger={
                    "event": "ENTERS_BATTLEFIELD",
                    "condition": {"subject": "group", "type": "creature", "controller": "you", "other": True},
                },
                optional=optional, raw_text=raw, parser=provenance,
            )
            return Segment(raw=raw, spec=spec, claimed=True)

        creature_explores = _CREATURE_EXPLORES_TRIGGER_RE.match(cond_text.strip())
        if creature_explores is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, group_subject=True)
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
            body, optional = _peel_optional(trig.group("body"))
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
                effects = parse_effect_body(body, self_subject=True)
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
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "LAST_TIME_COUNTER_REMOVED", "condition": {"subject": "self"}},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        self_milled = _SELF_MILLED_TO_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if self_milled is not None:
            body, optional = _peel_optional(trig.group("body"))
            # Narcomoeba's "put it onto the battlefield" is an untargeted
            # self-return, not a fresh RULE 115 target.
            if body.strip().rstrip(".").lower() == "put it onto the battlefield":
                effects = [EffectSpec("return_self_from_graveyard", {})]
            else:
                effects = parse_effect_body(body, self_subject=True)
                # Creeping Chill's optionality encloses its reflexive
                # exile-and-damage sequence; retain that composition instead
                # of peeling the leading ``you may`` into ability-level
                # optionality (which loses the pronoun's antecedent).
                if effects is None:
                    effects = parse_effect_body(trig.group("body"), self_subject=True)
                    optional = False
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects,
                trigger={"event": "CARDS_MILLED", "milled_source": True},
                optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        one_milled_card = _ONE_CARD_MILLED_TO_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if one_milled_card is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body, self_subject=True)
            if effects is None:
                return Segment(raw=raw)
            spec = AbilitySpec("triggered", effects=effects, trigger={
                "event": "MILLED_CARD", "condition": {"subject": "you"},
                "milled_card_type": one_milled_card.group("type").lower(),
            }, optional=optional, raw_text=raw, parser=provenance)
            return Segment(raw=raw, spec=spec, claimed=True)

        graveyard_exit = _CARDS_LEAVE_YOUR_GRAVEYARD_TRIGGER_RE.match(cond_text.strip())
        if graveyard_exit is not None:
            body, optional = _peel_optional(trig.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                return Segment(raw=raw)
            trigger: dict[str, Any] = {
                "event": "CARDS_LEFT_GRAVEYARD",
                "graveyard_owner": "you",
            }
            if graveyard_exit.group("during"):
                trigger["during_your_turn"] = True
            spec = AbilitySpec(
                "triggered", effects=effects, trigger=trigger, optional=optional,
                raw_text=raw, parser=provenance,
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
            # A `(event_name, filter_dict)` tuple carries an aggregate-event
            # gate ("1 or more **nontoken** creatures …" — Feywild Visitor).
            player_event_filter: Optional[dict[str, Any]] = None
            if isinstance(player_event, tuple):
                player_event, player_event_filter = player_event
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
                        **({"filter": dict(player_event_filter)} if player_event_filter else {}),
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
        head_trigger: dict[str, Any] = {}
        composed_head = False
        atk_lands = _ATTACKS_DEFENDER_LANDS_RE.match(cond_text.strip())
        atk_most_life = _ATTACKS_DEFENDER_MOST_LIFE_RE.match(cond_text.strip())
        multi = _SELF_MULTI_EVENT_RE.match(cond_text.strip())
        attached_multi = _ATTACHED_MULTI_EVENT_RE.match(cond_text.strip())
        defender_most_life = False
        if atk_lands is not None:
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
                    return Segment(raw=raw)  # unrecognised trigger/scope → unclaimed (fail-closed)
                event, condition, head_trigger = head.event, head.condition, head.trigger
                composed_head = True
        body, optional = _peel_optional(trig.group("body"))
        # PAR-98: Meanders Guide's optional tap is the antecedent for a
        # following "When you do" trigger.  Keep the pair together before
        # the ordinary optional wrapper can turn it into two unrelated
        # clauses.
        # `_peel_optional` deliberately leaves this "you may" in place (its
        # guard protects `_MAY_EFFECT_THEN_ANTECEDENT_PHRASES` shapes), so
        # peel it here — the optionality wraps the whole tap-then-return pair.
        reflexive_tap = _REFLEXIVE_TAP_PEEL_RE.match(body)
        if cond_text.strip() == "~ attacks" and reflexive_tap is not None:
            body = reflexive_tap.group("rest")
            optional = True
            effects = parse_effect_body(body, self_subject=True)
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
        effects = parse_effect_body(
            body, self_subject=(condition or {}).get("subject") == "self",
            group_subject=(condition or {}).get("subject") == "group",
            attached_subject=(condition or {}).get("subject") == "attached_permanent",
        )
        if effects is None:
            return Segment(raw=raw)
        stamped = _stamp_group_pronoun(condition, body, effects)
        if stamped is None:
            return Segment(raw=raw)
        effects = stamped
        if composed_head and _group_it_would_hit_source(condition, body, effects):
            return Segment(raw=raw)
        if event == "ATTACKERS_DECLARED" and _batch_attack_body_unresolvable(effects):
            return Segment(raw=raw)
        if composed_head:
            effects = _retarget_block_relation(event, head_trigger, effects)
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
                **({"attacked_player_has_lowest_life": True}
                   if attacked_lowest_life else {}),
                **({"attacked_player_has_most_life": True}
                   if defender_most_life else {}),
                **head_trigger,
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
        if cost_static is not None and (
            all(spec.type == "cost_reduction" and spec.params.get("affects") == "self" for spec in cost_static)
            or all(spec.type == "grant_graveyard_to_library_replacement" for spec in cost_static)
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
#: sacrifice/discard/pay life `<X>`. When you do, `<effect>`." family / PAR-79
#: seventh increment's "you may return/tap another `<permanent>` you
#: control. If you do, `<effect>`." (`handlers._may_effect_then`, via
#: `handlers._MAY_EFFECT_THEN_ANTECEDENT_PHRASES`) — every one of these is a
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
#: explicitly — they run only *after* `_peel_optional` has already stripped
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
    r"^you may (?:pay (?:\{e\})+|" + _MAY_COST_THEN_CLAUSE + r"|"
    + _MAY_EFFECT_THEN_ANTECEDENT_PHRASES + r")\.\s*(?:if|when) you do",
    re.IGNORECASE,
)


#: RULE 603.3's reflexive trigger tail — "…, when you do, `<effect>`" /
#: "…, if you do, `<effect>`". A "you may" body containing one is a choice
#: *plus a trigger*, not a single optional block; see `_MID_BODY_OPTIONAL_RE`'s
#: use site.
_REFLEXIVE_TRIGGER_RE = re.compile(r"\b(?:when|if) you do\b", re.IGNORECASE)


#: PAR-62: RULE 601.2b's "you may `<effect>`" as a *clause* rather than as an
#: ability-level prefix — what `_peel_optional` sees only when it leads the
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
    r"^its controller may\s+(?P<rest>.+)$", re.IGNORECASE | re.S
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
