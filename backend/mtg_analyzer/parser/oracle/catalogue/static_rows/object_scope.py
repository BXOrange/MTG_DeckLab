"""Static-ability helpers: object scope (split from `static_handlers` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, NamedTuple, Optional
from ...spec import EffectSpec
from ..subgrammars import scope_adjective as _scope_adjective
from ..characteristic_phrase import parse_object_phrase
from .....models.cards.creature_types import CREATURE_SUBTYPES
from .....models.cards.subtype_types import LAND_SUBTYPES
from .anthem_patterns import ARTIFACT_SUBTYPES, CARD_TYPE_WORDS, COLOR_WORDS, NONCREATURE_TYPES

#: A blocker filter's colour/subtype/keyword/power vocabulary, as it appears
#: after "can't be blocked by …"/"…except by …". Ordered most-specific-first
#: (`object_filter` tries them in order); every one is anchored, so an
#: unlisted phrasing falls through to ``None``.
_REFERENCE_POWER_RES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"creatures with greater power", re.I), "greater"),
    # PAR-290: the strict mirror of the "less" row below (Silumgar Assassin, Spitfire Handler).
    (re.compile(r"creatures with power greater than (?:~'?s power|its power|~)", re.I), "greater"),
    (
        # "creatures with power less than ~'s power" (Sedge Troll-shaped) —
        # anchored to the *source's own* power. The sibling phrasing whose
        # threshold is a board count instead ("…less than the number of
        # Islands you control", Kraken of the Straits) is a dynamic value,
        # not a literal int, so it gets its own regex below. The literal
        # "power/toughness N or less/greater" rows live in the shared
        # `characteristic_phrase` grammar (PAR-282).
        re.compile(r"creatures with power less than (?:~'?s power|its power|~)", re.I),
        "less",
    ),
]

#: A basic land type's singular/plural pair → the `subtype` this pool's
#: `continuous.count_selector`'s ``lands_you_control_of_type_<x>`` reads.
#: "Plains" has no distinct singular, unlike the other four.
_BASIC_LAND_PLURALS: dict[str, str] = {
    "islands": "island", "swamps": "swamp", "mountains": "mountain",
    "forests": "forest", "plains": "plains",
}
#: "creatures with power less than the number of Islands you control"
#: (Kraken of the Straits) — the dynamic-threshold sibling of the literal
#: ``_FILTER_RES`` rows above, resolved fresh at combat time
#: (`combat.matches_object_filter`'s ``power_lt_count_selector``) rather
#: than baked into a fixed int at parse time.
_POWER_LT_COUNT_RE = re.compile(
    r"creatures with power less than the number of (?P<type>[a-z]+) you control", re.I
)

#: The shared grammar prints two-word combat keywords with a space ("first strike"); `combat.has` compares the
#: underscore slug (`combat._normalize`), so the adapter below converts back (RULE 702.7 / 702.4).
_KEYWORD_SLUG_KEYS = ("keyword", "without_keyword")


#: The keys a filter's noun produces: without one the phrase is only an adjective.
_NOUN_KEYS = frozenset({"card_type", "card_type_all", "card_type_any", "subtype", "subtype_any", "any_of", "token"})


def _slug(word: str) -> str:
    return word.replace(" ", "_")


def _shared_object_filter(text: str) -> Optional[dict]:
    """The shared `parse_object_phrase` reading of ``text`` as a controller-less filter, or ``None`` (PAR-282).

    "creatures with power 2 or less", "creatures with flying or reach", "creatures that are enchanted", "black
    creatures", "goblin, orc, or pirate" all parse through the one grammar the effect and trigger rows use. A
    controller tail ("… you control") is not part of a blocker/count operand, so it fails closed here."""
    parsed = parse_object_phrase(text, plural=True) or parse_object_phrase(text)
    if parsed is None or parsed[1] is not None:
        return None
    filt = dict(parsed[0])
    if not _NOUN_KEYS & filt.keys():
        return None  # a bare adjective ("black") names no object class; a blocker/count operand needs one
    for key in _KEYWORD_SLUG_KEYS:
        if isinstance(filt.get(key), str):
            filt[key] = _slug(filt[key])
    if "keyword_any" in filt:
        filt["keyword_any"] = [_slug(k) for k in filt["keyword_any"]]
    return filt


#: A leading combat-state/supertype word `combat.matches_object_filter`
#: already reads as its own boolean key (`filt["attacking"]`/
#: `filt["legendary"]`/…) rather than a printed characteristic. Without
#: stripping it first, the fallthrough to `parse_scope` below either silently
#: drops it (``attacking`` — `parse_scope` parses it for the *anthem* ``affects``
#: selector, a different consumer, and `object_filter` never read it back)
#: or, worse, mis-guesses it as a bogus creature *subtype* named e.g.
#: "Legendary" (`parse_scope`'s own digit-only guard doesn't catch a plain word
#: that just isn't a real subtype) — a filter that would then never match
#: any real creature, silently making the restriction impossible to satisfy
#: (the exact "1/1"-subtype failure mode `parse_scope`'s own digit guard exists
#: for, just via a non-digit word). One flag per call: no real card compounds
#: two ("legendary attacking creature") yet, and guessing at that shape
#: isn't this fix's job. Recurses on the remainder so any already-supported
#: filter (a subtype, "creature" alone, a colour, an "A or B" list, …) still
#: composes with the flag for free — this is what let PAR-79's dedicated
#: "target legendary creature"/"another target attacking creature" rows in
#: `catalogue/handlers.py` fold into the general "target `<filter>` can't be
#: blocked this turn" row instead of staying one-phrase-at-a-time regexes.
_OBJECT_FILTER_FLAG_WORDS = {"tapped", "attacking", "blocking", "legendary"}


def object_filter(text: str) -> Optional[dict]:
    """An object-describing phrase → a `combat.matches_object_filter` param
    dict, or ``None`` (fail-closed) for a phrasing outside the closed
    vocabulary above.

    Shared by every half of this family: the blocker set of "can't be blocked
    by <text>"/"…except by <text>", the counted set of "can't attack unless
    you control <text>", and — from `catalogue/handlers.py` — the same
    blocker set on the resolve-time "…this turn" variant. Public (no leading
    underscore) for that last cross-module use.
    """
    text = text.strip().rstrip(".").strip()
    if not text:
        return None
    # Share the validated subtype-negation vocabulary with other selectors.
    # RULE 509.1b: restrictions apply to either side of a proposed block.
    if text.startswith("non"):
        parsed = parse_object_phrase(text, plural=True)
        if parsed is None or parsed[1] is not None:
            return None
        negative = parsed[0]
        if "without_subtype" in negative:
            return negative
    words = text.split()
    if words and words[0] in _OBJECT_FILTER_FLAG_WORDS:
        flag = words.pop(0)
        rest = " ".join(words)
        if not rest:
            return {flag: True}
        sub = object_filter(rest)
        if sub is None or flag in sub:
            return None  # fail closed rather than silently drop/overwrite either half
        return {flag: True, **sub}
    if " and/or " in text and " with " not in text:
        # One noun shared by every alternative ("black and/or red creatures") is a same-dimension list the shared grammar
        # reads whole; a split of that text would leave "black" without its noun.
        joint = _shared_object_filter(text)
        if joint is not None:
            return joint
    if " and/or " in text:
        # "artifact creatures and/or red creatures" (PAR-79, Firefright
        # Mage) — a union across *different* filter dimensions (card type,
        # colour, subtype, …), unlike the same-dimension " or "/Oxford-comma
        # union below (subtype-only). Each side is independently parsed
        # through this same function — recursive, so any pairing of
        # already-supported single-phrase filters composes for free — and
        # combined via `matches_object_filter`'s new `any_of` combinator.
        parts = [p.strip() for p in text.split(" and/or ") if p.strip()]
        if len(parts) < 2:
            return None
        sub_filters = [object_filter(p) for p in parts]
        if any(f is None for f in sub_filters):
            return None
        return {"any_of": sub_filters}
    if text in ("creatures", "creature"):
        # No narrowing beyond the type itself — which still matters for the
        # "unless you control another creature" counting half, where a land
        # would otherwise be counted.
        return {"card_type": "creature"}
    if singularize(text) in CARD_TYPE_WORDS:
        # A bare card type ("unless you control another **artifact**") — the
        # anthem `parse_scope` parser below deliberately rejects these (a "+1/+1"
        # scope really is creatures-only), but a count/blocker filter is happy
        # with any permanent type.
        return {"card_type": singularize(text)}
    m = _POWER_LT_COUNT_RE.fullmatch(text)
    if m is not None:
        land_type = _BASIC_LAND_PLURALS.get(m.group("type").lower())
        return (
            None if land_type is None
            else {"power_lt_count_selector": f"lands_you_control_of_type_{land_type}"}
        )
    for pattern, relation in _REFERENCE_POWER_RES:
        if pattern.fullmatch(text):
            return {"power_vs_reference": relation}
    shared = _shared_object_filter(text)
    if shared is not None:
        return shared
    if " or " in text and " with " not in text:
        # "another Wolf or Werewolf" (Howlpack Wolf) — an OR over subtypes,
        # which `parse_scope` below can't express (it returns one subtype).
        # Splits on a bare " or " *or* an Oxford-comma list ("goblin, orc,
        # or pirate" — Corsairs of Umbar-shaped, PAR-78/79's own N-way
        # widening, folded into this shared function rather than kept as
        # each caller's own copy): `,\s*(?:or\s+)?` eats a comma plus an
        # optional trailing "or ", so a 3+-item list's final "or" doesn't
        # get left dangling on the last part. Every alternative must itself
        # be a recognisable single-word subtype, or the whole phrase fails
        # closed.
        parts = [
            p.strip() for p in re.split(r",\s*(?:or\s+)?|\s+or\s+", text) if p.strip()
        ]
        subtypes = []
        for part in parts:
            sub = parse_scope(part)
            if sub is None or not sub.subtype or " " in sub.subtype or sub.filt:
                return None
            subtypes.append(sub.subtype)
        return {"subtype_any": subtypes} if len(subtypes) > 1 else {"subtype": subtypes[0]}
    # "black creatures" / "artifact creatures" / "Walls" — reuse the anthem
    # family's own scope parser so the subtype/colour vocabulary can't drift
    # between "black creatures get +1/+1" and "can't be blocked by black
    # creatures".
    if text.endswith(" creatures") or text.endswith(" creature"):
        head = text.rsplit(" ", 1)[0]
        if head in CARD_TYPE_WORDS:
            return {"card_type": head}
    # `parse_scope` itself only recognises the plural "<subtype> creatures" (the
    # only form a real anthem/grant ever prints); a RULE 115 target's own
    # singular "target <subtype> creature" (Merfolk Sovereign) is the exact
    # same concept, just grammatically singular — pluralize once here
    # rather than teaching `parse_scope` a form its other callers never need.
    if text.endswith(" creature"):
        scope = parse_scope(text + "s")
    else:
        scope = parse_scope(text)
    if scope is None:
        return None
    filt: dict = {}
    if scope.subtype:
        if " " in scope.subtype:
            return None  # a multi-word "subtype" is `parse_scope` guessing — fail closed
        filt["subtype"] = scope.subtype
    if scope.colors:
        if len(scope.colors) != 1:
            return None  # a multi-colour blocker filter needs an OR this shape can't carry
        filt["color"] = scope.colors[0]
    if scope.filt:
        # PAR-134: a state/supertype adjective ("tapped", "nonlegendary",
        # "commander") — already in this filter's own vocabulary. A clash with
        # a key set above can't be one flat filter, so fail closed.
        if any(k in filt for k in scope.filt):
            return None
        filt.update(scope.filt)
    if scope.tokens or not filt:
        return None if scope.tokens else {}
    return filt


def defending_controls_condition(text: str) -> Optional[dict]:
    parsed = parse_object_phrase(re.sub(r'^an? ', '', text))
    if parsed is None or parsed[1] is not None:
        return None
    filt = dict(parsed[0])
    # Retain the existing basic-land spelling in emitted specs.
    if filt.get('subtype') in ('plains', 'island', 'swamp', 'mountain', 'forest'):
        filt['subtype'] = filt['subtype'].capitalize()
    return {'kind': 'defending_player_controls', 'filter': filt}


class _Scope(NamedTuple):
    subtype: Optional[str]  # a creature type ("Goblin"), or None for "creatures"
    tokens: bool  # True for "<…> tokens" (Intangible Virtue)
    colors: list  # WUBRG/C symbols; empty = no colour restriction (Bad Moon)
    #: PAR-3: "Artifact creatures you control get +1/+1" (Chief of the
    #: Foundry-shaped) — still a *creature* scope (RULE 205.2b: an artifact
    #: creature is both types), just narrowed by the printed card type
    #: rather than a creature subtype. Kept distinct from ``subtype``:
    #: `continuous.py`'s ``_has_subtype`` reads the type line's text
    #: *after* the em dash, where "Artifact" never appears (it's a type
    #: word, not a subtype) — this instead rides the generic ``card_type``
    #: filter param every `affected_objects` selector already supports.
    card_type: Optional[str] = None
    #: PAR-60 wave 19: "**Attacking** Pests/Vampires/Pirates/Elves you
    #: control get/have …" (Blight Mound, Crossway Troublemakers, Dire
    #: Fleet Neckbreaker, Elderfang Venom) — a leading combat-state filter
    #: narrowing the (usually subtype-scoped) creature set to just those
    #: currently attacking. Folded into an ``attacking_creatures_you_
    #: control[_of_type_<sub>]`` `affects` selector by `parse_scope_params`.
    attacking: bool = False
    #: PAR-134: the scope's adjectives that are *not* a creature subtype — a
    #: state ("tapped"/"untapped"/"nonattacking"), a supertype/designation
    #: ("legendary"/"nonlegendary"/"snow"/"commander"), a token status
    #: ("nontoken"), "multicolored", "modified" (RULE 700.9), a negation
    #: ("nonblack", "non-Wall") or a coordinated list ("Ninja and Rogue
    #: creatures" → ``any_of``) — as one `combat.matches_object_filter` dict.
    #: `parse_scope_params` ships it as the ``object_filter`` selector param and
    #: `object_filter` merges it into a target/blocker filter, so the two
    #: callers share the engine's one vocabulary instead of each guessing the
    #: word is a subtype. ``None`` = no such adjective.
    filt: Optional[dict] = None
    #: "Commanders you control" — the scope is every *permanent* of the
    #: designation, not just creatures (a planeswalker commander counts), so
    #: `parse_scope_params` picks a permanent selector.
    permanents: bool = False
    #: PAR-289: the card type a bare *non-creature* subtype word scopes to ("forests you control" is the Forest
    #: *lands*, RULE 205.3i; the same word is no creature type, RULE 205.3m). ``None`` = an ordinary creature scope.
    #: `parse_scope_params` then selects permanents of that card type instead of creatures.
    subtype_card_type: Optional[str] = None
    #: PAR-289: a coordinated list repeated its controller phrase ("goblins you control and elementals you control").
    #: The clause's own "you control" then has to be present for the list to mean what it says (`qualifier_ok`).
    requires_controller: bool = False


def _merge_scope_filter(into: dict, frag: dict) -> Optional[dict]:
    """``into`` ∪ ``frag`` (both AND-combined), or ``None`` on a clash that can't
    be expressed as one flat filter (two ``any_of``s, a repeated key)."""
    for key, value in frag.items():
        if key in into:
            if key == "without_color":
                into[key] = [*into[key], *value]
                continue
            return None
        into[key] = value
    return into


def _scope_filter(scope: _Scope) -> Optional[dict]:
    """A whole `_Scope` as one `matches_object_filter` dict (for a part of a
    coordinated list), or ``None`` when it can't be expressed."""
    filt: dict = dict(scope.filt or {})
    if scope.subtype:
        filt["subtype"] = scope.subtype
    if scope.colors:
        if scope.colors == ["C"]:
            filt["colorless"] = True
        elif "C" in scope.colors:
            return None
        elif len(scope.colors) == 1:
            filt["color"] = scope.colors[0]
        else:
            filt["color_any"] = list(scope.colors)
    if scope.tokens:
        filt["token"] = True
    if scope.card_type:
        filt["card_type"] = scope.card_type
    if scope.attacking:
        filt["attacking"] = True
    return filt


#: A coordinated list inside one scope phrase ("ninja and rogue creatures",
#: "green creatures and white creatures", "saproling creatures and other
#: treefolk creatures") — an OR over its parts, not one multi-word subtype.
_SCOPE_LIST_SPLIT_RE = re.compile(r",\s*(?:(?:and/or|and|or)\s+)?|\s+(?:and/or|and|or)\s+")


def _coordinated_scope(text: str) -> "Optional[_Scope] | bool":
    """PAR-134: parse ``text`` as an OR-list of scopes.

    ``False`` = not a coordinated list at all (no "and"/comma, or just a
    colour connector like "white and blue creatures" that `parse_scope` already
    reads); ``None`` = a list this can't express (fail-closed); else the
    `_Scope` carrying an ``any_of`` filter. Every part inherits the list's
    trailing noun ("ninja and rogue **creatures**"), and a part may carry its
    own leading "other" (Verdeloth — ``not_reference``)."""
    # A leading "attacking" qualifies the whole list ("attacking Klingons and Warriors"), not
    # just its first member, so it is hoisted out before the list is split.
    attacking = text.startswith("attacking ")
    if attacking:
        text = text[len("attacking "):]
    parts = [p.strip() for p in _SCOPE_LIST_SPLIT_RE.split(text) if p.strip()]
    if len(parts) < 2:
        return False
    if all(p in COLOR_WORDS for p in parts[:-1]):
        return False  # "white and blue creatures" — colours, handled by `parse_scope`
    noun = parts[-1].split()[-1]
    if noun not in ("creatures", "creature"):
        return _bare_subtype_list_scope(parts, attacking)
    alternatives: list[dict] = []
    for part in parts:
        words = part.split()
        if words[-1] not in ("creatures", "creature"):
            words.append("creatures")
        other = words[0] == "other"
        if other:
            words = words[1:]
        if "you" in words:
            return None  # a controller phrase inside one alternative
        sub = _simple_scope(words)
        filt = _scope_filter(sub) if sub is not None else None
        if filt is None or not filt:
            return None
        # PAR-270: a part naming a "subtype" must be one word; a comma inside a longer clause ("as long as enchanted
        # land is a basic Mountain, Goblin creatures ...") must never be read as a list.
        if sub.subtype and " " in sub.subtype:
            return None
        if other:
            filt["not_reference"] = True
        alternatives.append(filt)
    return _Scope(None, False, [], filt={"any_of": alternatives}, attacking=attacking)


#: A list part's repeated controller phrase ("goblins **you control** and elementals you control").
_REPEATED_CONTROLLER_SUFFIX = " you control"

#: The plural of a basic land type that is spelled like its singular ("plains"); every other land type pluralises
#: with a trailing "s".
_UNCHANGED_PLURAL_LAND_TYPES = frozenset({"plains"})

#: Bare artifact subtypes a coordinated scope list may name ("mounts and vehicles you control"). A Vehicle is an
#: artifact, not a creature type (RULE 205.3g), so its alternative carries its own card type.
_LIST_ARTIFACT_SUBTYPES = frozenset({"vehicle"})


def _singular_land_type(word: str) -> Optional[str]:
    """``word`` ("forests", "plains") → the land subtype it names (RULE 205.3i), or ``None``."""
    if word in _UNCHANGED_PLURAL_LAND_TYPES:
        return word
    singular = singularize(word)
    return singular if singular in LAND_SUBTYPES else None


def _list_part_alternative(word: str) -> Optional[dict]:
    """One bare word of a coordinated type list as the `matches_object_filter` alternative it names: a creature type
    (RULE 205.3m) is a creature of that type; a land type (RULE 205.3i) is a land of that type; a Vehicle is an artifact
    (RULE 205.3g). Anything else (a card-type word, a colour) is ``None`` so the whole list fails closed."""
    land = _singular_land_type(word)
    if land is not None:
        return {"card_type": "land", "subtype": land.capitalize()}
    singular = singularize(word)
    if singular in _LIST_ARTIFACT_SUBTYPES:
        return {"card_type": "artifact", "subtype": singular.capitalize()}
    if singular in CREATURE_SUBTYPES:
        return {"card_type": "creature", "subtype": singular.capitalize()}
    return None


def _bare_subtype_list_scope(parts: list[str], attacking: bool) -> "Optional[_Scope]":
    """PAR-270: a list of bare plural types with no "creatures" noun ("Klingons and Warriors you control",
    "attacking Klingons and/or Warriors", "Skeletons, Vampires, and Zombies").

    RULE 205.3m: each word names a creature type, and the list is a union: an object matching *any* listed type is in
    the scope (an "Elf Warrior creatures" two-word phrase is the opposite, an intersection, and never reaches here
    because it has no list connective). Every word must be the plural of a creature type (`CREATURE_SUBTYPES`); anything else
    ("artifacts and lands", "Vehicles") fails closed to ``None`` so a card-type list is never guessed to be a tribe.

    PAR-289: a list may also name a land type or a Vehicle ("other treefolk and forests you control", "mounts and
    vehicles you control"). Each word is then its own typed alternative (`_list_part_alternative`) and the scope is
    every permanent matching one of them, because a Forest is a land and no creature (RULE 205.3i vs 205.3m). A part may
    repeat the controller phrase ("goblins you control and elementals you control"), which `requires_controller` records."""
    words: list[str] = []
    repeated = False
    for part in parts:
        if part.endswith(_REPEATED_CONTROLLER_SUFFIX):
            part = part[: -len(_REPEATED_CONTROLLER_SUFFIX)]
            repeated = True
        if len(part.split()) != 1:
            return None  # "Elf Warriors" inside a list is a multi-word type, not a bare tribe
        words.append(part)
    alternatives = [_list_part_alternative(word) for word in words]
    if any(alt is None for alt in alternatives):
        return None
    if all(alt["card_type"] == "creature" for alt in alternatives):
        # The scope is "creatures you control", so only creature types qualify (a Forest or Vehicle is no creature type).
        subtypes = [alt["subtype"] for alt in alternatives]
        return _Scope(None, False, [], filt={"subtype_any": subtypes}, attacking=attacking,
                      requires_controller=repeated)
    if attacking:
        return None  # "attacking" narrows creatures; a land/Vehicle alternative is not in combat as such
    return _Scope(None, False, [], filt={"any_of": alternatives}, permanents=True, requires_controller=repeated)


def singularize(word: str) -> str:
    """A plural creature type → singular ("goblins"→"goblin", "elves"→"elf")."""
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s"):
        return word[:-1]
    return word


def parse_scope(body: str) -> Optional[_Scope]:
    """Parse a scope phrase into a `_Scope`, or ``None`` for a non-creature scope.

    Handles a leading global marker ("all"/"each"), leading colour words
    ("black", "white and blue"), scope adjectives that aren't creature types
    (`_SCOPE_ADJECTIVES`, PAR-134), "creatures", a plural type ("goblins"),
    "<type> creatures", coordinated lists ("Ninja and Rogue creatures") and
    the "<…> tokens" variants — always fail-closed (returns ``None`` rather
    than guess a scope it doesn't recognise).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):  # global emphasis, no scope change
        words = words[1:]
    listed = _coordinated_scope(" ".join(words))
    if listed is not False:
        return listed
    return _simple_scope(words)


def _simple_scope(words: list[str]) -> Optional[_Scope]:
    """`parse_scope` for one (non-coordinated) phrase, already split into words."""
    # PAR-60 wave 19: a leading "attacking" narrows the set by combat state
    # ("Attacking Elves you control have deathtouch").
    attacking = False
    if words and words[0] == "attacking":
        attacking = True
        words = words[1:]

    colors: list = []
    adjectives: dict = {}
    while words:
        if words[0] in COLOR_WORDS:
            colors.append(COLOR_WORDS[words[0]])
            words = words[1:]
        elif words[0] in ("and", "or") and len(words) > 1 and words[1] in COLOR_WORDS:
            words = words[1:]  # skip a colour connector ("white and blue")
        elif len(words) > 1 and (frag := _scope_adjective(words[0])) is not None:
            # A leading state/supertype adjective ("tapped", "nonlegendary") —
            # never the last word, which is the noun ("commander creatures").
            if _merge_scope_filter(adjectives, frag) is None:
                return None
            words = words[1:]
        else:
            break
    filt = adjectives or None

    tokens = False
    if words and words[-1] == "tokens":
        tokens = True
        words = words[:-1]
        if not words:  # bare "tokens" (creature tokens implied)
            return _Scope(None, True, colors, attacking=attacking, filt=filt)

    if words in (["creature"], ["creatures"]):
        return _Scope(None, tokens, colors, attacking=attacking, filt=filt)
    if not words:
        return None
    if words[-1] == "creatures":
        prefix = words[:-1]
        # "Artifact/Enchantment/Land/Planeswalker creatures [you control]
        # get/have …" (PAR-3) — a single printed card-type word ahead of
        # "creatures" narrows *which* creatures, it doesn't change the scope
        # away from creatures the way a bare "Artifacts you control" would.
        if len(prefix) == 1 and prefix[0] in (CARD_TYPE_WORDS - {"creature"}):
            return _Scope(None, tokens, colors, card_type=prefix[0], attacking=attacking, filt=filt)
        sub = singularize(" ".join(prefix))
    elif len(words) == 1:
        # "Commanders you control" — a designation, not a creature type, and
        # not limited to creatures (a planeswalker can be a commander).
        if words[0] in ("commander", "commanders"):
            return _Scope(
                None, tokens, colors, attacking=attacking,
                filt={**(filt or {}), "is_commander": True}, permanents=True,
            )
        land_type = _singular_land_type(words[0])
        if land_type is not None:
            # PAR-289, RULE 205.3i: "Forests you control have ..." names Forest *lands*; the same word is no creature
            # type (RULE 205.3m), so this must not be guessed as a creature scope.
            return _Scope(land_type.capitalize(), tokens, colors, attacking=attacking, filt=filt,
                          subtype_card_type="land")
        sub = singularize(words[0])
        # A *bare* artifact-subtype word ("Vehicles [you control]") is never
        # a creature scope — unlike the "<word> creatures" branch above
        # (RULE 205.2b's "Vehicle creatures", genuinely creature-scoped,
        # just narrowed further by the printed subtype), nothing here says
        # "creatures" at all, so this must fall through to `ANTHEM_RE`/
        # `GRANT_RE`/`QUOTED_GRANT_RE`'s `vehicle_scope_params` fallback
        # instead of being guessed as a creature subtype (a Vehicle isn't a
        # creature until crewed, RULE 702.122a).
        if sub in ARTIFACT_SUBTYPES:
            return None
    else:
        return None  # multi-word non-"creatures" scope — don't guess
    # A real creature subtype is never a P/T pattern — "a **1/1** creature"
    # (Lovestruck Beast's own "unless you control a 1/1 creature") must
    # never be guessed as a subtype named "1/1" (`combat.matches_object_
    # filter`'s substring `subtype` check would then just never match any
    # real card, silently making the restriction impossible to satisfy —
    # found via `object_filter`'s own singular-"creature" widening,
    # PAR-79, reaching this path for the first time on real card text). A
    # digit is the tell (no real subtype prints one); an outright
    # `.isalpha()` check is too strict — it would also reject a
    # legitimate multi-word `sub` this function's own callers (`object_
    # filter`'s "a multi-word 'subtype' is `parse_scope` guessing" check, e.g.)
    # still validate for themselves afterward.
    if not sub or sub in NONCREATURE_TYPES or any(c.isdigit() for c in sub):
        return None
    return _Scope(sub.capitalize(), tokens, colors, attacking=attacking, filt=filt)


def qualifier_params(qual: str) -> Optional[dict]:
    """The params a "with `<qualifier>`" tail adds to a group static's scope, or ``None`` (fail closed)."""
    text = qual.strip().lower()
    if text == "with the chosen name":
        return {"card_name_from_source": True}  # "…creatures you control with the chosen name have haste"
    filt = object_filter("creatures " + text)
    if filt and filt.get("card_type") == "creature":
        # The group is already "creatures", so the shared grammar's noun key is redundant (and would make "enchanted
        # creatures you control" and "creatures you control that are enchanted" differ for no rules reason).
        filt = {k: v for k, v in filt.items() if k != "card_type"}
    return {"object_filter": filt} if filt else None


def qualifier_ok(m: "re.Match[str]") -> bool:
    """Whether the clause's optional qualifier tail (if any) is one `parse_scope_params` can express."""
    qual = m.groupdict().get("qual")
    if qual and qualifier_params(qual) is None:
        return False
    scope = parse_scope(m.group("body"))
    # PAR-289: "goblins you control and elementals you control" only means a controlled group when the clause itself
    # names the controller; the bare "goblins you control and elementals have ..." is not that reading.
    return not (scope is not None and scope.requires_controller and not m.group("yours"))


#: The `affects` zone a static group selector names: a static ability acts on the battlefield only (RULE 613).
_GROUP_ZONE = "battlefield"


def and_filters(into: dict, extra: dict) -> dict:
    """``into`` AND ``extra`` as one `combat.matches_object_filter` dict (RULE 115.1: stacked adjectives are an
    intersection). Disjoint keys merge flat; a repeated key ("Elf Warrior", two ``any_of`` lists) keeps both
    operands whole under ``all_of`` instead of letting the later one overwrite the earlier."""
    if not extra:
        return into
    if not into:
        return dict(extra)
    if into.keys() & extra.keys():
        return {"all_of": [dict(into), dict(extra)]}
    return {**into, **extra}


def scope_color_filter(colors: list) -> dict:
    """A scope's leading colour words ("white and blue", "colorless") as a filter: any listed colour (RULE 105.2),
    ``"C"`` meaning colourless (RULE 105.2c: no colour at all)."""
    wubrg = [c for c in colors if c != "C"]
    listed = {"color": wubrg[0]} if len(wubrg) == 1 else {"color_any": list(wubrg)}
    if "C" not in colors:
        return listed
    return {"colorless": True} if not wubrg else {"any_of": [{"colorless": True}, listed]}


def scoped_group_selector(of: str, filt: dict) -> dict:
    """The structured ``affects`` selector (`continuous._structured_selector_objects`) for a static group: the
    battlefield permanents ``filt`` describes, controlled by ``of`` (``"you"``, ``"opponents"`` or ``"any"`` player)."""
    return {"zone": _GROUP_ZONE, "of": of, "filter": filt}


def group_selector(yours: bool, filt: dict) -> dict:
    """`scoped_group_selector` for "you control" (``of: you``) or any player's (``of: any``)."""
    return scoped_group_selector("you" if yours else "any", filt)


def parse_scope_params(scope: _Scope, m: "re.Match[str]") -> dict:
    """Build the structured ``affects`` selector from a scope and the clause match.

    The whole group — "you control" vs any player's, "other", subtype/colour/token/card-type narrowing, the
    "attacking" state, "of the chosen type/colour" and the "with the chosen name" qualifier — is one
    `combat.matches_object_filter` dict inside ``affects`` (ENG-60), read by `continuous.group_selector_objects`
    (RULE 613: the same set the retired flat ``subtype``/``color``/``tokens``/``card_type``/``exclude_self``
    params and named selectors picked out).
    """
    other = bool(m.group("scope"))
    yours = bool(m.group("yours"))
    filt: dict = {} if scope.permanents else {"card_type": "creature"}  # "Commanders you control" is any permanent
    if scope.subtype_card_type:  # PAR-289: "Forests you control" are lands (RULE 205.3i), not creatures
        filt["card_type"] = scope.subtype_card_type
    if other:
        filt["not_reference"] = True  # RULE 109.5: "other" excludes the ability's own source
    if scope.subtype:
        filt["subtype"] = scope.subtype
    if scope.card_type:  # "Artifact/Enchantment/… creatures …" (PAR-3): both types at once
        filt.pop("card_type", None)
        filt["card_type_all"] = ["creature", scope.card_type]
    if scope.tokens:
        filt["token"] = True
    if scope.attacking:  # PAR-60 wave 19: "Attacking …" narrows by combat state (RULE 506.4)
        filt["attacking"] = True
    if scope.colors:
        filt = and_filters(filt, scope_color_filter(scope.colors))
    if scope.filt:  # PAR-134: state/supertype adjectives, negations, coordinated lists
        filt = and_filters(filt, scope.filt)
    # "… of the chosen type/color …" (RULE 601.2b) — read fresh off the ability's own source at recompute time.
    chosen = m.groupdict().get("chosen")
    if chosen == "type":
        filt["subtype_from_source"] = True
    elif chosen == "color":
        filt["color_from_source"] = True
    qual = m.groupdict().get("qual")
    if qual:
        extra = qualifier_params(qual) or {}
        if "object_filter" in extra:
            filt = and_filters(filt, extra["object_filter"])
        if extra.get("card_name_from_source"):
            filt["name_from_source"] = True  # RULE 201.2: "with the chosen name"
    return {"affects": group_selector(yours, filt)}


#: PAR-3 — a *bare* non-creature permanent **type** word ("artifacts", "other
#: enchantments"), for `GRANT_RE`/`QUOTED_GRANT_RE` (and, since Balthier and
#: Fran, `ANTHEM_RE` too — a bare "+N/+N" clause on a non-creature permanent
#: *is* printed on a real card after all: "Vehicles you control get +1/+1").
#: The words the permanent-type scope accepts; each is a `card_type` of the structured group filter
#: (`permanent_scope_params`), "permanent" naming no type at all (RULE 110.1).
#: A bare *subtype* word ("vehicles") isn't in this set at all — see
#: `ARTIFACT_SUBTYPES`/`vehicle_scope_params` instead.
_PERMANENT_TYPE_WORDS: frozenset[str] = frozenset({"artifact", "enchantment", "land", "planeswalker", "permanent"})


def permanent_type_scope(body: str) -> Optional[str]:
    """A bare `_PERMANENT_TYPE_WORDS` word ("artifacts", "other
    enchantments") → the word itself, or ``None`` for anything `parse_scope`
    should own instead (a creature scope) or that this deliberately doesn't
    guess (a compound "artifacts and enchantments" — no engine selector
    ORs two card types yet; colour/subtype narrowing — no real card
    combines them with a non-creature scope).
    """
    words = body.split()
    while words and words[0] in ("all", "each"):
        words = words[1:]
    if len(words) != 1:
        return None
    word = singularize(words[0])
    return word if word in _PERMANENT_TYPE_WORDS else None


def permanent_scope_params(word: str, m: "re.Match[str]") -> dict:
    """The structured ``affects`` selector for a `permanent_type_scope` word — the non-creature sibling of
    `parse_scope_params`'s "you control"/"other"/global logic: every permanent of that card type, "other" excluding
    the ability's own source in *both* the "you control" and global cases ("Other enchantments **you control** have
    shroud." — Sterling Grove; "Other enchantments have '…'." — Aura Flux).
    """
    filt: dict = {} if word == "permanent" else {"card_type": word}
    if m.group("scope"):
        filt["not_reference"] = True  # RULE 109.5
    return {"affects": group_selector(bool(m.group("yours")), filt)}


def multi_permanent_type_list(body: str) -> Optional[list[str]]:
    """A "artifacts, creatures, enchantments, and lands" scope phrase →
    the ordered, de-duplicated list of singular `CARD_TYPE_WORDS` in it,
    or ``None`` (fail-closed) if it isn't two or more recognised
    permanent-type words. Splits on commas and "and" (RULE-text list
    punctuation), tolerating the Oxford comma.
    """
    words = [
        singularize(p.strip())
        for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", body.strip())
        if p.strip()
    ]
    if not words or any(w not in CARD_TYPE_WORDS for w in words):
        return None
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return seen if len(seen) >= 2 else None


#: Subtypes accepted in a graveyard-retrace grant's `<filter>` list
#: (Deeproot Historian's tribal scope). Kept tiny and explicit — only the
#: subtypes a real printed Retrace-grant card names.
_RETRACE_GRANT_SUBTYPES: frozenset[str] = frozenset({"merfolk", "druid"})
#: Main-type words a graveyard-card filter can name — the permanent types
#: plus instant/sorcery (a graveyard holds non-permanent cards too), all of
#: which `continuous._has_card_type` already recognises.
_GRAVEYARD_CARD_TYPE_WORDS: frozenset[str] = CARD_TYPE_WORDS | {"instant", "sorcery"}


def graveyard_retrace_grant_specs(filt: Optional[str]) -> Optional[list[EffectSpec]]:
    """The `grant_retrace` spec for a "[<filter>] cards in your graveyard
    have retrace" clause, or ``None`` (fail-closed) on an unrecognised
    filter word. ``filt`` is ``None`` for the bare form, else a comma/"and"
    list of `CARD_TYPE_WORDS` (→ ``card_types``) and/or
    `_RETRACE_GRANT_SUBTYPES` (→ ``subtypes``); "nonland" alone sets
    ``nonland_only``.
    """
    params: dict[str, Any] = {}
    if filt:
        words = [
            singularize(p.strip())
            for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", filt.strip())
            if p.strip()
        ]
        card_types: list[str] = []
        subtypes: list[str] = []
        for w in words:
            if w == "nonland":
                params["nonland_only"] = True
            elif w in _GRAVEYARD_CARD_TYPE_WORDS:
                card_types.append(w)
            elif w in _RETRACE_GRANT_SUBTYPES:
                subtypes.append(w.capitalize())
            else:
                return None
        if card_types:
            params["card_types"] = card_types
        if subtypes:
            params["subtypes"] = subtypes
        if not params:
            return None
    return [EffectSpec("grant_retrace", params)]


def is_vehicle_scope(body: str) -> bool:
    """A bare "[other] Vehicles [you control]" scope (Balthier and Fran) —
    the `ARTIFACT_SUBTYPES` sibling of `permanent_type_scope`'s bare
    main-type check, since "vehicle" is a *subtype* (`continuous.
    _has_subtype`), not one of `_PERMANENT_TYPE_WORDS`' main-type words.
    """
    words = body.split()
    while words and words[0] in ("all", "each"):
        words = words[1:]
    return len(words) == 1 and singularize(words[0]) in ARTIFACT_SUBTYPES


def vehicle_scope_params(m: "re.Match[str]") -> dict:
    """The structured ``affects`` selector for a bare Vehicle scope — the `ARTIFACT_SUBTYPES` sibling of
    `permanent_scope_params`: the artifacts of the printed subtype (a Vehicle is no creature until crewed,
    RULE 702.122a), "other" excluding the source."""
    filt: dict = {"card_type": "artifact", "subtype": "Vehicle"}
    if m.group("scope"):
        filt["not_reference"] = True
    return {"affects": group_selector(bool(m.group("yours")), filt)}
