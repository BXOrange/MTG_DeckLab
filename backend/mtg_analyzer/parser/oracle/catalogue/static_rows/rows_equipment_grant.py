"""ENG-68: "<group> are Equipment [in addition to their other types] and have "<static>" and equip {N}" (RULE 702.6, 113.6).

One clause is three continuous effects (RULE 613.1d type, 613.1f abilities): the group becomes Equipment, gains the
quoted "equipped creature gets ..." static, and gains one or more Equip activated abilities. Armed with Proof, Arterial
Alchemy, Dan Lewis, Gemcutter Buccaneer, Bram, Baguette Brawler and Bludgeon Brawl share it. The three specs carry one
``locked_group_tag`` so the layer-6 parts reach exactly the objects the layer-4 part affected (RULE 613.6)."""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..count_phrase import parse_count_phrase
from .granted_abilities import quoted_ability_grant_effects_list
from .matcher_types import StaticContext, StaticResult

#: The tag the three specs of one clause share (one such clause per card).
EQUIPMENT_GRANT_TAG = "equipment_grant"

#: The head: "<group> (is|are) [an] equipment[s] [in addition to (its|their) other types]" then ``tail`` is everything
#: after the connective ("and have ..." / "with ...").
_EQUIPMENT_GROUP_RE = re.compile(
    r"(?:each )?(?P<group>[^\"]+?) (?:is|are) (?:an? )?equipments?"
    r"(?: in addition to (?:its|their) other types)? (?:and (?:has|have)|with) (?P<tail>.+)",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r'"(?P<body>[^"]+?)[.,]?"')
#: "equip {2}" / "equip pirate {1}" -- the optional word is a creature-subtype qualifier (RULE 702.6a).
_EQUIP_ENTRY_RE = re.compile(r"\bequip (?:(?P<qualifier>[a-z]+) )?(?P<cost>(?:\{[^}]+\})+)", re.IGNORECASE)
#: Bludgeon Brawl's "equip {x} ... where x is that artifact's mana value".
_X_IS_MANA_VALUE_RE = re.compile(r",? where x is that artifact'?s mana value", re.IGNORECASE)
_SOURCE_MANA_VALUE = "source_mana_value"


def static_group_equipment_grant(ctx: StaticContext) -> StaticResult:
    m = _EQUIPMENT_GROUP_RE.fullmatch(ctx.text)
    if m is None:
        return None
    quoted = _QUOTED_RE.search(m.group("tail"))
    if quoted is None:
        return None
    x_is_mana_value = _X_IS_MANA_VALUE_RE.search(m.group("tail")) is not None
    rest = _X_IS_MANA_VALUE_RE.sub("", m.group("tail").replace(quoted.group(0), " "))
    entries: list[dict] = []
    for equip in _EQUIP_ENTRY_RE.finditer(rest):
        entry: dict = {"cost": equip.group("cost")}
        if equip.group("cost").lower() == "{x}":
            if not x_is_mana_value:
                return None  # a free {X} has no value to read
            entry = {"cost_from": _SOURCE_MANA_VALUE}
        if equip.group("qualifier"):
            entry["qualifier"] = equip.group("qualifier").lower()
        entries.append(entry)
    leftover = _EQUIP_ENTRY_RE.sub(" ", rest)
    if not entries or re.sub(r"[\s,.]|\band\b|\bwith\b", "", leftover):
        return None  # anything else in the clause is something this row does not model: fail closed
    selector = parse_count_phrase(m.group("group").strip())
    if selector is None:
        return None
    inner = quoted.group("body").strip()
    if x_is_mana_value:
        inner = re.sub(r"\+x/", "+1/", inner)  # the amount is a per-source count, set below
    grants = quoted_ability_grant_effects_list(inner)
    if grants is None or len(grants) != 1 or grants[0].type != "grant_static_ability":
        return None
    if x_is_mana_value:
        for static in grants[0].params["static_specs"]:
            if static["type"] != "anthem" or static["params"].get("power") != 1:
                return None
            static["params"]["power_count"] = _SOURCE_MANA_VALUE
    grants[0].params["affects"] = selector
    grants[0].params["locked_group_tag"] = EQUIPMENT_GRANT_TAG
    return [
        EffectSpec("type_change", {
            "affects": selector, "add_subtypes": ["Equipment"], "locks_group_tag": EQUIPMENT_GRANT_TAG,
        }),
        grants[0],
        EffectSpec("grant_equip_ability", {
            "affects": selector, "entries": entries, "locked_group_tag": EQUIPMENT_GRANT_TAG,
        }),
    ]


#: "Equipment you control have equip {1}." (Astor) / "... have equip Knight {0}." (Syr Gwyn) / "Vehicles you control have
#: crew 1." (Astor, Kotori): a plain layer-6 grant of one more Equip / Crew ability (RULE 702.6, 702.122, 113.2c) with no
#: type change, so no group lock is needed.
_PLAIN_GROUP_GRANT_RE = re.compile(
    r"(?:each )?(?P<group>[^\"]+?) (?:has|have) "
    r"(?:equip (?:(?P<qualifier>[a-z]+) )?(?P<cost>(?:\{[^}]+\})+)|crew (?P<crew>\d+))",
    re.IGNORECASE,
)


def static_group_equip_crew_grant(ctx: StaticContext) -> StaticResult:
    m = _PLAIN_GROUP_GRANT_RE.fullmatch(ctx.text)
    if m is None:
        return None
    selector = parse_count_phrase(m.group("group").strip())
    if selector is None:
        return None
    if m.group("crew"):
        n = int(m.group("crew"))
        if n <= 0:
            return None
        return [EffectSpec("grant_crew_ability", {"affects": selector, "entries": [{"n": n}]})]
    if m.group("cost").lower() == "{x}":
        return None  # a free {X} has no value to read
    entry: dict = {"cost": m.group("cost")}
    if m.group("qualifier"):
        entry["qualifier"] = m.group("qualifier").lower()
    return [EffectSpec("grant_equip_ability", {"affects": selector, "entries": [entry]})]
