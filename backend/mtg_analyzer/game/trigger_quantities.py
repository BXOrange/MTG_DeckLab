"""Quantities scoped to a trigger's own subject, captured when it triggers."""

from __future__ import annotations

from typing import Any


def matching_attackers(event: Any, context: Any, spec: dict, source: Any) -> list:
    """RULE 508.3a: select this head's attackers from the locked declaration."""
    from .combat import matches_object_filter

    state = context.state
    source_id = getattr(source, "instance_id", None)
    ids = event.get("attacker_ids") or []
    if spec.get("includes_source") and source_id not in ids:
        return []
    result = []
    for iid in ids:
        obj = state.find_object(iid)
        if obj is None or (spec.get("other") and iid == source_id):
            continue
        if matches_object_filter(obj, spec.get("filter"), reference=source, state=state):
            result.append(obj)
    return result


def capture_attackers(event: Any, context: Any, spec: dict, source: Any) -> Any:
    """RULE 603.2: keep each ability's count even if attackers later leave or change.

    The event bus payload belongs to all listeners; only this pending trigger gets
    the enriched copy. Neither another listener nor another combat can overwrite it.
    """
    attackers = matching_attackers(event, context, spec, source)
    captured = event.copy_with(matching_attacker_count=len(attackers),
                               matching_attacker_ids=[obj.instance_id for obj in attackers],
                               # "where X is the greatest power among those creatures" (Shriekwood Devourer)
                               matching_attacker_greatest_power=max((obj.power or 0 for obj in attackers), default=0))
    captured.turn = event.turn
    return captured
