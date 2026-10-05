"""PAR-105: the standing "you may [play `<lands>` and] cast `<spells>` from the top of your library" family
(Elven Chorus, Assemble the Players, Korlessa, Nalia de'Arnise, Errant and Giada, Madame Web, Crystal Skull,
Johann, Summoning Materia — ~35 cards sharing one skeleton and varying along three axes):

* **which spells** — a noun phrase of card types / subtypes / "noncreature" / "colorless" / "historic", a
  keyword ("with flash or flying") or a bound ("with mana value N or greater", "with power N or less"),
  read through `dig.parse_criteria` into a `card_query` criteria dict;
* **which lands** — the same for "play snow lands", "play historic lands";
* **how often** — a leading "once each turn,".

The old closed-vocabulary row in `static_handlers` keeps the five phrasings it always read; this grammar is the
general fallback. Anything outside the vocabulary — a conditional ("as long as you control …"), a rider
("if you cast a spell this way, it gains haste"), a rarity ("common spells"), an alternative cost ("by
sacrificing a nonland permanent") — returns ``None`` and the line stays unclaimed rather than losing its
restriction. Pure data in, `EffectSpec`s out — no ``game/`` imports (the security boundary).
"""

from __future__ import annotations

import re
from typing import Optional

from ..spec import EffectSpec
from .dig import parse_criteria

#: Words `dig.parse_criteria` would read as a subtype (and so silently never match a real card) although
#: they name something else — a rarity. Refused so the line stays unclaimed.
_NOT_A_TYPE_WORDS = frozenset({"common", "uncommon", "rare", "mythic"})

_BODY_RE = re.compile(
    r"(?P<once>once each turn, )?you may (?P<body>.+?) from the top of your library",
    re.IGNORECASE,
)
_WITH_POWER_RE = re.compile(r"(?P<head>.*?)\s*with power (?P<n>\d+) or (?P<cmp>less|greater)\Z")
_WITH_MV_RE = re.compile(r"(?P<head>.*?)\s*with mana value (?P<n>\d+) or (?P<cmp>less|greater)\Z")
_WITH_KEYWORDS_RE = re.compile(r"(?P<head>.*?)\s*with (?P<kws>[a-z]+(?: or [a-z]+)*)\Z")
#: Keyword display names `Card.keywords` carries, for the "with flash or flying" phrase.
_KEYWORD_NAMES = {
    "flash": "Flash", "flying": "Flying", "haste": "Haste", "trample": "Trample", "deathtouch": "Deathtouch",
    "lifelink": "Lifelink", "vigilance": "Vigilance", "reach": "Reach", "menace": "Menace",
}


def _spell_criteria(phrase: str) -> Optional[dict]:
    """"creature", "cleric, rogue, warrior, and wizard", "instant and sorcery", "spells with flash or flying",
    "creature spells with power 2 or less" → a criteria dict; ``None`` when any part is outside the
    vocabulary. ``phrase`` is the text between "cast" and "spells"/"spell" (empty = any spell)."""
    text = phrase.strip()
    bound: dict = {}
    power = _WITH_POWER_RE.fullmatch(text)
    if power is not None:
        bound["max_power" if power.group("cmp") == "less" else "min_power"] = int(power.group("n"))
        text = power.group("head").strip()
    mv = _WITH_MV_RE.fullmatch(text)
    if mv is not None:
        bound["max_mana_value" if mv.group("cmp") == "less" else "min_mana_value"] = int(mv.group("n"))
        text = mv.group("head").strip()
    keywords: list[str] = []
    kw = _WITH_KEYWORDS_RE.fullmatch(text)
    if kw is not None:
        for word in re.split(r"\s+or\s+", kw.group("kws")):
            if word not in _KEYWORD_NAMES:
                return None
            keywords.append(_KEYWORD_NAMES[word])
        text = kw.group("head").strip()
    # "spider spells and noncreature spells": the inner "spells" is the same noun, not a type word.
    text = re.sub(r"\s*\bspells?\b", "", text).strip()
    if any(word in _NOT_A_TYPE_WORDS for word in re.findall(r"[a-z]+", text)):
        return None
    if text:
        # "X and Y spells" lists alternatives here (a spell is one kind or the other), so the "and" is an
        # "or"; `parse_criteria` refuses a literal "and".
        listed = re.sub(r",\s*and\s+|\s+and\s+", ", or ", text)
        criteria = parse_criteria(f"{listed} cards")
        if criteria is None:
            return None
    else:
        criteria = {}
    if keywords:
        keyword_alts = [{"has_keyword": name} for name in keywords]
        criteria = (
            {"or": keyword_alts} if not criteria
            else {"or": [{**criteria, **alt} for alt in keyword_alts]}
        ) if len(keyword_alts) > 1 or criteria else {"has_keyword": keywords[0]}
    return {**criteria, **bound}


def _land_criteria(phrase: str) -> Optional[dict]:
    """"lands" / "historic lands" / "snow lands" → a criteria dict over the land card (always a land)."""
    words = phrase.strip()
    if words in ("", "lands", "land"):
        return {}
    match = re.fullmatch(r"(?P<adj>[a-z]+) lands?", words)
    if match is None or match.group("adj") in _NOT_A_TYPE_WORDS:
        return None
    # The card is a land by context, so the adjective alone is the criteria ("historic" → artifact,
    # legendary or Saga; "snow" → the Snow supertype).
    return parse_criteria(f"{match.group('adj')} cards")


def parse_top_library_permission(text: str) -> Optional[list[EffectSpec]]:
    """The `top_library_permission` spec for a whole normalised line, or ``None``."""
    match = _BODY_RE.fullmatch(text.strip().rstrip("."))
    if match is None:
        return None
    body = match.group("body").strip()
    params: dict = {"look": True}
    # "play lands", "play snow lands and cast snow spells", "cast spells", "play lands and cast creature spells"
    land_part = re.match(r"play (?P<lands>(?:[a-z]+ )?lands?)(?: and |\Z)", body)
    rest = body
    if land_part is not None:
        criteria = _land_criteria(land_part.group("lands"))
        if criteria is None:
            return None
        params["play_lands"] = True
        if criteria:
            params["land_criteria"] = criteria
        rest = body[land_part.end():].strip()
    if rest:
        cast = re.fullmatch(r"cast (?:an? )?(?:(?P<kind>.*?) )?spells?(?: with (?P<with>.+))?", rest)
        if cast is None:
            return None
        phrase = " ".join(
            part for part in (cast.group("kind") or "", f"with {cast.group('with')}" if cast.group("with") else "")
            if part
        )
        criteria = _spell_criteria(phrase)
        if criteria is None:
            return None
        params["cast_spells"] = True
        if criteria:
            params["spell_criteria"] = criteria
    elif land_part is None:
        return None
    if match.group("once"):
        params["once_each_turn"] = True
    return [EffectSpec("top_library_permission", params)]


#: "[Once during each of your turns, ]you may cast a `<kind>` spell from your graveyard[. If a spell cast this
#: way would be put into your graveyard, exile it instead.]" (Karador, Gisa and Geralf, Danitha, Kess) — the
#: graveyard sibling of the top-of-library permission above, onto `GraveyardCastPermissionEffect`.
_GRAVEYARD_SPELLS_RE = re.compile(
    r"(?P<once>once during each of your turns, )?you may cast (?:an? )?(?P<kind>.*?) spells? "
    r"from your graveyard(?P<rider>\. if a spell cast this way would be put into your graveyard, exile it instead)?",
    re.IGNORECASE,
)
#: "You may cast this card from your graveyard[ as long as `<condition>`| if `<condition>`]." (Gravecrawler,
#: Marang River Prowler, Oathsworn Vampire, Ebondeath, The Indomitable, Skaab Ruinator) — the card's own
#: standing permission; a condition outside the `static_conditions` vocabulary leaves the line unclaimed.
_GRAVEYARD_SELF_RE = re.compile(
    r"you may cast (?:this card|~) from your graveyard(?: (?:as long as|if) (?P<cond>.+))?",
    re.IGNORECASE,
)


def parse_graveyard_cast_permission(text: str) -> Optional[list[EffectSpec]]:
    """The `graveyard_cast_permission` / `self_graveyard_or_exile_cast_permission` spec for a whole
    normalised line, or ``None``."""
    stripped = text.strip().rstrip(".")
    own = _GRAVEYARD_SELF_RE.fullmatch(stripped)
    if own is not None:
        params: dict = {"zones": ["graveyard"]}
        if own.group("cond"):
            from .static_handlers import static_condition  # function-scoped: static_handlers imports this module

            condition = static_condition(own.group("cond"))
            if condition is None:
                return None
            params["active_if"] = condition
        return [EffectSpec("self_graveyard_or_exile_cast_permission", params)]
    spells = _GRAVEYARD_SPELLS_RE.fullmatch(stripped)
    if spells is None:
        return None
    kind = (spells.group("kind") or "").strip()
    criteria = _spell_criteria(kind)
    if criteria is None or (not criteria and not spells.group("once")):
        return None
    params = {"permanent_only": False, "once_per_turn": bool(spells.group("once"))}
    if criteria:
        params["spell_criteria"] = criteria
    if spells.group("rider"):
        params["exile_if_would_be_put_into_graveyard"] = True
    return [EffectSpec("graveyard_cast_permission", params)]
