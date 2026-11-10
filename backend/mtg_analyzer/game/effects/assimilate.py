"""RULE 701.72 Assimilate effects: targeted, from a linked exile pool, from a library, and the linked return."""
from __future__ import annotations

from typing import Any, Optional

from .core import GameContext, GameEffect, _controller_of
from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import Zone
from ..assimilate import assimilate, assimilated_with
from ..targeting import TargetSpec

#: The only pool an untargeted "assimilate a creature card exiled with ~" reads (RULE 607.2a).
POOL_LINKED_EXILE = "linked_exile"
#: Whose libraries `AssimilateFromLibraryEffect` digs through.
SCOPE_TARGET_OPPONENT = "target_opponent"
SCOPE_EACH_OPPONENT = "each_opponent"
#: How the digging player takes cards off the top: revealed (Gift of Perfection) or exiled (The Borg Queen).
DIG_REVEAL = "reveal"
DIG_EXILE = "exile"
#: A target kind that names a battlefield permanent, i.e. a steal (RULE 701.72a) rather than a card in another zone.
_BATTLEFIELD_TARGET_KINDS = ("creature", "creature_you_dont_control", "permanent", "nonland_permanent")


class AssimilateEffect(GameEffect):
    """"Assimilate target nonartifact creature an opponent controls" / "...up to one target creature card from a
    graveyard" / "...a creature card exiled with ~" (+ Borg Cube's "If you can't, exile up to one target creature").

    RULE 701.72a/b: the target (or the chosen linked card) is gained or put onto the battlefield under the
    ability's controller. RULE 701.72c: each assimilated permanent is recorded against the source's resolving visit.
    ``exile_else_target`` is the Borg Cube fallback: with no creature card to assimilate, the pre-announced optional
    creature target is exiled and linked to the source instead (RULE 608.2c's "if you can't").
    """

    def __init__(
        self,
        source: Optional[Any] = None,
        target_kind: Optional[str] = None,
        creature_filter: Optional[dict] = None,
        optional: bool = False,
        per_player: Optional[str] = None,
        pool: Optional[str] = None,
        exile_else_target: bool = False,
    ) -> None:
        super().__init__(source)
        self.target_kind = target_kind
        self.pool = pool
        self.exile_else_target = bool(exile_else_target)
        if self.exile_else_target:
            self.target_spec = TargetSpec(kind="creature", optional=True)
        elif target_kind is not None:
            self.target_spec = TargetSpec(
                kind=target_kind, optional=optional, per_player=per_player, creature_filter=creature_filter)

    def target_polarity(self) -> Optional[str]:
        if self.exile_else_target or self.target_kind in _BATTLEFIELD_TARGET_KINDS:
            return "harmful"
        return None

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        incarnation = context.resolving_source_incarnation
        if self.pool == POOL_LINKED_EXILE:
            from ..linked_exile import linked_cards

            candidates = [o for o in linked_cards(context.state, self.source, incarnation) if o.card.is_creature]
            if candidates:
                # RULE 701.72: "a creature card exiled with it" is the controller's pick; one candidate is forced.
                context.choose_objects(controller, candidates, "assimilate", count=1, source=self.source)
                return
            if self.exile_else_target:
                for victim in targets or []:
                    context.exile(victim)
                    if self.source is not None:
                        context.state.track_exiled_with(self.source, victim, incarnation)
            return
        for target in targets or []:
            if getattr(target, "instance_id", None) is not None:
                assimilate(context.engine, controller.id, target, self.source, incarnation)


class AssimilateFromLibraryEffect(GameEffect):
    """"Each opponent reveals cards from the top of their library until they reveal a creature card. Assimilate one
    of the creature cards revealed this way. Then each opponent puts the other cards they revealed this way on the
    bottom of their library in a random order." (Gift of Perfection) and "Target opponent exiles cards from the top
    of their library until they exile a creature card. Assimilate that card. They put the rest on the bottom in a
    random order." (The Borg Queen).

    RULE 701.20 / 406.1: each victim walks their own library from the top; RULE 701.72b: the controller assimilates
    the creature card (their pick when several opponents each found one). Cards revealed or exiled that are not the
    assimilated one go to the bottom of their owner's library in a random order.
    """

    def __init__(self, source: Optional[Any] = None, scope: str = SCOPE_EACH_OPPONENT, dig: str = DIG_REVEAL) -> None:
        super().__init__(source)
        self.scope = scope
        self.dig = dig
        if scope == SCOPE_TARGET_OPPONENT:
            self.target_spec = TargetSpec(kind="opponent")

    def target_polarity(self) -> Optional[str]:
        return "harmful" if self.scope == SCOPE_TARGET_OPPONENT else None

    def _victims(self, context: GameContext, controller: Any, targets: Optional[list[Any]]) -> list[Any]:
        if self.scope == SCOPE_TARGET_OPPONENT:
            return [t for t in (targets or []) if getattr(t, "id", None) is not None and t.id != controller.id]
        return [p for p in context.state.players if p.id != controller.id and not p.has_lost]

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        controller = _controller_of(self.source, context)
        if controller is None:
            return
        engine = context.engine
        hits: list[Any] = []
        walked: list[tuple[Any, list[Any]]] = []
        for victim in self._victims(context, controller, targets):
            dug: list[Any] = []
            for obj in reversed(list(victim.library)):  # the top of the library is the end of the list
                dug.append(obj)
                if self.dig == DIG_EXILE:
                    context.exile(obj)
                else:
                    context.state.fire_event(GameEvent(
                        EventType.REVEAL, player_id=victim.id, object=obj.name,
                        instance_id=obj.instance_id, from_zone="library"))
                if obj.card.is_creature:
                    hits.append(obj)
                    break
            walked.append((victim, dug))
        incarnation = context.resolving_source_incarnation
        hit_ids = {o.instance_id for o in hits}
        # Put the cards that were not creature hits on the bottom now; the hits stay where they are until chosen.
        for victim, dug in walked:
            rest = [o.instance_id for o in dug if o.instance_id not in hit_ids]
            if rest:
                engine._handle_rest_inspected(victim, rest, "library_bottom_random")
        if len(hits) == 1:
            assimilate(engine, controller.id, hits[0], self.source, incarnation)
        elif hits:
            # RULE 701.72b: several opponents each found a creature card; the controller assimilates one of them
            # and the others go to the bottom of their owners' libraries once the pick is made.
            engine._request_choose_objects(
                controller, hits, "assimilate", count=1, source=self.source,
                rest_ids=[o.instance_id for o in hits], rest_destination="library_bottom_random")


class ReturnAssimilatedEffect(GameEffect):
    """"Exile the Borg assimilated with this Saga, then return it to the battlefield under its owner's control."
    (The Best of Both Worlds III) -- RULE 701.72c's linked reader: only permanents this visit of the source
    assimilated that are still the same battlefield visit. RULE 400.7: the return is a new object, so it loses the
    Borg type change and the counter and is under its owner's control (RULE 110.2).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        pool = assimilated_with(context.state, self.source, context.resolving_source_incarnation)
        for obj in pool:
            if obj.zone == Zone.BATTLEFIELD:
                context.engine.blink(obj)


EFFECT_FACTORIES = {
    "assimilate": lambda p: AssimilateEffect(
        target_kind=p.get("target_kind"), creature_filter=p.get("creature_filter"),
        optional=bool(p.get("optional", False)), per_player=p.get("per_player"), pool=p.get("pool"),
        exile_else_target=bool(p.get("exile_else_target", False)),
    ),
    "assimilate_from_library": lambda p: AssimilateFromLibraryEffect(
        scope=str(p.get("scope", SCOPE_EACH_OPPONENT)), dig=str(p.get("dig", DIG_REVEAL)),
    ),
    "exile_return_assimilated": lambda p: ReturnAssimilatedEffect(),
}
