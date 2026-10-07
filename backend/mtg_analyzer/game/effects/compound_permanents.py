"""Resolution sequences involving permanent names and death information."""
from __future__ import annotations

from ...models.game.events import EventType
from ...models.game.game_object import Zone
from ..targeting import TargetSpec
from .core import GameEffect, EffectRegistry, _apply_effects_partitioned
from .. import continuations
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
    def __init__(self, history_start, source=None, destination="hand"):
        super().__init__(source)
        self.history_start = history_start
        self.destination = destination

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
            'return_from_graveyard_to_hand' if self.destination == 'hand' else 'return_from_graveyard',
            optional=True, source=self.source,
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


class TokensPerDiscardedCardTypeEffect(GameEffect):
    """"Create a 1/1 white Spirit creature token with flying for each card type among cards discarded this way." (Occult
    Epiphany) — the distinct RULE 205.2a card types over the ``DISCARD_CARD`` events logged since the source's
    `MarkEventLogEffect` window opened (the same "this way" window `DiscardedThisWayRidersEffect` reads), then one
    ``create_token`` of ``token`` params with that count."""

    #: Card types a "for each card type" count looks at; the discard event's ``object_types`` also carries
    #: supertypes and the always-added "permanent" word, which are not card types.
    _CARD_TYPES = frozenset({
        "artifact", "battle", "creature", "enchantment", "instant", "kindred", "land", "planeswalker", "sorcery",
    })

    def __init__(self, token=None, source=None):
        super().__init__(source)
        self.token = dict(token or {})

    def apply(self, context, targets=None):
        from ..binding.core import build_effects  # function-scoped: effects↔binder cycle
        from ...parser.oracle.spec import EffectSpec

        mark = int(getattr(self.source, "window_event_mark", 0) or 0)
        types: set[str] = set()
        for event in context.state.event_log[mark:]:
            if event.type == EventType.DISCARD_CARD:
                types |= {str(t).lower() for t in (event.get("object_types") or ())} & self._CARD_TYPES
        if not types:
            return
        spec = EffectSpec("create_token", {**self.token, "count": len(types)})
        _apply_effects_partitioned(build_effects([spec], self.source), context, None, None, source=self.source)


class DamageOpponentsByDiscardedManaValueEffect(GameEffect):
    """"When you discard a card this way, ~ deals damage equal to that card's mana value to each opponent." (Summon: Kujata, chapter III) — the controller's
    ``DISCARD_CARD`` events since the source's `MarkEventLogEffect` window opened; each discarded card's mana value (read off the card, now in the graveyard)
    is dealt to every opponent."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        mark = int(getattr(self.source, "window_event_mark", 0) or 0)
        for event in context.state.event_log[mark:]:
            if event.type != EventType.DISCARD_CARD or event.get("player_id") != player.id:
                continue
            discarded = context.state.find_object(event.get("instance_id"))
            mana_value = int(getattr(discarded, "mana_value", 0) or 0)
            context.enqueue_reflexive_trigger([
                {"type": "damage", "params": {"amount": mana_value, "selector": "each_opponent"}},
            ], self.source)


class CoinOfFateSplitEffect(GameEffect):
    """The controller selects an opponent; that opponent chooses the bottomed exile card."""

    def apply(self, context, targets=None):
        from .choices_actions import offer_opponent_decision

        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        ids = list(self.source.last_cost_exiled_ids)
        incarnations = dict(self.source.last_cost_exiled_incarnations)
        self.source.last_cost_exiled_ids = []
        self.source.last_cost_exiled_incarnations = {}
        cards = [o for o in (context.state.find_object(i) for i in ids)
                 if o is not None and o.zone == Zone.EXILE
                 and o.zone_incarnation == incarnations.get(o.instance_id, o.zone_incarnation)]
        decision = {"kind": "coin_of_fate_split", "owner_id": player.id,
                    "card_ids": [o.instance_id for o in cards],
                    "incarnations": {str(o.instance_id): o.zone_incarnation for o in cards},
                    "optional": False, "prompt": "Coin of Fate: Welche Karte kommt unter die Bibliothek?",
                    "options": [{"id": str(o.instance_id), "instance_id": o.instance_id, "label": o.name}
                                for o in cards]}
        if not cards or not offer_opponent_decision(context.engine, player, decision):
            context.engine.become_monarch(player)


@continuations.choice("coin_of_fate_split", answer=continuations.ANSWER_INT, rule="608.2d")
def _resume_coin_of_fate_split(rules, choice, answer):
    if answer not in choice["card_ids"]:
        rules.open_choice(choice)
        raise ValueError("Choose a listed exiled card")
    for iid in choice["card_ids"]:
        obj = rules.state.find_object(iid)
        if (obj is None or obj.zone != Zone.EXILE
                or obj.zone_incarnation != choice["incarnations"][str(iid)]):
            continue
        if iid == answer:
            owner = rules.state.player_by_id(obj.owner_id)
            owner.remove_from_zone(obj, Zone.EXILE)
            obj.zone = Zone.LIBRARY
            owner.library.insert(0, obj)
        else:
            rules.return_from_graveyard(obj, "battlefield_tapped")
    rules.become_monarch(rules.state.player_by_id(choice["owner_id"]))


class ExileRandomGraveyardCardsCastFreeEffect(GameEffect):
    """Kefka: random exile, optional repeated immediate casts, then owner life loss.

    RULE 608.2g keeps every cast inside this resolution. The recorded spell
    mana values are paid as life loss only after the entire casting sequence.
    """

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        cards = []
        with context.state.simultaneous():
            for opponent in [p for p in context.state.living_players() if p.id != player.id]:
                if not opponent.graveyard:
                    continue
                obj = context.engine.random_choice(list(opponent.graveyard))
                context.exile(obj)
                cards.append(obj)
        context.engine._request_resolution_play(player, cards, repeat=True, only_spells=True,
                                                owner_life_loss=True)


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
    def __init__(self, player_id, source, count=1):
        super().__init__(source)
        self.player_id = player_id
        self.count = count

    def apply(self, context, targets=None):
        context.mill(context.state.player_by_id(self.player_id), self.count)


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


class MillAttackersEachPlayerCastFreeEffect(GameEffect):
    """Ur-Sphinx: mill for each attacking Sphinx, then offer one immediate cast per player.

    Milling choices finish first. Each subsequent offer is scoped to the
    corresponding player’s newly milled graveyard incarnations (RULE 608.2g).
    """

    def __init__(self, subtype: str = "sphinx", source=None):
        super().__init__(source)
        self.subtype = str(subtype).lower()

    def apply(self, context, targets=None):
        from ..continuous import has_subtype

        player = _controller_of(self.source, context)
        if player is None:
            return
        event = context.trigger_event or {}
        count = 0
        for iid in event.get("attacker_ids") or []:
            attacker = context.state.find_object(iid)
            if attacker is not None and has_subtype(attacker, self.subtype):
                count += 1
        if count <= 0:
            return
        start = len(context.state.event_log)
        players = list(context.state.living_players_apnap())
        effects = [_MillOnePlayerEffect(p.id, self.source, count) for p in players]
        effects.extend(_OfferMilledPlayerCastEffect(p.id, start, self.source) for p in players)
        _apply_effects_partitioned(effects, context, None, None, source=self.source)


class _OfferMilledPlayerCastEffect(GameEffect):
    def __init__(self, owner_id, history_start, source):
        super().__init__(source)
        self.owner_id, self.history_start = owner_id, history_start

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        cards = []
        for event in context.state.event_log[self.history_start:]:
            if event.type != EventType.CARDS_MILLED or event.get("player_id") != self.owner_id:
                continue
            for record in event.get("cards", []):
                obj = context.state.find_object(record["instance_id"])
                if (obj is not None and obj.zone == Zone.GRAVEYARD
                        and obj.zone_incarnation == record.get("zone_incarnation", obj.zone_incarnation)):
                    cards.append(obj)
        context.engine._request_resolution_play(player, cards, zone="graveyard", only_spells=True)


def _offer_graveyard_spell_exiles(rules, frame):
    remaining = list(frame["remaining_owner_ids"])
    selected = list(frame.get("selected", []))
    while remaining:
        owner_id = remaining.pop(0)
        owner = rules.state.player_by_id(owner_id)
        cards = [o for o in owner.graveyard if o.card.is_instant or o.card.is_sorcery]
        if not cards:
            continue
        if len(cards) == 1:
            selected.append({"instance_id": cards[0].instance_id, "incarnation": cards[0].zone_incarnation})
            continue
        rules.open_choice({**frame, "kind": "choose_graveyard_spell_exile",
            "remaining_owner_ids": remaining, "selected": selected,
            "optional": False, "prompt": f"Wähle einen Instant oder eine Sorcery aus {owner.name}s Friedhof",
            "options": [{"id": str(o.instance_id), "instance_id": o.instance_id,
                         "incarnation": o.zone_incarnation, "label": o.name} for o in cards]})
        return
    source = rules.state.find_object(frame.get("source_id"))
    can_link = source is not None and source.zone_incarnation == frame.get("source_incarnation")
    with rules.state.simultaneous():
        for record in selected:
            obj = rules.state.find_object(record["instance_id"])
            if obj is None or obj.zone != Zone.GRAVEYARD or obj.zone_incarnation != record["incarnation"]:
                continue
            rules.exile(obj)
            if can_link and obj.zone == Zone.EXILE:
                source.exiled_with_ids.append(obj.instance_id)


@continuations.choice("choose_graveyard_spell_exile", answer=continuations.ANSWER_INT, rule="608.2d")
def _resume_graveyard_spell_exile(rules, choice, answer):
    option = next((o for o in choice["options"] if o["instance_id"] == answer), None)
    if option is None:
        rules.open_choice(choice)
        raise ValueError("Choose a listed graveyard spell")
    _offer_graveyard_spell_exiles(rules, {**choice, "selected": [*choice["selected"], {
        "instance_id": answer, "incarnation": option["incarnation"],
    }]})


class ExileInstantSorceryFromEachGraveyardEffect(GameEffect):
    """Controller selects a spell from each graveyard; exile the selected set together."""

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is not None:
            _offer_graveyard_spell_exiles(context.engine, {
                "player_id": player.id, "selected": [],
                "remaining_owner_ids": [p.id for p in context.state.living_players_apnap()],
                "source_id": getattr(self.source, "instance_id", None),
                "source_incarnation": context.resolving_source_incarnation,
            })


class CastExiledWithSourceEffect(GameEffect):
    """Valigarmanda: offer one linked spell during this chapter, paying its normal costs.

    Mana may be spent as any type for this cast; the permission and mana
    flexibility end when the player casts or declines (RULE 608.2g).
    """

    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        cards = [context.state.find_object(iid) for iid in self.source.exiled_with_ids]
        cards = [obj for obj in cards if obj is not None and obj.zone == Zone.EXILE
                 and (obj.card.is_instant or obj.card.is_sorcery)]
        context.engine._request_resolution_play(player, cards, only_spells=True, free=False,
                                                mana_wildcard="type")


EffectRegistry.register("mark_event_log", lambda p: MarkEventLogEffect())
EffectRegistry.register(
    "discarded_this_way_riders",
    lambda p: DiscardedThisWayRidersEffect(
        creature_effects=p.get("creature_effects"), noncreature_effects=p.get("noncreature_effects"),
    ),
)
EffectRegistry.register(
    "tokens_per_discarded_card_type", lambda p: TokensPerDiscardedCardTypeEffect(token=p.get("token")),
)
EffectRegistry.register(
    "mill_attackers_each_player_cast_free", lambda p: MillAttackersEachPlayerCastFreeEffect(subtype=p.get("subtype", "sphinx")),
)
EffectRegistry.register(
    "damage_opponents_by_discarded_mana_value", lambda p: DamageOpponentsByDiscardedManaValueEffect(),
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
            obj = max(candidates, key=lambda o: int(o.mana_value or 0))
            copy = obj.card.as_copy(only_types=['Artifact'])
            context.created_objects.extend(context.create_token(player.id, copy, 1) or [])


EffectRegistry.register('exile_opponent_graveyards_copy_creature', lambda p: ExileOpponentGraveyardsCopyCreatureEffect())


class ReturnCapturedGraveyardCardEffect(GameEffect):
    """RULE 400.7 / 603.7c: return the captured graveyard incarnation.

    CreateDelayedTriggerEffect stamps the target, zone and incarnation when
    the delayed trigger is created. Leaving and re-entering the graveyard
    breaks that link, even though this engine retains the instance ID.
    """

    def __init__(self, source=None):
        super().__init__(source)
        self.target = None
        self._captured_target_incarnation = None
        self._captured_target_zone = None

    def apply(self, context, targets=None):
        iid = getattr(self.target, 'instance_id', None)
        obj = context.state.find_object(iid) if iid is not None else None
        if (obj is None or obj.zone != Zone.GRAVEYARD
                or self._captured_target_zone != Zone.GRAVEYARD
                or obj.hideaway_incarnation != self._captured_target_incarnation):
            return
        player = _controller_of(self.source, context)
        if player is not None:
            context.return_from_graveyard(obj, controller_id=player.id)


EffectRegistry.register('return_captured_graveyard_card', lambda p: ReturnCapturedGraveyardCardEffect())


class SacrificeAttachedDrawPowerEffect(GameEffect):
    """RULE 608.2h: choose to sacrifice the damage dealer, then draw its saved power."""

    def apply(self, context, targets=None):
        obj = context.state.find_object((context.trigger_event or {}).get('source_id'))
        player = _controller_of(self.source, context)
        if (obj is None or obj not in context.state.battlefield or obj.controller_id != player.id
                or obj.cant_be_sacrificed_this_turn):
            return
        context.choose_objects(player, [obj], 'sacrifice', optional=True, source=self.source,
                               prompt='Kreatur opfern und Karten ziehen?',
                               then_specs=[{'type': 'draw', 'params': {'count': max(0, obj.power or 0)}}])


class MillRecoverPermanentEffect(GameEffect):
    """Mill a fixed number and choose a permanent from that exact mill batch."""

    def __init__(self, count=4, destination='battlefield', source=None):
        super().__init__(source)
        self.count, self.destination = count, destination

    def apply(self, context, targets=None):
        from .core import MillEffect
        _apply_effects_partitioned([
            MillEffect(count=self.count, source=self.source),
            _RecoverMilledPermanentEffect(len(context.state.event_log), self.source, self.destination),
        ], context, None, None, source=self.source)


class SacrificePreviousDealerEffect(GameEffect):
    def apply(self, context, targets=None):
        obj = context.previous_targets[0] if context.previous_targets else None
        if obj is not None and obj in context.state.battlefield and obj.controller_id == _controller_of(self.source, context).id:
            context.engine.put_into_graveyard(obj)


EffectRegistry.register('sacrifice_attached_draw_power', lambda p: SacrificeAttachedDrawPowerEffect())
EffectRegistry.register('mill_recover_permanent', lambda p: MillRecoverPermanentEffect(p.get('count', 4), p.get('destination', 'battlefield')))
EffectRegistry.register('sacrifice_previous_dealer', lambda p: SacrificePreviousDealerEffect())
