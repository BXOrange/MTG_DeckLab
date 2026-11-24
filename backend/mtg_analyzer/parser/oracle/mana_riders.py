"""The sentences a mana ability may carry after its ``Add`` clause, and which of them the engine really executes.

RULE 605.1a lets a mana ability do more than add mana, and the printed riders around the ``Add`` clause (a spend
restriction, a timing limit, a pain-land hit, a counter) are not effects the spec IR carries: `game/mana_abilities.py`
reads them off the line itself when it builds a `ManaAbility`, and `GameEngine.tap_for_mana` applies them. This module
is the single source of those readers, so the parser claims a trailing sentence exactly when the engine will carry it
out (BUG-73: the segmenter used to claim any sentence after an ``Add`` clause, so a rider the builder never reads --
a delayed draw, a life gain, "Activate only as a sorcery" -- was dropped silently). The module is pure text: no
``game/`` imports, so the parser may use it (the `game/` side imports from here, never the reverse).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .catalogue.effect_rows.costs_mana_limits import activation_condition_dict
from .normalize import normalize

#: Spelled-out counts as printed on the riders below ("You get two rad counters", "put a depletion counter").
COUNT_WORDS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_COUNT_TOKEN = r"\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten"


def count_token_value(match: "re.Match[str]") -> int:
    """A captured ``n`` group (digit or spelled-out count) as an int; an unknown word counts as 1."""
    token = match.group("n").lower()
    return int(token) if token.isdigit() else COUNT_WORDS.get(token, 1)

#: A mana ability's own extra "You get N rad counters" side effect (RULE
#: 729/605.1a — Harold and Bob's granted "{T}: Add three mana of any one
#: color. You get two rad counters."), the rad-counter sibling of
#: `_SELF_DAMAGE_RE`. A spelled-out count needs the same local word map
#: `COUNT_WORDS` provides below (raw, non-normalized oracle text).
_SELF_RAD_COUNTERS_RE = re.compile(
    r"you get (?P<n>\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten) rad counters?",
    re.IGNORECASE,
)

#: How a mana ability's own source names itself after the oracle normalizer ("~") or on raw text ("this land");
#: Talisman of Conviction's "This artifact deals 1 damage to you." never matched the shorter list.
_SELF_SUBJECT = r"this creature|this land|this permanent|this artifact|this enchantment|~"
def normalized_condition(text: str) -> str:
    """``text`` the way the oracle normalizer spells it ("this land" -> "~", "three" -> "3"), so the activation-condition
    vocabulary (written against normalized text) reads a raw rider ("Activate only if this land entered this turn",
    Mirrex; "... three or more brick counters on this land", Pyramid of the Pantheon) the same as the parser does."""
    return normalize(text)


#: A mana ability's own extra "this creature/land deals N damage to you"
#: side effect (RULE 605.1a permits a mana ability other effects besides
#: producing mana) — the painland/Elves-of-Deep-Shadow template.
_SELF_DAMAGE_UNLESS_SUBTYPE_RE = re.compile(
    r"damage to you if you (?:don't|do not) control an? (?P<subtype>[a-z]+)", re.IGNORECASE,
)

_SELF_DAMAGE_RE = re.compile(
    r"(?:" + _SELF_SUBJECT + r") deals (\d+) damage to you",
    re.IGNORECASE,
)

#: RULE 602.5d's own timing/frequency riders, printed as a trailing sentence
#: right after a mana ability's "Add …" clause rather than as part of its
#: ``<cost>:`` — Vivi Ornitier's "Activate only during your turn and only
#: once each turn.", or either half alone (a bare "Activate only during
#: your turn." or "Activate only once each turn." with no partner clause).
#: The general activated-ability grammar for this shape already exists
#: (`parser/oracle/catalogue/handlers.py`), but mana abilities never reach
#: that pipeline (RULE 605.1a routes them through this module's own
#: line-based parse instead, entirely outside `parse_oracle`), so it's
#: recognized here too rather than left unparsed.
_MANA_ACTIVATION_LIMIT_RE = re.compile(
    r"activate only during your turn, before attackers are declared\.|"
    r"activate only during your turn(?: and only once each turn)?\.|"
    r"activate only once each turn\.",
    re.IGNORECASE,
)

# --- RULE 605.3a mana spend restrictions ("Spend this mana only ...") ----

#: The whole restriction sentence's own clause, captured separately from the
#: "Add ..." clause since they're two sentences on the same cost line.
_RESTRICTION_CLAUSE_RE = re.compile(r"spend this mana only (?:to|on)\s+(?P<clause>.+?)\.", re.IGNORECASE)
#: RULE 601.2c's "and that spell can't be countered" rider, printed on some
#: of these (Cavern of Souls, Delighted Halfling) — stripped before
#: classifying the clause below; the "can't be countered" half isn't a
#: spend restriction at all and isn't modeled here (a resolve-time
#: property of the cast spell, not the mana that paid for it).
_CANT_BE_COUNTERED_TAIL_RE = re.compile(r",\s*and that spell can'?t be countered$", re.IGNORECASE)
#: "... or activate an ability of a(n) <source>" / "... or activate
#: abilities of <source>(s)" — peeled off the end of a clause (Castle
#: Garenbrig, Primal Beyond); the exact trailing source word isn't
#: re-verified against the clause's own type (fail-soft: every real card
#: found pairs them, so this is a simplification, not a guess).
_RESTRICTION_ABILITY_TAIL_RE = re.compile(
    r"^(?P<head>.+?)\s+or activate (?:an ability of an?|abilities of)\s+.+$", re.IGNORECASE
)
_RESTRICTION_CONTAINS_X_RE = re.compile(r"^costs that contain \{x\}$", re.IGNORECASE)
_RESTRICTION_CREATURE_SPELL_RE = re.compile(r"^cast (?:an? )?creature spells?$", re.IGNORECASE)
_RESTRICTION_COMMANDER_RE = re.compile(r"^cast your commander$", re.IGNORECASE)
_RESTRICTION_LEGENDARY_RE = re.compile(r"^cast (?:an? )?legendary spell$", re.IGNORECASE)
_RESTRICTION_INSTANT_SORCERY_RE = re.compile(
    r"^cast (?:an? )?instant (?:and|or) sorcery spells?$", re.IGNORECASE
)
#: "cast a <Type1> or <Type2> spell" (Turtle Lair) — checked before the
#: single-type form below since it also matches "cast (?:an? )?[a-z]+".
_RESTRICTION_MULTI_TYPE_RE = re.compile(
    r"^cast (?:an? )?(?P<t1>[a-z]+) or (?P<t2>[a-z]+) spells?$", re.IGNORECASE
)
#: "cast a(n) <Type> spell" / "cast a(n) <Type> creature spell" (Flamebraider's
#: "Elemental", Gnarlroot Trapper's "Elf creature") — a single named
#: creature type, the optional literal "creature" just along for the ride.
#: RULE 709.5e (MEC-111): "cast Room spells and unlock doors" (Smoky Lounge) and "cast an enchantment spell, unlock
#: a door, or turn a permanent face up" (Creeping Peeper) — a spell-type restriction that also covers paying an unlock
#: cost (``allow_unlock``) and, for the Peeper, the special action of turning a permanent face up (``allow_face_up``).
_RESTRICTION_TYPE_OR_UNLOCK_RE = re.compile(
    r"^cast (?:an? )?(?P<type>[a-z]+) spells?(?:,)? (?:and )?unlock (?:a )?doors?"
    r"(?:,? (?:and|or) turn a permanent face up)?$",
    re.IGNORECASE,
)
_RESTRICTION_TYPE_RE = re.compile(
    r"^cast (?:an? )?(?P<type>[a-z]+)(?: creature)? spells?$", re.IGNORECASE
)
#: "cast a creature spell of the chosen type" (Cavern of Souls, Unclaimed
#: Territory) — unlike `_RESTRICTION_TYPE_RE` above, the type isn't printed
#: at all; it's whatever the land's own RULE 601.2b "as ~ enters, choose a
#: creature type" ETB choice picked (`GameObject.chosen_type`, already
#: modeled for the `enter_replacement` family — see `game/binding/core.py`).
#: The restriction dict parsed here carries no ``types`` of its own; it's
#: resolved into an ordinary ``type_spell`` restriction dynamically, at tap
#: time, off the tapped land's *own* `chosen_type` (`GameEngine.
#: tap_for_mana`) — the same restriction dict shape `_RESTRICTION_TYPE_RE`
#: already produces, just filled in per-instance instead of parsed from
#: fixed text.
_RESTRICTION_CHOSEN_TYPE_RE = re.compile(
    r"^cast (?:an? )?creature spells? of the chosen type$", re.IGNORECASE
)
#: "cast monocolored spells of that color" (Throne of Eldraine) — like the
#: chosen-type restriction above, the colour isn't printed here; it's
#: resolved per-instance off the source's `chosen_color` at tap time
#: (`GameEngine.tap_for_mana` → a concrete ``monocolored_spell`` restriction).
_RESTRICTION_CHOSEN_COLOR_MONO_RE = re.compile(
    r"^cast monocolou?red spells? of that colou?r$", re.IGNORECASE
)

#: "cast [creature ]spells with mana value N or greater or [creature ]spells
#: with {X} in their mana costs" (Helga, Skittish Seer / Troyan, Gutsy
#: Explorer) — a mana-value threshold *or* an unresolved {X}, optionally
#: creature-restricted; both halves always agree on the creature
#: qualifier on every real card, so a mismatch is left unrecognized
#: (fail-soft) rather than guessed.
_RESTRICTION_MANA_VALUE_OR_X_RE = re.compile(
    r"^cast (?P<c1>creature )?spells with mana value (?P<mv>\d+) or greater "
    r"or (?P<c2>creature )?spells with \{x\} in their mana costs$",
    re.IGNORECASE,
)

#: RULE 605.3a's negative form, printed by the Powerstone token: "This mana can't be spent to cast a nonartifact
#: spell." Everything except casting a nonartifact spell stays legal (abilities, artifact spells, special actions).
_CANT_CAST_NONARTIFACT_RE = re.compile(
    r"this mana can'?t be spent to cast (?:a |any )?nonartifact spells?\.?", re.IGNORECASE
)
#: Restriction kind for the above (see `_restriction_allows_cast`).
NONARTIFACT_CAST_BAN_KIND = "no_nonartifact_spell"


def parse_restriction(effect_text: str) -> Optional[dict[str, Any]]:
    """A "Spend this mana only ..." clause (RULE 605.3a) in ``effect_text``
    as a restriction dict, or ``None`` when there's no such clause at all
    *or* it's outside the recognised vocabulary (fail-soft — the "Add ..."
    production still parses either way, just unrestricted; see the module
    docstring for exactly which shapes this covers)."""
    if _CANT_CAST_NONARTIFACT_RE.search(effect_text):
        # Powerstone: a ban rather than an allow-list — abilities, unlocking and turning face up are not casts.
        return {
            "kind": NONARTIFACT_CAST_BAN_KIND, "allow_ability": True, "allow_unlock": True, "allow_face_up": True,
        }
    m = _RESTRICTION_CLAUSE_RE.search(effect_text)
    if m is None:
        return None
    clause = _CANT_BE_COUNTERED_TAIL_RE.sub("", m.group("clause").strip())
    allow_ability = False
    tail = _RESTRICTION_ABILITY_TAIL_RE.match(clause)
    if tail is not None:
        clause, allow_ability = tail.group("head"), True

    if _RESTRICTION_CONTAINS_X_RE.match(clause):
        return {"kind": "contains_x"}
    if _RESTRICTION_CHOSEN_TYPE_RE.match(clause):
        return {"kind": "chosen_type_spell"}
    if _RESTRICTION_CHOSEN_COLOR_MONO_RE.match(clause):
        return {"kind": "chosen_color_monocolored_spell"}
    m = _RESTRICTION_MANA_VALUE_OR_X_RE.match(clause)
    if m is not None:
        creature_only = bool(m.group("c1")) and bool(m.group("c2"))
        if bool(m.group("c1")) != bool(m.group("c2")):
            return None  # the two halves disagree — outside the recognised shape
        return {
            "kind": "mana_value_or_x_spell",
            "min_mana_value": int(m.group("mv")),
            "creature_only": creature_only,
        }
    if _RESTRICTION_CREATURE_SPELL_RE.match(clause):
        return {"kind": "creature_spell", "allow_ability": allow_ability}
    if _RESTRICTION_COMMANDER_RE.match(clause):
        return {"kind": "commander_spell"}
    if _RESTRICTION_LEGENDARY_RE.match(clause):
        return {"kind": "legendary_spell"}
    if _RESTRICTION_INSTANT_SORCERY_RE.match(clause):
        return {"kind": "instant_or_sorcery_spell"}
    m = _RESTRICTION_TYPE_OR_UNLOCK_RE.match(clause)
    if m is not None:
        return {
            "kind": "type_spell", "types": [m.group("type").lower()], "allow_ability": allow_ability,
            "allow_unlock": True, **({"allow_face_up": True} if "face up" in clause.lower() else {}),
        }
    m = _RESTRICTION_MULTI_TYPE_RE.match(clause)
    if m is not None:
        return {
            "kind": "type_spell",
            "types": [m.group("t1").lower(), m.group("t2").lower()],
            "allow_ability": allow_ability,
        }
    m = _RESTRICTION_TYPE_RE.match(clause)
    if m is not None:
        word = m.group('type').lower()
        # RULE 205.2: artifact is a card type, not a creature subtype.
        return {'kind': 'card_type_spell' if word == 'artifact' else 'type_spell',
                'types': [word], 'allow_ability': allow_ability}
    return None

def counter_mana_riders(text: str) -> tuple[Optional[dict], Optional[dict]]:
    """RULE 106.6: attach conditional payoffs to this mana, not its source's tap."""
    text = text.lower()
    trigger = re.search(
        r"when you spend this mana to cast a dragon creature spell, it enters with an additional \+1/\+1 counter on it and gains hexproof until your next turn(?:\.|$)", text,
    )
    if trigger:
        return {"kind": "entry_counters", "count": 1, "creature": True, "subtype": "Dragon",
                "keyword": "hexproof", "duration": "until_next_turn", "triggered": True}, None
    if re.search(
        r"if you spend this mana to cast your commander, it enters with a number of additional \+1/\+1 counters on it equal to the number of times it'?s been cast from the command zone this game(?:\.|$)", text,
    ):
        return {"kind": "entry_counters", "count": "commander_casts", "commander": True}, None
    spent = re.search(r"(?:if|when) (?:this|that) mana is spent (?:to cast|on) (?:a |an )?(?P<kind>[^,.]+?) spell, (?P<body>[^.]+)", text)
    if spent:
        kind, body = spent.group("kind"), spent.group("body")
        if kind not in {"creature", "non-human creature", "multicolored creature", "legendary", "goblin"}:
            return None, None
        filt = {}
        if "creature" in kind: filt["creature"] = True
        if "non-human" in kind: filt["exclude_subtype"] = "Human"
        if "multicolored" in kind: filt["multicolored"] = True
        if "legendary" in kind: filt["legendary"] = True
        if "goblin" in kind: filt["subtype"] = "Goblin"
        if body == "that creature enters with an additional +1/+1 counter on it":
            return {"kind": "entry_counters", "count": 1, **filt}, None
        if body == "put a +1/+1 counter on this land":
            return {"kind": "source_counters", "count": 1, "counter": "+1/+1", "triggered": True, **filt}, None
        if body == "you get an experience counter":
            return {"kind": "player_counters", "count": 1, "counter": "experience", **filt}, None
    nxt = re.search(r"when you next cast an? (?P<kind>bird creature|creature|artifact) spell this turn, (?P<body>[^.]+)", text)
    if nxt:
        kind, body = nxt.group("kind"), nxt.group("body")
        filt = {"creature": True} if "creature" in kind else {"artifact": True}
        if "bird" in kind: filt["subtype"] = "Bird"
        if body == "that spell gains sunburst":
            return None, {"kind": "sunburst", **filt}
        count = re.fullmatch(r"(?:it|that creature) enters with (?P<n>an|two|2) additional \+1/\+1 counters? on it", body)
        if count:
            return None, {"kind": "entry_counters", "count": count_token_value(count), **filt}
    return None, None

# --- the riders the builder reads off the line itself ------------------------------------------------------------

#: RULE 605.3b: "Put a <kind> counter on this land" printed after (or before) the Add clause -- counters on the source,
#: placed as the ability resolves. Only a complete, unconditional sentence: a spend-trigger's "When ..., put ..." is
#: not an immediate placement.
SOURCE_COUNTER_RIDER_RE = re.compile(
    r"(?:^|(?<=\.))\s*put (?P<n>" + _COUNT_TOKEN + r") "
    r"(?P<kind>[a-z][a-z -]*|[+\-]\d+/[+\-]\d+) counters? on "
    r"(?:this (?:land|artifact|creature|permanent)|~)\.", re.IGNORECASE,
)
#: RULE 122.1: "You get a poison / experience counter." as the ability resolves.
PLAYER_COUNTER_RIDER_RE = re.compile(
    r"(?:^|(?<=\.))\s*you get (?P<n>" + _COUNT_TOKEN + r") (?P<kind>poison|experience) counters?\.", re.IGNORECASE,
)
#: RULE 729: "You get N rad counters." (a sentence of its own, as `SELF_RAD_COUNTERS_RE` reads it).
_RAD_SENTENCE_RE = re.compile(r"you get (?:" + _COUNT_TOKEN + r") rad counters?\.", re.IGNORECASE)
#: The painland rider as a whole sentence, optionally conditional ("... if you don't control a Swamp").
_SELF_DAMAGE_SENTENCE_RE = re.compile(
    r"(?:" + _SELF_SUBJECT + r") deals \d+ damage to you"
    r"(?: if you (?:don't|do not) control an? [a-z]+)?\.", re.IGNORECASE,
)
#: RULE 602.5d: "Activate only if <condition>." -- modelled when the activation-condition vocabulary reads the condition
#: (`activation_condition_dict`); an unread one makes the engine drop the whole ability, never grant it unconditionally.
_ACTIVATE_ONLY_IF_RE = re.compile(r"activate (?:this ability )?only if (?P<condition>[^.]+)\.", re.IGNORECASE)
#: RULE 702.19b / 611.2a: "~ doesn't untap during your next untap step." -- the source's one-shot skip flag
#: (`GameObject.skip_next_untap`), the same primitive "tap it; it doesn't untap" effects set.
SKIP_NEXT_UNTAP_RIDER_RE = re.compile(
    r"(?:" + _SELF_SUBJECT + r") doesn'?t untap during your next untap step\.",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """``text`` cut after each sentence-ending period (RULE 608.2c reads a rules text sentence by sentence)."""
    return [part for part in re.split(r"(?<=\.)\s+", text.strip()) if part]


def is_executed_rider(sentence: str) -> bool:
    """Whether ``sentence`` (one sentence after a mana ability's ``Add`` clause) is something the engine carries out.

    Fail closed: every shape here is read by `game/mana_abilities._parse_mana_ability_lines` into a `ManaAbility`
    field `GameEngine.tap_for_mana` applies; anything else (a draw, a life gain, a delayed copy, a sacrifice, a
    timing limit the cost grammar has no flag for) is unmodelled, so the line must not be claimed.
    """
    text = sentence.strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered.startswith("spend this mana only"):
        # RULE 605.3a. "...and that spell can't be countered" is not read by the engine (the restriction is built
        # from the clause alone), so a restriction that carries it is only half modelled.
        return (
            not _CANT_BE_COUNTERED_TAIL_RE.search(lowered.rstrip("."))
            and _RESTRICTION_CLAUSE_RE.fullmatch(text) is not None
            and parse_restriction(text) is not None
        )
    if _CANT_CAST_NONARTIFACT_RE.fullmatch(text):
        return True
    if _SELF_DAMAGE_SENTENCE_RE.fullmatch(text) or _RAD_SENTENCE_RE.fullmatch(text):
        return True
    if SOURCE_COUNTER_RIDER_RE.fullmatch(text) or PLAYER_COUNTER_RIDER_RE.fullmatch(text):
        return True
    if SKIP_NEXT_UNTAP_RIDER_RE.fullmatch(text):
        return True
    if _MANA_ACTIVATION_LIMIT_RE.fullmatch(text):
        return True
    only_if = _ACTIVATE_ONLY_IF_RE.fullmatch(text)
    if only_if is not None:
        return activation_condition_dict(normalized_condition(only_if.group("condition").lower())) is not None
    return counter_mana_riders(text) != (None, None)


def mana_riders_executed(effect_text: str) -> bool:
    """Whether every sentence after the leading ``Add`` clause of ``effect_text`` is one the engine executes."""
    return all(is_executed_rider(sentence) for sentence in split_sentences(effect_text)[1:])
