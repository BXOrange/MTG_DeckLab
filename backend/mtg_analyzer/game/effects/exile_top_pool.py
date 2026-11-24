"""Exile-from-the-top pools for the Commander Cube singleton batch (Glimpse the Impossible, Ignite the Future,
Improvisation Capstone).

Each card exiles cards from the top of its controller's library and then lets the player use that pool. The
engine already has the two halves: `ImpulsiveDrawEffect` (RULE 601.3b window, `GameContext.created_objects`) and
`CastWindowFromExiledPoolEffect` (PAR-167, reads `GameContext.latest_exiled_visits`). This module adds only what
neither can express: an exile loop that stops on a running mana-value total, a bridge that turns the impulsive
draw's pool into a casting pool, simultaneous entry of its permanent cards, and a RULE 603.7 end-step cleanup
that makes tokens from the leftovers.
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.game_object import Zone
from ...models.cards.card_query import is_permanent_card, matches
from .core import EffectRegistry, GameEffect, GameContext, _controller_of
from .counters_tokens import CreateTokenEffect
from .library import ReturnRemainingExiledEffect

#: Printed text of the Eldrazi Spawn token Glimpse the Impossible makes (its sacrifice mana ability).
_SPAWN_ORACLE = "Sacrifice this token: Add {C}."


class PutLatestExiledOntoBattlefieldEffect(GameEffect):
    """Put qualifying permanent cards from this resolution's latest exile pool into play together."""

    def __init__(self, card_filter: Any = None, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.card_filter = card_filter

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .battlefield_batches import start_exile_return_batch

        controller = _controller_of(self.source, context)
        if controller is None:
            return
        # RULE 400.7 / 608.2c: only this instruction's exact exile visits,
        # never an earlier activation's leftovers or a card exiled again.
        visits = [(obj.instance_id, visit) for obj, visit in context.latest_exiled_visits
                  if obj.zone == Zone.EXILE and obj.zone_incarnation == visit
                  and is_permanent_card(obj.card) and matches(obj.card, self.card_filter)]
        start_exile_return_batch(context.engine, visits, controller.id, source=self.source)


class ExileUntilTotalManaValueEffect(GameEffect):
    """RULE 701.13 with a running total: "exile cards from the top of your library until you exile cards with total
    mana value N or greater" (Improvisation Capstone). Each card is exiled one at a time and the loop stops as soon
    as the exiled cards' total mana value reaches ``threshold``; a library that runs out simply ends the loop. The
    exiled cards are recorded as the pool for the following `CastWindowFromExiledPoolEffect` (RULE 608.2g).
    """

    def __init__(self, threshold: int, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.threshold = int(threshold)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        before = len(context.exiled_objects)
        total = 0
        while total < self.threshold and player.library:
            top = player.library[-1]
            context.exile(top)
            total += int(getattr(top, "mana_value", 0) or 0)
        context.latest_exiled_visits = [(obj, obj.zone_incarnation) for obj in context.exiled_objects[before:]]


class ExilePoolFromCreatedEffect(GameEffect):
    """Hand the cards the immediately preceding impulsive draw exiled to the casting-pool window: after
    `ImpulsiveDrawEffect`, its exiled cards sit in ``context.created_objects`` (MEC-58), and the
    `CastWindowFromExiledPoolEffect` that follows reads the pool from ``context.latest_exiled_visits``."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        context.latest_exiled_visits = [
            (obj, obj.zone_incarnation) for obj in context.created_objects if obj.zone == Zone.EXILE
        ]


class GlimpseCleanupEffect(GameEffect):
    """RULE 603.7 delayed trigger body for Glimpse the Impossible: "at the beginning of the next end step, if any of
    those cards remain exiled, put them into your graveyard, then create a 0/1 colorless Eldrazi Spawn creature token
    for each card put into your graveyard this way." Only the cards still in exile move (the rest were cast or played
    and have left exile), and the token count is exactly the number that moved. ``instance_ids`` is plain data, so
    it survives `GameState.clone`."""

    def __init__(self, instance_ids: list[int], source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.instance_ids = list(instance_ids)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        leftovers = []
        for iid in self.instance_ids:
            obj = context.state.find_object(iid)
            if obj is not None and obj.zone == Zone.EXILE:
                leftovers.append(iid)
        if not leftovers:
            return
        ReturnRemainingExiledEffect(leftovers, source=self.source).apply(context)
        CreateTokenEffect(
            count=len(leftovers), token_name="Eldrazi Spawn", power=0, toughness=1, colors=[],
            subtypes=["Eldrazi", "Spawn"], oracle_text=_SPAWN_ORACLE, source=self.source,
        ).apply(context)


class ArmGlimpseCleanupEffect(GameEffect):
    """Arm the end-step cleanup for the cards the preceding impulsive draw exiled (``context.created_objects``).
    Mirrors `GraveyardImpulsiveCastEffect`'s delayed-trigger arming: `DelayedTrigger` with ``step="end"`` and
    ``scope="any"`` is "the next end step" of any turn."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...models.game.game_state import DelayedTrigger  # function-scoped: game_state imports effects

        controller_id = getattr(self.source, "controller_id", None) or context.active_player.id
        exiled_ids = [obj.instance_id for obj in context.created_objects if obj.zone == Zone.EXILE]
        if not exiled_ids:
            return
        source_name = self.source.name if self.source is not None else None
        context.state.delayed_triggers.append(DelayedTrigger(
            controller_id=controller_id, step="end", scope="any",
            effects=[GlimpseCleanupEffect(exiled_ids, source=self.source)],
            description=f"{source_name}: übrige Karten ins Grab, Eldrazi-Brut" if source_name else "",
        ))


EffectRegistry.register(
    "exile_until_total_mana_value",  # Improvisation Capstone: exile until the running mana value reaches N
    lambda p: ExileUntilTotalManaValueEffect(threshold=int(p["threshold"])),
)
EffectRegistry.register(
    "exile_pool_from_created",  # bridge: the impulsive draw's pool becomes the casting-window pool
    lambda p: ExilePoolFromCreatedEffect(),
)
EffectRegistry.register(
    "put_latest_exiled_onto_battlefield",
    lambda p: PutLatestExiledOntoBattlefieldEffect(card_filter=p.get("card_filter")),
)
EffectRegistry.register(
    "glimpse_arm_cleanup",  # Glimpse the Impossible: arm the next-end-step leftover cleanup
    lambda p: ArmGlimpseCleanupEffect(),
)
