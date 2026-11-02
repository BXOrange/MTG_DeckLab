"""Who an attacking creature is attacking, relative to a reference permanent's controller.

RULE 506.2: the defending player is the one being attacked, or the controller of the planeswalker (or the
protector of the battle) being attacked. "Creatures attacking your opponents" (Blast-Furnace Hellkite) therefore
asks whether that defending player is an opponent of the reference permanent's controller (RULE 102.2 / 102.3),
whoever controls the attacking creature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState

#: `GameObject.combat_defender["kind"]` values that name a permanent rather than a player.
_PERMANENT_DEFENDER_KINDS = ("planeswalker", "battle")


def defending_player_id(obj: "GameObject", state: Optional["GameState"]) -> Optional[str]:
    """The id of the player ``obj`` is attacking (RULE 506.2), or ``None`` if it is not attacking."""
    if not getattr(obj, "attacking", False):
        return None
    defender: dict[str, Any] = getattr(obj, "combat_defender", None) or {}
    if defender.get("kind") == "player":
        return defender.get("id")
    if defender.get("kind") in _PERMANENT_DEFENDER_KINDS and state is not None:
        attacked = state.find_object(defender.get("instance_id"))
        if attacked is None:
            return None
        # RULE 310.8d: a battle's defending player is its protector, not its controller.
        return attacked.protector_id if attacked.is_battle else attacked.controller_id
    return None


def attacks_opponent_of(obj: "GameObject", reference: Optional["GameObject"], state: Optional["GameState"]) -> bool:
    """Whether ``obj`` is attacking a player (or that player's planeswalker/battle) who is an opponent of
    ``reference``'s controller."""
    if reference is None or reference.controller_id is None:
        return False
    defender_id = defending_player_id(obj, state)
    return defender_id is not None and defender_id != reference.controller_id
