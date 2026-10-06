"""Resolution sequences involving permanent names and death information."""
from __future__ import annotations

from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ..targeting import TargetSpec
from .core import GameEffect, EffectRegistry, _apply_effects_partitioned
from .core import DestroyEffect, _controller_of


class DestroySameNameEffect(GameEffect):
    """RULE 608.2: fix the name before destroying the entire matching group."""

    def __init__(self, target_kind='nonland_permanent', source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context, targets=None):
        if not targets:
            return
        name = targets[0].name
        victims = [obj for obj in context.state.permanents() if obj.name == name]
        _apply_effects_partitioned(
            [DestroyEffect(target=obj, source=self.source) for obj in victims],
            context, None, None, source=self.source,
        )


class _CopyIfDiedEffect(GameEffect):
    def __init__(self, original, power, toughness, controller_id, history_start, source=None):
        super().__init__(source)
        self.original = original.card
        self.instance_id = original.instance_id
        self.power, self.toughness = power, toughness
        self.controller_id = controller_id
        self.history_start = history_start

    def apply(self, context, targets=None):
        died = any(
            event.type == EventType.DIES and event.get('instance_id') == self.instance_id
            for event in context.state.event_log[self.history_start:]
        )
        if died:
            # RULE 707.9: these exceptions are copiable values of the new tokens.
            card = self.original.as_copy(set_power=self.power, set_toughness=self.toughness)
            context.created_objects.extend(context.create_token(self.controller_id, card, 2) or [])


class DestroyAndHalfCopiesEffect(GameEffect):
    """Destroy a creature, then copy it only if that destruction made it die.

    Captures controller, copiable characteristics and live P/T before the zone
    change (RULE 608.2h). The sequence resumes after replacement choices.
    """

    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind='creature')

    def apply(self, context, targets=None):
        if not targets:
            return
        obj = targets[0]
        follow = _CopyIfDiedEffect(
            obj, ((obj.power or 0) + 1) // 2, ((obj.toughness or 0) + 1) // 2,
            obj.controller_id, len(context.state.event_log), self.source,
        )
        _apply_effects_partitioned(
            [DestroyEffect(target=obj, source=self.source), follow], context, None, None,
            source=self.source,
        )


class ExileSameNameTokensEffect(GameEffect):
    """"Exile target nonland permanent an opponent controls and all tokens that player controls with the same name as
    that permanent." (Legions to Ashes) — RULE 608.2: the name and the controller are fixed from the target as the spell
    resolves; the target itself is exiled even if it is not a token."""

    def __init__(self, target_kind='nonland_permanent_you_dont_control', source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind=target_kind)

    def apply(self, context, targets=None):
        if not targets:
            return
        target = targets[0]
        name, controller_id = target.name, target.controller_id
        victims = [target] + [
            obj for obj in context.state.permanents()
            if obj is not target and obj.is_token and obj.name == name and obj.controller_id == controller_id
        ]
        for obj in victims:
            context.exile(obj)


EffectRegistry.register('destroy_same_name', lambda p: DestroySameNameEffect(p.get('target_kind', 'nonland_permanent')))
EffectRegistry.register('exile_same_name_tokens', lambda p: ExileSameNameTokensEffect(p.get('target_kind', 'nonland_permanent_you_dont_control')))
EffectRegistry.register('destroy_and_half_copies', lambda p: DestroyAndHalfCopiesEffect())


class SacrificePermanentOrDiscardEffect(GameEffect):
    """The iteration's player chooses a creature/planeswalker, else a hand card."""

    def apply(self, context, targets=None):
        if not targets:
            return
        player = targets[0]
        candidates = [
            obj for obj in context.state.permanents_controlled_by(player.id)
            if obj.is_creature or obj.is_planeswalker
        ]
        if candidates:
            context.choose_objects(player, candidates, 'sacrifice', source=self.source)
        else:
            context.discard_choice(player, 1)


EffectRegistry.register('sacrifice_permanent_or_discard', lambda p: SacrificePermanentOrDiscardEffect())


class _RecoverMilledPermanentEffect(GameEffect):
    def __init__(self, history_start, source=None):
        super().__init__(source)
        self.history_start = history_start

    def _milled(self, context):
        from .core import _controller_of
        player = _controller_of(self.source, context)
        return [
            context.state.find_object(card['instance_id'])
            for event in context.state.event_log[self.history_start:]
            if event.type == EventType.CARDS_MILLED and event.get('player_id') == player.id
            for card in event.get('cards', [])
        ]

    def apply(self, context, targets=None):
        from .core import _controller_of
        permanent_types = {'artifact', 'battle', 'creature', 'enchantment', 'land', 'planeswalker'}
        candidates = [obj for obj in self._milled(context)
                      if obj is not None and obj.zone == Zone.GRAVEYARD
                      and set(obj.type_words) & permanent_types]
        context.choose_objects(
            _controller_of(self.source, context), candidates,
            'return_from_graveyard_to_hand', optional=True, source=self.source,
        )


class _MilledSubtypeBonusEffect(_RecoverMilledPermanentEffect):
    def apply(self, context, targets=None):
        from ..continuous import has_subtype
        from .core import _controller_of, CreateTokenEffect
        player = _controller_of(self.source, context)
        has_squirrel = any(has_subtype(obj, 'Squirrel') for obj in context.state.permanents_controlled_by(player.id))
        returned_squirrel = any(obj is not None and obj in player.hand and has_subtype(obj, 'Squirrel')
                                for obj in self._milled(context))
        if has_squirrel or returned_squirrel:
            CreateTokenEffect(token_name='Food', source=self.source).apply(context)


class MillRecoverPermanentAndSubtypeBonusEffect(GameEffect):
    """Mill four, optionally recover one permanent, then check the tribal bonus."""

    def apply(self, context, targets=None):
        from .core import MillEffect
        start = len(context.state.event_log)
        _apply_effects_partitioned([
            MillEffect(count=4, source=self.source),
            _RecoverMilledPermanentEffect(start, self.source),
            _MilledSubtypeBonusEffect(start, self.source),
        ], context, None, None, source=self.source)


class RepeatPaidProcessEffect(GameEffect):
    """A finite graveyard-consuming process with a new payment choice each time.

    Reusing the payment continuation avoids a synchronous loop overwriting
    unanswered choices. Every repetition consumes three cards (RULE 118.3).
    """

    def apply(self, context, targets=None):
        from .core import CreateTokenEffect
        _apply_effects_partitioned([
            CreateTokenEffect(token_name='Food', source=self.source),
            _OfferExileRepeatEffect(source=self.source),
        ], context, None, None, source=self.source)


class _OfferExileRepeatEffect(GameEffect):
    def apply(self, context, targets=None):
        from .core import _controller_of
        from .composition import OptionalEffect
        player = _controller_of(self.source, context)
        if len(player.graveyard) >= 3:
            OptionalEffect(
                effects=[{'type': 'exile_graveyard_then_repeat_food', 'params': {}}],
                prompt='Drei Karten aus deinem Friedhof ins Exil schicken?',
                source=self.source,
            ).apply(context)


class _ExileGraveyardAndRepeatEffect(GameEffect):
    def apply(self, context, targets=None):
        from .core import _controller_of
        player = _controller_of(self.source, context)
        if len(player.graveyard) < 3:
            return
        # Once accepted, all three picks are mandatory: no partial payment.
        context.choose_objects(
            player, list(player.graveyard), 'exile', count=3, source=self.source,
            then_specs=[{'type': 'repeat_food_exile_process', 'params': {}}],
        )


EffectRegistry.register('mill_recover_permanent_subtype_bonus', lambda p: MillRecoverPermanentAndSubtypeBonusEffect())
EffectRegistry.register('repeat_food_exile_process', lambda p: RepeatPaidProcessEffect())

EffectRegistry.register('exile_graveyard_then_repeat_food', lambda p: _ExileGraveyardAndRepeatEffect())


# --- PLAY-ALL (Revival Trance): graveyard / discard riders -----------------------------------------------------------


class MarkEventLogEffect(GameEffect):
    """Remember how long the event log is now, on the source (``window_event_mark``) — the start of a "this way" window
    a later `DiscardedThisWayRidersEffect` reads (Mog, Moogle Warrior)."""

    def apply(self, context, targets=None):
        if self.source is not None:
            self.source.window_event_mark = len(context.state.event_log)


class DiscardedThisWayRidersEffect(GameEffect):
    """"If a creature card was discarded this way, `<creature effects>`. Then if a noncreature card was discarded this way,
    `<noncreature effects>`." (Mog, Moogle Warrior) — reads the ``DISCARD_CARD`` events logged since the source's
    `MarkEventLogEffect` window opened (RULE 608.2: "this way" is exactly the discards of the effect before it), then runs the
    matching serialized effect lists in printed order."""

    def __init__(self, creature_effects=None, noncreature_effects=None, source=None):
        super().__init__(source)
        self.creature_specs = list(creature_effects or [])
        self.noncreature_specs = list(noncreature_effects or [])

    def apply(self, context, targets=None):
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        mark = int(getattr(self.source, "window_event_mark", 0) or 0)
        discards = [e for e in context.state.event_log[mark:] if e.type == EventType.DISCARD_CARD]
        creature = any("creature" in (e.get("object_types") or ()) for e in discards)
        noncreature = any("creature" not in (e.get("object_types") or ()) for e in discards)
        specs = [*self.creature_specs] if creature else []
        if noncreature:
            specs.extend(self.noncreature_specs)
        _apply_effects_partitioned(
            build_effects([EffectSpec.from_dict(d) for d in specs], self.source),
            context, None, None, source=self.source,
        )


class CoinOfFateSplitEffect(GameEffect):
    """"An opponent chooses one of the exiled cards. You put that card on the bottom of your library and return the other
    to the battlefield tapped. You become the monarch." (Coin of Fate) — the two creature cards the ability's cost exiled
    (`GameObject.last_cost_exiled_ids`). **Simplification:** the opponent's choice is made for them as the one that is worst
    for you — the card with the greater mana value goes to the bottom, the cheaper one returns."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        ids = list(getattr(self.source, "last_cost_exiled_ids", None) or [])
        self.source.last_cost_exiled_ids = []
        cards = [o for o in (context.state.find_object(i) for i in ids) if o is not None and o.zone == Zone.EXILE]
        if cards:
            cards.sort(key=lambda o: int(o.card.converted_mana_cost or 0))
            for bottomed in cards[1:]:
                owner = context.state.player_by_id(bottomed.owner_id)
                owner.remove_from_zone(bottomed, Zone.EXILE)
                bottomed.zone = Zone.LIBRARY
                owner.library.insert(0, bottomed)  # the bottom (index 0 — see Player.library)
            context.return_from_graveyard(cards[0], "battlefield_tapped")
        context.engine.become_monarch(player)


class ExileRandomGraveyardCardsCastFreeEffect(GameEffect):
    """"Exile a card at random from each opponent's graveyard. You may cast any number of spells from among cards exiled
    this way without paying their mana costs. Then each player who owns a spell you cast this way loses life equal to its
    mana value." (Kefka, Dancing Mad) — each exiled nonland card gets a free-cast window for this effect's controller (the
    Etali shape) and is marked so its owner loses life equal to its mana value when it is actually cast
    (`GameState.free_cast_owner_loses_life_ids`)."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        for opponent in [p for p in context.state.living_players() if p.id != player.id]:
            if not opponent.graveyard:
                continue
            card = context.engine.random_choice(list(opponent.graveyard))
            context.exile(card)
            if card.card.is_land:
                continue
            context.engine.grant_free_cast_window_from_exile(card, caster=player, ignore_timing=True)
            context.state.free_cast_owner_loses_life_ids.add(card.instance_id)


class MillEachPlayerMayCastMilledEffect(GameEffect):
    """"Each player mills a card. If a land card was milled this way, create a Treasure token. Until end of turn, you may
    cast a spell from among those cards." (Locke, Treasure Hunter) — one mill per living player; any milled land gives the
    controller one Treasure; every milled nonland card may be cast by the controller from its graveyard this turn
    (`GameState.temp_graveyard_cast_permissions`), paying its costs normally."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        effects = [_MillOnePlayerEffect(p.id, self.source)
                   for p in context.state.living_players_apnap()]
        effects.append(_GrantMilledSpellWindowEffect(len(context.state.event_log), self.source))
        _apply_effects_partitioned(effects, context, None, None, source=self.source)


class _MillOnePlayerEffect(GameEffect):
    def __init__(self, player_id, source):
        super().__init__(source)
        self.player_id = player_id

    def apply(self, context, targets=None):
        context.mill(context.state.player_by_id(self.player_id), 1)


class _GrantMilledSpellWindowEffect(GameEffect):
    def __init__(self, history_start, source):
        super().__init__(source)
        self.history_start = history_start

    def apply(self, context, targets=None):
        from .core import CreateTokenEffect
        player = _controller_of(self.source, context)
        snapshots = [card
                     for event in context.state.event_log[self.history_start:]
                     if event.type == EventType.CARDS_MILLED
                     for card in event.get('cards', [])]
        ids = frozenset(c['instance_id'] for c in snapshots
                        if 'land' not in c.get('object_types', []))
        for iid in ids:
            obj = context.state.find_object(iid)
            if obj is not None and obj.zone == Zone.GRAVEYARD:
                context.state.temp_graveyard_cast_permissions[iid] = player.id
                context.state.temp_graveyard_cast_permission_groups[iid] = ids
        if any('land' in c.get('object_types', []) for c in snapshots):
            CreateTokenEffect(token_name='Treasure', count=1, source=self.source).apply(context)


class ExileInstantSorceryFromEachGraveyardEffect(GameEffect):
    """"Exile an instant or sorcery card from each graveyard." (Summon: Esper Valigarmanda, chapter I) — the exiled cards are
    remembered as exiled with the source Saga (`exiled_with_ids`). **Simplification:** the most recently added matching card
    of each graveyard is taken rather than offering a choice."""

    def apply(self, context, targets=None):
        for p in list(context.state.players):
            card = next((o for o in reversed(p.graveyard) if o.card.is_instant or o.card.is_sorcery), None)
            if card is None:
                continue
            context.exile(card)
            if self.source is not None:
                self.source.exiled_with_ids.append(card.instance_id)


class CastExiledWithSourceEffect(GameEffect):
    """"You may cast an instant or sorcery card exiled with this Saga, and mana of any type can be spent to cast that
    spell." (Summon: Esper Valigarmanda, chapters II–IV) — a this-turn cast permission, with mana of any type, over every
    instant/sorcery card the source exiled and still has in exile. **Simplification:** the window lasts the rest of the turn
    rather than ending when the chapter ability finishes resolving."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        for instance_id in list(getattr(self.source, "exiled_with_ids", None) or []):
            obj = context.state.find_object(instance_id)
            if obj is None or obj.zone != Zone.EXILE or not (obj.card.is_instant or obj.card.is_sorcery):
                continue
            context.engine._grant_temp_play_permission(
                obj, player, self.source.name, same_turn_only=True, mana_wildcard="type",
            )


EffectRegistry.register("mark_event_log", lambda p: MarkEventLogEffect())
EffectRegistry.register(
    "discarded_this_way_riders",
    lambda p: DiscardedThisWayRidersEffect(
        creature_effects=p.get("creature_effects"), noncreature_effects=p.get("noncreature_effects"),
    ),
)
EffectRegistry.register("coin_of_fate_split", lambda p: CoinOfFateSplitEffect())
EffectRegistry.register("exile_random_graveyard_cards_cast_free", lambda p: ExileRandomGraveyardCardsCastFreeEffect())
EffectRegistry.register("mill_each_player_may_cast_milled", lambda p: MillEachPlayerMayCastMilledEffect())
EffectRegistry.register(
    "exile_instant_sorcery_from_each_graveyard", lambda p: ExileInstantSorceryFromEachGraveyardEffect(),
)
EffectRegistry.register("cast_exiled_with_source", lambda p: CastExiledWithSourceEffect())


class ExileOpponentGraveyardsCopyCreatureEffect(GameEffect):
    """Exile opponents' graveyards and make an artifact-only copy of a creature.

    The draft's explicit simplification selects the greatest mana value,
    rather than opening the printed reflexive optional target choice.
    """

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        candidates = []
        for opponent in context.state.living_players_apnap():
            if opponent.id == player.id:
                continue
            for obj in list(opponent.graveyard):
                context.exile(obj)
                if obj.card.is_creature and obj.zone == Zone.EXILE:
                    candidates.append(obj)
        if candidates:
            obj = max(candidates, key=lambda o: int(o.card.converted_mana_cost or 0))
            copy = obj.card.as_copy(only_types=['Artifact'])
            context.created_objects.extend(context.create_token(player.id, copy, 1) or [])


EffectRegistry.register('exile_opponent_graveyards_copy_creature', lambda p: ExileOpponentGraveyardsCopyCreatureEffect())
