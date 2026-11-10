"""'Copy that card X times ... You may cast the copies without paying their mana costs.' (Infinite Diversity).

`CopyImprintedCardEffect`'s ``from_previous`` mode makes one copy; this is its counted sibling. X copies of the card an
earlier clause of this resolution exiled (RULE 707.12) are created in exile and offered together as one repeated
resolution-time cast window (RULE 608.2g), so the controller may cast any number of them, one after another. A copy
nobody casts ceases to exist at the next state-based action pass once the window closes (RULE 707.10a / 704.5e,
`_sba_collect_stranded_tokens`).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .core import EffectRegistry, GameContext, GameEffect, _controller_of

#: The measured copy count is clamped so a runaway amount cannot allocate unbounded objects in one resolution.
MAX_COPIES = 50


if TYPE_CHECKING:  # pragma: no cover - typing only
    from ...models.game.game_object import GameObject


class CopyExiledCardXTimesEffect(GameEffect):
    def __init__(self, count: Any = 1, free: bool = True, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count
        self.free = bool(free)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_object import GameObject, Zone  # function-scoped: import boundary
        from ..binding.core import bind_from_catalogue

        player = _controller_of(self.source, context)
        exiled = next((obj for obj in context.previous_targets if obj is not None and obj.zone == Zone.EXILE), None)
        if player is None or exiled is None:
            return
        copies_wanted = max(0, min(int(self._measured(self.count, context, targets) or 0), MAX_COPIES))
        copies: list["GameObject"] = []
        for _ in range(copies_wanted):
            copy_obj = GameObject(exiled.card.as_copy(), owner_id=player.id, zone=Zone.EXILE)
            copy_obj.is_copy = True
            bind_from_catalogue(copy_obj)
            player.add_to_zone(copy_obj, Zone.EXILE)
            copies.append(copy_obj)
        if copies:
            context.engine._request_resolution_play(
                player, copies, free=self.free, only_spells=True, repeat=True,
            )


EffectRegistry.register(
    "copy_exiled_card_x_times", lambda p: CopyExiledCardXTimesEffect(count=p.get("count", 1), free=bool(p.get("free", True))),
)
