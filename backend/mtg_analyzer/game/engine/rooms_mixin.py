"""Rooms: the unlock-cost special action (RULE 709.5e, 116.2m; MEC-111).

A Room's doors, designations and abilities live in `game/rooms.py`; this mixin is the one thing a *player*
does to them, paying the mana cost of a locked half to unlock it. Like Foretell and turning a permanent face
up it is a special action — no stack, nothing to respond to — but with its own timing: any time the player has
priority with an empty stack during a main phase of their turn.
"""

from __future__ import annotations

from typing import Any

from ...models.game.game_object import GameObject, Zone
from ...models.game.player import Player
from .. import rooms
from ..mana_abilities import restriction_predicate_for_unlock


class RoomsMixin:
    def can_unlock_door(self, player: Player, obj: GameObject, door: str, *, assume_mana_available: bool = False) -> bool:
        """RULE 709.5e: may ``player`` pay ``door``'s mana cost to unlock it now?"""
        if obj.zone != Zone.BATTLEFIELD or obj.controller_id != player.id or obj.phased_out:
            return False
        if door not in rooms.locked_doors(obj):
            return False
        if player is not self.state.active_player or not self._in_main_phase() or self.state.stack:
            return False
        if self.interactive_priority and self.state.priority_player is not player:
            return False
        if assume_mana_available:
            return True
        return player.mana_pool.can_pay(
            rooms.door_cost(obj.card, door), life_available=player.life,
            allows_restriction=restriction_predicate_for_unlock(),
        )

    def unlock_door_actions(self, player: Player, obj: GameObject) -> list[dict[str, Any]]:
        """The `legal_actions` entries for unlocking each locked half of ``obj`` — payable from the pool, or
        (``auto_tap``) by tapping plain untapped sources first, like a spell's cost."""
        from .. import mana_potential  # function-scoped: the mana modules import the engine's own helpers

        actions: list[dict[str, Any]] = []
        for door in rooms.locked_doors(obj):
            if not self.can_unlock_door(player, obj, door, assume_mana_available=True):
                continue
            cost = rooms.door_cost(obj.card, door)
            action = {
                "type": "unlock_door", "instance_id": obj.instance_id, "name": obj.name,
                "door": door, "door_name": rooms.door_name(obj.card, door), "cost_label": cost.raw or "{0}",
            }
            if not self.can_unlock_door(player, obj, door):
                if not mana_potential.is_castable_via_potential(
                    self, player, cost, allows_restriction=restriction_predicate_for_unlock(),
                ):
                    continue
                action["auto_tap"] = True
            actions.append(action)
        return actions

    def unlock_door(self, player: Player, obj: GameObject, door: str) -> bool:
        """Take the RULE 709.5e special action: pay ``door``'s mana cost and give ``obj`` the designation."""
        cost = rooms.door_cost(obj.card, door) if rooms.has_doors(obj.card) else None
        if cost is None or not self.can_unlock_door(player, obj, door, assume_mana_available=True):
            raise ValueError(f"{player.id} cannot unlock {door} door of {obj.name} now")
        if not self.can_unlock_door(player, obj, door):
            self.auto_tap_for(player, cost=cost, allows_restriction=restriction_predicate_for_unlock())
        if not self.can_unlock_door(player, obj, door):
            raise ValueError(f"{player.id} cannot pay {cost.raw} to unlock {obj.name}")
        life_spent = player.mana_pool.pay(
            cost, life_available=player.life, allows_restriction=restriction_predicate_for_unlock(),
        )
        self.rules.lose_life(player, life_spent, cause="cost")
        rooms.unlock(self.state, obj, door)
        self.recompute_continuous_effects()
        # RULE 117.3c: taking an action reclaims priority for its taker, as for any other action.
        self.give_priority(player)
        return True
