"""Group subjects the plain "<scope>s you control get/have ..." rows do not read (PAR-289).

* "each [other] creature [you control] that's a Wolf or a Werewolf gets +1/+1 and has trample." -- the singular
  "each ... that's a <type list>" spelling (Howlpack Resurgence, Brenard, Kaheera, Lovisa Coldeyes).
* "[other] legendary permanents you control have indestructible." -- a supertype group over every permanent type
  (Avacyn's Memorial); `parse_scope` only knows creature-type scopes, so this is its own row.

* "each land gets +2/+2 as long as it's a creature." / "each Vehicle you control gets +1/+1 as long as it's a creature."
  -- the per-object "as long as it's a creature" folds into the group's own filter (Earth Surge, Depala).

All are standing statics (RULE 611.3a) whose subject is the structured ``{zone, of, filter}`` group the layer system
re-reads every recompute (RULE 613), so a creature that stops matching, or leaves, stops being affected.

Pure regex + data; no ``game/`` imports.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..subtype_vocabulary import SUBTYPES
from .keyword_flags import flag_keywords
from .matcher_types import StaticContext, StaticResult
from .object_scope import group_selector

_KEYWORDS = r"[a-z][a-z, ]*?"
_EACH_THATS_RE = re.compile(
    r"each (?P<other>other )?creature(?P<yours> you control)? that's (?P<types>[a-z ,'-]+?) "
    rf"(?:gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+)(?: and has (?P<kw>{_KEYWORDS}))?|has (?P<kw2>{_KEYWORDS}))"
)
_LIST_SPLIT_RE = re.compile(r",\s*(?:or\s+)?|\s+or\s+")
_LEGENDARY_PERMANENTS_RE = re.compile(
    rf"(?P<other>other )?legendary permanents (?P<yours>you control) have (?P<kw>{_KEYWORDS})"
)


#: RULE 613.6: "as long as it's a creature" is tested per affected object, so a group of non-creature permanents whose
#: effect is conditional on being a creature is exactly the group of those that are creatures right now. The card types
#: this folding accepts; every one is a permanent type a creature can also be.
_CREATURE_CONDITIONAL_TYPES = frozenset({"land", "artifact", "enchantment"})
_CONDITIONAL_CREATURE_GROUP_RE = re.compile(
    r"each (?P<noun>[a-z]+)(?P<yours> you control)? gets (?P<p>[+-]\d+)/(?P<t>[+-]\d+) as long as it's an? creature"
)


def _type_list(text: str) -> Optional[list[str]]:
    """"a wolf or a werewolf" / "a cat, elemental, or beast" -> ["Wolf", "Werewolf"]; ``None`` on any non-subtype word
    (never guessed to be a type)."""
    names: list[str] = []
    for part in _LIST_SPLIT_RE.split(text.strip()):
        word = re.sub(r"^(?:an?\s+)", "", part.strip())
        if not word or word not in SUBTYPES:
            return None
        names.append("-".join(p.capitalize() for p in word.split("-")))
    return names or None


def static_each_creature_thats(ctx: StaticContext) -> StaticResult:
    m = _EACH_THATS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    types = _type_list(m.group("types"))
    if types is None:
        return None
    filt: dict = {"card_type": "creature"}
    if m.group("other"):
        filt["not_reference"] = True  # RULE 109.5
    filt["subtype" if len(types) == 1 else "subtype_any"] = types[0] if len(types) == 1 else types
    affects = group_selector(bool(m.group("yours")), filt)
    specs: list[EffectSpec] = []
    if m.group("p") is not None:
        specs.append(EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")), "affects": affects}))
    keyword_text = m.group("kw") or m.group("kw2")
    if keyword_text:
        keywords = flag_keywords(keyword_text)
        if keywords is None:
            return None
        specs.append(EffectSpec("grant_keyword", {"keywords": keywords, "affects": dict(affects)}))
    return specs or None


def static_legendary_permanents_grant(ctx: StaticContext) -> StaticResult:
    m = _LEGENDARY_PERMANENTS_RE.fullmatch(ctx.text)
    if m is None:
        return None
    keywords = flag_keywords(m.group("kw"))
    if keywords is None:
        return None
    filt: dict = {"legendary": True}  # RULE 205.4a; no card type: every battlefield object is a permanent
    if m.group("other"):
        filt["not_reference"] = True
    return [EffectSpec("grant_keyword", {"keywords": keywords, "affects": group_selector(True, filt)})]


def static_each_permanent_gets_if_creature(ctx: StaticContext) -> StaticResult:
    m = _CONDITIONAL_CREATURE_GROUP_RE.fullmatch(ctx.text)
    if m is None:
        return None
    noun = m.group("noun")
    if noun in _CREATURE_CONDITIONAL_TYPES:
        filt: dict = {"card_type_all": [noun, "creature"]}
    elif noun == "vehicle":
        filt = {"card_type_all": ["artifact", "creature"], "subtype": "Vehicle"}  # RULE 301.7a / 205.3g
    else:
        return None
    affects = group_selector(bool(m.group("yours")), filt)
    return [EffectSpec("anthem", {"power": int(m.group("p")), "toughness": int(m.group("t")), "affects": affects})]
