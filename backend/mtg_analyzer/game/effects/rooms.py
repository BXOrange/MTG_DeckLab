"""Room door effects (RULE 709.5f/709.5g, MEC-111)."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register

install(globals())


class UnlockDoorEffect(GameEffect):
    """"Unlock a locked door of `<a Room you control | target Room you control>`." (RULE 709.5f), or — with
    ``lock_or_unlock`` — "Lock or unlock a door of target Room you control." (RULE 709.5g, Marina Vendrell, Keys to the House).

    ``target_kind`` names the Room as a RULE 115 target (``"room_you_control"``); ``None`` is the untargeted
    "a Room you control" (Ghostly Dancers), chosen on resolution. The door itself is always a choice made on
    resolution — free when only one door qualifies, otherwise the controller's (`RoomsRulesMixin._request_door_choice`).
    """

    def __init__(
        self,
        target_kind: Optional[str] = None,
        optional: bool = False,
        lock_or_unlock: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.lock_or_unlock = bool(lock_or_unlock)
        self.target_spec = TargetSpec(kind=target_kind, optional=optional) if target_kind else None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_object import GameObject  # function-scoped: the effects modules share one namespace

        controller = _controller_of(self.source, context)
        if controller is None:
            return
        if self.target_spec is not None:
            candidates = [t for t in (targets or []) if isinstance(t, GameObject)]
        else:
            candidates = [o for o in context.state.permanents_controlled_by(controller.id)]
        options = context.engine._door_options(candidates, can_lock=self.lock_or_unlock)
        if not options:
            return
        if len(options) == 1:
            context.engine._apply_door_option(*options[0])
            return
        context.engine._request_door_choice(controller, options)


register(globals())
