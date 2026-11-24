"""Resolution-time edict continuations; all paused state uses serialized specs."""
from __future__ import annotations

from .core import GameEffect, ReplacementEffect, _controller_of
from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ..targeting import TargetSpec


def _seq(context, source, specs, targets=None):
    context.engine._apply_effect_specs([{"type": "seq", "params": {"effects": specs}}], source, targets)


def _spec(kind, **params):
    return {"type": kind, "params": params}


class SacrificeWithRidersEffect(GameEffect):
    """RULE 609.3: sacrifice as much as possible, then the success/failure rider."""

    def __init__(self, count=1, what="creature", success=None, failure=None, exclude_source=False,
                 from_damage=False, source=None):
        super().__init__(source)
        self.count, self.what = count, what
        self.success, self.failure = list(success or []), list(failure or [])
        self.exclude_source, self.from_damage = exclude_source, from_damage

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        count = int((context.trigger_event or {}).get("amount", 0)) if self.from_damage else self.count
        if count <= 0:
            return
        pool = context.engine._sacrifice_candidates(player, self.what, exclude=self.source if self.exclude_source else None)
        branch = self.success if len(pool) >= count else self.failure
        # RULE 608.2c: the rider waits behind any sacrifice selection.
        _seq(context, self.source, [_spec("sacrifice", count=count, what=self.what, selector="controller",
                                         exclude_source=self.exclude_source), *branch])


class InfernalDenizenOfferEffect(GameEffect):
    """An opponent chosen by the controller may take one of that controller's creatures."""
    def __init__(self, beneficiary=None, object_ids=None, source=None):
        super().__init__(source)
        self.beneficiary, self.object_ids = beneficiary, object_ids

    def apply(self, context, targets=None):
        from .exile_control import GainControlUntilEndOfTurnEffect
        beneficiary = self.beneficiary or getattr(self.source, "chosen_player_id", None)
        if beneficiary is None:
            return
        if self.object_ids is not None:
            objects = [context.state.find_object(iid) for iid in self.object_ids]
            old = context.acting_player_id
            context.acting_player_id = beneficiary
            try:
                for obj in objects:
                    if obj is not None and obj.zone == Zone.BATTLEFIELD and obj.is_creature:
                        GainControlUntilEndOfTurnEffect(source=self.source, duration="permanent", untap=False,
                            haste=False, while_source="on_battlefield").apply(context, [obj])
            finally:
                context.acting_player_id = old
            return
        player = context.state.player_by_id(beneficiary)
        pool = [o for o in context.state.permanents_controlled_by(self.source.controller_id) if o.is_creature]
        context.choose_objects(player, pool, "select_referent", optional=True, source=self.source,
            then_specs=[_spec("infernal_denizen_offer", beneficiary=beneficiary,
                              object_ids={"kind": "chosen_instance_ids"})],
            prompt="Du kannst die Kontrolle über eine Kreatur übernehmen")


class ChoiceOfDamnationsEffect(GameEffect):
    """RULE 107.1c: the opponent chooses any nonnegative integer; controller chooses the consequence."""
    def __init__(self, number=None, player_id=None, sacrifice=False, source=None):
        super().__init__(source)
        self.number, self.player_id = number, player_id
        self.sacrifice = sacrifice
        self.target_spec = TargetSpec(kind="opponent") if player_id is None else None

    def apply(self, context, targets=None):
        player = context.state.player_by_id(self.player_id) if self.player_id else (targets or [None])[0]
        if player is None:
            return
        if self.number is None:
            # Buttons are suggestions, not an upper bound. The existing free-text UI accepts every integer.
            suggested = max(0, player.life, len(context.state.permanents_controlled_by(player.id)))
            context.engine._request_number_choice(player, 0, suggested,
                [_spec("choice_of_damnations", number="x", player_id=player.id)], self.source)
            context.state.pending_choice.update({"free_text": True, "unbounded": True})
            return
        if self.sacrifice:
            from .life_sacrifice import SacrificeEffect
            count = max(0, len(context.state.permanents_controlled_by(player.id)) - int(self.number))
            SacrificeEffect(count=count, player=player, source=self.source).apply(context)
            return
        from .composition import OptionalEffect
        OptionalEffect(effects=[_spec("lose_life", amount=int(self.number), player_id=player.id)],
            else_effects=[_spec("choice_of_damnations", number=self.number, player_id=player.id, sacrifice=True)],
            source=self.source).apply(context)


def skip_draw_replacement(params):
    # RULE 614.1a / 614.6: the replaced draw never happens (including empty-library draws).
    return ReplacementEffect(event_type=EventType.DRAW, replacement_fn=lambda event, context: None)


def life_gain_to_draw_replacement(params):
    effect = ReplacementEffect(event_type=EventType.LIFE_GAIN, replacement_fn=lambda event, context: event)
    effect.condition = lambda event, context: effect.source is not None and event.get("player_id") == effect.source.controller_id
    def replace(event, context):
        player = context.state.player_by_id(event.get("player_id"))
        context.draw(player, max(0, int(event.get("amount", 0))))
        return None
    effect.replacement_fn = replace
    return effect


class SuspendedSacrificeOfferEffect(GameEffect):
    """RULE 702.62b: the intervening condition must hold at trigger and resolution."""
    def __init__(self, add_counters=False, source=None):
        super().__init__(source)
        self.add_counters = add_counters
    def apply(self, context, targets=None):
        from ..costs import ActivationCost
        if (self.source.zone != Zone.EXILE or self.source.counters.get("time", 0) <= 0
                or (context.resolving_source_incarnation is not None
                    and self.source.zone_incarnation != context.resolving_source_incarnation)) :
            return
        if self.add_counters:
            context.add_counters(self.source, 2, "time")
            return
        player = context.state.active_player
        context.engine._request_pay_cost_then(player,
            ActivationCost(sacrifice="permanent"),
            [_spec("suspended_sacrifice_offer", add_counters=True)], self.source)
