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
from typing import Any, NamedTuple, Optional

from ...models.cards.subtype_types import SUBTYPES_BY_CARD_TYPE
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
#: Garenbrig, Primal Beyond). MEC-174: the source is checked against the
#: clause's own types (`_ability_source_agrees`), since the engine enforces
#: the ability half against the same words.
_RESTRICTION_ABILITY_TAIL_RE = re.compile(
    r"^(?P<head>.+?)\s+or activate (?:an ability of an?|abilities of)\s+(?P<source>.+)$", re.IGNORECASE
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


# --- MEC-174: the wider spend-restriction vocabulary -----------------------------------------------------------

#: RULE 205.2: the card types a restriction may name ("cast an instant or sorcery spell", "activate abilities of
#: artifacts"); "colorless" (RULE 105.2c) rides along as a characteristic word the engine reads off the object.
_RESTRICTION_CARD_TYPES = frozenset({
    "artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery",
})
COLORLESS_WORD = "colorless"
#: Every type word a restriction may name: card types, colorless and every subtype of RULE 205.3 (lower case, as the
#: clause is read; "time lord" is one word of this list).
_RESTRICTION_TYPE_WORDS = _RESTRICTION_CARD_TYPES | {COLORLESS_WORD} | frozenset(
    word for words in SUBTYPES_BY_CARD_TYPE.values() for word in words
)
_TYPE_LIST_SEPARATOR_RE = re.compile(r",?\s+and/or\s+|,?\s+or\s+|,?\s+and\s+|\s*,\s*")
#: Restriction kinds of the wider vocabulary (`game/mana_abilities._restriction_allows_*` is where each is enforced).
TYPE_LIST_SPELL_KIND = "type_list_spell"
ABILITY_ONLY_KIND = "ability_only"
ANY_SPELL_KIND = "spell"
X_SPELL_KIND = "x_spell"
SPELL_FROM_ZONE_KIND = "spell_from_zone"

#: "activate an ability" / "activate abilities" with an optional source: "of a creature", "of land sources",
#: "of artifacts", "of a cleric, rogue, warrior, or wizard".
_ACTIVATE_PHRASE = r"activate (?:an? ability|abilities)(?: of (?P<source>.+?))?"
_ACTIVATE_ONLY_RE = re.compile(r"^" + _ACTIVATE_PHRASE + r"$", re.IGNORECASE)
#: "<cast clause> or [to] activate ..." / "... and activate ..." and the same two halves in the other order
#: ("activate an ability or cast an artifact spell", Automated Artificer).
_CAST_THEN_ACTIVATE_RE = re.compile(
    r"^(?P<cast>cast .+?),?\s+(?:or|and)\s+(?:to )?" + _ACTIVATE_PHRASE + r"$", re.IGNORECASE
)
_ACTIVATE_THEN_CAST_RE = re.compile(
    r"^activate (?:an? ability|abilities)\s+or\s+(?P<cast>cast .+)$", re.IGNORECASE
)
_CAST_ANY_SPELL_RE = re.compile(r"^cast (?:a |any )?spells?$", re.IGNORECASE)
_CAST_X_SPELL_RE = re.compile(r"^cast spells with \{x\} in their mana costs$", re.IGNORECASE)
#: "cast a spell from your graveyard" / "cast spells from exile" / "cast a spell from anywhere other than your hand".
#: RULE 601.2a: the zone is the one the card is in when it is cast (before it moves to the stack).
_CAST_FROM_ZONE_RE = re.compile(
    r"^cast (?:a |any )?spells? from (?P<where>your graveyard|exile|anywhere other than your hand)$", re.IGNORECASE
)
_CAST_TYPE_LIST_RE = re.compile(r"^cast (?P<list>.+\s+spells?)$", re.IGNORECASE)
_ZONE_OF_PHRASE = {"your graveyard": "graveyard", "exile": "exile"}
HAND_ZONE = "hand"


def _type_list(text: str, *, spells: bool) -> Optional[list[str]]:
    """``text`` ("a cleric, rogue, warrior, or wizard", "instant and/or sorcery", "dragon spell or an omen") as the
    list of type words it names, or ``None`` when any element is not a card type / subtype / colorless (so a
    compound like "a chandra planeswalker" stays unclaimed). ``spells``: elements may carry their own trailing
    "spell(s)" ("a dragon spell or an omen spell"); otherwise a plural noun ("lands", "artifacts") is singularised
    and a trailing "source(s)" dropped."""
    words: list[str] = []
    for element in _TYPE_LIST_SEPARATOR_RE.split(text.strip().lower()):
        word = re.sub(r"^(?:an?|any)\s+", "", element.strip())
        word = re.sub(r"\s+spells?$" if spells else r"\s+sources?$", "", word)
        if word not in _RESTRICTION_TYPE_WORDS and word.endswith("s") and word[:-1] in _RESTRICTION_TYPE_WORDS:
            word = word[:-1]  # "artifacts", "lands", "creatures"
        if word not in _RESTRICTION_TYPE_WORDS:
            return None
        words.append(word)
    return words or None


def _cast_clause_restriction(cast: str) -> Optional[dict[str, Any]]:
    """The spell-casting half of a wider-vocabulary restriction (no ability half yet), or ``None``."""
    if _CAST_ANY_SPELL_RE.match(cast):
        return {"kind": ANY_SPELL_KIND}
    if _CAST_X_SPELL_RE.match(cast):
        return {"kind": X_SPELL_KIND}
    zone = _CAST_FROM_ZONE_RE.match(cast)
    if zone is not None:
        where = zone.group("where").lower()
        if where.startswith("anywhere"):
            return {"kind": SPELL_FROM_ZONE_KIND, "not_zone": HAND_ZONE}
        return {"kind": SPELL_FROM_ZONE_KIND, "zone": _ZONE_OF_PHRASE[where], **({"owned_by_you": True} if "your" in where else {})}
    listed = _CAST_TYPE_LIST_RE.match(cast)
    if listed is not None:
        types = _type_list(listed.group("list"), spells=True)
        if types is not None:
            return {"kind": TYPE_LIST_SPELL_KIND, "types": types}
    return None


def _wider_restriction(clause: str) -> Optional[dict[str, Any]]:
    """MEC-174: the shapes `parse_restriction`'s older vocabulary has no reading for. ``clause`` is the text after
    "Spend this mana only to"; the ability half ("activate abilities [of <source>]") is enforced against the
    activated ability's source (RULE 605.3a: the mana pays a cost of an ability of that kind of source only)."""
    activate = _ACTIVATE_ONLY_RE.match(clause)
    if activate is not None:
        return _with_ability_half({"kind": ABILITY_ONLY_KIND}, activate.group("source"))
    both = _CAST_THEN_ACTIVATE_RE.match(clause)
    if both is None:
        both = _ACTIVATE_THEN_CAST_RE.match(clause)
        if both is not None:
            cast_part = _cast_clause_restriction(both.group("cast"))
            return None if cast_part is None else _with_ability_half(cast_part, None)
        cast_part = _cast_clause_restriction(clause)
        return cast_part
    cast_part = _cast_clause_restriction(both.group("cast"))
    return None if cast_part is None else _with_ability_half(cast_part, both.group("source"))


def _with_ability_half(restriction: dict[str, Any], source: Optional[str]) -> Optional[dict[str, Any]]:
    """``restriction`` extended so it also pays an activated ability: any ability (``source`` is ``None``) or only
    one of a source with one of the named types. A source phrase naming a type outside the vocabulary yields ``None``."""
    restriction = {**restriction, "allow_ability": True}
    if source is not None:
        types = _type_list(source, spells=False)
        if types is None:
            return None
        restriction["ability_types"] = types
    return restriction


def _ability_source_agrees(restriction: dict[str, Any], source: str) -> bool:
    """Whether the "... or activate an ability of <source>" half names the same source types the spell half does,
    which is how `_restriction_allows_activation` enforces it (creature_spell: a creature; type kinds: ``types``)."""
    if not restriction.get("allow_ability"):
        return True  # a kind with no ability half (legendary, commander, ...) never reads the source
    named = _type_list(source, spells=False)
    if restriction.get("kind") == "creature_spell":
        return named == ["creature"]
    return named is not None and named == restriction.get("types")


def _classic_restriction(clause: str, allow_ability: bool) -> Optional[dict[str, Any]]:
    """The long-standing spell-restriction shapes (BUG-73 and before); ``clause`` has its ability tail peeled off."""
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
    wider_clause = clause
    ability_source = None
    tail = _RESTRICTION_ABILITY_TAIL_RE.match(clause)
    if tail is not None:
        clause, allow_ability, ability_source = tail.group("head"), True, tail.group("source")

    if ability_source is not None:
        classic = _classic_restriction(clause, allow_ability)
        if classic is not None:
            return classic if _ability_source_agrees(classic, ability_source) else None
    elif (classic := _classic_restriction(clause, allow_ability)) is not None:
        return classic
    return _wider_restriction(wider_clause)


#: MEC-175 (RULE 106.6): the payoff of mana spent on a matching spell -- "When you spend this mana to cast a Dragon
#: creature spell, scry 2." / "If that mana is spent on a creature spell, it gains haste until end of turn." The head
#: names the spell (`_spent_spell_filter`), the body what happens (`_payoff_body`); a "when" head is a triggered ability
#: (it uses the stack, RULE 603.2), an "if" head is applied to the spell as it is cast.
_PAYOFF_HEAD_RE = re.compile(
    r"(?P<head>if|when) (?:you spend (?:this|that) mana|(?:this|that|any of that) mana is spent) "
    r"(?:to cast|on) (?P<spell>[^,.]+?),\s+(?P<body>[^.]+)"
)
_SPENT_CREATURE_SPELL_RE = re.compile(r"^(?:an? )?(?:(?P<type>[a-z]+) )?creature spell$")
_SPENT_MANA_VALUE_SPELL_RE = re.compile(r"^(?:an? )?spell with mana value (?P<mv>\d+) or greater$")
_PAYOFF_LIFE_RE = re.compile(r"^you gain (?P<n>" + _COUNT_TOKEN + r") life$")
_PAYOFF_SCRY_RE = re.compile(r"^scry (?P<n>\d+)$")
_PAYOFF_SCRY_COMMANDER_RE = re.compile(
    r"^scry x, where x is the number of times it'?s been cast from the command zone this game$"
)
_PAYOFF_DRAW_RE = re.compile(r"^(?:you )?draw a card$")
_PAYOFF_HASTE_RE = re.compile(r"^it gains haste(?P<until> until end of turn)?$")
#: "that mana" payoffs a spell filter key reads (`game/mana_spend_riders.matches`).
HASTE_KEYWORD = "haste"
END_OF_TURN_DURATION = "end_of_turn"
REST_OF_GAME_DURATION = "rest_of_game"  # RULE 611.2a: a stated-nothing duration lasts the rest of the game
#: RULE 107.3 / 107.3f: half of the X a spell was cast with, rounded down.
_NEXT_CAST_X_RE = re.compile(
    r"when you next cast a spell with \{x\} in its mana cost this turn, "
    r"you draw a card and gain half x life, rounded down"
)


def _spent_spell_filter(spell: str) -> Optional[dict[str, Any]]:
    """The spell filter ("creature spell", "Dragon creature spell", "spell with mana value 6 or greater", "your
    commander") as `game/mana_spend_riders.matches` keys, or ``None`` when outside this vocabulary."""
    if spell == "your commander":
        return {"commander": True}
    if re.sub(r"^an? ", "", spell) == "creature spell that shares a creature type with your commander":
        return {"creature": True, "shares_type_with_commander": True}  # Path of Ancestry
    creature = _SPENT_CREATURE_SPELL_RE.match(spell)
    if creature is not None:
        subtype = creature.group("type")
        if subtype is None:
            return {"creature": True}
        if subtype in _RESTRICTION_TYPE_WORDS and subtype not in _RESTRICTION_CARD_TYPES:
            return {"creature": True, "subtype": subtype.title()}
        return None
    value = _SPENT_MANA_VALUE_SPELL_RE.match(spell)
    return None if value is None else {"min_mana_value": int(value.group("mv"))}


def _payoff_body(body: str) -> Optional[dict[str, Any]]:
    life = _PAYOFF_LIFE_RE.match(body)
    if life is not None:
        return {"kind": "life", "count": count_token_value(life)}
    scry = _PAYOFF_SCRY_RE.match(body)
    if scry is not None:
        return {"kind": "scry", "count": int(scry.group("n"))}
    if _PAYOFF_SCRY_COMMANDER_RE.match(body):
        return {"kind": "scry", "count": "commander_casts"}
    if _PAYOFF_DRAW_RE.match(body):
        return {"kind": "draw", "count": 1}
    haste = _PAYOFF_HASTE_RE.match(body)
    if haste is not None:
        return {"kind": "grant_keyword", "keyword": HASTE_KEYWORD,
                "duration": END_OF_TURN_DURATION if haste.group("until") else REST_OF_GAME_DURATION}
    return None


def _spent_payoff_riders(text: str) -> tuple[Optional[dict], Optional[dict]]:
    """MEC-175: the spend rider / next-cast rider of a payoff sentence this module reads beyond the counter shapes."""
    next_cast = _NEXT_CAST_X_RE.search(text)
    if next_cast is not None:
        return None, {"kind": "draw_gain_half_x", "has_x": True, "triggered": True}
    head = _PAYOFF_HEAD_RE.search(text)
    if head is None:
        return None, None
    spell = _spent_spell_filter(head.group("spell").strip())
    payoff = _payoff_body(head.group("body").strip())
    if spell is None or payoff is None:
        return None, None
    # An "if" head is applied to the spell as it is cast; a "when" head is a triggered ability (RULE 603.2).
    # (Only the keyword grant is an "if" payoff the engine applies without the stack.)
    if (payoff["kind"] == "grant_keyword") != (head.group("head") == "if"):
        return None, None
    return {**payoff, **spell, **({"triggered": True} if head.group("head") == "when" else {})}, None


def counter_mana_riders(text: str) -> tuple[Optional[dict], Optional[dict]]:
    """RULE 106.6: attach conditional payoffs to this mana, not its source's tap."""
    text = text.lower()
    payoff = _spent_payoff_riders(text)
    if payoff != (None, None):
        return payoff
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
        if body in ("put a +1/+1 counter on this land", "put a +1/+1 counter on ~"):  # raw / normalized self-reference
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
        return mana_condition_dict(normalized_condition(only_if.group("condition").lower())) is not None
    if (
        instead_rider(text) is not None or life_rider(text) is not None or draw_rider(text) is not None
        or delayed_draw_rider(text) or exhaustion_sacrifice_rider(text) is not None
    ):
        return True
    return counter_mana_riders(text) != (None, None)


def mana_riders_executed(effect_text: str) -> bool:
    """Whether every sentence after the leading ``Add`` clause of ``effect_text`` is one the engine executes."""
    return all(is_executed_rider(sentence) for sentence in split_sentences(effect_text)[1:])


# --- MEC-175: conditions, amount overrides, life, draws and counter exhaustion ----------------------------------------

#: A board condition of a mana ability's rider ("activate only if ...", "if ..., add ... instead", "if ..., you gain 1
#: life"): the shared activation vocabulary (`activation_condition_dict`) plus the compound shapes the mana lines print.
_OR_IF_SPLIT_RE = re.compile(r"\s+or\s+if\s+")
_CONTROL_LIST_RE = re.compile(r"^you control (?P<list>.+)$")
_LIST_OR_SPLIT_RE = re.compile(r",?\s+or\s+|,\s*")
_LIST_AND_SPLIT_RE = re.compile(r",?\s+and\s+")
_SAME_NAME_LANDS_RE = re.compile(r"^you control (?P<n>\d+) or more (?P<type>[a-z]+)s with the same name$")
_CONTROL_NAMED_RE = re.compile(r"^you control creatures named (?P<names>.+)$")
#: RULE 201.2: a part of "you control X and Y" the card-type/subtype vocabulary cannot read is a card name (Urza's
#: Tower, Command Power Plant) -- a name has no digits and names no characteristic of the shared vocabulary.
_NAME_PART_RE = re.compile(r"^(?:an?\s+)?(?P<name>[a-z][a-z' \-]*[a-z])$")
#: "you control <A> and <B>" needs at least this many named parts: a lone unread noun is more likely a vocabulary gap
#: than a card name, so it stays unread.
_MIN_NAMED_PARTS = 2


def _control_part(part: str) -> Optional[dict[str, Any]]:
    """One element of a "you control A, B, or C" list as a condition: the shared vocabulary, else a card name."""
    condition = activation_condition_dict(f"you control a {part}")
    if condition is not None and not (
        condition.get("kind") == "control_legendary_subtype" and condition.get("subtype") in _RESTRICTION_CARD_TYPES
    ):
        return condition  # (a "legendary enchantment" is not the creature-only `control_legendary_subtype`)
    return None


def mana_condition_dict(text: str) -> Optional[dict[str, Any]]:
    """MEC-175 (RULE 602.5b / 608.2c): ``text`` (normalized, no trailing period) as a `static_conditions` dict, or
    ``None`` when this vocabulary cannot read it. The single reader behind "Activate only if", "if ..., add ...
    instead" and "if ..., you gain N life", so each is claimed exactly when the engine evaluates it."""
    stripped = text.strip().rstrip(".").strip()
    plain = activation_condition_dict(stripped)
    if plain is not None and not (
        plain.get("kind") == "control_legendary_subtype" and plain.get("subtype") in _RESTRICTION_CARD_TYPES
    ):
        return plain
    if _OR_IF_SPLIT_RE.search(stripped):
        parts = [mana_condition_dict(part) for part in _OR_IF_SPLIT_RE.split(stripped)]
        return None if any(part is None for part in parts) else {"kind": "any", "conditions": parts}
    same_name = _SAME_NAME_LANDS_RE.match(stripped)
    if same_name is not None and same_name.group("type") in _RESTRICTION_CARD_TYPES:
        return {"kind": "control_same_name_at_least", "card_type": same_name.group("type"), "min": int(same_name.group("n"))}
    named = _CONTROL_NAMED_RE.match(stripped)
    if named is not None:
        names = _LIST_AND_SPLIT_RE.split(named.group("names"))
        if len(names) >= _MIN_NAMED_PARTS:
            return {"kind": "all", "conditions": [{"kind": "control_named", "name": name.strip()} for name in names]}
        return None
    listed = _CONTROL_LIST_RE.match(stripped)
    if listed is None:
        return None
    body = listed.group("list")
    conjunction, splitter = ("any", _LIST_OR_SPLIT_RE) if re.search(r",?\s+or\s+", body) else ("all", _LIST_AND_SPLIT_RE)
    parts = [part.strip() for part in splitter.split(body) if part.strip()]
    if len(parts) < _MIN_NAMED_PARTS:
        return None
    conditions = []
    for part in parts:
        bare = re.sub(r"^(?:an?|another)\s+", "", part)
        condition = _control_part(bare)
        if condition is None:
            name = _NAME_PART_RE.match(part)
            if name is None or conjunction == "any":
                return None
            condition = {"kind": "control_named", "name": name.group("name")}
        conditions.append(condition)
    return {"kind": conjunction, "conditions": conditions}


def rider_text(sentence: str, name: Optional[str] = None) -> str:
    """``sentence`` normalized the way the parser reads it (the builder passes raw text and its card name)."""
    return normalize(sentence.strip(), name).strip()


#: RULE 605.1a / 608.2c "If <condition>, add <mana> instead." (the Urza lands, the "four or more creatures" druids) and
#: "If <condition>, instead add <mana>." (Gemstone Caverns): the replacement production of the one ability.
_INSTEAD_RE = re.compile(
    r"^if (?P<cond>.+?), (?:add (?P<clause>.+?) instead|instead add (?P<clause2>.+?))\.$"
)
#: The replacement clauses `game/mana_abilities` builds a production from: symbols, or a counted any-colour clause.
_INSTEAD_CLAUSE_RE = re.compile(
    r"^(?:(?:\{[wubrgc]\})+|(?:\d+ )?mana of any (?:1 |one )?colou?r(?: in your commander's colou?r identity)?)$"
)


class InsteadRider(NamedTuple):
    """``condition`` (a `static_conditions` dict) turns the ability's production into ``clause`` (normalized Add text)."""

    condition: dict[str, Any]
    clause: str


def instead_rider(sentence: str, name: Optional[str] = None) -> Optional[InsteadRider]:
    """The "if <condition>, add <mana> instead" sentence as its condition and replacement clause, or ``None``."""
    match = _INSTEAD_RE.match(rider_text(sentence, name))
    if match is None:
        return None
    clause = (match.group("clause") or match.group("clause2")).strip()
    condition = mana_condition_dict(match.group("cond"))
    if condition is None or _INSTEAD_CLAUSE_RE.match(clause) is None:
        return None
    return InsteadRider(condition, clause)


_INSTEAD_ANY_COLOR_RE = re.compile(
    r"^(?:(?P<n>\d+) )?mana of any (?:1 |one )?colou?r(?P<identity> in your commander's colou?r identity)?$"
)


def instead_production_clause(clause: str) -> str:
    """The replacement clause as the raw "Add ..." text `game/mana_abilities` parses ("{c}{c}" -> "{C}{C}", "2 mana of
    any 1 color" -> "2 mana of any one color"), so the replacement is built by the very grammar the base ability uses."""
    any_color = _INSTEAD_ANY_COLOR_RE.match(clause)
    if any_color is None:
        return clause.upper()
    return (f"{any_color.group('n') or 1} mana of any one color"
            + (" in your commander's color identity" if any_color.group("identity") else ""))


#: RULE 605.1a: "You gain N life." on a mana ability (Pristine Talisman), optionally behind "If <condition>,".
_LIFE_RIDER_RE = re.compile(r"^(?:if (?P<cond>.+?), )?you gain (?P<n>\d+) life\.$")


class LifeRider(NamedTuple):
    amount: int
    condition: Optional[dict[str, Any]]


def life_rider(sentence: str, name: Optional[str] = None) -> Optional[LifeRider]:
    """The life-gain rider as ``(amount, condition)``, or ``None`` (also when its condition is unreadable)."""
    match = _LIFE_RIDER_RE.match(rider_text(sentence, name))
    if match is None:
        return None
    if match.group("cond") is None:
        return LifeRider(int(match.group("n")), None)
    condition = mana_condition_dict(match.group("cond"))
    return None if condition is None else LifeRider(int(match.group("n")), condition)


#: RULE 605.1a: "Draw a card." as part of the ability (Chromatic Sphere, the Eggs): no stack, drawn on resolution.
_DRAW_RIDER_RE = re.compile(r"^draw (?P<n>a|an|one|\d+) cards?\.$")
#: RULE 603.7: "Draw a card at the beginning of the next turn's upkeep." (Astrolabe, Barbed Sextant) -- a delayed
#: triggered ability, so it uses the stack when it triggers even though the mana ability does not.
_DELAYED_DRAW_RIDER_RE = re.compile(r"^draw a card at the beginning of the next turn's upkeep\.$")


def draw_rider(sentence: str, name: Optional[str] = None) -> Optional[int]:
    """The number of cards an immediate "Draw a card." rider draws, or ``None``."""
    match = _DRAW_RIDER_RE.match(rider_text(sentence, name))
    if match is None:
        return None
    token = match.group("n")
    return int(token) if token.isdigit() else 1


def delayed_draw_rider(sentence: str, name: Optional[str] = None) -> bool:
    return _DELAYED_DRAW_RIDER_RE.match(rider_text(sentence, name)) is not None


#: RULE 122.1 / 704: "If there are no <kind> counters on this land, sacrifice it." (Peat Bog, Gemstone Mine): printed
#: after the cost removed the last counter, it is a rider of the ability, checked as the ability resolves.
_EXHAUSTION_SACRIFICE_RE = re.compile(
    r"^if there are no (?P<kind>[a-z][a-z \-]*) counters on (?:~|this (?:land|artifact|creature|permanent)), sacrifice it\.$"
)


def exhaustion_sacrifice_rider(sentence: str, name: Optional[str] = None) -> Optional[str]:
    """The counter kind whose absence sacrifices the source, or ``None``."""
    match = _EXHAUSTION_SACRIFICE_RE.match(rider_text(sentence, name))
    return None if match is None else match.group("kind")


# --- the Add clause itself ---------------------------------------------------------------------------------------

#: The mana symbols an ``Add`` clause may print and the builder turns into mana (`game/mana_abilities._PIP_RE`).
_ADD_CLAUSE_SYMBOLS = frozenset("wubrgc")
_SYMBOL_RE = re.compile(r"\{([^}]*)\}")
#: "mana of any type that a land / Gate you control could produce" -- the only "any type" referent the builder reads
#: (`game/mana_abilities._LAND_TYPE_COULD_PRODUCE_RE`); the sacrificed land's types (Squandered Resources) are not.
_ANY_TYPE_RE = re.compile(r"mana of any type")
_ANY_TYPE_READABLE_RE = re.compile(r"mana of any type that an? (?:land|gate) you control could produce")
_X_COMBINATION_RE = re.compile(r"\bx mana in any combination of\b")
_X_COMBINATION_SUBJECT_RE = re.compile(r", where x is (?P<subject>.+?)\.?$")
#: The "where X is ..." subjects `game/mana_abilities._parse_combination_selector` resolves: the greatest power among
#: creatures you control, the source's own power, or one of `_selector_from_subject`'s count phrases.
_X_COMBINATION_SUBJECT_READABLE_RE = re.compile(
    r"the greatest power among creatures you control|(?:~|this creature)'s power"
    r"|(?:the number of )?.+ (?:you control|on the battlefield)"
    r"|(?:the number of )?(?:[a-z]+ )?cards in your graveyard"
    r"|(?:the number of )?[+\-]?[\w/+\-]+ counters? on (?:this (?:creature|artifact|enchantment|land|permanent)|~)"
)
#: "Remove X <kind> counters from ..." in a cost sizes an X the builder never announces (Crucible of the Spirit Dragon).
_REMOVE_X_COUNTERS_COST_RE = re.compile(r"\bremove x\b")
SELF_COUNTER_X_COST_RE = re.compile(r"(?:^|,)\s*remove x [a-z]+ counters from (?:~|this land)\s*$", re.I)
X_COUNTER_MANA_RE = re.compile(
    r"x mana in any combination of (?:colou?rs|\{[wubrg]\} and/or \{[wubrg]\})", re.I,
)
TWO_DISTINCT_MANA_RE = re.compile(r"(?:two|2) mana of different colou?rs", re.I)


def add_clause_readable(cost_text: str, effect_text: str) -> bool:
    """Whether the leading ``Add`` clause of a mana ability is one `game/mana_abilities` builds a working ability from.

    BUG-85 (RULE 605.1a): the segmenter claims a ``<cost>: Add ...`` line as a mana ability without a spec, so a
    clause the builder cannot read would leave a MODELED card with no mana ability at all. The vocabulary mirrored here
    is deliberately narrow: only the shapes known to be unreadable are refused (a symbol that is not a mana symbol, "two
    mana of different colors", an unreadable "any type" referent, an X the cost sizes by removing counters, an X-sized
    combination over an unread subject); the full-cache parity test in `test_bug85_add_clause_claims.py` fails when a
    claimed line yields no `ManaAbility`, which is what keeps this list honest.
    """
    clause = (split_sentences(effect_text) or [""])[0].lower().removesuffix(".").strip()
    cost = cost_text.lower()
    if any(symbol not in _ADD_CLAUSE_SYMBOLS for symbol in _SYMBOL_RE.findall(clause)):
        return False  # {T}{T} (Sole Performer), {∞} (Mox Lotus), {HR}: not mana the pool can hold
    if "different colors" in clause or "different colours" in clause:
        return TWO_DISTINCT_MANA_RE.fullmatch(clause.removeprefix("add ")) is not None
    if _ANY_TYPE_RE.search(clause) and not _ANY_TYPE_READABLE_RE.search(clause):
        return False
    if _X_COMBINATION_RE.search(clause):
        if _REMOVE_X_COUNTERS_COST_RE.search(cost):
            return bool(SELF_COUNTER_X_COST_RE.search(cost) and X_COUNTER_MANA_RE.fullmatch(clause.removeprefix("add ")))
        subject = _X_COMBINATION_SUBJECT_RE.search(clause)
        if subject is not None and _X_COMBINATION_SUBJECT_READABLE_RE.fullmatch(subject.group("subject")) is None:
            return False
    return True
