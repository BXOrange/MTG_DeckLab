"""PAR-292 M27, RULE 400.3 / 701.24a: the source together with other objects moved into *their owners'* libraries.

* "shuffle ~ and target creature with a stun counter on it into their owners' libraries" (Floodpits Drowner);
* "put ~ and target creature on top of their owners' libraries, then those players shuffle their libraries" (Void
  Stalker), which is a shuffle into the libraries (the placement on top is erased by the shuffle that follows);
* "put ~ and each creature it's blocking [or: each creature blocking or blocked by it] on top of their owners'
  libraries, then those players shuffle" (Gomazoa, Vortex Elemental): a group read before anything moves, from the
  combat relations of the source (`combat.matches_object_filter`'s ``blocked_by_source`` /
  ``blocking_or_blocked_by_source``);
* "shuffle ~ and your graveyard into their owner's library" (Elixir of Immortality), the graveyard-wide sibling;
* "shuffle ~ and up to three target cards from a single graveyard into their owners' libraries" (Serene Remembrance),
  whose picks share one graveyard (RULE 601.2c).

All of them are one `return_to_library` with ``with_source``: the objects go to their own owners' libraries and each
affected library is shuffled once. Without the "then those players shuffle" tail a "put ... on top" stays a placement.
"""

from __future__ import annotations

import re
from typing import Optional

from ...spec import EffectSpec
from ..named_groups import OF_ANY, battlefield_group
from ..subgrammars import TARGET, resolve_target_creature_state_filter, resolve_target_kind
from .shared import compile_clause, EffectHandler

#: The group phrases a source names about itself: the creatures it is blocking, or blocking / blocked by it.
_COMBAT_GROUPS: dict[str, str] = {
    "each creature it's blocking": "blocked_by_source",
    "each creature blocking or blocked by it": "blocking_or_blocked_by_source",
}
_COMBAT_GROUP_ALT = "|".join(re.escape(p) for p in _COMBAT_GROUPS)
_GRAVEYARD_PICK = r"up to (?P<n>\d+) target cards from a single graveyard"

_SOURCE_AND_OTHERS_RE = compile_clause(
    r"(?P<verb>shuffle|put) ~ and (?:(?P<group>" + _COMBAT_GROUP_ALT + r")|(?P<graveyard>" + _GRAVEYARD_PICK + r")|"
    + TARGET + r") (?P<dest>into their owners' libraries|on top of their owners' libraries"
    r"(?P<shuffled>, then those players shuffle(?: their libraries)?)?)"
)


def _source_and_others(m: re.Match[str]) -> Optional[list[EffectSpec]]:
    on_top = m.group("dest").startswith("on top")
    if on_top and m.group("shuffled") is None:
        position = "top"
    else:
        if m.group("verb") == "put" and not on_top:
            return None  # "put ... into their owners' libraries" is not a printed template
        position = "shuffle"
    params: dict = {"with_source": True, "position": position}
    if m.group("group"):
        params["target_kind"] = None
        params["group"] = battlefield_group(OF_ANY, "creature", **{_COMBAT_GROUPS[m.group("group")]: True})
    elif m.group("graveyard"):
        count = int(m.group("n"))
        params.update({"target_kind": "any_graveyard_card", "count": count, "optional": True, "same_graveyard": True})
    else:
        kind = resolve_target_kind(m.group("target"))
        if kind != "creature":
            return None
        state = resolve_target_creature_state_filter(m.group("target"))
        params["target_kind"] = kind
        if state:
            params["creature_filter"] = state
        if m.group("up_to_one"):
            params["optional"] = True
    return [EffectSpec("return_to_library", params)]


#: "shuffle ~ and your graveyard into their owner's library" (Elixir of Immortality): the source and the controller's
#: graveyard together, `shuffle_graveyard_into_library` with ``with_source``.
_SOURCE_AND_GRAVEYARD_RE = compile_clause(r"shuffle ~ and your graveyard into their owner's library")


def _source_and_graveyard(m: re.Match[str]) -> list[EffectSpec]:
    return [EffectSpec("shuffle_graveyard_into_library", {"with_source": True})]


ROWS: list[EffectHandler] = [
    EffectHandler("shuffle_source_and_graveyard_into_libraries", _SOURCE_AND_GRAVEYARD_RE, _source_and_graveyard),
    EffectHandler("shuffle_source_and_others_into_owners_libraries", _SOURCE_AND_OTHERS_RE, _source_and_others),
]
