"""ENG-65 -- RULE 118.9 / 601.2b-h: the caster, not the engine, picks which permanents an alternative cost returns or
sacrifices (Gush's two Islands, Daze's Island, a Borderpost's basic land, "sacrifice three black creatures").

The picks are announced *before* the spell moves (RULE 601.2b: choices are made while the spell is still being
proposed), one question at a time through the continuation primitive (`game/continuations.py`), the same shape the
additional-cost pick in `cast_cost_alternatives.py` uses. A pick is only asked when there is a real choice: a pool no
larger than what is still owed is forced, so it is taken silently -- the convention `_pick_payment_object` already
follows ("more than one candidate or no question").

The finished picks travel back into `cast_spell` as ``alt_cost_choices`` (instance ids in slot order). While the cast
runs they sit on ``obj._alt_cost_picks`` where `GameEngine._pay_alt_cast_cost` reads them (the same transient-attribute
idiom ``_announced_damage_divisions`` uses, instead of threading one more argument through every cast helper).
"""
from __future__ import annotations

from functools import wraps
import inspect
from typing import Any, Optional

from . import combat, continuous
from .continuations import choice
from .costs import RETURN_SELF_TO_HAND, SACRIFICE_ENCHANTED

#: ``ActivationCost.sacrifice``'s "sacrifice this permanent" word (`GameEngine._sacrifice_candidate`).
SACRIFICE_SELF = "self"

#: The cost components that name permanents to move, in the order they are paid (`_pay_alt_cast_cost`).
RETURN = "return_to_hand"
RETURN_COUNT = "return_to_hand_count"
SACRIFICE = "sacrifice"
SACRIFICE_COUNT = "sacrifice_count"
SACRIFICE_FILTER = "sacrifice_filter"
#: ENG-69: the hand cards a pitch / discard cost names and the untapped permanents a tap cost names.
EXILE_HAND = "exile_hand_card_color"
EXILE_HAND_COUNT = "exile_hand_card_color_count"
DISCARD_LAND = "discard_land_type"
TAP_OTHERS = "tap_others"
#: The slot kinds whose candidates are hand cards (everything else is a permanent the caster controls).
_HAND_KINDS = frozenset({EXILE_HAND, EXILE_HAND_COUNT, DISCARD_LAND})

#: ``ActivationCost.sacrifice`` words that name one fixed permanent (RULE 701.17), never a choice among several.
_FIXED_SACRIFICE_WORDS = frozenset({SACRIFICE_SELF, SACRIFICE_ENCHANTED})

#: Transient attribute carrying the announced picks while the cast runs (cleared in a ``finally``).
PICKS_ATTRIBUTE = "_alt_cost_picks"


def alt_cost_slots(cost: Any) -> list[str]:
    """One entry per permanent ``cost`` asks the caster to name, in payment order."""
    slots: list[str] = []
    if cost.return_to_hand and cost.return_to_hand != RETURN_SELF_TO_HAND:
        slots.append(RETURN)
    if cost.return_to_hand_count:
        slots.extend([RETURN_COUNT] * int(cost.return_to_hand_count[0]))
    if cost.sacrifice and cost.sacrifice not in _FIXED_SACRIFICE_WORDS:
        slots.append(SACRIFICE)
    if cost.sacrifice_count and isinstance(cost.sacrifice_count[0], int) and cost.sacrifice_count[0] > 0:
        slots.extend([SACRIFICE_COUNT] * cost.sacrifice_count[0])
    if cost.sacrifice_filter:
        slots.append(SACRIFICE_FILTER)
    if cost.exile_hand_card_color:
        slots.append(EXILE_HAND)
    if cost.exile_hand_card_color_count:
        slots.extend([EXILE_HAND_COUNT] * int(cost.exile_hand_card_color_count[0]))
    if cost.discard_land_type:
        slots.append(DISCARD_LAND)
    # An X-valued tap count (`TAP_OTHERS_X`) is not a fixed number of slots; only fixed counts are announced here.
    if cost.tap_others and isinstance(cost.tap_others[0], int) and cost.tap_others[0] > 0:
        slots.extend([TAP_OTHERS] * cost.tap_others[0])
    return slots


def alt_cost_pool(engine: Any, player: Any, obj: Any, cost: Any, kind: str) -> list[Any]:
    """Every permanent ``player`` could name for one ``kind`` slot of ``cost`` (before earlier picks are removed)."""
    if kind == RETURN:
        return engine._return_to_hand_pool(player, cost.return_to_hand)
    if kind == RETURN_COUNT:
        return engine._return_to_hand_count_pool(player, cost.return_to_hand_count[1])
    if kind == SACRIFICE:
        return [o for o in engine.state.permanents_controlled_by(player.id)
                if engine._sacrifice_candidate(player, obj, cost.sacrifice, chosen_id=o.instance_id) is not None]
    if kind == EXILE_HAND:
        # RULE 601.2a: the spell is already being cast, so it never pays for itself.
        return [c for c in player.hand if c is not obj and cost.exile_hand_card_color in c.colors]
    if kind == EXILE_HAND_COUNT:
        return [c for c in player.hand if c is not obj and cost.exile_hand_card_color_count[1] in c.colors]
    if kind == DISCARD_LAND:
        return [c for c in player.hand
                if c is not obj and c.card.is_land and cost.discard_land_type.strip().capitalize() in c.card.type_line]
    if kind == TAP_OTHERS:
        # RULE 118.3 / 302.6: untapped permanents only; the spell is in hand, never on the battlefield.
        return [o for o in engine._tap_others_pool(player, obj, cost.tap_others[1]) if o is not obj]
    if kind == SACRIFICE_COUNT:
        # RULE 701.17: a permanent that can't be sacrificed can't pay.
        return [o for o in engine._sacrifice_count_pool(player, cost.sacrifice_count[1])
                if not o.cant_be_sacrificed_this_turn]
    return [o for o in engine.state.permanents_controlled_by(player.id)
            if not o.cant_be_sacrificed_this_turn and combat.matches_object_filter(o, cost.sacrifice_filter)]


def announced_alt_cost(engine: Any, player: Any, obj: Any, params: Optional[dict] = None) -> Optional[Any]:
    """The alternative cost this cast would pay (the same lookup the cast body performs): the spell's own or granted
    alternative cost, or -- RULE 702.34a, a Flashback cast from the graveyard -- the non-mana part of its flashback cost
    (`_pay_alt_cast_cost` pays that one too)."""
    params = params or {}
    if params.get("alt_cost"):
        return getattr(obj, "alt_cast_cost", None) or continuous.granted_alt_cast_cost_for(
            engine.state, player, obj.card, obj)
    if obj in player.graveyard and params.get("blitz") is None and engine._graveyard_cast_keyword(obj) == "flashback":
        return engine._flashback_nonmana_cost(obj)
    return None


def _remaining_in_group(slots: list[str], index: int) -> int:
    """How many slots from ``index`` on belong to the same component as ``slots[index]``."""
    return sum(1 for s in slots[index:] if s == slots[index])


def plan_picks(engine: Any, player: Any, obj: Any, cost: Any, picks: list[int]) -> tuple[list[int], Optional[list]]:
    """Extend ``picks`` over the slots whose pool is forced; stop at the first real choice.

    Returns ``(picks, options)``: ``options`` is the pool of the next unforced slot (``None`` when every slot is
    filled). ``options`` is an empty list when a slot cannot be filled at all (the cost is unpayable).
    """
    slots = alt_cost_slots(cost)
    picks = list(picks)
    while len(picks) < len(slots):
        index = len(picks)
        pool = [o for o in alt_cost_pool(engine, player, obj, cost, slots[index]) if o.instance_id not in picks]
        owed = _remaining_in_group(slots, index)
        if len(pool) < owed:
            return picks, []
        if len(pool) > owed:
            return picks, pool
        picks.append(pool[0].instance_id)  # forced: exactly as many candidates as slots still owed
    return picks, None


def validate_picks(engine: Any, player: Any, obj: Any, cost: Any, picks: list[int]) -> bool:
    """Whether ``picks`` fill every slot of ``cost`` with distinct, eligible permanents."""
    slots = alt_cost_slots(cost)
    if len(picks) != len(slots) or len(set(picks)) != len(picks):
        return False
    return all(
        picks[i] in {o.instance_id for o in alt_cost_pool(engine, player, obj, cost, kind)}
        for i, kind in enumerate(slots)
    )


def picked_objects(engine: Any, player: Any, obj: Any, cost: Any, picks: Optional[list[int]]) -> dict[str, list]:
    """The permanents each component pays with. ``picks=None`` is the non-interactive fallback (first eligible)."""
    slots = alt_cost_slots(cost)
    if picks is None:
        picks, options = plan_picks(engine, player, obj, cost, [])
        while options:
            picks.append(options[0].instance_id)
            picks, options = plan_picks(engine, player, obj, cost, picks)
    by_id = {o.instance_id: o for o in engine.state.permanents_controlled_by(player.id)}
    by_id.update({c.instance_id: c for c in player.hand})
    out: dict[str, list] = {kind: [] for kind in (
        RETURN, RETURN_COUNT, SACRIFICE, SACRIFICE_COUNT, SACRIFICE_FILTER,
        EXILE_HAND, EXILE_HAND_COUNT, DISCARD_LAND, TAP_OTHERS)}
    for kind, instance_id in zip(slots, picks):
        if instance_id in by_id:
            out[kind].append(by_id[instance_id])
    return out


_PROMPTS = {
    RETURN: "Permanent für die alternativen Kosten auf die Hand zurückgeben",
    RETURN_COUNT: "Permanent für die alternativen Kosten auf die Hand zurückgeben",
    SACRIFICE: "Permanent für die alternativen Kosten opfern",
    SACRIFICE_COUNT: "Permanent für die alternativen Kosten opfern",
    SACRIFICE_FILTER: "Permanent für die alternativen Kosten opfern",
    EXILE_HAND: "Karte für die alternativen Kosten aus der Hand ins Exil schicken",
    EXILE_HAND_COUNT: "Karte für die alternativen Kosten aus der Hand ins Exil schicken",
    DISCARD_LAND: "Land für die alternativen Kosten abwerfen",
    TAP_OTHERS: "Permanent für die alternativen Kosten tappen",
}


def choose_alt_cost_payment(cast):
    """RULE 601.2b: announce the permanents an alternative cost returns or sacrifices before the spell moves."""
    signature = inspect.signature(cast)

    @wraps(cast)
    def announce(engine, player, obj, *args, **kwargs):
        bound = signature.bind(engine, player, obj, *args, **kwargs)
        bound.apply_defaults()
        params = {k: v for k, v in bound.arguments.items() if k not in {"self", "player", "obj"}}
        if params.get("alt_cost") and (getattr(obj, "parametric_keywords", None) or {}).get("emerge"):
            return cast(engine, player, obj, *args, **kwargs)
        cost = announced_alt_cost(engine, player, obj, params)
        if cost is None or not alt_cost_slots(cost):
            return cast(engine, player, obj, *args, **kwargs)
        picks = params.get("alt_cost_choices")
        if picks is not None:
            if not validate_picks(engine, player, obj, cost, picks):
                raise ValueError("Ungültige Wahl für die alternativen Kosten")
        else:
            if engine.state.pending_choice:
                raise ValueError("Zuerst die offene Entscheidung abschließen")
            if not engine.can_cast(player, obj, assume_mana_available=True, alt_cost=bool(params.get("alt_cost"))):
                return cast(engine, player, obj, *args, **kwargs)  # not castable: the body raises the real reason
            picks, options = plan_picks(engine, player, obj, cost, [])
            if options is not None:
                if options:
                    _open_pick(engine.rules, player, obj, params, picks, options, alt_slot_kind(cost, picks))
                    return None
                return cast(engine, player, obj, *args, **kwargs)  # unpayable: the body raises the real reason
        setattr(obj, PICKS_ATTRIBUTE, picks)
        try:
            return cast(engine, player, obj, *args, **kwargs)
        finally:
            if hasattr(obj, PICKS_ATTRIBUTE):
                delattr(obj, PICKS_ATTRIBUTE)

    return announce


def alt_slot_kind(cost: Any, picks: list[int]) -> str:
    return alt_cost_slots(cost)[len(picks)]


def _open_pick(rules, player, obj, params, picks, options, kind) -> None:
    rules.open_choice({
        "kind": "cast_alt_cost_object", "player_id": player.id,
        "source": obj, "incarnation": obj.zone_incarnation, "kwargs": params, "picks": list(picks),
        "prompt": _PROMPTS[kind],
        "options": [{"id": str(o.instance_id), "label": o.name, "instance_id": o.instance_id} for o in options],
    })


@choice("cast_alt_cost_object", rule="601.2b")
def _resume_cast_alt_cost_object(rules, payload, answer):
    if str(answer) not in {option["id"] for option in payload["options"]}:
        rules.open_choice(payload)  # an answer outside the offered pool re-asks the same question
        return
    obj = payload["source"]
    if obj.zone_incarnation != payload["incarnation"]:
        return
    from .game_engine import GameEngine
    engine = GameEngine(rules.state, rules=rules)
    player = rules.state.player_by_id(payload["player_id"])
    params = dict(payload["kwargs"])
    cost = announced_alt_cost(engine, player, obj, params)
    picks = list(payload["picks"]) + [int(answer)]
    picks, options = plan_picks(engine, player, obj, cost, picks)
    if options:
        _open_pick(rules, player, obj, params, picks, options, alt_slot_kind(cost, picks))
        return
    params["alt_cost_choices"] = picks
    engine.cast_spell(player, obj, **params)
