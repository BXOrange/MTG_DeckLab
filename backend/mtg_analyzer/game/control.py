"""Resolved control effects, retained independently of the object's owner.

RULE 800.4a/611.2: ending one recipient's effects must expose the previous
surviving effect, or the original controller (which need not be the owner).
Standing layer-2 abilities remain in continuous.py.
"""
from __future__ import annotations


def gain_control(state, obj, controller_id, *, duration="permanent", window=None):
    """Record a represented control effect, including its expiration window."""
    recipient = state.player_by_id(controller_id)
    if recipient.has_lost:  # RULE 800.4b
        return False
    if getattr(obj, "control_origin", None) is None:
        obj.control_origin = getattr(obj, "_control_base", None) or obj.controller_id
    records = getattr(obj, "control_effects", None)
    if records is None:
        obj.control_effects = records = []
    records.append({"controller_id": controller_id, "duration": duration, "window": window,
                    "timestamp": state.next_timestamp()})
    changed = obj.controller_id != controller_id
    obj.controller_id = controller_id
    if hasattr(obj, "_control_base"):
        obj._control_base = None
    if changed and hasattr(obj, "summoning_sick"):
        obj.summoning_sick = True  # RULE 302.6
    return True


def end_control_effects(obj, predicate):
    """End matching effects without resurrecting an older, ended effect."""
    records = getattr(obj, "control_effects", [])
    remaining = [record for record in records if not predicate(record)]
    if len(records) == len(remaining):
        return False
    obj.control_effects = remaining
    if hasattr(obj, "control_change_until_eot"):
        obj.control_change_until_eot = (obj.control_origin
                                       if any(record["duration"] == "end_of_turn" for record in remaining) else None)
        for duration, attribute in (("end_of_your_next_turn", "control_change_until_owner_turn"),
                                    ("while_source", "control_change_while_source")):
            windows = [record["window"] for record in remaining if record["duration"] == duration]
            setattr(obj, attribute, windows[-1] if windows else None)
    controller = remaining[-1]["controller_id"] if remaining else obj.control_origin
    if obj.controller_id != controller and hasattr(obj, "summoning_sick"):
        obj.summoning_sick = True
    obj.controller_id = controller
    if hasattr(obj, "_control_base"):
        obj._control_base = None
    return True


def exchange_control(state, first, second):
    """RULE 701.12b: both recipients are captured before either change."""
    first_controller, second_controller = first.controller_id, second.controller_id
    if state.player_by_id(first_controller).has_lost or state.player_by_id(second_controller).has_lost:
        return False
    gain_control(state, first, second_controller)
    gain_control(state, second, first_controller)
    return True


def control_window_active(state, obj, window):
    """RULE 611.2b / 400.7: source visit and target condition must still hold."""
    from ..models.game.game_object import Zone
    source = state.find_object(window["source_id"])
    if (source is None or source.zone != Zone.BATTLEFIELD
            or source.zone_incarnation != window["incarnation"]
            or (window["needs_control"] and source.controller_id != window["player_id"])
            or (window.get("needs_tapped") and not source.tapped)
            or state.player_by_id(window["player_id"]).has_lost):
        return False
    if window.get("needs_haunted"):
        from .effects.haunted import is_haunted
        if not is_haunted(state, obj):
            return False
    if window.get("target_filter"):
        from .combat import matches_object_filter
        if not matches_object_filter(obj, window["target_filter"], reference=source, state=state):
            return False
    return True
