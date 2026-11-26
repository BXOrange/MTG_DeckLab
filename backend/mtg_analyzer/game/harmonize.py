"""RULE 702.180: announce the optional creature tapped for Harmonize."""
from functools import wraps
from inspect import signature

from . import mana_potential


def pool(engine, player):
    return [obj for obj in engine.state.permanents_controlled_by(player.id) if obj.is_creature and not obj.tapped]


def selection(engine, player, picks):
    available = pool(engine, player)
    if picks is None:
        return max(available, key=lambda obj: obj.power or 0, default=None)
    if len(picks) == 1:
        return next((obj for obj in available if obj.instance_id == picks[0]), None)
    return None


def choose_payment(cast):
    sig = signature(cast)

    @wraps(cast)
    def announce(engine, player, obj, *args, **kwargs):
        params = sig.bind(engine, player, obj, *args, **kwargs).arguments
        if (obj not in player.graveyard or engine._graveyard_cast_keyword(obj) != "harmonize"
                or params.get("tap_choices") is not None):
            return cast(engine, player, obj, *args, **kwargs)
        available = pool(engine, player)
        if not available:
            return cast(engine, player, obj, *args, **kwargs)
        supplied = {k: v for k, v in params.items() if k not in {"self", "player", "obj", "tap_choices"}}
        check_args = {k: v for k, v in supplied.items() if k in signature(engine.can_cast).parameters}
        cost_args = {k: v for k, v in supplied.items() if k in signature(engine.effective_cast_cost).parameters}
        options = []
        for creature in [None, *available]:
            picks = [creature.instance_id] if creature is not None else []
            if not engine.can_cast(player, obj, tap_choices=picks, assume_mana_available=True, **check_args):
                continue
            cost = engine.effective_cast_cost(player, obj, tap_choices=picks, **cost_args)
            if (not engine.can_cast(player, obj, tap_choices=picks, **check_args)
                    and mana_potential.find_tap_plan(engine, player, cost, reserved_ids=picks) is None):
                continue
            options.append({
                "id": str(creature.instance_id) if creature else "none",
                "label": f"{creature.name} · {cost.raw}" if creature else f"Without tapping · {cost.raw}",
                "visit": creature.zone_incarnation if creature else None,
            })
        if not options:
            raise ValueError(f"{obj.name}: Harmonize cannot be paid")
        engine.state.pending_harmonize_cast = supplied
        engine.rules.open_choice({
            "kind": "harmonize_payment", "prompt": "Harmonize",
            "player_id": player.id, "source_id": obj.instance_id, "source_visit": obj.zone_incarnation,
            "options": [*options, {"id": "decline", "label": "Cancel"}],
        })

    return announce
