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

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models.game_object import GameObject
    from ..models.game_state import GameState


def conditional_flash_holds(condition: dict[str, Any], obj: "GameObject", state: "GameState") -> bool:
    """Whether ``obj``'s `conditional_flash` condition holds right now.

    Fails closed on an unrecognized key (defensive — `AbilitySpec.validate`
    already rejects one at bind time).
    """
    for key, value in condition.items():
        if key == "entered_this_turn":
            if bool(value) != (obj.turn_entered == state.turn_number):
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
