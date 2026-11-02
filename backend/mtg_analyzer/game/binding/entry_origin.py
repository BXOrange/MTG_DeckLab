"""Trigger predicates on *how* an entering object arrived (the zone its spell was cast from).

`ENTERS_BATTLEFIELD` carries ``cast_from_zone`` (RULE 601.2a: the zone the spell was cast from; ``None`` when the
object was put onto the battlefield rather than cast). "If you didn't cast it from your hand" (Chainer,
Nightmare Adept) is the negated reading: true for a creature cast from a graveyard or exile, and for one that
was never cast at all.
"""

from __future__ import annotations

from typing import Any, Callable

TriggerPredicate = Callable[[Any, Any], bool]


def entry_origin_predicates(trigger: dict[str, Any]) -> list[TriggerPredicate]:
    """The predicates a trigger dict's entry-origin keys (``not_cast_from_zone``) ask for."""
    predicates: list[TriggerPredicate] = []
    excluded_zone = trigger.get("not_cast_from_zone")
    if excluded_zone:
        def _not_cast_from_zone_ok(event: Any, context: Any, zone: str = str(excluded_zone)) -> bool:
            return event.get("cast_from_zone") != zone

        predicates.append(_not_cast_from_zone_ok)
    return predicates
