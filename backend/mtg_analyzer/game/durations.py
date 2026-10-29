"""RULE 611 continuous effects with a **duration** — the time-bound half of
"as long as", and the sweep that ends them.

`game/static_conditions.py` answers "while *what* is true"; this module
answers "until *when*". Together they cover every way a card bounds a
continuous effect: a fixed window ("until end of turn", "until your next
turn", "until end of combat"), or a live condition ("for as long as you
control ~"), which RULE 611.2b treats as a duration in its own right — the
effect *ends*, permanently, the moment the condition stops holding, rather
than merely lying dormant the way an ``active_if`` gate does.

That distinction is the whole reason both exist:

* ``active_if`` (`static_conditions`) is re-checked every recompute and can
  turn back **on** — "as long as ~ is untapped" applies again when it untaps.
* a ``for_as_long_as`` duration is checked the same way but, once false,
  *removes* the effect — "for as long as ~ remains tapped" is gone for good
  once it untaps, even if it taps again later.

Where a duration lives
----------------------
On the `StaticAbility` itself (``duration``/``duration_data``), and the
ability sits in `GameState.floating_statics`. The existing per-object
``temp_power``/``temp_keywords``/``temp_protections`` fields are *not*
migrated onto this: they express exactly one duration ("until end of turn",
swept by `GameEngine._step_cleanup` per RULE 514.2), they are the path every
shipped pump/grant already uses, and rewriting them would be a large,
behaviour-neutral change. New work that needs any *other* duration goes
through here instead — which is also the only way to get one, since a
``temp_*`` field has nowhere to record when it should end.

Timed copies use `GameObject._duration_copy_layers` instead of a floating
static: `sweep` expires their snapshot layers in the same windows, preserving
newer copies when an older layer ends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from . import static_conditions

if TYPE_CHECKING:
    from ..models.game.game_state import GameState


#: Every duration a floating static may carry.
#:
#: ``end_of_turn``      — RULE 514.2, the cleanup step of the current turn.
#: ``end_of_combat``    — RULE 511.3, when the combat phase ends.
#: ``your_next_turn``   — RULE 611.2b "until your next turn": ends as the
#:                        *creating player's* next turn begins, which is why
#:                        it can't be a ``temp_*`` field (those are cleared at
#:                        the cleanup of the turn they were made in).
#: ``end_of_your_next_turn`` — RULE 611.2 "until the end of your next turn":
#:                        lasts through the *cleanup step of the creating
#:                        player's next turn* (not the turn it was made in,
#:                        even when that is their own); the creating turn's
#:                        number is stamped in ``duration_data["turn"]``.
#: ``next_end_step``    — "until the beginning of the next end step".
#: ``for_as_long_as``   — RULE 611.2b's condition-bounded form; the condition
#:                        itself is a `static_conditions` dict in
#:                        ``duration_data["condition"]``.
#: ``until_source_cast_from_exile`` — RULE 611.2a, ended by casting the exact
#:                        exile visit captured when the source paid its cost.
#: ``rest_of_game``     — never swept (Teferi's Protection-shaped permanence,
#:                        and what an omitted duration means).
DURATIONS: frozenset[str] = frozenset(
    {
        "end_of_turn",
        "end_of_combat",
        "your_next_turn",
        "end_of_your_next_turn",
        "next_end_step",
        "your_next_upkeep",
        "your_next_end_step",
        "for_as_long_as",
        "until_source_cast_from_exile",
        "rest_of_game",
    }
)


def owners_next_turn_has_ended(
    state: "GameState", owner_id: Optional[str], since_turn: Optional[int],
) -> bool:
    """Whether ``owner_id``'s next turn after ``since_turn`` has reached its cleanup step.

    The single predicate behind every "until the end of your next turn"
    (RULE 611.2 / 514.2): the sweep is evaluated at a cleanup step, so it ends
    once the *active* player is the owner and the running turn is a later one
    than the turn the effect was created in (``internal_turn.number`` counts
    every player's turn and extra turns, RULE 500.1/500.7). A skipped owner
    turn never reaches a cleanup, so the effect simply waits for the owner's
    next turn that is actually played. An owner who has left the game has no
    next turn, so their effect ends (RULE 800.4a ends the effects they
    controlled). Consumed by floating statics, impulse play permissions and
    temporary control changes alike -- no second expiry clock.
    """
    if owner_id is None or since_turn is None:
        return False
    try:
        owner = state.player_by_id(owner_id)
    except (KeyError, ValueError):
        owner = None
    if owner is None or getattr(owner, "has_lost", False):
        return True
    active = getattr(state, "active_player", None)
    return (
        active is not None and active.id == owner_id
        and state.internal_turn.number > since_turn
    )


def _affected_object(ability: Any, state: "GameState") -> Any:
    """The single permanent a floating static is aimed at, or ``None``.

    Only a condition with ``of="affected"`` needs it — "…doesn't untap for as
    long as it has a paralyzation counter on **it**", where "it" is the
    *locked* permanent and not the source that locked it. `StaticAbility.
    object_ids` is where a resolution-time referent lives (it can't be in
    ``params``, which is card-text-derived); a multi-object static has no
    single referent, so it yields ``None`` and the condition fails closed.
    """
    object_ids = list(getattr(ability, "object_ids", None) or [])
    if len(object_ids) != 1:
        return None
    for obj in state.permanents():
        if getattr(obj, "instance_id", None) == object_ids[0]:
            visits = (getattr(ability, "params", None) or {}).get("object_incarnations", {})
            visit = visits.get(obj.instance_id, visits.get(str(obj.instance_id)))
            return obj if visit is None or obj.zone_incarnation == visit else None
    return None


def is_expired(ability: Any, state: "GameState", window: str) -> bool:
    """Whether ``ability`` ends at ``window`` (or has already ended).

    ``window`` is the sweep point being run: ``"cleanup"`` (RULE 514.2),
    ``"end_of_combat"`` (511.3), ``"turn_begin"`` (the active player's turn
    starting), ``"end_step"``, or ``"recompute"`` (every layer pass — the
    only window a condition-bounded duration can be noticed at).

    Fails *closed the safe way* for an unknown duration: it is treated as
    ``rest_of_game`` and never swept, so a mis-parsed duration leaves a
    lingering effect rather than silently deleting a legitimate one — the
    error is visible on the board instead of invisible.
    """
    duration = getattr(ability, "duration", None)
    if duration in (None, "rest_of_game") or duration not in DURATIONS:
        return False

    data = getattr(ability, "duration_data", None) or {}
    if data.get("affected_incarnation") is not None:
        affected = _affected_object(ability, state)
        if affected is None or affected.zone_incarnation != data["affected_incarnation"]:
            return True
    if duration == "for_as_long_as":
        # Checked at *every* window including the recompute pass: this is a
        # board condition, so it can stop holding at any moment, not only at
        # a step boundary.
        data = getattr(ability, "duration_data", None) or {}
        source = getattr(ability, "source", None)
        # RULE 400.7 / 611.2b: a source-bound clock follows one visit.
        if data.get("source_incarnation") is not None and (
            source is None or source.zone_incarnation != data["source_incarnation"]
            or source not in state.permanents()
        ):
            return True
        if (data.get("attachment_generation") is not None and
                getattr(source, "attachment_generation", None) != data["attachment_generation"]):
            return True
        return not static_conditions.condition_holds(
            data.get("condition"),
            state,
            getattr(ability, "source", None),
            data.get("player_id") or getattr(getattr(ability, "source", None), "controller_id", None),
            affected=_affected_object(ability, state),
        )

    if window == "cleanup":
        if duration == "end_of_your_next_turn":
            data = getattr(ability, "duration_data", None) or {}
            owner = data.get("player_id") or getattr(
                getattr(ability, "source", None), "controller_id", None
            )
            return owners_next_turn_has_ended(state, owner, data.get("turn"))
        return duration == "end_of_turn"
    if window == "end_of_combat":
        # "Until end of turn" outlives combat; only the combat-scoped one ends.
        return duration == "end_of_combat"
    if (window, duration) in (("upkeep", "your_next_upkeep"), ("end_step", "your_next_end_step")):
        data = getattr(ability, "duration_data", None) or {}
        active = getattr(state, "active_player", None)
        return active is not None and active.id == data.get("player_id")
    if window == "end_step":
        return duration == "next_end_step"
    if window == "turn_begin":
        # "Until your next turn" ends as that player's turn begins — the
        # caller passes the turn's active player as ``duration_data`` owner.
        if duration != "your_next_turn":
            return False
        active = getattr(state, "active_player", None)
        data = getattr(ability, "duration_data", None) or {}
        owner = data.get("player_id") or getattr(
            getattr(ability, "source", None), "controller_id", None
        )
        return active is not None and owner is not None and active.id == owner
    return False


def sweep(state: "GameState", window: str) -> bool:
    """Drop every floating static whose duration ends at ``window``.

    Returns whether anything was removed, so the caller can decide to
    recompute (an ended continuous effect changes derived characteristics,
    and RULE 704 wants a state-based-action check right after).
    """
    from .copy_mechanics import expire_copies

    copies_ended = expire_copies(state, window)
    from types import SimpleNamespace
    from .control import end_control_effects
    for obj in state.battlefield:
        if end_control_effects(obj, lambda record: record["duration"] == "clock"
            and is_expired(SimpleNamespace(**record["window"], source=state.find_object(record["window"].get("source_id"))), state, window)):
            copies_ended = True
    for obj in state.battlefield:
        kept = [e for e in obj.replacement_effects if not is_expired(e, state, window)]
        if len(kept) != len(obj.replacement_effects):
            obj.replacement_effects = kept
            copies_ended = True
    for player in state.players:
        kept_effects = [e for e in player.player_effects if not is_expired(e, state, window)]
        if len(kept_effects) != len(player.player_effects):
            player.player_effects = kept_effects
            copies_ended = True
    for iid, clock in list(state.temp_play_permission_clocks.items()):
        if play_clock_expired(state, state.find_object(iid), clock, window):
            state.temp_play_permission_clocks.pop(iid, None)
            state.temp_play_permissions.pop(iid, None)
            copies_ended = True
    floating = getattr(state, "floating_statics", None)
    if not floating:
        return copies_ended
    kept = [ab for ab in floating if not is_expired(ab, state, window)]
    if len(kept) == len(floating):
        return copies_ended
    state.floating_statics = kept
    return True


def active_statics(state: "GameState") -> list[Any]:
    """The floating statics that currently apply, for `continuous.recompute`.

    This **removes** a ``for_as_long_as`` whose condition has stopped holding
    rather than merely skipping it, and that is the load-bearing detail: RULE
    611.2b's condition-bounded duration *ends* the effect, so it must not come
    back if the condition becomes true again later. Skipping it would silently
    turn every such duration into an `static_conditions` ``active_if`` gate —
    which is the opposite semantic, and the two are otherwise indistinguishable
    from the outside.

    The recompute pass is the right place to notice it: a board condition can
    stop holding at any moment, not only at a step boundary, and this function
    is called on every pass.
    """
    sweep(state, "recompute")
    return list(getattr(state, "floating_statics", None) or [])


def describe(ability: Any) -> str:
    """A terse German label for the board's static-effect panel, or ``""``
    for a static with no duration at all (the standing, permanent case —
    which is most of them, so it must not add noise to the list).

    Mirrors `static_conditions.describe`'s register: a few words naming when
    the effect ends, not a sentence. ``for_as_long_as`` prints its condition
    through that same function, since "bis ~ ungetappt ist" is the useful
    half — naming the duration kind alone would say nothing.
    """
    duration = getattr(ability, "duration", None)
    if duration in (None, "rest_of_game") or duration not in DURATIONS:
        return ""
    if duration == "for_as_long_as":
        data = getattr(ability, "duration_data", None) or {}
        inner = static_conditions.describe(data.get("condition"))
        return f"bis {inner}" if inner else "bedingt befristet"
    return {
        "until_source_cast_from_exile": "bis die exilierte Karte gewirkt wird",
        "end_of_turn": "bis Zugende",
        "end_of_combat": "bis Kampfende",
        "your_next_turn": "bis zu deinem nächsten Zug",
        "end_of_your_next_turn": "bis zum Ende deines nächsten Zuges",
        "next_end_step": "bis zum nächsten Endsegment",
        "your_next_upkeep": "bis zu deinem nächsten Versorgungssegment",
        "your_next_end_step": "bis zu deinem nächsten Endsegment",
    }[duration]


def normalize_duration(duration: Optional[str]) -> str:
    """A parsed duration string → a whitelisted one (``rest_of_game`` if not).

    Fail-closed in the same direction as `is_expired`: an unrecognized
    duration becomes the permanent one rather than being dropped to
    "immediately expired", which would make the effect silently do nothing.
    """
    return duration if duration in DURATIONS else "rest_of_game"


def end_on_exile_cast(state, source_id, exile_incarnation):
    """RULE 611.2a: casting ends this exact exile visit's grant, after costs.

    An unrelated exit leaves the grant intact forever (RULE 400.7); casting
    a later exile incarnation of the same physical card cannot end it.
    """
    state.floating_statics = [ability for ability in state.floating_statics if not (
        ability.duration == "until_source_cast_from_exile"
        and ability.duration_data.get("source_id") == source_id
        and ability.duration_data.get("source_exile_incarnation") == exile_incarnation
    )]


def arm_play_clock(context, obj, duration, condition=None, source=None):
    """Attach an exact lifetime to the ordinary zone-visit play permission."""
    from types import SimpleNamespace
    clock = stamp(SimpleNamespace(), context, source, duration, condition)
    context.state.temp_play_permission_clocks[obj.instance_id] = {
        "duration": clock.duration, "duration_data": clock.duration_data,
        "source_id": getattr(source, "instance_id", None), "visit": obj.zone_incarnation,
    }
    context.state.temp_play_permission_standing.add(obj.instance_id)
    context.state.temp_play_permission_same_turn_only.discard(obj.instance_id)


def play_clock_expired(state, obj, clock, window="recompute"):
    from types import SimpleNamespace
    if obj is None or obj.zone_incarnation != clock["visit"]:
        return True
    return is_expired(SimpleNamespace(duration=clock["duration"], duration_data=clock["duration_data"],
        source=state.find_object(clock.get("source_id")), object_ids=[obj.instance_id]), state, window)


def stamp(effect, context, source, duration, condition=None, affected=None):
    """RULE 611.2: capture the controller, source visit and affected visit once."""
    from .effects.core import _controller_of
    controller = _controller_of(source, context)
    effect.source, effect.duration = source, duration
    effect.duration_data = {"player_id": controller.id if controller else None,
                            "turn": context.state.internal_turn.number}
    effect.object_ids = [affected.instance_id] if affected is not None else []
    if condition:
        effect.duration = "for_as_long_as"
        effect.duration_data["condition"] = dict(condition)
        if condition.get("kind") == "source_attached_to_affected":
            effect.duration_data["attachment_generation"] = condition.get("attachment_generation",
                (context.trigger_event or {}).get("attachment_generation", getattr(source, "attachment_generation", None)))
        if condition.get("kind") == "captured_player_is_monarch":
            from .targeting import trigger_player_antecedent
            effect.duration_data["condition"]["player_id"] = trigger_player_antecedent(context.state, context.trigger_event)
        def uses_source(cond):
            if cond.get("kind") in ("all", "any"):
                return any(uses_source(c) for c in cond.get("conditions", []))
            return cond.get("kind", "").startswith("source_") and cond.get("of", "source") == "source"
        if uses_source(condition):
            effect.duration_data["source_incarnation"] = (context.resolving_source_incarnation
                if context.resolving_source_incarnation is not None else getattr(source, "zone_incarnation", None))
    if affected is not None:
        effect.duration_data["affected_incarnation"] = affected.zone_incarnation
    return effect


def apply_timed_prevention(effect, context, targets):
    """Keep the existing prevention construction, replacing only its clock."""
    if effect.duration is None:
        return False
    from copy import copy
    def shields():
        return [e for p in context.state.players for e in p.player_effects] + [
            e for o in context.state.battlefield for e in o.replacement_effects]
    before = {id(e) for e in shields()}
    plain = copy(effect)
    plain.duration = None
    plain.apply(context, targets)
    for shield in shields():
        if id(shield) not in before:
            affected = context.state.find_object(getattr(shield, "duration_subject_id", None))
            stamp(shield, context, effect.source, effect.duration, effect.duration_condition, affected)
            shield.damage_prevention_shield = False
    sweep(context.state, "recompute")
    return True
