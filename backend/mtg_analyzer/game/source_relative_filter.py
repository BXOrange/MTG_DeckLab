"""Combat-restriction filters that compare a creature against the *ability's own source*.

A ``combat_restriction`` static is stamped onto the restricted objects once per layer pass
(`continuous._apply_post_layer_combat_restrictions_and_goad`) but evaluated much later, at block time, with
the *attacker* as the filter's reference object -- so a filter that must read the printing permanent
("Creatures with power less than **this creature's** power can't block creatures you control", Champion of
Lambholt) cannot be answered there. It is resolved at stamp time instead, where the source and its freshly
derived power (RULE 613.4c, layer 7) are both in hand, into the plain numeric filter keys
`combat.matches_object_filter` already understands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject


def resolve_source_relative_entry(entry: dict[str, Any], source: Optional["GameObject"]) -> dict[str, Any]:
    """Return ``entry`` with any source-relative filter key replaced by a literal threshold.

    ``power_lt_source_power`` becomes ``max_power = source.power - 1`` ("power less than" is strictly less, so
    the largest qualifying power is one under the source's). An entry without such a key is returned untouched.
    """
    restriction_filter = entry.get("filter")
    if not isinstance(restriction_filter, dict) or not restriction_filter.get("power_lt_source_power"):
        return entry
    resolved = {k: v for k, v in restriction_filter.items() if k != "power_lt_source_power"}
    resolved["max_power"] = int(getattr(source, "power", 0) or 0) - 1
    return {**entry, "filter": resolved}
