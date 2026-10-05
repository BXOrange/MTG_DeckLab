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
#: ``next_end_step``    — "until the beginning of the next end step".
#: ``for_as_long_as``   — RULE 611.2b's condition-bounded form; the condition
#:                        itself is a `static_conditions` dict in
#:                        ``duration_data["condition"]``.
#: ``rest_of_game``     — never swept (Teferi's Protection-shaped permanence,
#:                        and what an omitted duration means).
DURATIONS: frozenset[str] = frozenset(
    {
        "end_of_turn",
        "end_of_combat",
        "your_next_turn",
        "next_end_step",
        "for_as_long_as",
        "rest_of_game",
    }
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
            return obj
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

    if duration == "for_as_long_as":
        # Checked at *every* window including the recompute pass: this is a
        # board condition, so it can stop holding at any moment, not only at
        # a step boundary.
        data = getattr(ability, "duration_data", None) or {}
        return not static_conditions.condition_holds(
            data.get("condition"),
            state,
            getattr(ability, "source", None),
            getattr(getattr(ability, "source", None), "controller_id", None),
            affected=_affected_object(ability, state),
        )

    if window == "cleanup":
        return duration == "end_of_turn"
    if window == "end_of_combat":
        # "Until end of turn" outlives combat; only the combat-scoped one ends.
        return duration == "end_of_combat"
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
    floating = getattr(state, "floating_statics", None)
    if not floating:
        return False
    kept = [ab for ab in floating if not is_expired(ab, state, window)]
    if len(kept) == len(floating):
        return False
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
        "end_of_turn": "bis Zugende",
        "end_of_combat": "bis Kampfende",
        "your_next_turn": "bis zu deinem nächsten Zug",
        "next_end_step": "bis zum nächsten Endsegment",
    }[duration]


def normalize_duration(duration: Optional[str]) -> str:
    """A parsed duration string → a whitelisted one (``rest_of_game`` if not).

    Fail-closed in the same direction as `is_expired`: an unrecognized
    duration becomes the permanent one rather than being dropped to
    "immediately expired", which would make the effect silently do nothing.
    """
    return duration if duration in DURATIONS else "rest_of_game"
