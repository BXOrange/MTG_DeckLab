"""Live, whitelisted conditions gating a conditional cast/activation timing
permission — RULE 702.8b's "you may cast this spell as though it had flash
if <condition>" and RULE 606.3's "you may activate this permanent's loyalty
abilities any time you could cast an instant if <condition>" (The Wandering
Emperor-shaped). Bound onto ``obj.conditional_flash`` by
`game/effect_binder.py`'s `attach_to_object` from `AbilitySpec.
conditional_flash` (`parser/oracle/spec.py`'s ``ALLOWED_CAST_CONDITION_KEYS``
whitelist — a deliberately separate one from `EffectSpec.condition`'s, which
gates whether an already-resolving *effect* applies rather than a cast/
activation *legality* check).

Checked live off the object each time (never cached), unlike
`obj.granted_keywords` (layer-6, battlefield-only) — this has to work for a
hand-zone spell too, and a turn-scoped condition changes every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..models.game_object import GameObject
    from ..models.game_state import GameState


def conditional_flash_holds(
    condition: dict[str, Any],
    obj: "GameObject",
    state: "GameState",
    targets: Optional[list[Any]] = None,
) -> bool:
    """Whether ``obj``'s `conditional_flash` condition holds right now.

    Fails closed on an unrecognized key (defensive — `AbilitySpec.validate`
    already rejects one at bind time).

    ``"targets_a_commander"`` (Timely Ward-shaped, MEC-7) is the one key
    that depends on a choice — RULE 601.2c targets aren't picked until
    *after* the timing-permission check `GameEngine.can_cast` makes this
    call for, so ``targets`` is optional: ``None`` (the offer-time call,
    before the player has chosen anything) answers optimistically — legal to
    *offer* the flash-speed cast whenever a commander is anywhere in play or
    a command zone, since a legal target isn't known yet — while the real
    cast (`_cast_current_face`, which already has the chosen ``targets`` in
    hand) checks the actual choice and enforces it for real. A caster who
    announces flash-speed and then doesn't actually pick a commander target
    has this same call reject the cast at that final checkpoint, matching
    RULE 601.2i's "the game returns to the moment before the illegal cast".
    """
    for key, value in condition.items():
        if key == "entered_this_turn":
            if bool(value) != (obj.turn_entered == state.turn_number):
                return False
        elif key == "targets_a_commander":
            if targets is None:
                has_commander = any(getattr(p, "is_commander", False) for p in state.battlefield) or any(
                    getattr(c, "is_commander", False) for player in state.players for c in player.command
                )
            else:
                has_commander = any(getattr(t, "is_commander", False) for t in targets)
            if bool(value) != has_commander:
                return False
        else:
            return False
    return True


def free_cast_condition_holds(condition: dict[str, Any], obj: "GameObject", state: "GameState") -> bool:
    """Whether ``obj``'s `free_cast_condition` (RULE 601.2f-adjacent
    condition-gated free-cast alternative cost) holds right now — checked
    live off the board, mirroring `conditional_flash_holds`.

    ``"control_commander"``: whether ``obj``'s controller currently controls
    any commander (RULE 903.4 — a `GameObject.is_commander` permanent/card
    in their command zone or on the battlefield). Fails closed on an
    unrecognized key.
    """
    controller_id = getattr(obj, "controller_id", None)
    for key, value in condition.items():
        if key == "control_commander":
            player = None
            for p in getattr(state, "players", []):
                if p.id == controller_id:
                    player = p
                    break
            has_commander = False
            if player is not None:
                has_commander = any(getattr(c, "is_commander", False) for c in player.command)
            if not has_commander:
                has_commander = any(
                    getattr(o, "is_commander", False) and o.controller_id == controller_id
                    for o in state.battlefield
                )
            if bool(value) != has_commander:
                return False
        else:
            return False
    return True
