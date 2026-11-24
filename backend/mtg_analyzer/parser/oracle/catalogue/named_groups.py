"""The structured battlefield group selectors the effect rows emit (ENG-61).

One place for the ``{"zone": "battlefield", "of": ..., "filter": ...}`` dicts that replaced the named group strings
(``each_creature_you_control``, ``all_creatures``, ``opponents_permanents``, ...): the engine reads them through
`continuous.group_selector_objects` / `_structured_selector_objects`, whose ``of`` is relative to the effect's
controller and whose ``filter`` is a `combat.matches_object_filter` dict (``not_reference`` is RULE 109.5's "other").
"""

from __future__ import annotations

from typing import Any, Optional

BATTLEFIELD = "battlefield"
OF_YOU = "you"
OF_OPPONENTS = "opponents"
OF_ANY = "any"


def battlefield_group(
    of: str, card_type: Optional[str] = "creature", *, other: bool = False, **filt: Any,
) -> dict[str, Any]:
    """The battlefield permanents ``of`` a player scope that are ``card_type`` (``None``: any permanent), narrowed by
    ``filt``; ``other`` excludes the ability's own source (RULE 109.5)."""
    body: dict[str, Any] = {} if card_type is None else {"card_type": card_type}
    if other:
        body["not_reference"] = True
    body.update(filt)
    return {"zone": BATTLEFIELD, "of": of, "filter": body}


#: `DealDamageEffect`'s mass-damage names (RULE 601.2c) -> (creature [and planeswalker] group, players also hit).
#: The union names also hit players, which are never part of a battlefield group, so the players ride beside it as
#: ``group_and_players``; ``each_other_*`` is RULE 109.5's source exclusion.
MASS_DAMAGE_GROUPS: dict[str, tuple[str, bool, Optional[str], Optional[str]]] = {
    # name: (of, with_planeswalkers, group_and_players, other)
    "each_creature": (OF_ANY, False, None, None),
    "each_other_creature": (OF_ANY, False, None, "other"),
    "each_creature_and_player": (OF_ANY, False, "each_player", None),
    "each_creature_and_planeswalker": (OF_ANY, True, None, None),
    "each_creature_opponents_control": (OF_OPPONENTS, False, None, None),
    "each_creature_and_planeswalker_opponents_control": (OF_OPPONENTS, True, None, None),
    "each_opponent_and_their_creatures": (OF_OPPONENTS, False, "each_opponent", None),
    "each_opponent_and_their_creatures_and_planeswalkers": (OF_OPPONENTS, True, "each_opponent", None),
}


def mass_damage_params(selector: str, selector_filter: Optional[dict] = None) -> Optional[dict[str, Any]]:
    """The ``group`` (and ``group_and_players``) params of `DealDamageEffect` for a retired mass-damage name, or
    ``None`` when ``selector`` is not one. ``selector_filter`` narrows the creatures (a planeswalker the name also
    covers stays unfiltered unless the name is the opponents' union, which filtered both)."""
    entry = MASS_DAMAGE_GROUPS.get(selector)
    if entry is None:
        return None
    of, with_planeswalkers, and_players, other = entry
    creature_filter = dict(selector_filter or {})
    group = battlefield_group(of, other=bool(other), **creature_filter)
    if with_planeswalkers:
        if of == OF_OPPONENTS:
            group["filter"] = {"card_type_any": ["creature", "planeswalker"], **creature_filter}
        elif creature_filter:
            group["filter"] = {"any_of": [
                {"card_type": "creature", **creature_filter}, {"card_type": "planeswalker"},
            ]}
        else:
            group["filter"] = {"card_type_any": ["creature", "planeswalker"]}
    params: dict[str, Any] = {"group": group}
    if and_players:
        params["group_and_players"] = and_players
    return params
