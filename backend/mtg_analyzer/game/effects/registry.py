"""Built-in effect factories and parser-facing registration wiring."""
from __future__ import annotations

from .core import EffectRegistry
from ._runtime import install, register

install(globals())

EffectRegistry.register("living_death", lambda p: LivingDeathEffect())
EffectRegistry.register("play_hideaway_card", lambda p: PlayHideawayCardEffect(p.get("condition")))
EffectRegistry.register("sacrifice_to_return_targets", lambda p: SacrificeToReturnTargetsEffect())
EffectRegistry.register("return_remembered_graveyard_cards", lambda p: ReturnRememberedGraveyardCardsEffect(
    instance_ids=p.get("instance_ids", []), tapped=bool(p.get("tapped", False)),
    exile_instead_of_leaving=bool(p.get("exile_instead_of_leaving", False)),
    graveyard_incarnations=p.get("graveyard_incarnations"),
))
EffectRegistry.register("sacrifice_shared_type_to_return", lambda p: SacrificeSharedTypeToReturnEffect(
    target_kind=p.get("target_kind", "graveyard_permanent"),
))

# Register the core one-shot effects (RULE R3.1 in docs/02).
EffectRegistry.register(
    "damage",
    lambda p: DealDamageEffect(
        amount=p.get("amount", 0),
        target=p.get("target"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        colors=p.get("colors"),
        creature_filter=p.get("creature_filter"),
        selector_filter=p.get("selector_filter"),
        group=p.get("group"),
        group_player=p.get("group_player"),
        group_and_players=p.get("group_and_players"),
        divided=bool(p.get("divided", False)),
        distinct_from_others=bool(p.get("distinct_from_others", False)),
        double_at=p.get("double_at"),
        amount_if_kicked=p.get("amount_if_kicked"),
        amount_if_teamwork=p.get("amount_if_teamwork"),
        amount_if_raid=p.get("amount_if_raid"),
        amount_if_mana_color_spent=p.get("amount_if_mana_color_spent"),
        each_target_if_mana_color_spent=p.get("each_target_if_mana_color_spent"),
        amount_if_full_party=p.get("amount_if_full_party"),
        amount_if_bargained=p.get("amount_if_bargained"),
        double_if_bargained=bool(p.get("double_if_bargained", False)),
        amount_if_target_color=(
            (p["amount_if_target_color"]["amount"], list(p["amount_if_target_color"]["colors"]))
            if p.get("amount_if_target_color") else None
        ),
        amount_if_cast_from_exile=p.get("amount_if_cast_from_exile"),
        amount_if_source_subtype=(
            (str(p["amount_if_source_subtype"]["subtype"]), int(p["amount_if_source_subtype"]["amount"]))
            if p.get("amount_if_source_subtype") else None
        ),
        tap_target_if_colorless=bool(p.get("tap_target_if_colorless", False)),
        x_multiplier=p.get("x_multiplier"),
        amount_from_noncreature_spells_cast_this_turn=bool(
            p.get("amount_from_noncreature_spells_cast_this_turn", False)
        ),
        amount_from_count_selector=p.get("amount_from_count_selector"),
        amount_plus_count_selector=int(p.get("amount_plus_count_selector", 0) or 0),
        amount_multiplier=int(p.get("amount_multiplier", 1) or 1),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        amount_from_defending_player_hand_size=bool(p.get("amount_from_defending_player_hand_size", False)),
        recipient_subject=p.get("recipient_subject"),
        unpreventable=bool(p.get("unpreventable", False)),
        dealer_event_key=p.get("dealer_event_key"),
        dealer_subject=p.get("dealer_subject"),
        per_player=p.get("per_player"),
    ),
)
EffectRegistry.register(
    # "If you do, you skip your draw step this turn." (Elfhame Sanctuary)
    # is a resolving, one-shot skip, unlike the standing ``skip_step``
    # StaticAbility used by Necropotence.
    "skip_next_step",
    lambda p: SkipNextStepEffect(
        step=p.get("step", "draw"), target_kind=p.get("target_kind"), selector=p.get("selector"),
    ),
)
EffectRegistry.register("establish_day_on_entry", lambda p: EstablishDayOnEntryEffect())
EffectRegistry.register(
    # "…its controller may draw a card if its power is greater than each
    # other creature's power." (Selvala, Heart of the Wilds, MEC-43) — see
    # `DrawIfTriggerObjectGreatestPowerEffect`.
    "draw_if_trigger_object_greatest_power",
    lambda p: DrawIfTriggerObjectGreatestPowerEffect(),
)
EffectRegistry.register(
    "draw",
    lambda p: DrawCardEffect(
        count=p.get("count", 1), player=p.get("player"), count_selector=p.get("count_selector"),
        target_kind=p.get("target_kind"), selector=p.get("selector"),
        target_count=int(p.get("target_count", 1) or 1), target_optional=bool(p.get("target_optional", False)),
    ),
)
EffectRegistry.register(
    "draw_each_player_with_creature_power",
    lambda p: DrawEachPlayerWithCreaturePowerEffect(min_power=int(p.get("min_power", 4))),
)
EffectRegistry.register(
    # "…if a land entered this turn and you control a prime number of lands,
    # create Primo, the Indivisible …" (Zimone, All-Questioning, PAR-60)
    "zimone_all_questioning_end_step",
    lambda p: ZimoneAllQuestioningEndStepEffect(),
)
EffectRegistry.register(
    # "draw a card for each Aura you controlled that was attached to it"
    # (Hateful Eidolon, PAR-60) — off the DIES event's snapshot.
    "draw_per_attached_aura_controller",
    lambda p: DrawPerAttachedAuraControllerEffect(),
)
EffectRegistry.register(
    "draw_controlled_chosen_creature_type", lambda p: DrawControlledChosenCreatureTypeEffect(),
)
EffectRegistry.register(
    "return_chosen_creature_type_from_graveyard",
    lambda p: ReturnChosenCreatureTypeFromGraveyardEffect(),
)
EffectRegistry.register(
    "cast_target_elemental_from_graveyard_free",
    lambda p: CastTargetElementalFromGraveyardFreeEffect(),
)
EffectRegistry.register(
    "kindred_summons",
    lambda p: KindredSummonsEffect(),
)
EffectRegistry.register(
    # "Reveal cards from the top of your library until you reveal X land
    # cards. Put those onto the battlefield tapped and the rest on the
    # bottom of your library in a random order." (Open the Way, PAR-60)
    "reveal_until",
    lambda p: RevealUntilMatchingEffect(
        criteria=p.get("criteria", "land"),
        count=p.get("count", 1),
        hit_destination=p.get("hit_destination", "battlefield"),
        rest_destination=p.get("rest_destination", "library_bottom_random"),
        tapped=bool(p.get("tapped", False)),
        scope=p.get("scope"),
        entry_choices=bool(p.get("entry_choices", False)),
    ),
)
EffectRegistry.register(
    # "Each opponent chooses a creature with the greatest mana value among creatures they control. Return those creatures to their
    # owners' hands." (Summon: Valefor)
    "each_opponent_returns_greatest_mv_creature",
    lambda p: EachOpponentReturnsGreatestManaValueCreatureEffect(),
)
EffectRegistry.register(
    # "You may exile target creature card from a graveyard. If you do, create a 1/1 white Spirit … +1/+1 counter if its mana value is 4 or
    # greater." (Summoner's Sending)
    "exile_creature_card_make_spirit",
    lambda p: ExileCreatureCardMakeSpiritEffect(min_mana_value_for_counter=int(p.get("min_mana_value_for_counter", 4))),
)
EffectRegistry.register(
    # "For each opponent, choose an artifact or land that player controls. Destroy the chosen permanents." (Ultimate Magic: Meteor)
    "destroy_artifact_or_land_per_opponent",
    lambda p: DestroyArtifactOrLandPerOpponentEffect(),
)
EffectRegistry.register(
    # "…return that card to its owner's hand." under a turn-scoped DIES trigger (Together Forever)
    "return_trigger_subject_to_hand",
    lambda p: ReturnTriggerSubjectToHandEffect(),
)
EffectRegistry.register(
    # "Exile all creatures you control, then reveal … until you reveal that many creature cards …" (Mass Polymorph;
    # ``delayed`` is Synthetic Destiny's next-end-step form)
    "exile_creatures_reveal_that_many",
    lambda p: ExileCreaturesRevealThatManyEffect(delayed=bool(p.get("delayed", False))),
)
EffectRegistry.register(
    # "Exile/bottom target X. [Its controller / you] reveal(s) until a <type> card; put it onto the battlefield, the rest
    # on the bottom." (Jace, Multiverse Architect; Proteus Staff)
    "replace_target_with_revealed",
    lambda p: ReplaceTargetWithRevealedEffect(
        target_kind=p.get("target_kind", "creature"), removal=p.get("removal", "exile"),
        revealer=p.get("revealer", "controller"), criteria=p.get("criteria"),
    ),
)
EffectRegistry.register(
    # "The owner of up to one other target nonland permanent puts it on their choice of the top or bottom of their library."
    # (Plan for All Outcomes)
    "owner_puts_on_top_or_bottom",
    lambda p: OwnerChoosesLibraryPositionEffect(
        target_kind=p.get("target_kind", "nonland_permanent"), optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    # "Target opponent reveals … until they reveal a <criteria> card. You put that card onto the battlefield under your
    # control and lose life equal to its mana value. …" (Jhoira, Weatherlight Corsair)
    "reveal_opponent_library_steal",
    lambda p: RevealOpponentLibraryStealEffect(criteria=p.get("criteria")),
)
EffectRegistry.register(
    # "Reveal the top X cards. Put all land cards onto the battlefield
    # tapped … Spell mastery — … untap those lands." (Animist's Awakening)
    "animists_awakening",
    lambda p: AnimistsAwakeningEffect(count=p.get("count", "x")),
)
EffectRegistry.register(
    # "Look at the top N cards. Put any number of nonland permanent cards
    # with total mana value M or less onto the battlefield …" (Ao, the Dawn
    # Sky's first mode, PAR-60)
    "budget_dig_onto_battlefield",
    lambda p: BudgetDigOntoBattlefieldEffect(
        look=int(p.get("look", 7)), budget=int(p.get("budget", 4)),
    ),
)
EffectRegistry.register(
    # "Shuffle. Exile top cards while total MV <= 13; cast any of those free
    # this turn." (Dance with Calamity, PAR-60)
    "dance_with_calamity",
    lambda p: DanceWithCalamityEffect(),
)
EffectRegistry.register(
    # "Exile two piles of four. An opponent chooses one -> graveyard. From
    # the other, cast one spell free; rest to hand." (Abstract Performance)
    "abstract_performance",
    lambda p: AbstractPerformanceEffect(),
)
EffectRegistry.register(
    # "…each player exiles from the top until a nonland. An opponent denies
    # one; cast up to two of the rest free." (Plargg and Nassari, PAR-60)
    "plargg_and_nassari",
    lambda p: PlarggAndNassariEffect(),
)
EffectRegistry.register(
    # "Look at the top three cards … one to hand, one to bottom, exile one
    # (playable this turn)." (Expressive Iteration, PAR-60)
    "expressive_iteration",
    lambda p: ExpressiveIterationEffect(),
)
EffectRegistry.register(
    # Plumb the Forbidden — "sacrifice one or more creatures … copy this
    # spell for each" as an at-resolution optional sacrifice + net
    # draw/lose scaled by the count. (PAR-60 round 4)
    "sacrifice_any_number_draw_lose_scaled",
    lambda p: SacrificeAnyNumberDrawLoseScaledEffect(),
)
EffectRegistry.register(
    "sacrifice_count_draw_lose",
    lambda p: SacrificeCountDrawLoseTailEffect(
        player_id=p.get("player_id"), before=int(p.get("before", 0) or 0),
    ),
)
EffectRegistry.register(
    # Immoral Bargain — "sacrifice X creatures. Destroy X target nonland
    # permanents." X defined by the additional-cost sacrifice. (PAR-60 rd 4)
    "immoral_bargain",
    lambda p: ImmoralBargainEffect(destroy_kind=str(p.get("destroy_kind", "nonland_permanent"))),
)
EffectRegistry.register(
    "immoral_bargain_destroy",
    lambda p: ImmoralBargainDestroyTailEffect(
        player_id=p.get("player_id"), before=int(p.get("before", 0) or 0),
        destroy_kind=str(p.get("destroy_kind", "nonland_permanent")),
    ),
)
EffectRegistry.register(
    # Primo, the Unbounded's second ability — base-power-0 creatures deal
    # combat damage -> sized Fractal token. (PAR-60 round 4)
    "base0_combat_damage_fractal",
    lambda p: Base0CombatDamageFractalEffect(),
)
EffectRegistry.register(
    # Unbound Flourishing's first ability — double a permanent spell's
    # announced X on the stack. (PAR-60 round 4)
    "double_cast_x",
    lambda p: DoubleCastXEffect(),
)
EffectRegistry.register(
    # Mirrorwing Dragon — copy a spell that targets only this creature once
    # per other creature you control, each copy retargeted. (PAR-60 round 4)
    "mirrorwing_copy",
    lambda p: MirrorwingCopyEffect(),
)
EffectRegistry.register(
    # Nils, Discipline Enforcer — "for each player, put a +1/+1 counter on
    # up to one target creature that player controls." (PAR-60 round 4)
    "nils_end_step_counters",
    lambda p: NilsEndStepCountersEffect(),
)
EffectRegistry.register(
    # Intermediate Chirography level 3 — "at the beginning of each end step,
    # if a modified creature died under your control this turn, create an
    # Inkling." (PAR-60 round 4)
    "intermediate_chirography_l3",
    lambda p: IntermediateChirographyL3Effect(),
)
EffectRegistry.register(
    # Advanced Reconstruction level 1 — "mill a card, then exile a card from
    # your graveyard at random. You may play it this turn." (PAR-60 round 4)
    "advanced_reconstruction_l1",
    lambda p: AdvancedReconstructionL1Effect(),
)
EffectRegistry.register(
    "expressive_iteration_exile_step", lambda p: ExpressiveIterationExileStepEffect(),
)
EffectRegistry.register(
    "expressive_iteration_finish", lambda p: ExpressiveIterationFinishEffect(),
)
EffectRegistry.register(
    "descendants_fury_sacrifice",
    lambda p: DescendantsFurySacrificeEffect(),
)
EffectRegistry.register(
    "inspect_top_choose",
    lambda p: InspectTopChooseEffect(
        count=p.get("count", 1),
        action=p.get("action", "library_to_hand"),
        filter=p.get("filter"),
        rest_destination=p.get("rest_destination", "library_bottom_random"),
        optional=bool(p.get("optional", False)),
        prompt=p.get("prompt", "Wähle eine Karte"),
        decline_leaves_untouched=bool(p.get("decline_leaves_untouched", False)),
        max_picks=p.get("max_picks", 1) if p.get("max_picks") == "all" else int(p.get("max_picks", 1) or 1),
        max_picks_if_teamwork=p.get("max_picks_if_teamwork"),
        criteria=p.get("criteria"),
        else_effects=p.get("else_effects"),
        distinct_card_types=bool(p.get("distinct_card_types", False)),
    ),
)
EffectRegistry.register(
    "discard",
    lambda p: DiscardEffect(
        count=p.get("count", 1), player=p.get("player"),
        target_kind=p.get("target_kind"), scope=p.get("scope"),
        player_from_trigger_event=bool(p.get("player_from_trigger_event", False)),
        draw_per_discard=bool(p.get("draw_per_discard", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        random=bool(p.get("random", False)),
        whole_hand=bool(p.get("whole_hand", False)),
        count_max=p.get("count_max"),
        then_draw_discarded=bool(p.get("then_draw_discarded", False)),
        filter=p.get("filter"),
        unless_discard=p.get("unless_discard"), player_id=p.get("player_id"),
    ),
)
EffectRegistry.register(
    # PAR-74: "target opponent exiles a card from their hand." (Kyoki,
    # Sanity's Eclipse) — the exile-zone sibling of ``"discard"`` above.
    "exile_hand_card",
    lambda p: ExileHandCardEffect(
        count=p.get("count", 1), target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject", False)),
        zone=p.get("zone", "hand"),
    ),
)
EffectRegistry.register(
    "look_at_hand",  # "look at target player's hand" (Clairvoyance) — an informational choice
    lambda p: LookAtHandEffect(
        target_kind=p.get("target_kind", "player"), previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # The "then draw that many" tail of the above — queued as ``then_specs``,
    # reads the caller's `cards_discarded_this_turn` delta. Not for direct
    # card use.
    "draw_cards_discarded_delta",
    lambda p: DiscardCardsDiscardedDeltaDrawEffect(
        player_id=p.get("player_id"), before=int(p.get("before", 0) or 0),
    ),
)
EffectRegistry.register(
    # "You may discard a card. If you do, draw N cards, then mill M."
    # (Quintorius, History Chaser's +1, PAR-60) — a loot with a fixed
    # payoff; see `MayDiscardThenDrawMillEffect`.
    "may_discard_then_draw_mill",
    lambda p: MayDiscardThenDrawMillEffect(
        draw=int(p.get("draw", 2) or 0), mill=int(p.get("mill", 1) or 0),
    ),
)
EffectRegistry.register(
    # The "if you do, draw then mill" tail of the above — queued as
    # ``then_specs``, gated on the `cards_discarded_this_turn` delta. Not
    # for direct card use.
    "draw_mill_if_discarded",
    lambda p: DrawMillIfDiscardedEffect(
        player_id=p.get("player_id"), before=int(p.get("before", 0) or 0),
        draw=int(p.get("draw", 2) or 0), mill=int(p.get("mill", 1) or 0),
    ),
)
EffectRegistry.register(
    "put_hand_cards_on_top",  # "put N cards from your hand on top of your library" (Brainstorm)
    lambda p: PutHandCardsOnTopEffect(count=p.get("count", 1), player=p.get("player")),
)
EffectRegistry.register(
    "put_hand_card_on_bottom_then_draw",  # "you may put a card from your hand on the bottom of your library. If you do, draw a card." (Volcanic Spite)
    lambda p: PutHandCardOnBottomThenDrawEffect(player=p.get("player")),
)
EffectRegistry.register(
    "choose_hand_card_to_library_bottom",  # "Put a card from your hand on the bottom of your library." (Jace, Multiverse Architect)
    lambda p: ChooseHandCardToLibraryBottomEffect(),
)
EffectRegistry.register(
    "reveal_hand_choose_discard",  # Duress/Thoughtseize/Coercion-shaped
    lambda p: RevealHandChooseDiscardEffect(
        target_kind=p.get("target_kind", "player"),
        target=p.get("target"),
        exclude_land=bool(p.get("exclude_land", False)),
        exclude_creature=bool(p.get("exclude_creature", False)),
        card_types=p.get("card_types"),
        max_mana_value=p.get("max_mana_value"),
        optional=bool(p.get("optional", False)),
        else_specs=p.get("else_specs"),
        count=p.get("count", 1),
        up_to=bool(p.get("up_to", False)),
        destination=str(p.get("destination", "discard")),
    ),
)
EffectRegistry.register(
    "reveal_random_hand_card_if_named",
    lambda p: RevealRandomHandCardIfNamedEffect(
        named_card=p.get("named_card", ""), target_kind=p.get("target_kind", "opponent"),
        target=p.get("target"),
    ),
)
EffectRegistry.register(
    # "Target opponent reveals a card at random from their hand."
    # (Planeswalker's Favor, PAR-80) — see `RevealRandomHandCardEffect`.
    "reveal_random_hand_card",
    lambda p: RevealRandomHandCardEffect(
        target_kind=p.get("target_kind", "opponent"), target=p.get("target"),
    ),
)
EffectRegistry.register(
    # "Reveal any number of `<color>` cards in your hand." (Ivy Seer, Scent
    # of Ivy, PAR-80) — see `RevealAnyNumberHandCardsEffect`.
    "reveal_any_number_hand_cards",
    lambda p: RevealAnyNumberHandCardsEffect(colors=p.get("colors")),
)
EffectRegistry.register(
    # RULE 701.20 — reveal a library's top card, stash it as
    # `GameContext.revealed_card` (ENG-37 B5). The `of: "revealed"` referent.
    "reveal_top",
    lambda p: RevealTopEffect(whose=p.get("whose", "you")),
)
EffectRegistry.register(
    # Move the revealed card (RULE 121.4 non-draw for "hand"). ENG-37 B5.
    "put_revealed_card",
    lambda p: PutRevealedCardEffect(
        destination=p.get("destination", "hand"), whose=p.get("whose", "you"),
    ),
)
EffectRegistry.register(
    # "You may cast that card without paying its mana cost." (ENG-37 B5).
    "cast_revealed_free",
    lambda p: CastRevealedCardFreeEffect(whose=p.get("whose", "you")),
)
EffectRegistry.register(
    "destroy",
    lambda p: DestroyEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        selector=p.get("selector"),
        filter=p.get("filter"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
        color=p.get("color"),
        colors=p.get("colors"),
        max_mana_value=p.get("max_mana_value"),
        min_mana_value=p.get("min_mana_value"),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        exclude_created=bool(p.get("exclude_created", False)),
        target_from_trigger_event=p.get("target_from_trigger_event"),
        group=p.get("group"), group_player=p.get("group_player"),
        count_selector=p.get("count_selector"),
    ),
)
EffectRegistry.register(
    "regenerate",
    lambda p: RegenerateEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    "gain_life",
    lambda p: GainLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), target_kind=p.get("target_kind"),
        count_selector=p.get("count_selector"),
        count_selector_multiplier=int(p.get("count_selector_multiplier", 1) or 1),
        life_from_target_creature=p.get("life_from_target_creature"),
        target_creature_kind=p.get("target_creature_kind"),
        selector=p.get("selector"),
    ),
)
EffectRegistry.register(
    # RULE 118.5/119.6: "<player>'s life total becomes N." — see `SetLifeEffect`.
    "set_life",
    lambda p: SetLifeEffect(
        amount=int(p.get("amount", 0) or 0),
        target_kind=p.get("target_kind", "player"),
        only_reduce=bool(p.get("only_reduce", False)),
    ),
)
EffectRegistry.register(
    # MEC-54: "For the rest of the game, your maximum life total is N."
    # (You Compleat Me) — a permanent player-scoped cap, see
    # `RulesEngine.set_max_life_total`.
    "set_max_life_total",
    lambda p: SetMaxLifeTotalEffect(amount=int(p.get("amount", 0) or 0)),
)
EffectRegistry.register(
    "prevent_damage_shield",
    # RULE 615 one-shot "prevent all/the next N damage that would be dealt
    # to you this turn" (Riot Control/Thought Lash) — NOT the standing-
    # permanent shape; see `ReplacementRegistry`'s own unrelated
    # `"prevent_damage"` factory below for that (the Sphere/absorb/Shield of
    # the Realm family — MEC-30), or `"request_prevent_damage_source"`/
    # `"prevent_damage_from_target"` just below for the *chosen-source*
    # one-shot family (Circle/Rune of Protection).
    lambda p: PreventDamageEffect(
        amount=p.get("amount", "all"),
        target_kind=p.get("target_kind"),
        creature_filter=p.get("creature_filter"),
        target=p.get("target"),
        count=p.get("count", 1),
        optional=bool(p.get("optional", False)),
        divided=bool(p.get("divided", False)),
        self_only=bool(p.get("self_only", False)),
        watched_source_is_self=bool(p.get("watched_source_is_self", False)),
        recipient_is_activator=bool(p.get("recipient_is_activator", False)),
        combat_only=bool(p.get("combat_only", False)),
        rider=p.get("rider"),
        source_filter=p.get("source_filter"),
        recipient_scope=p.get("recipient_scope"),
        recipient_creatures_scope=p.get("recipient_creatures_scope"),
        recipient_filter=p.get("recipient_filter"),
        attached_only=bool(p.get("attached_only", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "prevent_combat_damage_dealt",
    lambda p: PreventCombatDamageDealtEffect(subject=p.get("subject")),
)
EffectRegistry.register(
    "prevent_all_combat_damage",
    # RULE 615's unscoped Fog-shaped shield — distinct from
    # "prevent_damage_shield" above, which always shields one recipient.
    lambda p: PreventAllCombatDamageEffect(exclude_subtype=p.get("exclude_subtype")),
)
EffectRegistry.register(
    # Kaya, Geist Hunter's −2 — "until end of turn, … twice that many of those tokens are created
    # instead": `double_tokens`' turn-scoped sibling (`DoubleTokensThisTurnEffect`).
    "double_tokens_this_turn",
    lambda p: DoubleTokensThisTurnEffect(multiplier=int(p.get("multiplier", 2) or 2)),
)
EffectRegistry.register(
    "prevent_life_gain",
    # RULE 119.3's "can't gain life this turn" — distinct from
    # "prevent_damage_shield" above (a damage shield, numeric or "all");
    # this cancels a `LIFE_GAIN` outright, no bank to track.
    lambda p: PreventLifeGainEffect(recipient=p.get("recipient", "opponents")),
)
EffectRegistry.register(
    # RULE 104.3a: "You can't lose the game this turn." (Angel's Grace,
    # MEC-43 round 4E)
    "grant_cant_lose_this_turn",
    lambda p: GrantCantLoseThisTurnEffect(),
)
EffectRegistry.register(
    # RULE 104.3a's damage-floor half of Angel's Grace, MEC-43 round 4E.
    "damage_life_floor",
    lambda p: DamageLifeFloorEffect(floor=int(p.get("floor", 1))),
)
EffectRegistry.register(
    "disable_damage_prevention",
    # RULE 615 "Damage can't be prevented this turn." (MEC-30 — Insult //
    # Injury/Isengard Unleashed) — see `DisableDamagePreventionEffect`.
    lambda p: DisableDamagePreventionEffect(),
)
EffectRegistry.register(
    "grant_damage_multiplier_this_turn",
    # RULE 616 "…it deals double/triple that damage instead" (MEC-30), the
    # spell-cast sibling of the standing `"double_damage"` replacement
    # below — see `GrantDamageMultiplierThisTurnEffect`.
    lambda p: GrantDamageMultiplierThisTurnEffect(
        multiplier=int(p.get("multiplier", 2)),
        to_opponent_only=bool(p.get("to_opponent_only", False)),
    ),
)
EffectRegistry.register(
    "commander_damage_multiplier",
    lambda p: StaticAbility(
        "commander_damage_multiplier", affects="all",
        params={"multiplier": int(p.get("multiplier", 3))},
    ),
)
EffectRegistry.register(
    "request_prevent_damage_source",
    # RULE 615/616.1d "the next time a source of your choice would deal
    # damage to `<recipient>` this turn, prevent that damage" (MEC-30 —
    # Circle of Protection/Rune of Protection and siblings) — see
    # `RequestPreventDamageSourceEffect`.
    lambda p: RequestPreventDamageSourceEffect(
        source_filter=p.get("source_filter"),
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        amount=p.get("amount", "all"),
        rider=p.get("rider"),
        optional=bool(p.get("optional", False)),
        recipient=p.get("recipient"),
    ),
)
EffectRegistry.register(
    "request_prevent_damage_chosen_color",
    # RULE 615/616.1d "sources of the color of your choice" (PAR-78 —
    # Avacyn, Guardian Angel) — see `RequestPreventDamageChosenColorEffect`.
    lambda p: RequestPreventDamageChosenColorEffect(
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        amount=p.get("amount", "all"),
    ),
)
EffectRegistry.register(
    "request_redirect_damage_source",
    # RULE 616.1c "the next time a source of your choice would deal damage
    # this turn, that damage is dealt to `<X>` instead" (MEC-30 — Opal-Eye,
    # Konda's Yojimbo) — see `RequestRedirectDamageSourceEffect`.
    lambda p: RequestRedirectDamageSourceEffect(
        source_filter=p.get("source_filter"),
        amount=p.get("amount", "all"),
        recipient=p.get("recipient", "self"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "redirect_damage_to_target_creature",
    lambda p: RedirectDamageToTargetCreatureEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    "choose_source_coinflip",
    # "Choose a source you control and flip a coin. If you win, ... double
    # ... . If you lose, ... prevent ...." (MEC-30 — Desperate Gambit) —
    # see `ChooseSourceCoinFlipEffect`.
    lambda p: ChooseSourceCoinFlipEffect(),
)
EffectRegistry.register(
    "prevent_damage_from_target",
    # RULE 615/616.1d's targeted, no-chooser-needed sibling of
    # "request_prevent_damage_source" above (MEC-30 — Awe Strike/Dazzling
    # Reflection: "the next time **target creature** would deal damage this
    # turn, prevent that damage") — see `PreventDamageFromTargetEffect`.
    lambda p: PreventDamageFromTargetEffect(
        target_kind=p.get("target_kind", "creature"),
        target=p.get("target"),
        count=p.get("count", 1),
        amount=p.get("amount", "all"),
        rider=p.get("rider"),
    ),
)
EffectRegistry.register(
    "extra_land_play",
    lambda p: ExtraLandPlayEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "graveyard_play_permission_this_turn",  # Yawgmoth's Will's own first clause
    lambda p: GraveyardPlayPermissionThisTurnEffect(),
)
EffectRegistry.register(
    "graveyard_redirect_to_exile_this_turn",  # Yawgmoth's Will's own second clause
    lambda p: GraveyardRedirectToExileEffect(),
)
EffectRegistry.register(
    # "Whenever you discard a card, you may exile that card from your
    # graveyard. If you do, you may play that card this turn." (Containment
    # Construct / Conspiracy Theorist / Currency Converter, PAR-60)
    "exile_triggering_discard_may_play_this_turn",
    lambda p: ExileTriggeringDiscardMayPlayThisTurnEffect(
        play_permission=bool(p.get("play_permission", True)),
        track_exiled_with=bool(p.get("track_exiled_with", False)),
    ),
)
EffectRegistry.register(
    # "{T}: Put a card exiled with this artifact into its owner's graveyard.
    # Land -> Treasure; nonland -> 2/2 black Rogue." (Currency Converter, PAR-60)
    "currency_converter_cash_out",
    lambda p: CurrencyConverterCashOutEffect(),
)
EffectRegistry.register(
    "currency_converter_resolve",  # then_specs tail of the chooser branch
    lambda p: CurrencyConverterResolveEffect(),
)
EffectRegistry.register(
    "exchange_life_totals",  # "Two target players exchange life totals." (Soul Conduit)
    lambda p: ExchangeLifeTotalsEffect(
        target_kind=p.get("target_kind"),
        life_difference_at_most=p.get("life_difference_at_most"),
    ),
)
EffectRegistry.register(
    # PAR-30 (RULE 701.10i residue, Mirror Mirror) — see TripleExchangeEffect.
    "triple_exchange",
    lambda p: TripleExchangeEffect(),
)
EffectRegistry.register(
    # "Exchange target opponent's life total with ~'s toughness." (Tree of
    # Perdition) — hand-authored singleton, see the effect's docstring.
    "exchange_life_total_with_toughness",
    lambda p: ExchangeLifeTotalWithToughnessEffect(player_scope=str(p.get("player", "opponent"))),
)
EffectRegistry.register(
    # PAR-30 (RULE 701.10 residue, Juxtapose) — see JuxtaposeEffect.
    "juxtapose",
    lambda p: JuxtaposeEffect(),
)
EffectRegistry.register(
    # PAR-30 (RULE 701.10 residue, Cultural Exchange) — see
    # CulturalExchangeEffect.
    "cultural_exchange",
    lambda p: CulturalExchangeEffect(),
)
EffectRegistry.register(
    "cultural_exchange_round2",
    lambda p: CulturalExchangeRound2Effect(
        from_player_id=p.get("from_player_id"), to_player_id=p.get("to_player_id"),
    ),
)
EffectRegistry.register(
    "lose_life",
    lambda p: LoseLifeEffect(
        amount=p.get("amount", 0), player=p.get("player"), selector=p.get("selector"),
        target_kind=p.get("target_kind"), player_id=p.get("player_id"),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "add_player_counters",
    lambda p: AddPlayerCountersEffect(
        amount=p.get("amount", 0), kind=p.get("kind", "rad"), player=p.get("player"),
        selector=p.get("selector"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "lose_all_player_counters",
    lambda p: LoseAllPlayerCountersEffect(
        kind=p.get("kind", "rad"), player=p.get("player"), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    "counter",
    lambda p: CounterSpellEffect(
        target=p.get("target"),
        unless_pays=p.get("unless_pays"),
        noncreature=bool(p.get("noncreature", False)),
        card_types=p.get("card_types"),
        subtype_any=p.get("subtype_any"),
        mana_value=p.get("mana_value"),
        color=p.get("color"),
        target_from_trigger_event=p.get("target_from_trigger_event"),
        suspend_instead=p.get("suspend_instead"),
        on_pay_effect_specs=p.get("on_pay_effect_specs"),
        unless_pays_extra_selector=p.get("unless_pays_extra_selector"),
        target_kind=p.get("target_kind", "spell"),
        tap_lands_empty_pool_if_unpaid=bool(p.get("tap_lands_empty_pool_if_unpaid", False)),
        exile_then_cast_free=bool(p.get("exile_then_cast_free", False)),  # Transcendent Dragon
        exile_standing_free_cast=bool(p.get("exile_standing_free_cast", False)),  # Kheru Spellsnatcher
    ),
)
EffectRegistry.register(
    # "Counter target activated or triggered ability." (RULE 701.5b —
    # Stifle/Trickbind, ENG-26) — the ability-item sibling of ``"counter"``.
    "counter_ability",
    lambda p: CounterAbilityEffect(target=p.get("target")),
)
EffectRegistry.register(
    "copy_spell",
    lambda p: CopySpellEffect(
        choose_new_targets=bool(p.get("choose_new_targets", False)),
        card_types=p.get("card_types"),
        count=p.get("count", 1),
        target_count=int(p.get("target_count", 1) or 1),
        optional=bool(p.get("optional", False)),
        target_kind=p.get("target_kind", "spell"),
        spell_from_trigger_event=p.get("spell_from_trigger_event"),
        controller_from_trigger_event=p.get("controller_from_trigger_event"),
        count_selector=p.get("count_selector"),
        max_mana_value=p.get("max_mana_value"),
    ),
)
EffectRegistry.register(
    # "Copy that ability." (RULE 707.10 — Rings of Brighthearth) — the
    # ability-item sibling of ``"copy_spell"``; ``"that ability"`` is read
    # off `GameObject.remembered_stack_id`, not a target.
    "copy_ability",
    lambda p: CopyAbilityEffect(choose_new_targets=bool(p.get("choose_new_targets", False))),
)
EffectRegistry.register(
    # "Copy target activated or triggered ability you control X times." (Gogo, Master of Mimicry)
    "copy_target_ability",
    lambda p: CopyTargetAbilityEffect(choose_new_targets=bool(p.get("choose_new_targets", False))),
)
EffectRegistry.register(
    # "Conjure a duplicate of that spell into your hand." (Spellchain
    # Scatter, PAR-124) — the hand-zone sibling of ``"copy_spell"``.
    "conjure_duplicate_into_hand",
    lambda p: ConjureDuplicateIntoHandEffect(
        spell_from_trigger_event=p.get("spell_from_trigger_event"),
    ),
)
EffectRegistry.register(
    "copy_self_spell",
    lambda p: CopySelfSpellEffect(controller=p.get("controller"), choose_new_targets=bool(p.get("choose_new_targets", False))),
)
EffectRegistry.register(
    "change_target",
    lambda p: ChangeTargetEffect(
        target=p.get("target"),
        single_target=bool(p.get("single_target", False)),
        optional=bool(p.get("optional", False)),
        spell_or_ability=bool(p.get("spell_or_ability", False)),
        card_types=p.get("card_types"),
        redirect_to_source=bool(p.get("redirect_to_source", False)),
    ),
)
EffectRegistry.register(
    # "Gain control of target noncreature spell. You may choose new targets
    # for it." (Commandeer)
    "gain_control_of_spell",
    lambda p: GainControlOfSpellEffect(target=p.get("target")),
)
EffectRegistry.register(
    # RULE 701.10i (PAR-30 residue) — Perplexing Chimera / Sudden
    # Substitution. See `ExchangeControlSpellEffect`.
    "exchange_control_spell",
    lambda p: ExchangeControlSpellEffect(
        permanent_target_kind=p.get("permanent_target_kind"),
        spell_filter=p.get("spell_filter"),
        reflexive_spell=bool(p.get("reflexive_spell", False)),
    ),
)
EffectRegistry.register(
    # "Return it to the battlefield [tapped] under its owner's control."
    # (Nezahal, Primal Tide's own delayed-trigger half)
    "return_self_to_battlefield",
    lambda p: ReturnSelfToBattlefieldEffect(
        tapped=bool(p.get("tapped", False)),
        under_your_control=bool(p.get("under_your_control", False)),
        extra_counters=p.get("extra_counters"),
        lose_all_abilities=bool(p.get("lose_all_abilities", False)),
        target_kind=p.get("target_kind"),
        trigger_event_key=p.get("trigger_event_key"),
        face_down_kind=p.get("face_down_kind"),
        turn_face_up=bool(p.get("turn_face_up", False)),
    ),
)
EffectRegistry.register(
    # "Whenever ~ deals combat damage to a player, reveal that many cards
    # from the top of your library. You may put a creature card and/or a
    # land card from among them onto the battlefield. Put the rest on the
    # bottom in a random order." (Ojer Kaslem, Deepest Growth)
    "reveal_top_then_creature_and_or_land_battlefield",
    lambda p: RevealTopThenCreatureAndOrLandBattlefieldEffect(
        amount=p.get("amount", 0),
    ),
)
EffectRegistry.register(
    # `RevealTopThenCreatureAndOrLandBattlefieldEffect`'s own land-half
    # continuation — never placed in a card's own `AbilitySpec`, only in
    # that effect's own `then_specs`/`else_specs`.
    "ojer_kaslem_land_pick",
    lambda p: OjerKaslemLandPickEffect(),
)
EffectRegistry.register(
    # "When ~ dies, if it was a creature, return it to the battlefield
    # under its owner's control. It's an enchantment." (Enduring Vitality)
    "dies_return_as_enchantment",
    lambda p: DiesReturnAsEnchantmentEffect(),
)
EffectRegistry.register(
    # "Each creature you control deals damage equal to its power to each
    # opponent." (Lukka, Coppercoat Outcast)
    "each_creature_you_control_damages_each_opponent",
    lambda p: EachCreatureYouControlDamageEachOpponentEffect(),
)
EffectRegistry.register(
    # "<subject> deals damage equal to its power to each opponent."
    # (Champion of the Path / Gau, Feral Youth / Giggling Skitterspike /
    # Pyrotechnic Performer — PAR-30)
    "subject_damages_each_opponent_equal_to_power",
    lambda p: SubjectDamagesEachOpponentEqualToPowerEffect(),
)
EffectRegistry.register(
    # "Creature cards exiled this way gain 'You may cast this card from
    # exile as long as `<condition>`.'" (Lukka, Coppercoat Outcast's +1) —
    # the grant half of the retired `exile_top_then_grant_conditional_cast`
    # fusion; reads the just-exiled batch off `GameContext.created_objects`.
    "grant_conditional_cast_from_exile",
    lambda p: GrantConditionalCastFromExileEffect(
        condition=p.get("condition"), all_cards=bool(p.get("all_cards", False)),
        linked_source=bool(p.get("linked_source", False)),
        cost_override=p.get("cost_override"),
        exiled_this_way=bool(p.get("exiled_this_way", False)),
        permanent_only=bool(p.get("permanent_only", False)),
        any_color=bool(p.get("any_color", False)),
        during_resolution=bool(p.get("during_resolution", False)),
    ),
)
EffectRegistry.register(
    # "You and target opponent each reveal the top card of your library.
    # You each lose life equal to the mana value of the card revealed by
    # the other player. You each put the card you revealed into your
    # hand." (MEC-43 round 4F, Keen Duelist) — the genuinely new
    # simultaneous two-player sibling of `reveal_top_then_take_and_lose_
    # life` just above.
    "mutual_reveal_compare_mana_value",
    lambda p: MutualRevealCompareManaValueEffect(target_kind=p.get("target_kind", "opponent")),
)
EffectRegistry.register(
    # "End the turn." (Day's Undoing/Time Stop-shaped reminder text)
    "end_the_turn",
    lambda p: EndTheTurnEffect(),
)
EffectRegistry.register("cant_be_countered", lambda p: CantBeCounteredEffect())
EffectRegistry.register(
    "grant_cant_be_countered",
    lambda p: GrantCantBeCounteredEffect(scope=p.get("scope", "you"), color=p.get("color")),
)
EffectRegistry.register(
    "demonstrate_copy",  # RULE 702.144a — the body of a Demonstrate cast trigger
    lambda p: DemonstrateCopyEffect(),
)
EffectRegistry.register(
    "attacked_curse_gold",  # Curse of Opulence
    lambda p: AttackedCurseGoldEffect(),
)
EffectRegistry.register(
    "draw_per_damage_dealt_to_source",  # Grothama, All-Devouring
    lambda p: DrawPerDamageDealtToSourceEffect(),
)
EffectRegistry.register(
    "reselect_attack",  # Misleading Signpost
    lambda p: ReselectAttackEffect(),
)
EffectRegistry.register(
    "fight_each_opposing_creature",  # Ezuri's Predation
    lambda p: FightEachOpposingCreatureEffect(),
)
EffectRegistry.register(
    # "You don't lose unspent red mana as steps and phases end." (Leyline Tyrant) — a standing permission read by
    # `continuous.empty_mana_pool` as each step ends; no ``colors`` keeps every colour.
    "retain_mana",
    lambda p: StaticAbility("retain_mana", affects="self", params={"colors": list(p.get("colors") or [])}),
)
EffectRegistry.register(
    # "If you would lose unspent mana, that mana becomes colorless instead." (Omnath, Locus of the Void) — a standing
    # replacement read by `continuous.empty_mana_pool` as each step ends.
    "unspent_mana_colorless",
    lambda p: StaticAbility("unspent_mana_colorless", affects="self", params={}),
)
EffectRegistry.register(
    "behold_then",  # "You may behold a Dragon. If you do, …" (Sarkhan, Dragon Ascendant)
    lambda p: BeholdThenEffect(quality=p.get("quality", "Dragon"), effects=p.get("effects")),
)
EffectRegistry.register(
    "exile_top_play_then_burn",  # Dragonhawk, Fate's Tempest
    lambda p: ExileTopPlayThenBurnEffect(count_selector=p.get("count_selector"), amount=p.get("amount", 2)),
)
EffectRegistry.register(
    # "~ enters with a number of +1/+1 counters on it equal to 1 plus the number of other creatures you control." (Boss's
    # Chauffeur) — read by `RulesEngine._apply_entry_counters`; ``base`` plus a `count_selector` as it enters.
    "enters_with_counters_count",
    lambda p: StaticAbility("entry_counters_self", affects="self", params={
        "kind": str(p.get("kind", "+1/+1")), "base": int(p.get("base", 0)),
        # A named selector, or a structured ``{zone, of, filter}`` one (Diregraf Colossus's Zombie cards in
        # your graveyard) — `continuous.count_selector` takes both.
        "count_selector": p["count_selector"] if isinstance(p.get("count_selector"), dict) else str(p.get("count_selector", "")),
        # Sin, Unending Cataclysm: strip counters from a scope of permanents as it enters; X = ``multiplier`` × counters removed.
        **({"remove_counters_scope": str(p["remove_counters_scope"])} if p.get("remove_counters_scope") else {}),
        "multiplier": int(p.get("multiplier", 1)),
    }),
)
EffectRegistry.register(
    "grant_search_prohibited",
    lambda p: GrantSearchProhibitedEffect(scope=p.get("scope", "opponents")),
)
EffectRegistry.register(
    "grant_search_limited_to_top_n",
    lambda p: GrantSearchLimitedToTopNEffect(n=p.get("n", p.get("count", 4))),
)
EffectRegistry.register("grant_skip_extra_turns", lambda p: GrantSkipExtraTurnsEffect())
EffectRegistry.register(
    "mark_cant_be_countered",
    lambda p: MarkCantBeCounteredEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    # "Spells you control can't be countered this turn." (Veil of Summer), "Creature spells
    # you cast this turn can't be countered." (Domri), "The next spell you cast this turn
    # can't be countered." (Mistrise Village)
    "cant_be_countered_this_turn",
    lambda p: CantBeCounteredThisTurnEffect(
        card_types=p.get("card_types"), next_only=bool(p.get("next_only", False)),
    ),
)
EffectRegistry.register(
    "look_at_cards",  # "look at the top card of target player's library" (Mishra's Bauble)
    lambda p: LookAtCardsEffect(target=p.get("target"), target_kind=p.get("target_kind", "player")),
)
EffectRegistry.register(
    "mill", lambda p: MillEffect(
        count=p.get("count", 1), target_kind=p.get("target_kind"),
        count_selector=p.get("count_selector"), selector=p.get("selector"), half=p.get("half"),
        capture_milled=bool(p.get("capture_milled", False)),
        any_number_of_players=bool(p.get("any_number_of_players", False)),
    )
)
EffectRegistry.register(
    "sacrifice_self",  # "Sacrifice ~." (Dress Down/Underworld Breach-shaped)
    lambda p: SacrificeSelfEffect(
        target_kind=p.get("target_kind"), trigger_event_key=p.get("trigger_event_key"),
    ),
)
EffectRegistry.register("sacrifice_target", lambda p: SacrificeTargetEffect())
EffectRegistry.register(
    "sacrifice_controller_permanent",
    lambda p: SacrificeControllerPermanentEffect(what=p.get("what", "permanent")),
)
EffectRegistry.register(
    "sacrifice_unless_attacked",
    lambda p: SacrificeUnlessAttackedEffect(),
)
EffectRegistry.register(
    # "Sacrifice ~ unless you pay <cost>." (Arcades Sabboth/Breeding Pit/
    # Child of Gaea) — an interactive pay-or-lose-it choice, not a plain
    # sacrifice. ``cost`` is the printed cost *text*, parsed to an
    # `ActivationCost` at resolution.
    "sacrifice_unless_pay",
    lambda p: SacrificeUnlessPayEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # "Destroy ~ unless you pay <cost>." (The Tabernacle at Pendrell Vale's
    # mass granted upkeep trigger) — RULE 701.16's real-destruction sibling
    # of "sacrifice_unless_pay" above (regenerable — see
    # `DestroyUnlessPayEffect`'s docstring).
    "destroy_unless_pay",
    lambda p: DestroyUnlessPayEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # "Whenever an opponent casts a spell, you may draw a card unless that
    # player pays <cost>." (Rhystic Study/Mystic Remora/Esper Sentinel) —
    # the payer is the *triggering* event's caster, not this ability's
    # controller.
    "taxed_draw",
    lambda p: TaxedDrawEffect(
        cost=p.get("cost", ""),
        amount=p.get("amount"),
        count=int(p.get("count", 1) or 1),
    ),
)
EffectRegistry.register(
    # PAR-13: "Each player loses N life unless they `<pay cost>`." — the
    # APNAP mass sibling of `sacrifice_unless_pay` above.
    "each_player_pay_or",
    lambda p: EachPlayerPayOrEffect(
        cost=p.get("cost", ""), effects=list(p.get("effects", [])),
        scope=p.get("scope", "each_player"), effect_targets=p.get("effect_targets", "decliner"),
        sacrifice_or_discard=bool(p.get("sacrifice_or_discard", False)),
    ),
)
EffectRegistry.register(
    "exile",
    lambda p: ExileEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        selector=p.get("selector"),
        filter=p.get("filter"),
        remember=bool(p.get("remember", False)),
        until_source_leaves=bool(p.get("until_source_leaves", False)),
        until_opponent_monarch=bool(p.get("until_opponent_monarch", False)),
        creature_filter=p.get("creature_filter"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        track_exiled_with=bool(p.get("track_exiled_with", False)),
        max_mana_value=p.get("max_mana_value"),
        min_mana_value=p.get("min_mana_value"),
        grant_owner_play_permission=bool(p.get("grant_owner_play_permission", False)),
        owner_play_permission_tax=p.get("owner_play_permission_tax"),
        owner_play_permission_cost=p.get("owner_play_permission_cost"),
        trigger_event_key=p.get("trigger_event_key"),
        grant_free_cast_window=bool(p.get("grant_free_cast_window", False)),
        spell_or_permanent=bool(p.get("spell_or_permanent", False)),
        colors=p.get("colors"),
        bend_kind=p.get("bend_kind"),
        count_selector=p.get("count_selector"),
        unless_flag=p.get("unless_flag"),
        kind_if_flag=p.get("kind_if_flag"),
        group=p.get("group"), group_player=p.get("group_player"),
    ),
)
EffectRegistry.register(
    "exile_own_graveyard_cards",
    lambda p: ExileOwnGraveyardCardsEffect(count=int(p.get("count", 1) or 1)),
)
EffectRegistry.register(
    # "Exile the top card of your library[, face down]." (MEC-38,
    # Necropotence) — deterministic, no chooser, unlike "exile"/"search".
    "exile_top_of_library",
    lambda p: ExileTopOfLibraryEffect(
        face_down=bool(p.get("face_down", False)),
        player_selector=p.get("player_selector", "controller"),
        count=p["count"] if isinstance(p.get("count"), dict) else int(p.get("count", 1) or 1),
        keep_bottom=p.get("keep_bottom"),
        track_exiled_with=bool(p.get("track_exiled_with", False)),
        target_kind=p.get("target_kind"),
        position=p.get("position", "top"),
    ),
)
EffectRegistry.register(
    # "If it's a land card, the player puts it onto the battlefield.
    # Otherwise, the player casts it without paying its mana cost if
    # able." (MEC-33, Omen Machine/Wild Evocation's shared tail) — see
    # `LandOrFreeCastEffect`.
    "land_or_free_cast",
    lambda p: LandOrFreeCastEffect(player_selector=p.get("player_selector", "controller")),
)
EffectRegistry.register(
    # "Put that card into your hand." (MEC-38, Necropotence's own delayed
    # trigger, and Beseech the Mirror/Rebound's existing "if it wasn't
    # cast this way" tail — see `ReturnUncastExiledEffect`'s own
    # docstring) — never built as its own EffectSpec entry point before;
    # every prior use constructed it directly in Python inside another
    # effect's own `apply()`. ``exiled_object`` is set at resolve time by
    # `CreateDelayedTriggerEffect`'s `capture="created_objects"`, never a
    # bare param (a raw object reference can't cross the EffectSpec
    # security boundary).
    "return_uncast_exiled",
    lambda p: ReturnUncastExiledEffect(exiled_object=None, destination=p.get("destination", "hand")),
)
EffectRegistry.register(
    # RULE 702.45-adjacent Imprint: "you may exile a `<filter>` card from
    # your hand." (MEC-17, Chrome Mox-shaped) — see `ImprintEffect`.
    "imprint",
    lambda p: ImprintEffect(
        optional=bool(p.get("optional", True)),
        exclude_card_types=p.get("exclude_card_types"),
        include_card_type=p.get("include_card_type"),
        max_mana_value=p.get("max_mana_value"),
        pool=p.get("pool", "hand"),
    ),
)
EffectRegistry.register(
    "become_copy_of_imprinted_until_eot",  # Dermotaxi
    lambda p: BecomeCopyOfImprintedUntilEndOfTurnEffect(add_types=p.get("add_types"), add_subtypes=p.get("add_subtypes")),
)
EffectRegistry.register(
    # "You may copy the exiled card. If you do, you may cast the copy
    # without paying its mana cost." (Isochron Scepter) — see
    # `CopyImprintedCardEffect`.
    "copy_imprinted_card",
    lambda p: CopyImprintedCardEffect(),
)
EffectRegistry.register(
    # RULE 601.2b-adjacent "as ~ enters, you may choose a nonland
    # permanent." (MEC-26, Scheming Fence) — see `ChoosePermanentEffect`.
    "choose_permanent",
    lambda p: ChoosePermanentEffect(optional=bool(p.get("optional", True))),
)
EffectRegistry.register(
    # "Whenever a player casts a spell, that player returns a land they
    # control to its owner's hand." (Mana Breach, MEC-43) — see
    # `BounceOwnLandFromTriggerEffect`.
    "bounce_own_land_from_trigger",
    lambda p: BounceOwnLandFromTriggerEffect(),
)
EffectRegistry.register(
    # RULE 601.2f-adjacent "you may cast a spell with mana value N or less
    # from your hand without paying its mana cost." (MEC-20, the
    # "Expertise" cycle) — see `FreeCastFromHandEffect`.
    "free_cast_from_hand",
    lambda p: FreeCastFromHandEffect(
        criteria={"max_mana_value": p.get("max_mana_value")},
        max_mana_value_selector=p.get("max_mana_value_selector"),
        noncreature_only=bool(p.get("noncreature_only", False)),
        mana_value_from_trigger=bool(p.get("mana_value_from_trigger", False)),
        permanent_only=bool(p.get("permanent_only", False)),
        else_effects=p.get("else_effects"),
        shares_type_with_trigger=bool(p.get("shares_type_with_trigger", False)),
        strictly_less_than_trigger=bool(p.get("strictly_less_than_trigger", False)),
        arm_all=bool(p.get("arm_all", False)),
        during_resolution=bool(p.get("during_resolution", False)),
    ),
)
EffectRegistry.register(
    "exile_bottom_graveyard_card",  # "Exile the bottom card of target player's graveyard." (Phyrexian Furnace)
    lambda p: ExileBottomGraveyardCardEffect(target_kind=p.get("target_kind", "player")),
)
EffectRegistry.register(
    "exile_all_graveyards",
    lambda p: ExileAllGraveyardsEffect(
        colors=p.get("colors"), opponents_only=bool(p.get("opponents_only", False)), card_type=p.get("card_type"),
    ),
)
EffectRegistry.register(
    "exile_graveyard_card_counter_if_permanent",  # Lion Sash
    lambda p: ExileGraveyardCardCounterIfPermanentEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "any_graveyard_card")
    ),
)
EffectRegistry.register(
    "exile_target_graveyard",  # Bojuka Bog/Tormod's Crypt; Crypt Incursion (card_type)
    lambda p: ExileTargetGraveyardEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        card_type=p.get("card_type"),
    ),
)
EffectRegistry.register(
    # "Whenever a player attacks one of your opponents, that attacking
    # player creates a tapped … token that's attacking that opponent."
    # (Combat Calligrapher, PAR-60)
    "attacker_creates_attacking_token",
    lambda p: AttackerCreatesAttackingTokenEffect(
        power=p.get("power"), toughness=p.get("toughness"),
        colors=list(p.get("colors", [])), subtypes=list(p.get("subtypes", [])),
        keywords=list(p.get("keywords", [])),
        token_name=p.get("token_name"),
    ),
)
EffectRegistry.register(
    # "Destroy/Exile target creature. … Its controller reveals cards from
    # the top of their library until they reveal a creature card, puts it
    # onto the battlefield, then shuffles the rest into their library."
    # (Polymorph destroy-mode / Transmogrify exile-mode)
    "destroy_exile_then_controller_reveal_creature",
    lambda p: DestroyExileThenControllerRevealCreatureEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
        mode=p.get("mode", "destroy"), criteria=p.get("criteria", "Creature"),
    ),
)
EffectRegistry.register(
    # Zealous Conscripts / Coercive Recruiter (default: end-of-turn, untap,
    # haste); with ``duration="permanent"`` + ``untap=False`` + ``haste=
    # False`` it is the Mind Control / Control Magic / Entrancing Melody
    # family instead (RULE 611.2 no-duration control change, PAR-60).
    "gain_control_until_eot",
    lambda p: GainControlUntilEndOfTurnEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
        haste=bool(p.get("haste", True)), max_mana_value=p.get("max_mana_value"),
        exact_mana_value=p.get("exact_mana_value"),
        selector=p.get("selector"), creature_filter=p.get("creature_filter"),
        count_selector=p.get("count_selector"),
        mass_of_target_player=p.get("mass_of_target_player"),
        mark_no_sacrifice=bool(p.get("mark_no_sacrifice", False)),
        duration=str(p.get("duration", "end_of_turn")),
        untap=bool(p.get("untap", True)),
        player_from_trigger_event=p.get("player_from_trigger_event"),
    ),
)
EffectRegistry.register(
    # "You can't attack that player this turn." (Call for Aid) — "that
    # player" is this effect's own shared RULE 115 target (the opponent
    # whose creatures were taken); "you" is the ability's controller. Bars
    # the pair in `GameState.no_attack_pairs_this_turn` for the rest of the
    # turn; no `target_spec` of its own (it reads `targets[0]`, the same
    # "no target_spec, sees the shared list" idiom `ConditionalEffect` uses).
    "prevent_attacking_player_this_turn",
    lambda p: PreventAttackingPlayerThisTurnEffect(reversed=bool(p.get("reversed", False))),
)
EffectRegistry.register(
    # "Creatures they control can't attack Jaces you control this turn." (Jace, Multiverse Architect) — "they" is the
    # decliner of the pay-or flow it follows.
    "prevent_attacking_planeswalkers_this_turn",
    lambda p: PreventAttackingPlaneswalkersThisTurnEffect(subtype=str(p.get("subtype", "jace"))),
)
EffectRegistry.register(
    "return_linked_exile",
    lambda p: ReturnLinkedExileEffect(destination=p.get("destination", "battlefield")),
)
EffectRegistry.register(
    # "You may behold a(n) <type>. If you do, untap that land." (Elven
    # Passage — PAR-30) — reads the fetched land off `linked_exile_id`.
    "may_behold_untap_linked",
    lambda p: MayBeholdThenUntapLinkedEffect(quality=p.get("quality", "Elf")),
)
EffectRegistry.register(
    # Incinerator of the Guilty (PAR-30): dynamic "collect evidence X" +
    # "X damage to each creature and planeswalker that player controls".
    "collect_evidence_x_then_board_damage",
    lambda p: CollectEvidenceXThenBoardDamageEffect(),
)
EffectRegistry.register(
    # Memory Vampire (PAR-30): dynamic multi-target mill + collect evidence
    # 9 + free-cast a nonland card from the defending player's graveyard.
    "memory_vampire_combat",
    lambda p: MemoryVampireCombatEffect(),
)
EffectRegistry.register(
    # Celestial Reunion (PAR-30): search for a creature card with mana value
    # X or less; onto the battlefield instead of into hand if the optional
    # behold-two additional cost was paid and it's the chosen type.
    "celestial_reunion_search",
    lambda p: CelestialReunionSearchEffect(),
)
EffectRegistry.register(
    "return_all_exiled_with",
    lambda p: ReturnAllExiledWithEffect(counter_if_creature=p.get("counter_if_creature"), tapped=bool(p.get("tapped", False))),
)
EffectRegistry.register("transfer_exiled_with_to_created", lambda p: TransferExiledWithToCreatedEffect())  # Mechtitan Core
EffectRegistry.register(  # "Exile ~ with three time counters on it." (Suspended Sentence)
    "exile_self_with_counters",
    lambda p: ExileSelfWithCountersEffect(kind=str(p.get("kind", "time")), count=int(p.get("count", 1) or 1)),
)
EffectRegistry.register(
    "exile_any_number_you_control",
    lambda p: ExileAnyNumberYouControlEffect(other_only=bool(p.get("other_only", True))),
)
EffectRegistry.register(
    "create_token_for_linked_exile",
    lambda p: CreateTokenForLinkedExileEffect(
        colors=p.get("colors"), subtypes=p.get("subtypes"), keywords=p.get("keywords"),
    ),
)
EffectRegistry.register(
    "exile_own_graveyard_card_mana_value_x",
    lambda p: ExileOwnGraveyardCardManaValueXEffect(
        creature_only=bool(p.get("creature_only", True)), then_specs=p.get("then_specs"),
    ),
)
EffectRegistry.register(
    "choose_void_counter_card",
    lambda p: ChooseVoidCounterCardEffect(),
)
EffectRegistry.register("exile_library", lambda p: ExileLibraryEffect())
EffectRegistry.register(
    "shuffle_target_into_library_reveal_top",  # Chaos Warp
    lambda p: ShuffleTargetIntoLibraryRevealTopEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent"),
    ),
)
EffectRegistry.register(
    "shuffle_graveyard_into_library",
    lambda p: ShuffleGraveyardIntoLibraryEffect(owner_of_source=bool(p.get("owner_of_source", False))),
)
EffectRegistry.register(
    # "Target player shuffles up to three target cards from their graveyard
    # into their library." (Quandrix Command mode 4)
    "shuffle_target_graveyard_cards_into_library",
    lambda p: ShuffleTargetGraveyardCardsIntoLibraryEffect(
        count_max=int(p.get("count_max", 3) or 3),
    ),
)
EffectRegistry.register(
    "no_max_hand_size_rest_of_game", lambda p: NoMaxHandSizeRestOfGameEffect()
)
EffectRegistry.register(
    "graveyard_to_library_bottom_random",  # Endurance
    lambda p: GraveyardToLibraryBottomRandomEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "player"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    # Borne Upon a Wind (unrestricted) / Complete the Circuit ("sorcery
    # spells", PAR-124's ``card_types`` narrowing).
    "grant_flash_until_eot",
    lambda p: GrantFlashUntilEndOfTurnEffect(card_types=p.get("card_types"), next_only=bool(p.get("next_only", False))),
)
EffectRegistry.register(
    "become_saddled", lambda p: BecomeSaddledEffect(),  # Guardian Sunmare's own "Saddle N"
)
EffectRegistry.register(
    "sylvan_library",
    lambda p: SylvanLibraryEffect(life=int(p.get("life", 4)), count=int(p.get("count", 2))),
)
EffectRegistry.register(
    "trigger_doubler",  # Roaming Throne / Panharmonicon / Elesh Norn, Mother of Machines / Delney …
    lambda p: TriggerDoublerEffect(
        cause=p.get("cause"), subject=p.get("subject"), active_if=p.get("active_if"),
        attached=p.get("affects") == "attached_permanent", tap_cost=p.get("tap_cost"),
    ),
)
EffectRegistry.register(
    "damage_then_investigate_if_excess",  # Torch the Witness
    lambda p: DamageThenInvestigateIfExcessEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "grant_graveyard_cast_permission_this_turn",  # Backdraft Hellkite, Kethis
    lambda p: GrantGraveyardCastPermissionThisTurnEffect(
        spell_criteria=p.get("spell_criteria"),
        instant_sorcery_only=bool(p.get("instant_sorcery_only", True)),
        plays_lands=bool(p.get("plays_lands", False)),
    ),
)
EffectRegistry.register(
    # MEC-24: "target instant or sorcery card in your graveyard gains
    # flashback [<cost>] until end of turn." — Recoup/Snapcaster Mage-shaped.
    # See `GrantFlashbackToTargetEffect`'s own docstring for why this is a
    # per-graveyard-card marker rather than reusing the untargeted grant
    # just above.
    "grant_flashback_to_target",
    lambda p: GrantFlashbackToTargetEffect(
        cost=p.get("cost"), target_kind=p.get("target_kind", "graveyard_instant_or_sorcery"),
        as_permission=bool(p.get("as_permission", False)),
        lock_casting=bool(p.get("lock_casting", False)),
        during_resolution=bool(p.get("during_resolution", False)),
    ),
)
EffectRegistry.register(
    "grant_self_activated_ability",  # Urza's Saga's own chapter grants
    lambda p: GrantSelfActivatedAbilityEffect(
        cost=p.get("cost"), effects=p.get("effects"),
    ),
)
EffectRegistry.register(
    # "Exile all the cards from your hand." — the untargeted hidden-zone
    # sibling of `exile_library`. "…then draw that many" (Invasion of
    # Kaldheim) is a `bind` over `resource: hand_size` around this.
    "exile_hand",
    lambda p: ExileHandEffect(),
)
EffectRegistry.register(
    # Etali, Primal Storm (top card only); Etali, Primal Conqueror's ETB
    # passes until_nonland=True (dig past lands to the first nonland hit).
    "exile_top_from_each_player_cast_free",
    lambda p: ExileTopFromEachPlayerCastFreeEffect(until_nonland=bool(p.get("until_nonland", False))),
)
EffectRegistry.register(
    # "Look at the top seven cards of your library. You may cast an instant or sorcery spell with
    # mana value ≤ ~'s power from among them without paying its mana cost. Put the rest on the bottom
    # in a random order." (Velomachus Lorehold)
    "look_top_cast_free",
    lambda p: LookTopCastFreeEffect(
        count=p.get("count", 7), criteria=p.get("criteria"), max_mana_value_from=p.get("max_mana_value_from"),
        prompt=p.get("prompt"),
    ),
)
EffectRegistry.register(
    "grant_die_to_exile_this_turn",  # Lava Coil/Smite the Deathless/Torch the Tower
    lambda p: GrantDieToExileThisTurnEffect(
        target=p.get("target"), target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject", False)),
        damaged_this_way=bool(p.get("damaged_this_way", False)),  # MEC-81
        creature_only=bool(p.get("creature_only", False)),  # PAR-128 (Carbonize)
    ),
)
EffectRegistry.register(
    "each_opponent_counter_own_creature",  # High Perfect Morcant's "blights"
    lambda p: EachOpponentCounterOwnCreatureEffect(
        amount=int(p.get("amount", 1) or 1), kind=p.get("kind", "-1/-1"),
    ),
)
EffectRegistry.register(
    "transform_named_tokens",  # Glissa, Herald of Predation
    lambda p: TransformNamedTokensEffect(
        token_name=p.get("token_name", "Incubator"),
        add_types=p.get("add_types"),
        add_subtypes=p.get("add_subtypes"),
        power=int(p.get("power", 0) or 0),
        toughness=int(p.get("toughness", 0) or 0),
    ),
)
EffectRegistry.register(
    "top_up_player_counter",  # Vraska, Betrayal's Sting's -9
    lambda p: TopUpPlayerCounterToThresholdEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "player"),
        kind=p.get("kind", "poison"),
        threshold=int(p.get("threshold", 9) or 9),
    ),
)
EffectRegistry.register(
    "exile_controller_searches_basic_land",  # Winds of Abandon
    lambda p: ExileControllerSearchesBasicLandEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "_request_choose_player",  # Stuffy Doll; ``opponents_only``/``then_effects``: Intellectual Offering
    lambda p: RequestChoosePlayerEffect(
        opponents_only=bool(p.get("opponents_only", False)), then_effects=p.get("then_effects"),
    ),
)
EffectRegistry.register("slithermuse", lambda p: SlithermuseEffect())
EffectRegistry.register("haunt", lambda p: HauntEffect())
EffectRegistry.register(
    "haunt_linked_death", lambda p: HauntLinkedDeathEffect(effects=p.get("effects")),
)
EffectRegistry.register(
    "cast_graveyard_instant_sorcery_free_exile",
    lambda p: CastGraveyardInstantSorceryFreeExileEffect(
        pick=bool(p.get("pick", False)), max_mana_value=p.get("max_mana_value"),
        target_kind=p.get("target_kind", "any_graveyard_instant_or_sorcery"),
    ),
)
EffectRegistry.register(
    "deal_damage_to_chosen_player", lambda p: DealDamageToChosenPlayerEffect()  # Stuffy Doll
)
EffectRegistry.register(
    "_request_choose_creature_type_grant",  # Selfless Safewright
    lambda p: RequestChooseCreatureTypeGrantEffect(then_specs=p.get("then_specs")),
)
EffectRegistry.register(
    "grant_keywords_to_chosen_type_until_eot",  # Selfless Safewright
    lambda p: GrantKeywordsToChosenTypeUntilEotEffect(keywords=p.get("keywords")),
)
EffectRegistry.register(
    "grant_keyword_to_trigger_subject",  # Tyvar Kell's emblem
    lambda p: GrantKeywordToTriggerSubjectEffect(
        keyword=p.get("keyword", "haste"), event_key=p.get("event_key", "instance_id"),
    ),
)
EffectRegistry.register(
    # "each player exiles a card from their graveyard. When one or more
    # nonland cards are exiled this way, put that many +1/+1 counters on
    # target attacking creature." (Augusta, Order Returned, PAR-60)
    "each_player_exile_from_graveyard_then_counters",
    lambda p: EachPlayerExileFromGraveyardThenCountersEffect(
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "destroy_controller_may_search_basic_land",  # Boseiju, Who Endures
    lambda p: DestroyControllerMaySearchBasicLandEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "artifact_enchantment_or_nonbasic_land"),
        can_be_regenerated=bool(p.get("can_be_regenerated", True)),
    ),
)
EffectRegistry.register("peek_top_land_battlefield_tapped", lambda p: PeekTopLandBattlefieldTappedEffect())
EffectRegistry.register(
    "peek_top_land_or_hand",  # Risen Reef; ``reveal_then``: Fisher's Talent's "you may reveal it if it's a land"
    lambda p: PeekTopLandOrHandEffect(reveal_then=p.get("reveal_then")),
)
EffectRegistry.register(
    # "Target player puts a +1/+1 counter on each creature they control."
    # (Shadrix Silverquill's third mode, PAR-60)
    "target_player_counter_each_creature",
    lambda p: TargetPlayerCounterEachCreatureEffect(
        amount=int(p.get("amount", p.get("count", 1)) or 1),
        kind=str(p.get("kind", "+1/+1")),
        target=p.get("target"), target_kind=str(p.get("target_kind", "player")),
    ),
)
EffectRegistry.register(
    "return_to_hand",  # "return target X to its owner's hand" (RULE 701.3)
    lambda p: ReturnToHandEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        selector=p.get("selector"),
        filter=p.get("filter"),
        spell_or_permanent=bool(p.get("spell_or_permanent", False)),
        creature_filter=p.get("creature_filter"),
        colors=p.get("colors"),
        to_library_top_if_clash_won=bool(p.get("to_library_top_if_clash_won", False)),
        then_specs=p.get("then_specs"),
        trigger_event_key=p.get("trigger_event_key"),
        group=p.get("group"), group_player=p.get("group_player"),
        count_selector=p.get("count_selector"),
        exact_mana_value=p.get("exact_mana_value"),
        max_mana_value=p.get("max_mana_value"),
    ),
)
EffectRegistry.register(
    # "Return each creature with power of the chosen quality to its owner's
    # hand. (Zero is even.)" (Zimone's Hypothesis, PAR-60)
    "return_creatures_by_power_parity",
    lambda p: ReturnCreaturesByPowerParityEffect(parity=str(p.get("parity", "even"))),
)
EffectRegistry.register(
    "return_to_library",  # "put target X on top/bottom of its owner's library" (RULE 701.3)
    lambda p: ReturnToLibraryEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        position=p.get("position", "top"),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        colors=p.get("colors"),
        depth=p.get("depth", 1),
        group=p.get("group"),
    ),
)
EffectRegistry.register("put_hand_on_bottom", lambda p: PutHandOnBottomEffect())
EffectRegistry.register(
    # "Shuffle ~ into its owner's library." (Green Sun's Zenith); with
    # ``subject="attached_permanent"`` the Aura-host form (Watery Grasp).
    "shuffle_self_into_library",
    lambda p: ShuffleSelfIntoLibraryEffect(subject=p.get("subject", "self")),
)
EffectRegistry.register(
    # "Put target permanent you own on the bottom of your library. Reveal
    # cards from the top of your library until you reveal a card that
    # shares a card type with that permanent…" (Reality Scramble)
    "return_to_library_then_dig_shared_type",
    lambda p: ReturnToLibraryThenDigSharedTypeEffect(
        target=p.get("target"), target_kind=p.get("target_kind", "permanent_you_control"),
    ),
)
EffectRegistry.register(
    # "An opponent gains control of ~." (Wishclaw Talisman) / "Gain control
    # of ~." on an opponent-only ability (Oft-Nabbed Goat — recipient="activator")
    "gain_control_by_source",
    lambda p: GainControlBySourceEffect(recipient=p.get("recipient", "opponent")),
)
EffectRegistry.register(
    # "…that creature's controller gains control of one of those lands of their choice and
    # untaps it." (Turf War)
    "take_contested_land",
    lambda p: ContestedLandControlEffect(),
)
EffectRegistry.register(
    # "When ~ dies, if it had one or more -1/-1 counters on it, its owner
    # draws that many cards and each other player loses that much life."
    # (Oft-Nabbed Goat) — hand-authored singleton, see the effect's docstring.
    "owner_draw_others_lose_per_dying_counter",
    lambda p: OwnerDrawOthersLosePerDyingCounterEffect(
        counter_kind=str(p.get("counter_kind", "-1/-1")),
    ),
)
EffectRegistry.register(
    # "[You / that player] gain(s) control of enchanted creature."
    # (Captivating Glance's clash win / otherwise branches)
    "gain_control_attached",
    lambda p: GainControlAttachedEffect(recipient=p.get("recipient", "controller")),
)
EffectRegistry.register(
    "return_milled_cards",
    lambda p: ReturnMilledCardsEffect(
        card_type=p.get("card_type", "card"), choose_one=bool(p.get("choose_one", False)),
        tapped=bool(p.get("tapped", False)),
    ),
)
EffectRegistry.register("lose_life_for_milled_card_types", lambda p: LoseLifeForMilledCardTypesEffect())
EffectRegistry.register(
    # "return target creature card from your graveyard to the battlefield/
    # your hand" (RULE 701.3, Regrowth/Reanimate-shaped)
    "return_from_graveyard",
    lambda p: ReturnFromGraveyardEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "graveyard_creature"),
        destination=p.get("destination", "battlefield"),
        under_your_control=bool(p.get("under_your_control", False)),
        optional=bool(p.get("optional", False)),
        lose_life_equal_mv=bool(p.get("lose_life_equal_mv", False)),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        shuffle_after=bool(p.get("shuffle_after", False)),
        subtype=p.get("subtype"),
        max_mana_value=p.get("max_mana_value"),
        exact_mana_value=p.get("exact_mana_value"),
        haste=bool(p.get("haste", False)),
        tapped=bool(p.get("tapped", False)),
        trigger_subject_key=p.get("trigger_subject_key"),
        players=p.get("players"),
        count_selector=p.get("count_selector"),
        colors=p.get("colors"),
        extra_counters=p.get("extra_counters"),
        exclude_legendary=bool(p.get("exclude_legendary", False)),
        chooser=p.get("chooser"),
        previous_subject=bool(p.get("previous_subject", False)),
        moved_pool=bool(p.get("moved_pool", False)),
        then_effects=p.get("then_effects"),
        face_down_as=p.get("face_down_as"),
        positional_top_creature=bool(p.get("positional_top_creature", False)),
        unless_flag=p.get("unless_flag"),
        attacking=bool(p.get("attacking", False)),
        pick=bool(p.get("pick", False)),
        creature_filter=p.get("creature_filter"),
        each_player_pick=bool(p.get("each_player_pick", False)),
        destination_if=p.get("destination_if"),
        previous_pool=bool(p.get("previous_pool", False)),
        controller_target_kind=p.get("controller_target_kind"),
        controller_target_active=bool(p.get("controller_target_active", False)),
        at_random=p.get("at_random"),
        else_destination=p.get("else_destination"),
        pick_mode=p.get("pick_mode"),
        attach_to_previous=bool(p.get("attach_to_previous", False)),
    ),
)
EffectRegistry.register(
    "return_creatures_total_mana_value",
    lambda p: ReturnCreatureCardsWithTotalMVEffect(
        budget=p.get("budget", 0), measure=str(p.get("measure", "mana_value")),
        own_graveyard=bool(p.get("own_graveyard", False)),
    ),
)
EffectRegistry.register(
    "add_mana",  # a spell's own bare "Add {B}{B}{B}." body (RULE 106.4, Dark Ritual)
    lambda p: AddManaEffect(
        colors=list(p.get("colors", [])),
        amount=p.get("amount"),
        color=p.get("color", "C"),
        amount_selector=p.get("amount_selector"),
        amount_from_trigger_event=p.get("amount_from_trigger_event"),
        recipient=p.get("recipient", "controller"),
        target_kind=p.get("target_kind"),
        any_amount=p.get("any_amount"),
        once_per_turn_ability=bool(p.get("once_per_turn_ability", False)),
        color_from_source_chosen_color=bool(p.get("color_from_source_chosen_color", False)),
        color_from_source_noted_color=bool(p.get("color_from_source_noted_color", False)),
        any_color_choices=p.get("any_color_choices"),
        any_amount_from_context=p.get("any_amount_from_context"),
        any_amount_multiplier=int(p.get("any_amount_multiplier", 1) or 1),
        amount_from_context=p.get("amount_from_context"),
        keep_until=p.get("keep_until"),
        any_amount_from_trigger_event=p.get("any_amount_from_trigger_event"),
        restriction=p.get("restriction"),
    ),
)
EffectRegistry.register(
    # "Add one mana of any type that permanent produced." (Kinnan) — RULE
    # 605.1b triggered-mana-ability body; the type comes from the firing.
    "mirror_produced_mana",
    lambda p: MirrorProducedManaEffect(count=int(p.get("count", 1) or 1), player=p.get("player")),
)
EffectRegistry.register(
    # "Tap all lands that player controls that could produce any type of
    # mana that land could produce." (Mana Web)
    "tap_matching_lands",
    lambda p: TapMatchingLandsEffect(),
)
EffectRegistry.register(
    "create_delayed_trigger",  # RULE 603.7 "at the beginning of your next … , …"
    lambda p: CreateDelayedTriggerEffect(
        step=p.get("step", "upkeep"),
        effects=list(p.get("effects", [])),
        scope=p.get("scope", "controller"),
        capture=p.get("capture"),
        min_turn_offset=p.get("min_turn_offset", 0),
        description=p.get("description", ""),
        condition=p.get("condition"),
        related_filter=p.get("related_filter"),
        trigger_event_key=p.get("trigger_event_key"),
    ),
)
EffectRegistry.register(
    # RULE 603.7-adjacent recurring player-scoped trigger (Nuka-Nuke
    # Launcher's "until the end of defending player's next turn, that
    # player gets rad counters whenever they cast a spell").
    "install_temporary_player_trigger",
    lambda p: InstallTemporaryPlayerTriggerEffect(
        event_type=p.get("event_type", "SPELL_CAST"),
        effects=list(p.get("effects", [])),
        description=p.get("description", ""),
    ),
)
EffectRegistry.register(
    # RULE 603.7a: a triggered ability created at resolution that lasts the turn
    # (Indulge // Excess's "whenever a creature you control attacks this turn").
    "create_turn_trigger",
    lambda p: CreateTurnTriggerEffect(
        trigger=p.get("trigger"),
        effects=list(p.get("effects", [])),
        optional=bool(p.get("optional", False)),
        once=bool(p.get("once", False)),
        description=p.get("description", ""),
        target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject", False)),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # RULE 122/601.2b resolve-time optional energy payment (Aether Chaser —
    # "you may pay {E}{E}. If you do, create a 1/1 Servo").
    "pay_energy_then",
    lambda p: PayEnergyThenEffect(
        amount=p.get("amount", 0),
        effects=list(p.get("effects", [])),
        variable=bool(p.get("variable", False)),
        target_kind=p.get("target_kind"),
        amount_from_target_mana_value=bool(p.get("amount_from_target_mana_value", False)),
    ),
)
EffectRegistry.register(
    # "You may exile this card. If you do, ..." while the source is already
    # in a graveyard (Greenwarden of Murasa). The `then_trigger` gets fresh
    # targets only after the optional exile actually happened.
    "may_exile_source_then",
    lambda p: MayExileSourceThenEffect(
        then_trigger=list(p.get("then_trigger", [])), prompt=p.get("prompt"),
    ),
)
EffectRegistry.register(
    # RULE 603.12 reflexive "When you do, <effect>" trigger, carried in an
    # antecedent effect's `then` list (Meanders Guide's tap-then-return).
    "reflexive_trigger",
    lambda p: ReflexiveTriggerEffect(then_trigger=list(p.get("then_trigger", []))),
)
EffectRegistry.register(
    # RULE 118.3 resolve-time optional payment, generalized past energy:
    # "you may pay <cost>. If you do, <effect>. [If you don't, <effect>.]"
    # (Mana Vault's upkeep untap, Wandering Archaic's per-opponent {2}).
    "pay_cost_then",
    lambda p: PayCostThenEffect(
        cost=p.get("cost", ""),
        effects=list(p.get("effects", [])),
        else_effects=list(p.get("else_effects", [])),
        payer=p.get("payer", "controller"),
        remember_trigger_subject=bool(p.get("remember_trigger_subject", False)),
        # "Target player loses 3 life unless they sacrifice..." (Tergrid's
        # Lantern, MEC-43 round 4E) — see PayCostThenEffect.target_spec.
        target_kind=p.get("target_kind"),
        sacrifice_or_discard=bool(p.get("sacrifice_or_discard", False)),
        capture_previous=bool(p.get("capture_previous", False)),
        prompt=p.get("prompt"),
        remember_trigger_stack_id=bool(p.get("remember_trigger_stack_id", False)),
        then_trigger=p.get("then_trigger"),
        then_trigger_modes=p.get("then_trigger_modes"),
        x_color=p.get("x_color"),
        x_from_trigger_event=p.get("x_from_trigger_event"),
        pay_life_x=bool(p.get("pay_life_x", False)),
        x_cap_from_trigger_event=p.get("x_cap_from_trigger_event"),
    ),
)
EffectRegistry.register(
    # MEC-52 — Back from the Brink: "Exile a creature card from your
    # graveyard and pay its mana cost: Create a token that's a copy of that
    # card." The whole ability body, modeled as a resolution-time flow (a
    # pick-then-price cost the activation flow has no primitive for). See
    # `BackFromTheBrinkEffect`.
    "back_from_the_brink",
    lambda p: BackFromTheBrinkEffect(),
)
EffectRegistry.register(
    # MEC-52 — the "and pay its mana cost" half of Back from the Brink:
    # `_request_pay_cost_then` priced off the just-exiled graveyard card.
    # Never placed in an `AbilitySpec` directly — only chained by
    # `BackFromTheBrinkEffect` as a `then_specs` entry.
    "pay_cost_then_previous_mv",
    lambda p: PayCostThenPreviousMvEffect(),
)
EffectRegistry.register(
    # MEC-19: "counter it/that spell[or ability] unless that player/its
    # controller pays <cost>" — the un-keyworded-Ward-shaped trigger
    # resolution (EventType.BECOMES_TARGET).
    "counter_unless_pay",
    lambda p: CounterUnlessPayEffect(
        cost=p.get("cost", ""), target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    # RULE 118.3-adjacent multi-player tax: "Any player may pay <cost>. If
    # no one does, <effect>." (Rhystic Circle, MEC-30) — `pay_cost_then`'s
    # multi-player, aggregate-outcome sibling.
    "all_players_decline_or",
    lambda p: RequestAllPlayersDeclineOrEffect(
        cost=p.get("cost", ""),
        effects=list(p.get("effects", [])),
    ),
)
EffectRegistry.register(
    # RULE 301.5c: "attach target Equipment you control to target creature
    # you control" (Brass Squire, Halvar) — two independently-chosen targets
    # of different kinds in one clause.
    "attach_chosen",
    lambda p: AttachChosenEffect(
        what_kind=p.get("what_kind", "equipment_you_control"),
        to_kind=p.get("to_kind", "creature_you_control"),
        what_optional=bool(p.get("what_optional", False)),
        what_count=int(p.get("what_count", 1)),
        to_optional=bool(p.get("to_optional", False)),
        to_subject=p.get("to_subject"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # RULE 701.14 fight — "target creature you control fights target creature
    # you don't control" (Prey Upon), "it fights up to one target creature you
    # don't control" (Kogla's ETB, ``fighter_kind=None``).
    "fight",
    lambda p: FightEffect(
        fighter_kind=p.get("fighter_kind"),
        other_kind=p.get("other_kind", "creature"),
        fighter_optional=bool(p.get("fighter_optional", False)),
        optional=bool(p.get("optional", False)),
        distinct=bool(p.get("distinct", False)),
        other_exact_mana_value=p.get("other_exact_mana_value"),
        other_instance_id=p.get("other_instance_id"),
    ),
)
EffectRegistry.register(
    # The one-sided fight — "target creature you control deals damage equal to
    # its power to target creature you don't control" (Rabid Bite), "when ~
    # dies, it deals damage equal to its power to any target".
    "damage_equal_to_power",
    lambda p: DamageEqualToPowerEffect(
        dealer_kind=p.get("dealer_kind"),
        target_kind=p.get("target_kind", "any"),
        selector=p.get("selector"),
        dealer_optional=bool(p.get("dealer_optional", False)),
        optional=bool(p.get("optional", False)),
        to_self=bool(p.get("to_self", False)),
        dealer_group=p.get("dealer_group"),
        excess_to_controller_if_trample=bool(p.get("excess_to_controller_if_trample", False)),
        distinct=bool(p.get("distinct", False)),
    ),
)
EffectRegistry.register(
    # "~ deals damage equal to the number of +1/+1 counters on it to any
    # other target." (Red Hulk) — `damage_equal_to_power`'s counter-count
    # sibling.
    "damage_equal_to_counters",
    lambda p: DamageEqualToCountersEffect(
        kind=p.get("kind", "+1/+1"),
        target_kind=p.get("target_kind", "any"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # RULE 601.2c target announcement with no effect of its own — "choose
    # target creature you control and target creature you don't control."
    "choose_targets",
    lambda p: ChooseTargetsEffect(
        kinds=list(p.get("kinds", []) or []),
        count=p.get("count"),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        optional=bool(p.get("optional", False)),
        per_player=p.get("per_player"),
    ),
)
EffectRegistry.register(
    # "Destroy each artifact with mana value X." (Dauntless Dismantler)
    "destroy_each_with_mana_value",
    lambda p: DestroyEachWithManaValueEffect(
        amount=p.get("amount", 0), card_type=p.get("card_type", "artifact"),
    ),
)
EffectRegistry.register(
    # RULE 701.17: "each opponent sacrifices a creature with the greatest
    # power among creatures that player controls" (Professor Onyx's −3).
    # Previously only reachable from the annihilator keyword, never the
    # registry.
    "sacrifice",
    lambda p: SacrificeEffect(
        count=p.get("count", 1) if str(p.get("count")).startswith("all_but_") or p.get("count") == "all"
        else int(p.get("count", 1) or 1),
        what=p.get("what", "permanent"),
        player=p.get("player"),
        selector=p.get("selector"),
        greatest_power=bool(p.get("greatest_power", False)),
        target_kind=p.get("target_kind"),
        greatest=p.get("greatest"),
        action=p.get("action", "sacrifice"),
    ),
)
EffectRegistry.register(
    # "You may discard one or more <what> cards. When you do, … that many …" (Loamcrafter Faun) — the hand-zone
    # sibling of `sacrifice_chosen_then` just below.
    "discard_chosen_then",
    lambda p: DiscardChosenThenEffect(
        what=str(p.get("what", "land")), effects=list(p.get("effects") or []), trigger=list(p.get("trigger") or []),
    ),
)
EffectRegistry.register(
    # MEC-103: "you may sacrifice up to N `<what>`. When you do, … that many …"
    # (Ravenous Rotbelly, Nyssa of Traken).
    "sacrifice_chosen_then",
    lambda p: SacrificeChosenThenEffect(
        what=str(p.get("what", "permanent")),
        count=p.get("count", "any") if p.get("count") == "any" else int(p.get("count", 1) or 1),
        effects=list(p.get("effects") or []),
        trigger=list(p.get("trigger") or []),
        optional=bool(p.get("optional", True)),
        exclude_self=bool(p.get("exclude_self", False)),
        measure=p.get("measure") if p.get("measure") in ("power", "mana_value") else None,
    ),
)
EffectRegistry.register(
    # "For each player, you choose … an artifact, a creature, an enchantment,
    # and a planeswalker. Then each player sacrifices all other nonland
    # permanents they control." (Tragic Arrogance, PAR-60)
    "tragic_arrogance",
    lambda p: TragicArroganceEffect(),
)
EffectRegistry.register(
    # "Exile all creatures. Each player creates a 0/0 Fractal … +1/+1
    # counters = total power of their exiled creatures." (Oversimplify)
    "oversimplify",
    lambda p: OversimplifyEffect(),
)
EffectRegistry.register(
    # "…for each creature token you control that entered this turn, create a
    # tapped and attacking token that's a copy of that token." (Redoubled
    # Stormsinger, PAR-60)
    "redoubled_stormsinger_copies",
    lambda p: RedoubledStormsingerCopiesEffect(),
)
EffectRegistry.register(
    # "Exile target instant or sorcery card from your graveyard. Creatures
    # you control get +X/+0 …" (Surge to Victory, PAR-60 — copy-on-damage
    # rider dropped)
    "surge_to_victory",
    lambda p: SurgeToVictoryEffect(),
)
EffectRegistry.register(
    # "…create a 2/1 blue Phyrexian Myr … Then you may choose a token you
    # control. If you do, each other token you control becomes a copy of
    # that token." (Brudiclad, Telchor Engineer, PAR-60)
    "brudiclad_combat",
    lambda p: BrudicladCombatEffect(),
)
EffectRegistry.register(
    # "Whenever another nontoken creature you control dies, exile it. If you
    # do, create a token that's a copy of that creature, except it's a
    # Spirit …" (Hofri Ghostforge, PAR-60 — leave-return rider dropped)
    "hofri_ghostforge_dies",
    lambda p: HofriGhostforgeDiesEffect(),
)
EffectRegistry.register(
    "brudiclad_become_copies", lambda p: BrudicladBecomeCopiesEffect(),
)
EffectRegistry.register(
    # "Sacrifice it at the beginning of the next end step." (Kiki-Jiki,
    # Mirror Breaker-shaped) — the ``objects`` list is never real
    # card-text data (an empty default here), only ever populated by
    # `CreateDelayedTriggerEffect`'s own ``capture="created_objects"``
    # mutating the constructed effect directly, the same "capture a
    # resolve-time fact the delayed firing can't see anymore" idiom
    # ``target_mana_value``/``target_controller`` use.
    "sacrifice_specific",
    lambda p: SacrificeSpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "Exile those tokens at the beginning of the next end step." (Twinflame-
    # shaped, MEC-12) — the plural sibling of `sacrifice_specific` just
    # above, same "empty default, only ever populated by `CreateDelayedTrigger
    # Effect`'s own `capture='created_objects'`" idiom.
    "exile_specific",
    lambda p: ExileSpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "Destroy it at the beginning of the next end step." (Old Hob, Alleycat
    # Blues-shaped) — the destroy sibling of `sacrifice_specific`/`exile_
    # specific`, same "empty default, only ever populated by `CreateDelayed
    # TriggerEffect`'s own `capture`" idiom.
    "destroy_specific",
    lambda p: DestroySpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "Discard the duplicate at the beginning of your next end step."
    # (Spellchain Scatter, PAR-124) — the hand-zone sibling of
    # `destroy_specific`/`sacrifice_specific`, same empty-default idiom.
    "discard_specific",
    lambda p: DiscardSpecificEffect(objects=[]),
)
EffectRegistry.register(
    # "Return that creature to its owner's hand at the beginning of the next
    # end step." (Ilharg, Zara, Alora — a put-onto-battlefield/unblockable
    # loan that's bounced end of turn). Same "empty default, only ever
    # populated by `CreateDelayedTriggerEffect`'s `capture`" idiom as the
    # sacrifice/exile/destroy siblings above.
    "return_specific_to_hand",
    lambda p: ReturnSpecificToHandEffect(objects=[]),
)
EffectRegistry.register("crewed_event", lambda p: CrewedEventEffect())  # RULE 702.122e — a Vehicle becomes crewed
EffectRegistry.register(
    # "…exile any number of cards from your graveyard with four or more card types among them. If you do, put a
    # permanent card from among them onto the battlefield with a finality counter on it." (Winter, Cynical Opportunist)
    "exile_selected_then_return_one",
    lambda p: ExileSelectedThenReturnOneEffect(
        instance_ids=p.get("instance_ids") if isinstance(p.get("instance_ids"), list) else [],
        min_card_types=int(p.get("min_card_types", 4) or 4),
    ),
)
EffectRegistry.register(
    # "Choose an opponent at random that ~ didn't attack during your last combat. ~ attacks that player this
    # combat if able. If you can't choose an opponent this way, tap ~." (Territorial Hellkite)
    "force_attack_unattacked_opponent",
    lambda p: ForceAttackUnattackedOpponentEffect(avoid_last_attacked=bool(p.get("avoid_last_attacked", True))),
)
EffectRegistry.register(
    # "Return it to the command zone at the beginning of the next end step." (Hellkite Courser) — the
    # command-zone sibling of `return_specific_to_hand`, same empty-default/`capture` idiom.
    "return_specific_to_command_zone",
    lambda p: ReturnSpecificToCommandZoneEffect(objects=[]),
)
EffectRegistry.register(
    # "If that creature would leave the battlefield, exile it instead of putting it anywhere else." (PAR-139)
    "exile_instead_of_leaving", lambda p: ExileInsteadOfLeavingEffect(),
)
EffectRegistry.register(
    # "Return that card to the battlefield under its owner's control at the beginning of the next
    # end step." (PAR-136, the Flickerwisp/Turn to Mist family) — the battlefield sibling above.
    "return_specific_to_battlefield",
    lambda p: ReturnSpecificToBattlefieldEffect(objects=[], tapped=bool(p.get("tapped", False))),
)
EffectRegistry.register(
    # "When this Aura leaves the battlefield, that creature's controller
    # sacrifices it." (MEC-34, Animate Dead/Necromancy) — no params at all,
    # reads `self.source.attached_to` live at resolution.
    "sacrifice_attached_permanent",
    lambda p: SacrificeAttachedPermanentEffect(),
)
EffectRegistry.register(
    # "Each opponent may discard a card. If they don't, they lose N life.
    # Repeat this process M more times." (Professor Onyx's −8)
    "discard_or_lose_life",
    lambda p: DiscardOrLoseLifeEffect(
        count=int(p.get("count", 1) or 1),
        amount=int(p.get("amount", 3) or 3),
        times=int(p.get("times", 1) or 1),
        selector=p.get("selector", "each_opponent"),
        round_index=int(p.get("round_index", 0) or 0),
        player_index=int(p.get("player_index", 0) or 0),
    ),
)
EffectRegistry.register(
    # RULE 903.3/110.2: "gain control of all commanders; put all commanders
    # from the command zone onto the battlefield under your control."
    # (Tevesh Szat, Doom of Fools' −10)
    "gain_control_of_all_commanders",
    lambda p: GainControlOfAllCommandersEffect(),
)
EffectRegistry.register(
    # RULE 903.3: "Target player returns each commander they control from the
    # battlefield to the command zone." (Leadership Vacuum)
    "return_commanders_to_command_zone",
    lambda p: ReturnCommandersToCommandZoneEffect(),
)
EffectRegistry.register(
    # RULE 108.4/110.2 (MEC-43 round 4D, Homeward Path): "each player
    # gains control of all creatures they own."
    "regain_control_of_owned_creatures",
    lambda p: RegainControlOfOwnedCreaturesEffect(),
)
EffectRegistry.register(
    # RULE 903.7 (MEC-43 round 4D, Command Beacon): "put your commander
    # into your hand from the command zone."
    "put_commander_into_hand",
    lambda p: PutCommanderIntoHandEffect(),
)
EffectRegistry.register(
    # RULE 616.1, scoped to one source / combat only / your opponents, and
    # duration-bounded (Jeska, Thrice Reborn's 0).
    "multiply_damage_from_target",
    lambda p: MultiplyDamageFromTargetEffect(
        multiplier=int(p.get("multiplier", 2) or 2),
        combat_only=bool(p.get("combat_only", True)),
        to=p.get("to", "opponents"),
    ),
)
EffectRegistry.register(
    "untap_self",  # "Untap this permanent." (Mana Vault)
    lambda p: UntapSelfEffect(),
)
EffectRegistry.register(
    # RULE 702.32b Fading / 702.61b Vanishing: "remove a counter … if you
    # can't, sacrifice it."
    "remove_counter_or_sacrifice",
    lambda p: RemoveCounterOrSacrificeEffect(kind=p.get("kind", "fade")),
)
EffectRegistry.register(
    # RULE 702.24b Cumulative Upkeep: "put an age counter … then sacrifice
    # unless you pay the upkeep cost for each age counter on it." (MEC-16)
    "cumulative_upkeep",
    lambda p: CumulativeUpkeepEffect(cost=p.get("cost", "")),
)
EffectRegistry.register(
    # "That player taps an untapped artifact, creature, or land they control
    # for each fade counter on this artifact." (Tangle Wire)
    "tap_permanents_per_counter",
    lambda p: TapPermanentsPerCounterEffect(
        kind=p.get("kind", "fade"), types=p.get("types"),
    ),
)
EffectRegistry.register(
    # "That player sacrifices a permanent of their choice for each soot
    # counter on this artifact." (Smokestack, MEC-43 round 4E)
    "sacrifice_permanents_per_counter",
    lambda p: SacrificePermanentsPerCounterEffect(kind=p.get("kind", "soot")),
)
EffectRegistry.register(
    "mutate",  # RULE 702.140b merge (Lore Drakkis)
    lambda p: MutateEffect(
        target_kind=p.get("target_kind", "non_human_creature_you_own"),
    ),
)
EffectRegistry.register(
    "name_card_then",  # "Choose a card name. <effect>" (Demonic Consultation)
    lambda p: NameCardThenEffect(effects=list(p.get("effects", []))),
)
EffectRegistry.register(
    # "Exile the top card of your library. You may put that card into your
    # hand unless it has the same name as another card exiled this way.
    # Repeat…" (Tainted Pact).
    "exile_until_duplicate_name",
    lambda p: ExileUntilDuplicateNameEffect(),
)
EffectRegistry.register(
    # "Sacrifice an artifact. If you do, search your library for an
    # artifact card…" (Transmute Artifact).
    "transmute_artifact",
    lambda p: TransmuteArtifactEffect(),
)
EffectRegistry.register(
    # "…reveal/exile cards from the top of your library until <predicate>"
    # — the parameterized form of the cascade/discover dig.
    "dig_until",
    lambda p: DigUntilEffect(
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        rest_destination=p.get("rest_destination", "exile"),
        pre_exile=int(p.get("pre_exile", 0) or 0),
        digger=str(p.get("digger", "controller")),
        caster=str(p.get("caster", "digger")),
        target_kind=p.get("target_kind"),
        hit_rider=p.get("hit_rider"),
        uncast_hit=str(p.get("uncast_hit", "library_bottom")),
    ),
)
EffectRegistry.register(
    # "…mills a card, then repeats this process until a creature card or X
    # cards…" (Helm of Obedience) — the first repeat-until-predicate loop.
    "mill_until_creature",
    lambda p: MillUntilCreatureEffect(
        amount=p.get("amount", 0), target_kind=p.get("target_kind", "player"),
    ),
)
EffectRegistry.register(
    # Possibility Storm / Tibalt's Trickery: answer a spell, then dig its
    # *controller's* library for a replacement they may cast for free.
    "scramble_spell",
    lambda p: ScrambleSpellEffect(
        answer=p.get("answer", "counter"),
        match=p.get("match", "different_name"),
        mill_random_max=int(p.get("mill_random_max", 0) or 0),
        card_types=p.get("card_types"),
    ),
)
EffectRegistry.register(
    # RULE 603.1 (MEC-43 round 4D, Jodah, the Unifier): "whenever you cast
    # a legendary spell from your hand, exile cards from the top of your
    # library until you exile a legendary nonland card with lesser mana
    # value. You may cast that card without paying its mana cost. Put the
    # rest on the bottom of your library in a random order."
    "legendary_spell_free_dig",
    lambda p: LegendarySpellFreeDigEffect(),
)
EffectRegistry.register(
    # RULE 603.1 (MEC-43 round 4D, Kodama of the East Tree): "you may put
    # a permanent card with equal or lesser mana value from your hand
    # onto the battlefield."
    "put_equal_or_lesser_mv_from_hand",
    lambda p: PutEqualOrLesserManaValueFromHandEffect(),
)
EffectRegistry.register(
    # Knowledge Pool: "Whenever a player casts a spell from their hand,
    # that player exiles it. If the player does, they may cast a spell
    # from among other cards exiled with this artifact without paying its
    # mana cost." — see `ExileCastSpellIntoImprintPoolEffect`.
    "exile_cast_spell_into_imprint_pool",
    lambda p: ExileCastSpellIntoImprintPoolEffect(),
)
EffectRegistry.register(
    # "As many times as you choose, you may pay 1 life…" (Lim-Dûl's Vault)
    "look_top_pay_life_loop",
    lambda p: LookTopPayLifeLoopEffect(
        count=int(p.get("count", 5) or 5), life_cost=int(p.get("life_cost", 1) or 1),
    ),
)
EffectRegistry.register(
    # "Reveal the top card of your library and put that card into your
    # hand. You lose life equal to its mana value. You may repeat this
    # process any number of times." (Ad Nauseam, MEC-41)
    "reveal_top_hand_lose_life_loop",
    lambda p: RevealTopHandLoseLifeLoopEffect(),
)
EffectRegistry.register(
    # RULE 108.4/701.10: "exchange control of ~ and up to one target
    # creature an opponent controls" (Gilded Drake) — a genuine two-way
    # swap, not a one-way grab.
    "exchange_control",
    lambda p: ExchangeControlEffect(
        target_kind=p.get("target_kind", "creature"),
        sacrifice_self_if_no_exchange=bool(p.get("sacrifice_self_if_no_exchange", False)),
        # Oko, Thief of Crowns' -5 (MEC-43 round 4E) — see
        # ExchangeControlEffect's own two-target-mode docstring.
        first_target_kind=p.get("first_target_kind"),
        second_creature_filter=p.get("second_creature_filter"),
        optional=bool(p.get("optional", False)),
        count=int(p.get("count", 1) or 1),
        distinct_controllers=bool(p.get("distinct_controllers", False)),
        # PAR-30 RULE 701.10 residue — resolve-time cross-target predicates.
        shares_type=p.get("shares_type"),
        second_not_greater=p.get("second_not_greater"),
        destroy_auras_if_exchanged=bool(p.get("destroy_auras_if_exchanged", False)),
        draw_if_neither_controlled=int(p.get("draw_if_neither_controlled", 0) or 0),
    ),
)
EffectRegistry.register(
    # Volatile Stormdrake's own compound "exchange control... if you do,
    # you get {E}{E}{E}{E}, then sacrifice that creature unless you pay {E}
    # equal to its mana value." (MEC-43).
    "exchange_control_then_energy_sacrifice",
    lambda p: ExchangeControlThenEnergySacrificeEffect(
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    # PAR-30 (Arteeoh, Dread Scavenger) — see ExchangeControlThenCopyTokenEffect.
    "exchange_control_then_copy_token",
    lambda p: ExchangeControlThenCopyTokenEffect(),
)
EffectRegistry.register(
    # RULE 702.26b + 611.2b: "all permanents you control phase out", plus
    # the life lock and protection from everything (Teferi's Protection).
    "phase_out_all_you_control",
    lambda p: PhaseOutAllYouControlEffect(
        target_kind=p.get("target_kind"), nonland_only=bool(p.get("nonland_only", False)),
    ),
)
EffectRegistry.register(
    # "return another permanent you control that shares a permanent type
    # with it to its owner's hand" (Cloudstone Curio).
    "return_shared_type_permanent",
    lambda p: ReturnSharedTypePermanentEffect(),
)
EffectRegistry.register(
    # "Whenever this creature deals combat damage to a creature, exile that
    # creature." (Kaldra Compleat's granted ability) — see
    # `ExileTriggerDamagedCreatureEffect`.
    "exile_trigger_damaged_creature",
    lambda p: ExileTriggerDamagedCreatureEffect(),
)
EffectRegistry.register(
    # "Put up to N <criteria> cards from your hand onto the battlefield."
    # (Tooth and Nail's second mode) — a pick from *hand*, unlike every
    # other "put onto the battlefield" (library/graveyard).
    "put_from_hand_onto_battlefield",
    lambda p: PutFromHandOntoBattlefieldEffect(
        criteria=p.get("criteria", p.get("type", "")),
        # ``"x"`` ("put up to X land cards …", Worldsoul's Rage) stays a sentinel for `_substitute_x`.
        count=p["count"] if p.get("count") == "x" else int(p.get("count", 1) or 1),
        tapped=bool(p.get("tapped", False)),
        attacking=bool(p.get("attacking", False)),
        trigger_attacks=bool(p.get("trigger_attacks", False)),
        max_mana_value_selector=p.get("max_mana_value_selector"),
        power_less_than_source=bool(p.get("power_less_than_source", False)),
        miss_effect_specs=p.get("miss_effect_specs"),
        zones=p.get("zones"),
        max_mana_value_from_trigger=p.get("max_mana_value_from_trigger"),
        then_effects=p.get("then_effects"),
    ),
)
EffectRegistry.register(
    # "Exile a permanent card from your graveyard at random, then create a
    # tapped token that's a copy of that card. If the exiled card is a land
    # card, repeat this process." (Sin, Spira's Punishment)
    "random_graveyard_exile_copy_loop",
    lambda p: RandomGraveyardExileCopyLoopEffect(),
)
EffectRegistry.register(
    "take_extra_turn",
    # ``count`` is coerced lazily by `TakeExtraTurnEffect` itself, not here —
    # see its own docstring (PAR-67: a `bind`-measured count reads as an
    # uncoerced ``"$n"`` sentinel the one time `target_specs` builds this
    # effect before substitution runs).
    lambda p: TakeExtraTurnEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "extra_combat_phase",
    lambda p: ExtraCombatPhaseEffect(
        main_phase_too=bool(p.get("main_phase_too", False)),
        after_current_phase=bool(p.get("after_current_phase", False)),
        untap_at_beginning=bool(p.get("untap_at_beginning", False)),
    ),
)
EffectRegistry.register(
    # MEC-51 (RULE 720): "You control target opponent during that player's
    # next turn / next combat phase." — see `ControlPlayerEffect`.
    "control_player",
    lambda p: ControlPlayerEffect(
        scope=str(p.get("scope", "turn")),
        target_kind=str(p.get("target_kind", "opponent")),
        grant_extra_turn_after=bool(p.get("grant_extra_turn_after", False)),
    ),
)
EffectRegistry.register(
    # MEC-51b (Word of Command) — see `WordOfCommandEffect`.
    "word_of_command",
    lambda p: WordOfCommandEffect(),
)
EffectRegistry.register(
    # "You may sacrifice/tap/return a <kind> you control." — the player
    # picks which; see `RulesEngine._request_choose_objects`.
    "choose_objects",
    lambda p: ChooseObjectsEffect(
        card_types_any=p.get("card_types_any"),
        then_that_many=p.get("then_that_many"),
        distinct_card_types=bool(p.get("distinct_card_types", False)),
        pool_zone=p.get("pool_zone", "battlefield"),
        pool_zones=p.get("pool_zones"),
        mana_value_less_than_trigger=bool(p.get("mana_value_less_than_trigger", False)),
        pool_player_selector=p.get("pool_player_selector", "chooser"),
        action=str(p.get("action", "sacrifice")),
        what=str(p.get("what", "permanent")),
        count="all" if p.get("count") == "all" else int(p.get("count", 1) or 1),
        optional=bool(p.get("optional", False)),
        exclude_self=bool(p.get("exclude_self", False)),
        prompt=str(p.get("prompt", "")),
        then=p.get("then"),
        then_if_commander=p.get("then_if_commander"),
        player_selector=str(p.get("player_selector", "controller")),
        require_untapped=bool(p.get("require_untapped", False)),
        else_effects=p.get("else_effects"),
        count_amount=p.get("count_amount"),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    # Expel the Interlopers — see `ChooseNumberThenEffect`.
    "choose_number_then",
    lambda p: ChooseNumberThenEffect(
        minimum=int(p.get("min", 0)), maximum=int(p.get("max", 10)), effects=p.get("then"),
    ),
)
EffectRegistry.register(
    # Slaughter the Strong — see `SlaughterTheStrongEffect`.
    "slaughter_the_strong",
    lambda p: SlaughterTheStrongEffect(
        budget=int(p.get("budget", 4)), stage=str(p.get("stage", "choose")),
        player_ids=p.get("player_ids"), kept_ids=p.get("kept_ids"),
    ),
)
EffectRegistry.register(
    # Disorienting Choice — see `DisorientingChoiceEffect`.
    "disorienting_choice",
    lambda p: DisorientingChoiceEffect(
        stage=str(p.get("stage", "choose")), player_ids=p.get("player_ids"), chosen_ids=p.get("chosen_ids"),
        pending_ids=p.get("pending_ids"),
    ),
)
EffectRegistry.register(
    "choose_player_objects",
    lambda p: ChoosePlayerObjectsEffect(
        player_ids=p.get("player_ids"), chosen_ids=p.get("chosen_ids"), then_that_many=p.get("then_that_many"),
        player_scope=p.get("player_scope", "you_and_defending"), action=p.get("action", "discard_or_sacrifice"),
        optional=bool(p.get("optional", False)), card_types_any=p.get("card_types_any"),
        declined_ids=p.get("declined_ids"), else_effects=p.get("else_effects"),
        permanent_filter=p.get("permanent_filter"), else_simultaneous=bool(p.get("else_simultaneous", False)),
        start_with_next_opponent=bool(p.get("start_with_next_opponent", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.47/701.50 (connive, MEC-43 — Ledger Shredder; PAR-29): draw a
    # card, then discard a card; if a nonland card was discarded this way,
    # put a +1/+1 counter on the conniving permanent. See `ConniveEffect`.
    "connive",
    lambda p: ConniveEffect(
        target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject", False)),
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        count_selector=p.get("count_selector"),
        times=int(p.get("times", 1) or 1),
        creature_filter=p.get("creature_filter"),
        convoked=bool(p.get("convoked", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.70a (recruit, PAR-29 — Tales of Middle-earth): draw a card,
    # then discard a card; if the discarded card was a nonland card, create
    # a 1/1 white Human Soldier token. See `RecruitEffect` /
    # `RulesEngine.recruit`.
    "recruit", lambda p: RecruitEffect(),
)
EffectRegistry.register(
    "learn", lambda p: LearnEffect(),  # RULE 701.48 "Learn."
)
EffectRegistry.register(
    # RULE 701.59 "Collect evidence N" as a resolving effect (the "you may"
    # is the segmenter's outer optional peel). See `CollectEvidenceEffect`.
    "collect_evidence", lambda p: CollectEvidenceEffect(amount=int(p.get("amount", 0) or 0)),
)
EffectRegistry.register(
    "exile_self_collect_evidence_return",
    lambda p: ExileSelfCollectEvidenceReturnEffect(
        amount=int(p.get("amount", 0) or 0), tapped=bool(p.get("tapped", True)),
    ),
)
EffectRegistry.register(
    # RULE 701.61 "Forage" as a resolving effect (the "you may" is the
    # segmenter's outer optional peel). See `ForageEffect`.
    "forage", lambda p: ForageEffect(),
)
EffectRegistry.register(
    # RULE 701.6x (Avatar: The Last Airbender): the Firebending attack-
    # trigger bending marker. See `RecordBendEffect`.
    "record_bend", lambda p: RecordBendEffect(kind=str(p.get("kind", "firebend"))),
)
EffectRegistry.register(
    # RULE 701.44 (explore, PAR-29): reveal top card of library — land to
    # hand, else +1/+1 counter on the permanent + may bin the card. See
    # `ExploreEffect` / `RulesEngine.explore`.
    "explore",
    lambda p: ExploreEffect(
        target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject")),
        optional=bool(p.get("optional")),
    ),
)
EffectRegistry.register(
    # RULE 701.36 (populate, PAR-29): put a token onto the battlefield
    # that's a copy of a creature token you control (nothing if you control
    # none). See `PopulateEffect` / `RulesEngine.populate`.
    "populate",
    lambda p: PopulateEffect(
        count=p.get("count", 1),
        tapped=bool(p.get("tapped", False)),
        attacking=bool(p.get("attacking", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.39 (bolster, PAR-29): put N +1/+1 counters on a least-
    # toughness creature you control (your choice on a tie). See
    # `BolsterEffect` / `RulesEngine.bolster`. Support (RULE 701.41) needs
    # no effect of its own — it's a parser alias onto `add_counters` with a
    # "up to N target creatures" spec.
    "bolster",
    lambda p: BolsterEffect(
        amount=p.get("amount", p.get("count", 1)),
    ),
)
EffectRegistry.register(
    # "Blight N" (Bloomburrow, PAR-29): put N -1/-1 counters on a creature
    # you control (your choice). See `BlightEffect` / `RulesEngine.blight`.
    "blight",
    lambda p: BlightEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    # "Time travel" (RULE 701.56, PAR-29): remove a time counter from each
    # suspended card you own / add one to each Vanishing-style permanent
    # you control. See `TimeTravelEffect` / `RulesEngine.time_travel`.
    "time_travel",
    lambda p: TimeTravelEffect(),
)
EffectRegistry.register(
    # "Face a villainous choice" (RULE 701.55, PAR-29): each facing player
    # picks one of two option effect-lists, applied for them. See
    # `FaceVillainousChoiceEffect` / `RulesEngine._request_villainous_choice`.
    "face_villainous_choice",
    lambda p: FaceVillainousChoiceEffect(
        option_a=list(p.get("option_a", [])),
        option_b=list(p.get("option_b", [])),
        subject=str(p.get("subject", "each_opponent")),
        labels=p.get("labels"),
        subject_min_life_lost=int(p.get("subject_min_life_lost", 0) or 0),
        capture_previous=bool(p.get("capture_previous", False)),
    ),
)
EffectRegistry.register(
    # "Vote" (RULE 701.38, PAR-29): an APNAP vote among `options`, then a
    # majority-branch or per-vote-scaled outcome. See `VoteEffect` /
    # `RulesEngine._request_vote`.
    "vote",
    lambda p: VoteEffect(
        options=list(p.get("options", [])),
        majority_specs=p.get("majority_specs"),
        tie_index=p.get("tie_index"),
        per_vote_specs=p.get("per_vote_specs"),
        winner_specs=p.get("winner_specs"),
    ),
)
EffectRegistry.register(
    # RULE 701.38f (MEC-46): "You choose how each player votes this turn."
    # (Illusion of Choice). See `SetForcedVoterEffect`.
    "set_forced_voter",
    lambda p: SetForcedVoterEffect(),
)
EffectRegistry.register(
    # MEC-46 (RULE 701.38): "each player votes for a nonland permanent you
    # don't control" / "…a card in your graveyard", then "exile / return
    # each `<object>` with the most votes or tied for most votes". See
    # `ObjectVoteEffect` / `RulesEngine._request_object_vote`. Closes
    # Council's Judgment, Custodi Squire.
    "vote_object",
    lambda p: ObjectVoteEffect(
        pool=str(p.get("pool", "nonland_permanents_opponents")),
        outcome=str(p.get("outcome", "exile")),
        card_types=list(p.get("card_types", [])),
    ),
)
EffectRegistry.register(
    # MEC-46 (Expropriate): the per-money-vote gain-control continuation —
    # never emitted by a parser handler directly, only chained by
    # `RulesEngine._advance_expropriate_gain_control` as a `choose_objects`
    # ``then_specs`` entry. See `ExpropriateGainControlEffect`.
    "expropriate_gain_control",
    lambda p: ExpropriateGainControlEffect(voter_ids=list(p.get("voter_ids", []))),
)
EffectRegistry.register(
    # "Earthbend N" (RULE 701.66, Avatar: The Last Airbender, PAR-29): a
    # target land you control becomes a 0/0 creature with haste that's still
    # a land, then gets N +1/+1 counters. See `EarthbendEffect` /
    # `RulesEngine.earthbend`.
    "earthbend",
    lambda p: EarthbendEffect(
        amount=p.get("amount", p.get("count", 1)),
        previous_subject=bool(p.get("previous_subject")),
    ),
)
EffectRegistry.register(
    # "Endure N" (RULE 701.63a, Bloomburrow, PAR-29): either N +1/+1
    # counters on the permanent, or an N/N white Spirit token — its
    # controller's choice. See `EndureEffect` / `RulesEngine.endure`.
    "endure",
    lambda p: EndureEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
        previous_subject=bool(p.get("previous_subject")),
        optional=bool(p.get("optional")),
    ),
)
EffectRegistry.register(
    "the_ring_tempts_you",  # RULE 701.51a
    lambda p: TheRingTemptsYouEffect(),
)
EffectRegistry.register(
    "cast_exiled_face_down",  # Beseech the Mirror (RULE 701.20a)
    lambda p: CastExiledFaceDownEffect(
        max_mana_value=p.get("max_mana_value"),
        require_bargained=p.get("require_bargained", False),
    ),
)
EffectRegistry.register(
    # "Exile any number of cards from your hand face down." (MEC-43 round
    # 4F — Scroll Rack, first half).
    "scroll_rack_exile",
    lambda p: ScrollRackEffect(),
)
EffectRegistry.register(
    # Scroll Rack's own back half — draw-that-many plus the reorder-onto-
    # top decision (`ScrollRackEffect`'s ``then_specs``, never placed in
    # an `AbilitySpec` directly).
    "scroll_rack_finish",
    lambda p: ScrollRackFinishEffect(),
)
EffectRegistry.register(
    "cheat_creature_from_hand",  # Sneak Attack/Meek Attack
    lambda p: CheatCreatureFromHandEffect(
        max_total_pt=p.get("max_total_pt"), subtypes=p.get("subtypes"),
    ),
)
EffectRegistry.register(
    "grant_protection",
    lambda p: GrantProtectionEffect(
        target_kind=p["target_kind"] if "target_kind" in p else "creature_you_control",
        allow_colorless=bool(p.get("allow_colorless", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "grant_fixed_protection_group",
    lambda p: GrantFixedProtectionGroupEffect(
        color=str(p.get("color", "W")), selector=str(p.get("selector", "creatures_you_control")),
    ),
)
EffectRegistry.register(
    "grant_cant_be_target_of_spell_color",
    lambda p: GrantCantBeTargetOfSpellColorEffect(
        colors=p.get("colors"), selector=p.get("selector", "creatures_you_control"),
    ),
)
EffectRegistry.register(
    "lose_game", lambda p: LoseGameEffect(reason=p.get("reason", "effect"), players=p.get("players"))
)
EffectRegistry.register(
    "lose_game_trigger_damaged_player",
    lambda p: LoseGameTriggerDamagedPlayerEffect(reason=p.get("reason", "effect")),
)
EffectRegistry.register(
    "add_counters_to_trigger_damaged_player",  # Etali, Primal Sickness
    lambda p: AddCountersToTriggerDamagedPlayerEffect(kind=p.get("kind", "poison")),
)
EffectRegistry.register(
    "blink",  # "Exile target permanent, then return it to the battlefield" (Ephemerate)
    lambda p: BlinkEffect(
        target_kind=p.get("target_kind", "creature_you_control"),
        under_your_control=bool(p.get("under_your_control", False)),
        creature_filter=p.get("creature_filter"),
        optional=bool(p.get("optional", False)),
        count=p.get("target_count", 1),
        count_max=p.get("target_count_max"),
        trigger_event_key=p.get("trigger_event_key"),
        tapped=bool(p.get("tapped", False)),
    ),
)
EffectRegistry.register(
    "tap",
    lambda p: TapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        untap=bool(p.get("untap", False)),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        count=p.get("count", 1),
        count_max=p.get("count_max"),
        # "Tap up to **X** target creatures" (Crashing Wave) — a
        # `TargetSpec.count_selector`, resolved at announce time off
        # `GameObject.x_paid`, not the plain ``count`` (see
        # `ExileEffect.count_selector`).
        count_selector=p.get("count_selector"),
        previous_subject=bool(p.get("previous_subject", False)),
        trigger_event_key=p.get("trigger_event_key"),
        creature_filter=p.get("creature_filter"),
        subtypes=p.get("subtypes"),
        choose_tap_or_untap=bool(p.get("choose_tap_or_untap", False)),
        colors=p.get("colors"),
        target_operand=p.get("target_operand"),
        selector_player=p.get("selector_player"),
        remove_from_combat=bool(p.get("remove_from_combat", False)),
        untap_if_yours=bool(p.get("untap_if_yours", False)),
    ),
)
EffectRegistry.register(
    # "[Target / that] permanent doesn't untap during its controller's next
    # untap step." (Barl's Cage + the ~95-card "Tap X. It doesn't untap …"
    # tempo family) — sets `GameObject.skip_next_untap` (RULE 702.19b's
    # own one-time flag).
    "skip_next_untap",
    lambda p: SkipNextUntapEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        previous_subject=bool(p.get("previous_subject", False)),
        optional=bool(p.get("optional", False)),
        creature_filter=p.get("creature_filter"),
        subject=p.get("subject"),
        target_operand=p.get("target_operand"),
    ),
)
EffectRegistry.register(
    "unblockable",  # "Target creature can't be blocked this turn" (Rogue's Passage)
    lambda p: UnblockableEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        creature_filter=p.get("creature_filter"),
        selector=p.get("selector"),
        count=int(p.get("count", 1) or 1),
        count_max=p.get("count_max"),
        count_selector=p.get("count_selector"),
        optional=bool(p.get("optional", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        opponents_only=bool(p.get("opponents_only", False)),
    ),
)
EffectRegistry.register(
    # "Target creature can't be regenerated this turn." (Gravebind) and its
    # pronoun / "dealt damage this way" forms — RULE 701.16.
    "cant_be_regenerated",
    lambda p: CantBeRegeneratedEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else None,
        previous_subject=bool(p.get("previous_subject", False)),
        damaged_this_way=bool(p.get("damaged_this_way", False)),
    ),
)
EffectRegistry.register(
    # "Target creature can't block this turn" (Falter/Abandon the Post) and
    # "creatures your opponents control can't block this turn" (the mass
    # form) — the blocker-side mirror of "unblockable" just above.
    "cant_block_this_turn",
    lambda p: CantBlockEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        selector=p.get("selector"),
        filter=dict(p.get("filter") or {}),
        count=int(p.get("count", 1)),
        optional=bool(p.get("optional", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # "~ can't be blocked by creatures with power 2 or less this turn"
    # (Cavern Stomper) — the resolve-time sibling of the standing
    # `combat_restriction` static registered further down.
    "combat_restriction_this_turn",
    lambda p: GrantCombatRestrictionEffect(
        restriction=dict(p.get("restriction") or {}),
        target=p.get("target"),
        target_kind=p.get("target_kind"),
        restrict_to_source=bool(p.get("restrict_to_source", False)),
        selector=p.get("selector"),
        selector_params=dict(p.get("selector_params") or {}),
        creature_filter=p.get("creature_filter"),
        count=int(p.get("count", 1)),
        count_max=p.get("count_max"),
        count_selector=p.get("count_selector"),
        optional=bool(p.get("optional", False)),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    # RULE 506.4 "remove enchanted creature from combat" (Observed Stasis).
    "remove_from_combat",
    lambda p: RemoveFromCombatEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "attach",
    lambda p: AttachEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "permanent"),
        creature_filter=p.get("creature_filter"),
        mover=p.get("mover"),
        mover_kind=p.get("mover_kind"),
        mover_optional=bool(p.get("mover_optional", False)),
    ),
)
EffectRegistry.register(
    # "Attach up to one target Equipment you control to it / target Rebel you control." (Cloud, Ex-SOLDIER; Barret, Avalanche Leader; Yuffie)
    "attach_equipment",
    lambda p: AttachEquipmentEffect(
        to_source=bool(p.get("to_source", False)), creature_kind=p.get("creature_kind", "creature_you_control"),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # "…it becomes an Aura with '<quoted enchant text>.'" (RULE 305.1c/
    # 303.4f, MEC-44 — Necromancy) — see `BecomeAuraEffect`.
    "become_aura",
    lambda p: BecomeAuraEffect(quality=p.get("quality", "creature")),
)
EffectRegistry.register(
    # MEC-47 (Tempest Licid cycle) — see `LicidBecomeAuraEffect`.
    "licid_become_aura",
    lambda p: LicidBecomeAuraEffect(keep_creature=bool(p.get("keep_creature", False))),
)
EffectRegistry.register(
    "licid_revert",  # MEC-47 — "you may pay {cost} to end this effect"
    lambda p: LicidRevertEffect(),
)
EffectRegistry.register(
    # "Whenever a[n] <X> you control enters, you may attach it to target
    # creature you control." (Sigarda's Aid) — the mover is the trigger
    # event's own subject, not a chosen target; see
    # `AttachTriggeringPermanentEffect`.
    "attach_triggering_permanent",
    lambda p: AttachTriggeringPermanentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "unattach",
    lambda p: UnattachEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "attached_equipment_you_control"),
        optional=bool(p.get("optional", True)),
    ),
)
EffectRegistry.register(
    "enter_as_copy",  # "You may have this enter as a copy of target X" (RULE 614.1c/614.12)
    lambda p: EnterAsCopyReplacement(
        target_kind=p.get("target_kind", "permanent"),
        add_types=list(p.get("add_types", [])),
        add_subtypes=list(p.get("add_subtypes", [])),
        optional=bool(p.get("optional", True)),
        extra_counter_if_creature=p.get("extra_counter_if_creature"),
        extra_counter_if_planeswalker=p.get("extra_counter_if_planeswalker"),
        extra_counters_from_x=bool(p.get("extra_counters_from_x", False)),
        grant_mana_option=p.get("grant_mana_option"),
        only_types=p.get("only_types"),
        add_keywords=p.get("add_keywords"),
        add_keywords_if_target_lacks=p.get("add_keywords_if_target_lacks"),
        keep_own_abilities=bool(p.get("keep_own_abilities", False)),
        max_mana_value_from_mana_spent=bool(p.get("max_mana_value_from_mana_spent", False)),
        not_legendary=bool(p.get("not_legendary", False)),
        set_name=p.get("set_name"),
        until_end_of_turn=bool(p.get("until_end_of_turn", False)),
        creature_filter=p.get("creature_filter"),
        token_add_subtypes=p.get("token_add_subtypes"),
        token_set_colors=p.get("token_set_colors"),
    ),
)
EffectRegistry.register(
    "choose_creature_type_on_enter",  # "As ~ enters, choose a creature type." (RULE 601.2b)
    lambda p: ChooseCreatureTypeReplacement(),
)
EffectRegistry.register(
    "choose_card_type_on_enter",  # "As ~ enters, choose a card type." (RULE 601.2b, Serra's Emissary)
    lambda p: ChooseCardTypeReplacement(),
)
EffectRegistry.register(
    "choose_color_on_enter",  # "As ~ enters, choose a color." (RULE 601.2b)
    lambda p: ChooseColorReplacement(count=int(p.get("count", 1) or 1)),
)
EffectRegistry.register(
    "choose_basic_land_type_on_enter",  # "As ~ enters, choose a basic land type." (RULE 601.2b, PAR-4)
    lambda p: ChooseBasicLandTypeReplacement(),
)
EffectRegistry.register(
    # "As ~ enters the battlefield, choose a card name." (MEC-12, Pithing
    # Needle/Phyrexian Revoker-shaped) — hand-authored only, no oracle-text
    # grammar yet.
    "choose_card_name_on_enter",
    lambda p: ChooseCardNameReplacement(),
)
EffectRegistry.register(
    # "As this enters, choose <Label1> or <Label2>." (Struggle for Project
    # Purity-shaped) — hand-authored only, no oracle-text grammar yet.
    "choose_named_mode",
    lambda p: ChooseNamedModeReplacement(options=list(p.get("options", []))),
)
EffectRegistry.register(
    "choose_opponent_on_enter", lambda p: ChooseOpponentReplacement()
)
EffectRegistry.register(
    "choose_player_on_enter", lambda p: ChooseOpponentReplacement(include_self=True)
)
EffectRegistry.register(
    # "~ enters with your choice of a flying counter or a first strike counter
    # on it." (RULE 614.1/122.1b, MEC-108) — `RulesEngine._offer_enter_choices`.
    "choose_enter_counter",
    lambda p: ChooseEnterCounterReplacement(options=list(p.get("options", []))),
)
EffectRegistry.register(
    # "As this creature enters, choose a number." (Sanctum Prelate, MEC-43)
    # — hand-authored only, no oracle-text grammar yet.
    "choose_number_on_enter",
    lambda p: ChooseNumberReplacement(),
)
EffectRegistry.register(
    "become_copy_until_eot",  # "~ becomes a copy of target creature until end of turn" (Cursed Mirror)
    lambda p: BecomeCopyUntilEndOfTurnEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        add_types=p.get("add_types"), add_subtypes=p.get("add_subtypes"), add_keywords=p.get("add_keywords"),
        not_legendary=bool(p.get("not_legendary", False)),
        keep_own_abilities=bool(p.get("keep_own_abilities", False)),
        set_name=p.get("set_name"),
    ),
)
EffectRegistry.register(
    # "Target artifact you control becomes a copy of another target artifact or creature you control until end of
    # turn, except it's an artifact in addition to its other types." (Saheeli, Sublime Artificer)
    "become_copy_of_target_until_eot",
    lambda p: BecomeCopyOfTargetUntilEndOfTurnEffect(
        target_kind=p.get("target_kind", "artifact_you_control"),
        copy_target_kind=p.get("copy_target_kind", "artifact_or_creature_you_control"),
        add_types=p.get("add_types"),
    ),
)
EffectRegistry.register(
    # "{2}{U}: ~ becomes a copy of another target creature." (Shameless
    # Charlatan) — the *permanent* (non-reverting) sibling of the row above.
    "become_copy_permanent",
    lambda p: BecomeCopyPermanentEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        exact_mana_value=p.get("exact_mana_value"),
        add_types=p.get("add_types"), add_subtypes=p.get("add_subtypes"), add_keywords=p.get("add_keywords"),
        not_legendary=bool(p.get("not_legendary", False)),
        keep_own_abilities=bool(p.get("keep_own_abilities", False)),
        set_name=p.get("set_name"),
        previous_subject=bool(p.get("previous_subject", False)),
        optional=bool(p.get("optional", False)),
        retain_trigger_index=p.get("retain_trigger_index"),
    ),
)
EffectRegistry.register(
    "set_copy_target",  # Vesuvan Shapeshifter's "you may have it be a copy of another target creature"
    lambda p: SetCopyTargetEffect(
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
    ),
)
EffectRegistry.register(
    "conditional_copy",  # RULE 707/613 layer 1 — "as long as [condition], ~ is a copy of [target]"
    lambda p: StaticAbility(
        "copy",
        affects="self",
        params={
            "requires_untapped": bool(p.get("requires_untapped", False)),
            "add_types": list(p.get("add_types", [])),
            "add_subtypes": list(p.get("add_subtypes", [])),
        },
    ),
)
EffectRegistry.register(
    "text_change",  # RULE 612 layer 3 — word-substitution over effective_oracle_text
    lambda p: StaticAbility(
        "text",
        affects=p.get("affects", "self"),
        params={"replace": {str(k): str(v) for k, v in dict(p.get("replace", {})).items()}},
    ),
)
EffectRegistry.register(
    "add_counters",
    lambda p: AddCountersEffect(
        amount=p.get("amount", p.get("count", 1)),
        target_kind=p.get("target_kind"),
        kind=p.get("kind", "+1/+1"),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
        trigger_subject_key=p.get("trigger_subject_key"),
        # A distinct key from "count"/"amount" (both already the *counter*
        # amount per card) — this is the *target* count (RULE 115.1a N>=2,
        # "put a counter on each of up to two target creatures").
        count=p.get("target_count", 1),
        # ENG-30: "1 or 2" range ceiling — see `target_count`'s own comment.
        count_max=p.get("target_count_max"),
        count_selector=p.get("target_count_selector"),
        subtypes=p.get("subtypes"),
        divided=bool(p.get("divided", False)),
        creature_filter=p.get("creature_filter"),
        ring_bearer=bool(p.get("ring_bearer", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        distinct_from_others=bool(p.get("distinct_from_others", False)),
        previous_group=bool(p.get("previous_group", False)),
        previous_group_scope=p.get("previous_group_scope"),
        previous_selector=bool(p.get("previous_selector", False)),
        group=p.get("group"),
        kind_options=p.get("kind_options"),
        choose_one=bool(p.get("choose_one", False)),
        group_other=bool(p.get("group_other", False)),
        per_recipient_stat=p.get("per_recipient_stat"),
        group_player=p.get("group_player"),
        trigger_contributors=p.get("trigger_contributors", False),
    ),
)
EffectRegistry.register(
    "transfer_event_counters",
    lambda p: TransferEventCountersEffect(
        target_kind=p.get("target_kind", "creature"),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "class_level",  # RULE 716.2c: activating "Level N: <cost>" sets class level to N
    lambda p: ClassLevelEffect(level=p.get("level", 1)),
)
EffectRegistry.register(
    "pump",  # "target creature gets +N/+N (and gains <kw>) until end of turn"
    lambda p: PumpEffect(
        power=p.get("power", 0),
        toughness=p.get("toughness", 0),
        group_player=p.get("group_player"),
        keywords=list(p.get("keywords", [])),
        removed_keywords=list(p.get("removed_keywords", [])),
        trigger_subject=bool(p.get("trigger_subject", False)),
        trigger_event_key=p.get("trigger_event_key"),
        target_kind=p.get("target_kind"),
        selector=p.get("selector"),
        unblockable=bool(p.get("unblockable", False)),
        count=p.get("target_count", 1),
        count_max=p.get("target_count_max"),
        optional=bool(p.get("optional", False)),
        count_selector=p.get("count_selector"),
        per_recipient_controller_counter=p.get("per_recipient_controller_counter"),
        dynamic_amount=p.get("dynamic_amount"),
        amount_from_count_selector_axis=str(p.get("amount_from_count_selector_axis", "both")),
        creature_filter=p.get("creature_filter"),
        previous_subject=bool(p.get("previous_subject", False)),
        subtypes=p.get("subtypes"),
        self_multiplier=p.get("self_multiplier"),
        self_multiplier_stat=str(p.get("self_multiplier_stat", "both")),
        parametric_keywords=p.get("parametric_keywords"),
        colors=p.get("colors"),
        power_if_kicked=p.get("power_if_kicked"),  # MEC-82
        toughness_if_kicked=p.get("toughness_if_kicked"),
        power_if_bargained=p.get("power_if_bargained"),
        toughness_if_bargained=p.get("toughness_if_bargained"),
        target_operand=p.get("target_operand"),
        perpetual=bool(p.get("perpetual", False)),  # MEC-98
        card_zones=p.get("card_zones"),
        card_type=p.get("card_type"),
        keyword_options=p.get("keyword_options"),
    ),
)
EffectRegistry.register(
    "scry", lambda p: ScryEffect(
        count=p.get("count", p.get("amount", 1)), target_kind=p.get("target_kind"),
    )
)
EffectRegistry.register(
    # "look at the top N cards of [target player's] library, then put them back in any order"
    "look_reorder_top", lambda p: LookReorderTopEffect(
        count=p.get("count", p.get("amount", 1)), target_kind=p.get("target_kind"),
        may_shuffle=bool(p.get("may_shuffle", False)),
    )
)
EffectRegistry.register(
    "surveil", lambda p: SurveilEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    # RULE 701.69a "heal all damage from <permanent>" / "… is healed" — see `HealEffect`.
    "heal", lambda p: HealEffect(selector=p.get("selector"))
)
EffectRegistry.register(
    # RULE 701.29a "fateseal N" — scry on an opponent's library. See `FateSealEffect`.
    "fateseal", lambda p: FateSealEffect(count=p.get("count", p.get("amount", 1)))
)
EffectRegistry.register(
    "look_top_select",
    lambda p: LookTopSelectEffect(
        count=p.get("count", 1),
        select_count=p.get("select_count", 1),
        rest_destination=p.get("rest_destination", "library_bottom"),
        rest_order=p.get("rest_order"),
        select_optional=bool(p.get("select_optional", False)),
        select_filter=p.get("select_filter"),
    ),
)
EffectRegistry.register(
    # RULE 701.40a manifest / RULE 701.58a cloak — one effect, one ``kind``
    # param (see `ManifestEffect`).
    "manifest",
    lambda p: ManifestEffect(
        count=p.get("count", p.get("amount", 1)), kind=p.get("kind", "manifest"),
        player=p.get("player"),
    ),
)
EffectRegistry.register("manifest_dread", lambda p: ManifestDreadEffect())
# RULE 702.110a: the exploit keyword's own ETB "you may sacrifice a creature".
EffectRegistry.register("exploit", lambda p: ExploitEffect())
EffectRegistry.register(
    # RULE 708.8 by an effect: "you may turn a permanent you control face up".
    "turn_face_up_chosen",
    lambda p: TurnFaceUpChosenEffect(
        optional=bool(p.get("optional", True)),
        creature_only=bool(p.get("creature_only", False)),
        trigger_subject_key=p.get("trigger_subject_key"),
    ),
)
def _top_library_gate(p: dict) -> Optional[dict]:
    """A top-of-library grant's whole gate as one `static_conditions` dict: the printed "as long as …"
    (``active_if``) and the legacy per-card gates the parser's Class-level / Leveler wrappers stamp
    (``min_level``/``level_counter``, ``min_count_selector``, ``active_player_only``) — this effect is not a
    `StaticAbility`, so the layer engine's own gate never reads either."""
    from ..static_conditions import condition_from_legacy_params

    parts = [c for c in (p.get("active_if") if isinstance(p.get("active_if"), dict) else None,
                         condition_from_legacy_params(p)) if c]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else {"kind": "all", "conditions": parts}


EffectRegistry.register(
    "top_library_permission",
    lambda p: TopLibraryPermissionEffect(
        look=p.get("look", False),
        play_lands=p.get("play_lands", False),
        cast_spells=p.get("cast_spells", False),
        min_mana_value=p.get("min_mana_value"),
        requires_attached=p.get("requires_attached", False),
        noncreature_only=p.get("noncreature_only", False),
        grants_flash=p.get("grants_flash", False),
        life_payment=p.get("life_payment", False),
        chosen_type_creature_only=p.get("chosen_type_creature_only", False),
        creature_only=bool(p.get("creature_only", False)),
        subtypes=p.get("subtypes"),
        spell_criteria=p.get("spell_criteria"),
        land_criteria=p.get("land_criteria"),
        once_each_turn=bool(p.get("once_each_turn", False)),
        active_if=_top_library_gate(p),
        sacrifice_type=p.get("sacrifice_type"),
    ),
)
EffectRegistry.register(
    "graveyard_cast_permission",
    lambda p: GraveyardCastPermissionEffect(
        max_mana_value=p.get("max_mana_value"),
        permanent_only=p.get("permanent_only", True),
        once_per_turn=p.get("once_per_turn", True),
        exile_if_would_be_put_into_graveyard=p.get("exile_if_would_be_put_into_graveyard", False),
        per_permanent_type=bool(p.get("per_permanent_type", False)),
        lands_only=bool(p.get("lands_only", False)),
        spell_criteria=p.get("spell_criteria"),
        active_if=_top_library_gate(p),
        sacrifice_type=p.get("sacrifice_type"),
        plays_lands=bool(p.get("plays_lands", False)),  # Titania, Nature's Force: lands matching ``spell_criteria``
        exile_graveyard_cards=int(p.get("exile_graveyard_cards", 0) or 0),
        instant_sorcery_only=bool(p.get("instant_sorcery_only", False)),  # Lier: standing flashback
        arrived_not_from_battlefield_this_turn=bool(p.get("arrived_not_from_battlefield_this_turn", False)),  # Banon
        enters_tapped=bool(p.get("enters_tapped", False)),  # Edgar
    ),
)
EffectRegistry.register(
    "self_graveyard_or_exile_cast_permission",
    lambda p: SelfGraveyardOrExileCastPermissionEffect(
        zones=p.get("zones"), active_if=_top_library_gate(p),
    ),
)
EffectRegistry.register(
    "create_token",
    lambda p: CreateTokenEffect(
        count=p.get("count", 1),
        token_name=p.get("token_name"),
        power=p.get("power"),
        toughness=p.get("toughness"),
        colors=list(p.get("colors", [])),
        subtypes=list(p.get("subtypes", [])),
        keywords=list(p.get("keywords", [])),
        count_selector=p.get("count_selector"),
        creators=p.get("creators", "you"),
        target_kind=p.get("target_kind"),
        tapped=bool(p.get("tapped", False)),
        attacking=bool(p.get("attacking", False)),
        legendary=bool(p.get("legendary", False)),
        pt_amount=p.get("pt_amount"),
        extra_counters=p.get("extra_counters"),
        grant_self_anthem=p.get("grant_self_anthem"),
        is_artifact=bool(p.get("is_artifact", False)),
        parametric_keywords=p.get("parametric_keywords"),
        per_opponent=bool(p.get("per_opponent", False)),
        defender_planeswalker=bool(p.get("defender_planeswalker", False)),
        token_dies_gain_life=p.get("token_dies_gain_life"),
        oracle_text=str(p.get("oracle_text", "")),
        vehicle=bool(p.get("vehicle", False)),
        is_enchantment=bool(p.get("is_enchantment", False)),
    ),
)
EffectRegistry.register(
    # "Create a token that's a copy of <a specific named real card>"
    # (The Joiner of Cats). The name is clamped parser data.
    "create_token_copy_of_named",
    lambda p: CreateNamedCardTokenEffect(
        card_name=str(p.get("card_name", "")),
        count=int(p.get("count", 1)),
        tapped=bool(p.get("tapped", False)),
        attacking=bool(p.get("attacking", False)),
        not_legendary=bool(p.get("not_legendary", False)),
    ),
)
EffectRegistry.register(
    "pay_life_equal_to_opponents_combat_damaged_draw_that_many",
    lambda p: PayLifeEqualToOpponentsCombatDamagedDrawThatManyEffect(),
)
EffectRegistry.register(
    "amass",  # RULE 701.48 "Amass <Type> N" (Orcish Bowmasters, MEC-42)
    lambda p: AmassEffect(subtype=p.get("subtype", "Zombies"), count=p.get("count", 1)),
)
EffectRegistry.register("empower_jace", lambda p: EmpowerJaceEffect(count=p.get("count", 1)))
EffectRegistry.register(
    "copy_permanent",  # "Create a token that's a copy of target creature" (RULE 707)
    lambda p: CopyPermanentEffect(
        count=p.get("count", 1),
        target=p.get("target"),
        target_kind=p.get("target_kind", "creature"),
        count_selector=p.get("count_selector"),
        haste=bool(p.get("haste", False)),
        tapped=bool(p.get("tapped", False)),
        attacking=bool(p.get("attacking", False)),
        add_types=p.get("add_types"),
        add_subtypes=p.get("add_subtypes"),
        not_legendary=bool(p.get("not_legendary", False)),
        referent=p.get("referent", "source"),
        require_exiled_trigger_subject=bool(p.get("require_exiled_trigger_subject", False)),
        target_instance_id=p.get("target_instance_id"),
        enter_counters=p.get("enter_counters"),
        target_count=int(p.get("target_count", 1) or 1),
        target_count_max=p.get("target_count_max"),
        target_optional=bool(p.get("target_optional", False)),
        set_power=p.get("set_power"),
        set_toughness=p.get("set_toughness"),
        set_colors=p.get("set_colors"),
        add_colors=p.get("add_colors"),
        extra_temp_keywords=p.get("extra_temp_keywords"),
        creature_filter=p.get("creature_filter"),
        legendary=bool(p.get("legendary", False)),
        max_mana_value=p.get("max_mana_value"),
        other_opponents=bool(p.get("other_opponents", False)),
    ),
)
EffectRegistry.register(
    "intuition_search",
    lambda p: IntuitionEffect(
        count=p.get("count", 3),
        search_optional=bool(p.get("search_optional", False)),
        distinct_names=bool(p.get("distinct_names", False)),
        chosen_count=p.get("chosen_count", 1),
        chosen_destination=p.get("chosen_destination", "hand"),
        rest_destination=p.get("rest_destination", "graveyard"),
    ),
)
EffectRegistry.register(
    "search",
    lambda p: SearchLibraryEffect(
        # "criteria" is the general form; "type" stays a shorthand for a
        # type-line restriction so an oracle handler can emit either.
        criteria=p.get("criteria", p.get("type", "")),
        destination=p.get("destination", "hand"),
        count=p.get("count", 1),
        optional=p.get("optional", True),
        player=p.get("player"),
        zones=p.get("zones"),
        destinations=p.get("destinations"),
        destination_if=p.get("destination_if"),
        exile_rest=p.get("exile_rest", False),
        mana_value_from=p.get("mana_value_from"),
        extra_counters=p.get("extra_counters"),
        attach_to_creature_you_control=bool(p.get("attach_to_creature_you_control", False)),
        remember=bool(p.get("remember", False)),
        total_mana_value_budget=p.get("total_mana_value_budget"),
        player_from_target=bool(p.get("player_from_target", False)),
        share_land_type=bool(p.get("share_land_type", False)),
        track_exiled_with=bool(p.get("track_exiled_with", False)),
        untap_if_lands_at_least=p.get("untap_if_lands_at_least"),
        then_specs=p.get("then_specs"),
    ),
)
EffectRegistry.register(
    "impulsive_look",
    lambda p: ImpulsiveLookEffect(
        count=p.get("count", 1),
        criteria=p.get("criteria", ""),
        hit_destination=p.get("hit_destination", "hand"),
        miss_destination=p.get("miss_destination", "graveyard"),
        optional=p.get("optional", True),
        hit_grant_keywords=p.get("hit_grant_keywords"),
        miss_effect_specs=p.get("miss_effect_specs"),
        hit_effect_specs=p.get("hit_effect_specs"),
    ),
)
EffectRegistry.register(
    "impulsive_draw",
    lambda p: ImpulsiveDrawEffect(
        count=p.get("count", 1), same_turn_only=bool(p.get("same_turn_only", False)),
        choose_one=bool(p.get("choose_one", False)),
        each_player=bool(p.get("each_player", False)),  # Mezzio Mugger
        mana_wildcard=p.get("mana_wildcard"),
        library_of=p.get("library_of"),  # Grenzo, Havoc Raiser: "that player's library"
        rest_to_bottom=bool(p.get("rest_to_bottom", False)),  # Florian, Voldaren Scion
        only_spells=bool(p.get("only_spells", False)),
    ),
)
EffectRegistry.register(
    "draw_reveal_cast_one_free",
    lambda p: DrawRevealCastOneFreeEffect(count=p.get("count", 1)),
)
EffectRegistry.register(
    "exile_opponents_graveyards_impulsive_cast",  # Mnemonic Betrayal
    lambda p: GraveyardImpulsiveCastEffect(mana_wildcard=p.get("mana_wildcard", "type")),
)
EffectRegistry.register("shuffle", lambda p: ShuffleLibraryEffect())
EffectRegistry.register(
    # RULE 701.20 — "shuffle your hand and graveyard into your library". The
    # wheel family's first sentence; the "then draws N cards" tail is a
    # sibling `draw` with ``selector="each_player"`` (ENG-37 retired the
    # fused `wheel`/`wheel_of_fortune`/`windfall` types onto `seq`/`bind`).
    "shuffle_hand_and_graveyard_into_library",
    lambda p: ShuffleHandAndGraveyardIntoLibraryEffect(scope=p.get("scope")),
)
EffectRegistry.register(
    "transform", lambda p: TransformEffect(target_kind=p.get("target_kind"))
)
EffectRegistry.register(
    # RULE 701.42a "exile them, then meld them into <result>." — see `MeldEffect`.
    "meld",
    lambda p: MeldEffect(
        partner_name=p.get("partner_name", ""), result_name=p.get("result_name", ""),
        tapped_attacking=bool(p.get("tapped_attacking", False)),
    ),
)
EffectRegistry.register(
    # "Look at the top card of your library. If it's a[n] <type> card,
    # transform ~." (Delver of Secrets-shaped).
    "reveal_top_then_transform",
    lambda p: RevealTopThenTransformEffect(criteria=p.get("criteria", "")),
)
EffectRegistry.register(
    "exile_return_transformed", lambda p: ExileReturnTransformedEffect()
)
EffectRegistry.register(
    "coin_flip",
    lambda p: CoinFlipEffect(
        win_effects=p.get("win_effects"), lose_effects=p.get("lose_effects"),
    ),
)
EffectRegistry.register(
    # RULE 701.30 "clash with an opponent" — see `ClashEffect`. The "if you
    # win, …" / "otherwise, …" branches are separate condition-gated specs,
    # not params here.
    "clash",
    lambda p: ClashEffect(with_opponent=p.get("with_opponent", True)),
)
EffectRegistry.register(
    # RULE 706 "roll a d20." / "roll two six-sided dice." — see `RollDieEffect`.
    # ``outcomes`` is the RULE 706.3a results table (list of {min,max,effects});
    # a bare roll with no table carries none.
    "roll_die",
    lambda p: RollDieEffect(
        sides=p.get("sides", 20),
        count=p.get("count", 1),
        ignore_lowest=p.get("ignore_lowest", 0),
        ignore_highest=p.get("ignore_highest", 0),
        outcomes=p.get("outcomes"),
        then_trigger=p.get("then_trigger"),
    ),
)
EffectRegistry.register(
    # RULE 706's other randomization — "a number from A to B chosen at
    # random" (Hapato's Might, PAR-80) — see `RandomNumberEffect`.
    "random_number",
    lambda p: RandomNumberEffect(min_value=p.get("min", 0), max_value=p.get("max", 6)),
)
EffectRegistry.register(
    # "`<process>`, then clash …. If you win, repeat this process." (Hoarder's Greed)
    "repeat_process",
    lambda p: RepeatProcessEffect(
        effects=list(p.get("effects", [])),
        repeat_while=p.get("repeat_while", "clash_won"),
    ),
)
# RULE 901.10 / 901.13 — "planeswalk" / "chaos ensues" outcome bodies
# (Path of the Animist/Enigma's vote; Plain Walker). No params.
EffectRegistry.register("planeswalk", lambda p: PlaneswalkEffect())
EffectRegistry.register("chaos_ensues", lambda p: ChaosEnsuesEffect())
EffectRegistry.register(
    "return_from_graveyard_transformed", lambda p: ReturnFromGraveyardTransformedEffect()
)
EffectRegistry.register(
    # "Return this card from your graveyard to the battlefield[, tapped]."
    # (Dread Wanderer/Bloodsoaked Champion/Drownyard Temple &c) — the plain
    # sibling of `return_from_graveyard_transformed` above.
    "return_self_from_graveyard",
    lambda p: ReturnSelfFromGraveyardToBattlefieldEffect(
        tapped=bool(p.get("tapped", False)), attacking=bool(p.get("attacking", False)),
        extra_counters=p.get("extra_counters"),
        attach_to_previous=bool(p.get("attach_to_previous", False)),
        face_choice=bool(p.get("face_choice", False)),
    ),
)
EffectRegistry.register(
    # "When enchanted creature dies, return that card to the battlefield
    # under its owner's control." (Gift of Immortality, PAR-60)
    "return_dying_subject_to_battlefield",
    lambda p: ReturnDyingSubjectToBattlefieldEffect(),
)
EffectRegistry.register(
    # "…return that card under its owner's control. Return this card
    # attached to that creature at the beginning of the next end step."
    # (Gift of Immortality, PAR-60)
    "gift_of_immortality_dies",
    lambda p: GiftOfImmortalityDiesEffect(),
)
EffectRegistry.register(
    # "…that creature gains 'when this creature dies, return it to the
    # battlefield tapped under its owner's control.'" (Malakir Rebirth's
    # granted death-return, temporary — unlike `return_self_from_graveyard`
    # above, which is a printed permanent's own standing ability) — the
    # untargeted, self-acting sibling of `return_from_graveyard`.
    "return_self_from_graveyard_untargeted",
    lambda p: ReturnSelfFromGraveyardEffect(
        destination=p.get("destination", "hand"),
        tapped=bool(p.get("tapped", False)),
        under_your_control=bool(p.get("under_your_control", False)),
        transformed=bool(p.get("transformed", False)),
    ),
)
EffectRegistry.register(
    # "Return this card from your graveyard to your hand." (PAR-16 —
    # Abzan Devotee/Aurora Eidolon &c) — the hand-destination sibling of
    # `return_self_from_graveyard` right above.
    "return_self_from_graveyard_to_hand",
    lambda p: ReturnSelfFromGraveyardToHandEffect(),
)
EffectRegistry.register(
    # "{N}: Put this card from your hand onto the battlefield." (Talon
    # Gates of Madara-shaped).
    "put_self_onto_battlefield_from_hand",
    lambda p: PutSelfOntoBattlefieldFromHandEffect(),
)
EffectRegistry.register(
    # "return it to the battlefield. It's a[n] <type> with '<ability>'. ~
    # loses all other abilities." (Harold and Bob, First Numens) —
    # hand-authored only, no oracle-text grammar for this shape yet.
    "return_dies_as_new_permanent",
    lambda p: ReturnDiesAsNewPermanentEffect(
        new_type_line=p.get("new_type_line", ""),
        new_oracle_text=p.get("new_oracle_text", ""),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register("become_prepared", lambda p: BecomePreparedEffect())
EffectRegistry.register(
    "phase_out",
    lambda p: PhaseOutEffect(
        target_kind=p.get("target_kind"),
        optional=bool(p.get("optional", False)),
        previous_subject=bool(p.get("previous_subject", False)),
        self_target=bool(p.get("self_target", False)),
        count=int(p.get("count", 1)),
        count_selector=p.get("count_selector"),
    ),
)
EffectRegistry.register("cascade", lambda p: CascadeEffect(mana_value=p.get("mana_value")))
EffectRegistry.register("proliferate", lambda p: ProliferateEffect(times=p.get("times", 1)))
EffectRegistry.register(
    # "Exile the top card of your library. You may play that card until you exile another card with this enchantment." (Furious Rise)
    "exile_top_play_until_next_exile",
    lambda p: ExileTopPlayUntilNextExileEffect(),
)
EffectRegistry.register(
    # "Nonartifact spells you cast have improvise." (Inspiring Statuary) — read by `GameEngine._help_pay_keyword`.
    "grant_help_pay_to_spells",
    lambda p: StaticAbility("spell_help_pay_grant", affects="self", params={
        "keyword": str(p.get("keyword", "improvise")),
        **({"exclude_card_type": str(p["exclude_card_type"])} if p.get("exclude_card_type") else {}),
    }),
)
EffectRegistry.register(
    # "…gains indestructible until end of turn. Put ~'s counters on that creature and attach an Equipment that was attached to ~ to that
    # creature." (Zack Fair)
    "transfer_sacrificed_legacy",
    lambda p: TransferSacrificedLegacyEffect(target_kind=p.get("target_kind", "creature_you_control")),
)
EffectRegistry.register(
    # "Put a +1/+1 counter on it if it's a creature and a loyalty counter on it if it's a planeswalker." (Forge of Heroes)
    "add_counter_matching_type",
    lambda p: AddCounterMatchingTypeEffect(target_kind=p.get("target_kind", "commander_entered_this_turn")),
)
EffectRegistry.register(
    # "remove all counters from target permanent" / "remove all counters
    # from all permanents" (RULE 122 — Vampire Hexmage/Oblivion Stone/
    # Aether Snap/Thief of Blood-shaped); no ``target_kind`` = untargeted,
    # board-wide. ``max_count`` (Glissa Sunslayer/Heartless Act/Render
    # Inert-shaped "remove up to N counters") switches to the interactive
    # chosen-amount shape instead — see `RemoveCountersEffect`.
    "remove_counters",
    lambda p: RemoveCountersEffect(
        target_kind=p.get("target_kind"), max_count=p.get("max_count"),
        draw_per_removed=bool(p.get("draw_per_removed", False)),
        self_only=bool(p.get("self_only", False)), kind=p.get("kind"),
        keep=int(p.get("keep", 0) or 0),
        count=p.get("count"),
        previous_subject=bool(p.get("previous_subject", False)),
    ),
)
EffectRegistry.register(
    "add_entry_counters",
    lambda p: AddEntryCountersEffect(amount=p.get("amount", 0), kind=p.get("kind", "+1/+1")),
)
EffectRegistry.register(
    # "Move a counter from target permanent you control onto a second
    # target permanent." (Nesting Grounds) — see `MoveCountersEffect`.
    "move_counters",
    lambda p: MoveCountersEffect(
        source_target_kind=p.get("source_target_kind", "permanent_you_control"),
        dest_target_kind=p.get("dest_target_kind", "permanent"),
        count=int(p.get("count", 1) or 1),
        move_all_kinds=bool(p.get("move_all_kinds", False)),
        any_number=bool(p.get("any_number", False)),
        choose_kind=bool(p.get("choose_kind", False)),
    ),
)
EffectRegistry.register(
    # "…choose any number of permanents you control that had a counter put on them this way. Those
    # permanents phase out." (Ripples of Potential) — see `PhaseOutProliferatedEffect`.
    "phase_out_proliferated",
    lambda p: PhaseOutProliferatedEffect(),
)
EffectRegistry.register(
    # "…move any number of +1/+1 counters from this creature onto other
    # creatures." (Forgotten Ancient, PAR-60 — simplified to all-onto-one)
    "move_all_plus_one_counters_from_self",
    lambda p: MoveAllPlusOneCountersFromSelfEffect(),
)
EffectRegistry.register(
    # "Remove any number of counters from among permanents on the
    # battlefield. You draw cards and lose life equal to the number of
    # counters removed this way." (Eventide's Shadow) — see
    # `RemoveCountersFromAmongThenDrawLoseLifeEffect`.
    "remove_counters_from_among_then_draw_lose_life",
    lambda p: RemoveCountersFromAmongThenDrawLoseLifeEffect(),
)
EffectRegistry.register(
    # The draw/lose-life tail of the above — queued as ``then_specs``.
    "draw_lose_life_counter_removed_delta",
    lambda p: DrawLoseLifeCounterRemovedDeltaEffect(
        player_id=p.get("player_id"), before=int(p.get("before", 0) or 0),
    ),
)
EffectRegistry.register(
    # "You may remove a lore counter from each of any number of Sagas you
    # control. Put a +1/+1 counter on ~ for each lore counter removed this
    # way." (Garnet, Princess of Alexandria, PAR-67) — see
    # `RemoveLoreCounterFromChosenSagasThenAddCountersEffect`.
    "remove_lore_counter_from_chosen_sagas_then_add_counters",
    lambda p: RemoveLoreCounterFromChosenSagasThenAddCountersEffect(),
)
EffectRegistry.register(
    # The +1/+1 tail of the above — queued as ``then_specs``.
    "add_counters_from_saga_lore_removed_delta",
    lambda p: AddCountersFromSagaLoreRemovedDeltaEffect(
        source_id=p.get("source_id"), player_id=p.get("player_id"),
        before=int(p.get("before", 0) or 0),
    ),
)
EffectRegistry.register(
    # "Double the number of each kind of counter on target creature."
    # (Ferrafor, Young Yew) — see `DoubleCountersOnTargetEffect`.
    "double_counters_on_target",
    lambda p: DoubleCountersOnTargetEffect(
        target_kind=p.get("target_kind", "creature"),
        mode=p.get("mode", "target"),
        kind=p.get("kind"),
        target_count=int(p.get("target_count", 1)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    "discover",
    lambda p: DiscoverEffect(
        mana_value=p.get("mana_value", p.get("amount", 0)),
        cast_limit=p.get("cast_limit"), treasures_below=p.get("treasures_below"),
    ),
)

# Static abilities applied through the layer system (RULE 613). Each becomes a
# `StaticAbility`; `game/continuous.py` folds them into derived characteristics.

#: The extra selector filters a static ability may narrow its `affects` set by —
#: a tribal subtype, tokens-only, a colour, "other" (exclude the source), or a
#: RULE 613.6-style "as long as this source's own <counter> is in range"
#: conditional gate (`min_level`/`max_level`/`level_counter` — Leveler tiers,
#: RULE 711, and cumulative Class levels, RULE 716). `continuous.
#: affected_objects`/`group_selector_objects` read these; only the non-
#: ``None`` ones are carried so a filter is off unless the parser/author set it.
_SELECTOR_KEYS: tuple[str, ...] = (
    "subtype", "tokens", "color", "exclude_self",
    "min_level", "max_level", "level_counter",
    # "During your turn, …" (Nahiri, Storm of Stone).
    "active_player_only",
    # Metalcraft-style "as long as you control N or more <count_selector>"
    # (Indomitable Archangel).
    "min_count_selector", "min_count",
    # A printed-card-type filter ("Artifacts your opponents control enter
    # tapped.", "Nonbasic lands are Mountains.") and its "nonbasic" qualifier
    # — `continuous._has_card_type`/the "basic" substring check.
    "card_type", "nonbasic",
    # RULE 601.2b "… of the chosen type/color …" (Adaptive Automaton/Caged
    # Sun-shaped) — read the ability source's own `chosen_type`/
    # `chosen_color` fresh each recompute instead of a literal `subtype`/
    # `color` baked in at parse time; see `continuous.group_selector_objects`.
    "subtype_from_source", "color_from_source",
    # "Activated abilities of permanents/sources **with the chosen name**
    # can't be activated …" (MEC-12, Pithing Needle/Phyrexian Revoker) — the
    # naming-choice sibling of `subtype_from_source`/`color_from_source`,
    # reading the ability source's own `chosen_card_name` fresh each
    # recompute instead of a literal baked in at parse time.
    "card_name_from_source",
    # A per-object power/toughness qualifier on the scope itself ("Each
    # creature you control **with power 4 or greater** …" — Challenger
    # Troll/Flopsie-shaped); read off each affected object's own *derived*
    # characteristics, unlike every filter above (all about type/colour).
    "min_power", "max_power", "min_toughness", "max_toughness",
    # A counter-presence qualifier on the scope ("Each creature you control
    # **with a +1/+1 counter on it** has flying." — the Abzan "outlast"
    # cycle, PAR-34); `continuous.affected_objects` reads it directly. Some
    # factories (`grant_borrowed_activated_ability`) thread it explicitly
    # too — listing it here makes it uniform across every scope-taking
    # factory via `_selectors`.
    "has_counter_kind",
    # The same qualifier with a *dynamic* threshold instead of a literal
    # ("Creatures your opponents control with power less than ~'s power are
    # goaded." — Baeloth Barrityl): `continuous.dynamic_threshold`'s
    # vocabulary, strict `<`/`>` to match the printed "less/greater than".
    "power_lt_selector", "power_gt_selector",
    # RULE 613.6's general "as long as <condition>" gate — one whitelisted
    # dict from `game/static_conditions.py`, evaluated live every recompute
    # (`continuous.group_selector_objects`). The three older gates above
    # (`active_player_only`, `min_level`/`max_level`, `min_count_selector`/
    # `min_count`) are the same idea per-card, and are translated into this
    # vocabulary rather than evaluated separately.
    "active_if",
    # RULE 112.7a's printed exception — "As long as this card is in your
    # graveyard, …" (Anger-shaped) — read by `continuous.
    # _battlefield_static_abilities`'s separate graveyard scan, which is
    # also what makes the *source's own zone* gate correct here: nothing
    # else about this static changes, only where it's looked for.
    "from_graveyard",
    # PAR-134: one `combat.matches_object_filter` dict narrowing the scope by
    # a state/supertype/designation adjective or a coordinated list ("Tapped
    # creatures …", "Commanders …", "Ninja and Rogue creatures …"); see
    # `continuous.group_selector_objects`.
    "object_filter",
)


def _selectors(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in _SELECTOR_KEYS if p.get(k) is not None}


EffectRegistry.register(
    "anthem",  # "Creatures you control get +N/+N" (layer 7c); tribal/colour-scoped
    lambda p: StaticAbility(
        "pt_mod",
        affects=p.get("affects", "other_creatures_you_control"),
        params={
            "power": p.get("power", 0), "toughness": p.get("toughness", 0),
            # A per-count anthem ("+1/+1 for each land you control") — see
            # `continuous._pt_mod_count` for the selector vocabulary
            # (controller-scoped `count_selector` names, plus the per-object
            # ``"equipment_attached_to_self"``).
            "power_count": p.get("power_count"), "toughness_count": p.get("toughness_count"),
            # The counter kind ``"counters_on_self"`` (`continuous.
            # _pt_mod_count`) reads — "unity"/other named counters, default
            # "+1/+1" so an unparameterized per-counter anthem is unchanged.
            "counter_kind": p.get("counter_kind", "+1/+1"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_set",  # "Each creature is 1/1" (layer 7b)
    lambda p: StaticAbility(
        "pt_set",
        affects=p.get("affects", "all_creatures"),
        params={"power": p.get("power", 0), "toughness": p.get("toughness", 0),
                "power_count": p.get("power_count"), "toughness_count": p.get("toughness_count"),
                **_selectors(p)},
    ),
)
EffectRegistry.register(
    # RULE 701.15b goad as a *standing static* ("Enchanted creature gets +2/+2
    # and is goaded.") — not a layer at all: goaded is explicitly neither an
    # ability nor a copiable value, so it can't be a layer-6 grant. Stamped
    # onto `GameObject._goaded_by_static` by `continuous.recompute` in the
    # same non-RULE-613 bucket the combat restrictions use.
    "goaded",
    lambda p: StaticAbility(
        "goaded",
        affects=p.get("affects", "attached_permanent"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "grant_keyword",  # "Creatures you control have flying" (layer 6); tribal too
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "keywords": list(p.get("keywords", [])),
            **({"mana_source_kind": p["mana_source_kind"]} if p.get("mana_source_kind") else {}),
            **({"first_matching_each_turn": True} if p.get("first_matching_each_turn") else {}),
            # Wildsear: "Enchantment spells you cast from your hand have cascade."
            **({"card_types": list(p["card_types"])} if p.get("card_types") else {}),
            **({"from_hand": True} if p.get("from_hand") else {}),
            # ENG-31: parametric keyword grants ("~ has firebending N …") —
            # ``[{"name": str, "n": int}, ...]``, stamped onto
            # `GameObject._granted_parametric_keywords` by `continuous._apply_
            # layer_6_ability` since a numbered keyword can't be a bare slug.
            **({"parametric_keywords": [dict(pk) for pk in p["parametric_keywords"]]}
               if p.get("parametric_keywords") else {}),
            # RULE 702.21b's quoted grant ("Other creatures you control
            # have 'Ward—Pay 2 life.'") — see `continuous.recompute`'s own
            # `ward_cost` consumer for why this rides `grant_keyword`
            # rather than a dedicated static kind.
            **({"ward_cost": p["ward_cost"]} if p.get("ward_cost") else {}),
            **({"cumulative_upkeep_cost": p["cumulative_upkeep_cost"]}
               if p.get("cumulative_upkeep_cost") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Equipped creature … loses flying" (Colossus Hammer) — layer 6,
    # ability-*removing* (RULE 613.7f), the mirror image of `grant_keyword`:
    # strips a flag keyword from `_obj_keywords` (`game/combat.py`) instead
    # of adding one, regardless of which of the object's three keyword
    # sources granted it.
    "remove_keyword",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={"remove_keywords": list(p.get("keywords", [])), **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "All creatures lose all abilities" (Humility, Dress Down) — layer 6,
    # RULE 613.7f, stripping *every* ability (keywords via `_obj_keywords`,
    # triggered/activated abilities gated at fire/activate time on
    # `GameObject.loses_all_abilities`), not just a named keyword.
    "remove_all_abilities",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "all_creatures"),
        params={"lose_all_abilities": True, **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "Cats you control have protection from Rats." (Hungry Lynx) /
    # "White creatures you control have protection from black." (Righteous
    # War) / "All creatures have protection from black." (Absolute Grace) /
    # "Enchanted creature has protection from the chosen color."
    # (Flickering Ward/Cho-Manno's Blessing) — layer 6, ability-adding
    # (RULE 613.7f/702.16), the *standing* sibling of the resolve-time
    # "until end of turn" grant `GameObject.temp_protections` already
    # carried (Mother of Runes). `continuous.recompute` folds the qualities
    # onto `obj._granted_protections`; `combat.is_protected_from` unions
    # them with the printed ones.
    #
    # ``protections`` is the printed quality word list, normalized to
    # `combat.protections_of_text` tokens at recompute time (the parser
    # front-end can't do it — no `game/` imports).
    # ``protection_from_chosen_color`` is the RULE 601.2b dynamic variant,
    # re-read off the source's own `chosen_color` every pass.
    #
    # Named ``_static`` to distinguish it from the pre-existing, unrelated
    # one-shot `grant_protection` above (Mother of Runes' resolve-time
    # "until end of turn" grant onto `temp_protections`) — same rule,
    # opposite duration, and `EffectRegistry.register` silently overwrites
    # a duplicate name.
    "grant_protection_static",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "protections": [str(q) for q in p.get("protections", [])],
            "protection_from_chosen_color": bool(
                p.get("protection_from_chosen_color", False)
            ),
            "protection_from_chosen_type": bool(
                p.get("protection_from_chosen_type", False)
            ),
            # "You and creatures you control have protection from …" (Serra's Emissary) — the controller half; a player
            # carries no text of its own, so `continuous.player_static_protections` reads it for `RulesEngine.deal_damage`.
            "protects_controller": bool(p.get("protects_controller", False)),
            # "…protection from each color that's not in your commander's
            # color identity." (Commander's Plate, MEC-43) — the complement
            # of `continuous.commander_color_identity`, read fresh every
            # pass the same way the two ``chosen_*`` branches above are.
            "protection_from_colors_not_in_commanders_identity": bool(
                p.get("protection_from_colors_not_in_commanders_identity", False)
            ),
            # "Artifacts you control have protection from each mana value among artifacts you control." (Rebbec,
            # Architect of Ascension) — one ``mv:N`` quality per distinct mana value, re-read every pass.
            "protection_from_mana_values_among_artifacts": bool(
                p.get("protection_from_mana_values_among_artifacts", False)
            ),
            # RULE 702.16n/p: "This effect doesn't remove this Aura." —
            # exempts the *granting* object's own attachment from RULE
            # 704.5m/n's illegal-attachment fall-off (`continuous.py`'s
            # layer-6 pass sets `GameObject._protection_self_exempt` on the
            # ability's source when this is set).
            "exempt_own_attachment": bool(p.get("exempt_own_attachment", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '{T}: Add {B}.'" (Tyvar Kell) — layer 6,
    # ability-adding (RULE 613.7f), same layer/bucket as `grant_keyword`, just
    # granting a mana ability's production options instead of a keyword.
    # `continuous.recompute` folds these onto `obj._granted_mana`; read
    # together with the object's own printed options via
    # `mana_abilities.mana_options_for`.
    #
    # ``cost`` (MEC-25, Goldspan Dragon — an `ActivationCost`-shaped dict,
    # same spelling `AbilitySpec.cost` uses) is the *upgrade* sibling: when
    # given, the granted ability isn't a bare repeatable ``{T}`` (the
    # default, unchanged for every pre-existing caller) but that cost
    # instead, and it *replaces* a printed mana ability of the same cost
    # shape on each affected object rather than adding an independent one
    # alongside it — "Treasures you control have '{T}, Sacrifice this
    # artifact: Add two mana of any one color.'" upgrades the token's own
    # printed one-mana version rather than granting a second, competing
    # ability. See `continuous._apply_layer_6_ability`'s ``mana_ability_
    # cost`` handling and `mana_abilities.mana_abilities_for`'s
    # replace-matching.
    "grant_mana_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "mana": list(p.get("mana", [])),
            **({"mana_restriction": dict(p["mana_restriction"])} if p.get("mana_restriction") else {}),
            **({"mana_any_combination": True} if p.get("mana_any_combination") else {}),
            **({"granted_mana_cost": str(p["granted_mana_cost"])} if p.get("granted_mana_cost") else {}),
            **({"mana_ability_cost": dict(p["cost"])} if p.get("cost") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # A quoted layer-6 replacement, for example "Creatures of type X have
    # 'If this permanent would be put into a graveyard, you may put it on top
    # of its owner's library instead.'"  The concrete group is carried by
    # the ordinary selectors, so this is not tied to either a creature type
    # or a card.
    "grant_graveyard_to_library_replacement",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "self"),
        params={"graveyard_to_library_replacement": True, **_selectors(p)},
    ),
)
EffectRegistry.register(
    # "You may spend mana as though it were mana of any color to activate
    # abilities of creatures you control." (MEC-21, Agatha's Soul Cauldron)
    # — a standing RULE 605.1a wildcard *permission* over activation-cost
    # mana, not a layer-6 characteristic grant at all (so it rides its own
    # non-RULE-613 bucket, same treatment `no_max_hand_size`/`extra_land_
    # drop` already get). ``creature_abilities_only`` (default ``True``,
    # matching every printed card seen so far) scopes it to abilities whose
    # *source* is a creature — see `continuous.any_color_for_activation`,
    # consulted by the activation-cost payment path in
    # `game/engine/activation_mixin.py` (`ManaPool`'s own ``wildcard`` param,
    # already shipped for RULE 605.1a casting-side grants).
    #
    # ``from_color`` (MEC-23, Quicksilver Elemental's own second ability —
    # "You may spend **blue** mana as though it were mana of any color to
    # pay the activation costs of this creature's abilities.") narrows
    # *which* mana counts as the wildcard: Agatha's grant lets any of the
    # five colors pay any colored pip, but Quicksilver's only lets **blue**
    # mana substitute — a green pip still needs real green (or blue) mana,
    # never white/black/red. ``None`` (every pre-existing card) keeps
    # Agatha's fully unrestricted behaviour. ``self_only`` narrows *whose*
    # abilities the grant covers to this exact permanent's own — Quicksilver
    # scopes to "this creature's abilities", not Agatha's unscoped
    # "creatures you control".
    "grant_any_color_for_activation",
    lambda p: StaticAbility(
        "any_color_for_activation",
        affects=p.get("affects", "you"),
        params={
            "creature_abilities_only": bool(p.get("creature_abilities_only", True)),
            **({"from_color": str(p["from_color"])} if p.get("from_color") else {}),
            **({"self_only": True} if p.get("self_only") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Creatures you control with +1/+1 counters on them have all activated
    # abilities of all creature cards exiled with ~." (MEC-21, Agatha's Soul
    # Cauldron) — a *dynamic* layer-6 ability grant whose granted-ability
    # set isn't fixed at parse time (`grant_activated_ability`'s own
    # ``grant_effects``) but read live off whichever creature cards this
    # static's own source has accumulated via `ExileEffect`'s generalized
    # ``track_exiled_with`` (`GameObject.exiled_with_ids`) — MEC-21's other
    # named primitive, reusable by any future "exile with ~" card (~185
    # cached cards print that shape). ``has_counter_kind`` (``None`` unless
    # given — MEC-26's Drana and Linvala/Scheming Fence print no such
    # qualifier on their own grantee, only Agatha's own "creatures you
    # control **with +1/+1 counters on them**" needs it, so it now passes
    # ``"+1/+1"`` explicitly rather than relying on a default every other
    # caller would silently inherit) is the *grantee* scope's own
    # qualifier — see `continuous.group_selector_objects`'s matching
    # filter — and ``creature_only`` (default ``True``) filters which
    # *donor* permanents contribute, matching the printed "creature cards
    # exiled with ~" (narrowed to ``False`` by Scheming Fence, whose donor
    # can be any nonland permanent type).
    # See `continuous._apply_borrowed_activated_abilities` for how each
    # borrowed ability is actually built.
    #
    # ``source_mode`` (MEC-26, Drana and Linvala / Scheming Fence) picks
    # *which* permanents' abilities get borrowed, generalizing beyond the
    # original ``exiled_with`` (default, unchanged) shape:
    #   - ``"exiled_with"``: `GameObject.exiled_with_ids` (Agatha's Soul
    #     Cauldron's own shape, above).
    #   - ``"group"``: a **standing, live-rederived** `affects` selector on
    #     the *battlefield* itself (``source_affects``, e.g.
    #     ``"creatures_opponents_control"``) — "Drana and Linvala has all
    #     activated abilities of all creatures your opponents control.":
    #     no exiling involved, so `exiled_with_ids` doesn't apply, but the
    #     "read the donor set live every recompute" shape is identical.
    #   - ``"chosen_permanent"``: `GameObject.chosen_permanent_id`
    #     (`continuous.group_selector_objects`'s matching selector) — "This
    #     creature has all activated abilities of the chosen permanent."
    #     (Scheming Fence), a single donor picked once by its own ETB
    #     `_request_choose_objects` rather than exiled or group-scoped.
    # ``exclude_loyalty`` (Scheming Fence's own "…except for loyalty
    # abilities" — RULE 606.5c abilities are a planeswalker-only concept
    # that makes no sense borrowed onto a creature) drops any donor ability
    # whose cost `is_loyalty`.
    "grant_borrowed_activated_ability",
    lambda p: StaticAbility(
        "borrowed_activated_ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            **({"has_counter_kind": str(p["has_counter_kind"])} if p.get("has_counter_kind") else {}),
            "creature_only": bool(p.get("creature_only", True)),
            "source_mode": p.get("source_mode", "exiled_with"),
            **({"source_affects": str(p["source_affects"])} if p.get("source_affects") else {}),
            # "…that is a **Goblin** card…" (MEC-43, Conspicuous Snoop) —
            # ``source_mode="top_of_library"``'s own subtype filter.
            **({"donor_subtype": str(p["donor_subtype"])} if p.get("donor_subtype") else {}),
            **({"exclude_loyalty": True} if p.get("exclude_loyalty") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "~ gains all activated abilities of target creature until end of
    # turn." (MEC-23, Quicksilver Elemental) — the resolve-time, targeted
    # sibling of `grant_borrowed_activated_ability` just above; see
    # `GainActivatedAbilitiesOfTargetEffect`'s own docstring for the
    # snapshot-vs-live-rederive distinction between the two.
    "gain_target_activated_abilities",
    lambda p: GainActivatedAbilitiesOfTargetEffect(),
)
EffectRegistry.register(
    # PAR-8: "Each [<filter>] card in your hand has cycling `<cost>`."
    # (Jo Grant/Rhet-Tomb Mystic/Tectonic Reformation) — layer 6, but its
    # targets are *hand* cards, a zone none of the battlefield `affects`
    # selectors reach; `affects` is left at its unused default ("self") and
    # `continuous._apply_hand_cycling_grants` reads ``cost``/``card_type``
    # directly off the ability instead of going through `affected_objects`.
    "grant_cycling_to_hand",
    lambda p: StaticAbility(
        "ability",
        params={
            "grant_cycling_cost": str(p["cost"]),
            "card_type": p.get("card_type"),
        },
    ),
)
EffectRegistry.register(
    # "Elves you control have '<triggered ability text>'" (Dionus, Elvish
    # Archdruid) — layer 6, ability-adding, granting a full triggered ability
    # rather than a keyword or a mana ability. ``effects`` is a list of
    # ``{"type": ..., "params": {...}}`` one-shot-effect specs, bound through
    # the same whitelisted `EffectRegistry` as everything else (docs/09
    # security boundary) — just invoked per affected object at grant time
    # (`continuous.recompute`) instead of once at bind-on-load.
    "grant_triggered_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "creatures_you_control"),
        params={
            "trigger_event": p.get("trigger_event"),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "optional": bool(p.get("optional", False)),
            "controllers_turn_only": bool(p.get("controllers_turn_only", False)),
            # RULE 120.3 "deals combat damage to a player/creature" — the
            # DAMAGE event's exact-match filter (`{"combat": ..., "is_player":
            # ...}`), threaded through by `static_handlers.
            # _quoted_ability_grant_effects`; `continuous._granted_trigger_
            # condition` ANDs it the same way `effect_binder._trigger_
            # condition`'s ``"filter"`` does for an ordinary printed trigger.
            # A granted RULE 500.7 phase trigger uses the same key for its
            # own ``{"step": "upkeep"}``.
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            # RULE 500.7 "at the beginning of *your* upkeep" granted onto
            # another permanent ("Enchanted creature has '…'", Commander's
            # Authority/Aura Flux) — "you" is the *granted-to* permanent's
            # controller, not the granting source's, so unlike
            # `effect_binder._trigger_condition`'s own `phase_relation`
            # branch (which closes over the printed source) this is resolved
            # per affected object in `continuous._granted_trigger_condition`.
            **({"phase_relation": p["phase_relation"]} if p.get("phase_relation") else {}),
            # PAR-32: a `{"subject": "group"}` condition re-granted to
            # another permanent ("Commander creatures you own have
            # 'Whenever an artifact or creature you control dies, …'" —
            # Agent of the Iron Throne). `continuous._apply_layer_6_ability`
            # builds the predicate via `effect_binder._build_group_ok` with
            # the *granted-to* permanent as the source, so "you control" /
            # "other" re-scope to it.
            **({"group_condition": dict(p["group_condition"])} if p.get("group_condition") else {}),
            **({"contributors": dict(p["contributors"])} if p.get("contributors") else {}),
            # PAR-32: firing-event gate flags on a re-granted trigger
            # ("Commander creatures you own have 'Whenever ~ attacks a
            # player, if no opponent has more life than that player, …'" —
            # Guild Artisan; "Whenever you cast a spell from exile, …" —
            # Passionate Archaeologist). `continuous._apply_layer_6_ability`
            # ANDs `effect_binder.regrant_trigger_gate_predicate`.
            **({"attacked_player_has_lowest_life": True}
               if p.get("attacked_player_has_lowest_life") else {}),
            **({"spell_from_exile": True} if p.get("spell_from_exile") else {}),
            # PAR-131: the composed cast-trigger keys ("Whenever you cast a
            # noncreature spell" — Black Mage's Rod; "… from exile" —
            # Passionate Archaeologist) re-granted verbatim.
            **({"spell_filter": dict(p["spell_filter"])}
               if isinstance(p.get("spell_filter"), dict) else {}),
            **({"spell_cast_from": [str(z) for z in p["spell_cast_from"]]}
               if isinstance(p.get("spell_cast_from"), (list, tuple)) else {}),
            # PAR-131: a DAMAGE recipient scope ("whenever this creature deals
            # combat damage to a creature/an opponent" — Kaldra Compleat).
            **({"recipient_relation": p["recipient_relation"]}
               if p.get("recipient_relation") in ("you", "opponent") else {}),
            **({"recipient_filter": dict(p["recipient_filter"])}
               if isinstance(p.get("recipient_filter"), dict) else {}),
            **({"spell_shares_creature_type_with_source": True}
               if p.get("spell_shares_creature_type_with_source") else {}),
            # PAR-32: a re-granted phase trigger's RULE 603.4 intervening-if
            # (Cloakwood Hermit / Dragon Cultist).
            **({"active_if": dict(p["active_if"])}
               if isinstance(p.get("active_if"), dict) else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Equipped creature/Enchanted land has '{cost}: <effect>.'" (Umbral
    # Mantle/Squirrel Nest-shaped) — layer 6, ability-adding, the activated
    # sibling of `grant_triggered_ability` just above. `continuous.recompute`
    # builds (and per-relationship caches) a real `ActivatedAbility` per
    # affected object onto `GameObject._granted_activated_abilities`, read
    # together with the object's own printed ones by `GameEngine.
    # can_activate`/`activate_ability`/`legal_actions`.
    "grant_activated_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "activated_cost": dict(p.get("cost") or {}),
            "grant_effects": list(p.get("grant_effects", [])),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "sorcery_speed_only": bool(p.get("sorcery_speed_only", False)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # MEC-55: "X have '<static ability>'" where the quoted body is itself a
    # static (anthem / lord / keyword grant) — Inspiring Leader
    # ("Commander creatures you own have 'Creature tokens you control get
    # +2/+2.'"). `continuous._apply_layer_6_ability` builds each
    # ``static_specs`` entry into a `StaticAbility` per affected object
    # (sourced on that object) and files it on
    # `GameObject._granted_static_abilities`, which
    # `_battlefield_static_abilities` then yields as an ordinary source.
    "grant_static_ability",
    lambda p: StaticAbility(
        "ability",
        affects=p.get("affects", "attached_permanent"),
        params={
            "static_specs": [dict(s) for s in p.get("static_specs", [])],
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each nonland card in your graveyard has escape. The escape cost is
    # equal to the card's mana cost plus exile N other cards from your
    # graveyard." (Underworld Breach) — RULE 702.138 as a *granted* keyword
    # onto cards in a graveyard, which no battlefield selector could reach;
    # consulted by `continuous.granted_escape_for` from `GameEngine.
    # _graveyard_cast_keyword`/`_escape_cost`.
    "grant_escape",
    lambda p: StaticAbility(
        "grant_escape",
        affects="all",
        params={
            "nonland_only": bool(p.get("nonland_only", True)),
            # "Each **enchantment** card in your graveyard has escape." (The Master of Keys)
            "card_type": str(p.get("card_type", "")),
            "exile_from_graveyard": int(p.get("exile_from_graveyard", 0) or 0),
        },
    ),
)
EffectRegistry.register(
    # "Instant and sorcery cards in your graveyard have retrace." (Wrenn and
    # Six's −7 emblem); "Merfolk and Druid cards in your graveyard have
    # retrace." (Deeproot Historian) — RULE 702.81 as a *granted* keyword
    # onto graveyard cards (MEC-53), the `grant_escape` sibling; consulted by
    # `continuous.granted_retrace_for` from `GameEngine._graveyard_cast_keyword`.
    "grant_retrace",
    lambda p: StaticAbility(
        "grant_retrace",
        affects="all",
        params={
            "nonland_only": bool(p.get("nonland_only", False)),
            "card_types": list(p.get("card_types", []) or []),
            "subtypes": list(p.get("subtypes", []) or []),
        },
    ),
)
EffectRegistry.register(
    # MEC-56: "This creature enters with an additional +1/+1 counter on it"
    # / "Other creatures you control enter with an additional +1/+1 counter
    # on them." (Master Chef, PAR-32) — a RULE 614.1-style entry-counter
    # *replacement*, not a trigger: the extra counter must already be on the
    # object when it enters (so an ETB trigger checking "if it has a +1/+1
    # counter on it" sees it, and so Undergrowth/proliferate-adjacent counts
    # are exact) rather than landing a beat late. The `grant_escape`/
    # `grant_retrace` idiom — a bare marker `StaticAbility` consulted
    # out-of-band by `continuous.extra_etb_counters_for` from
    # `RulesEngine._apply_entry_counters`, not routed through the layer 1-7
    # pass (nothing about *this* object's own characteristics changes).
    # ``self_only`` picks which half of a twin-quoted grant this instance
    # is: unset (creatures-you-control, source excluded) for "other
    # creatures…", set for "this creature enters with…" (checked against
    # the granting ability's own ``source`` — the affected commander
    # creature itself, since `grant_static_ability` sources each nested
    # static on the object it was granted to).
    "extra_etb_counter",
    lambda p: StaticAbility(
        "extra_etb_counter",
        affects="all",
        params={
            "kind": str(p.get("kind", "+1/+1")),
            "count": int(p.get("count", 1) or 1),
            "self_only": bool(p.get("self_only", False)),
            # "…an additional +1/+1 counter on them **for each creature that
            # died under your control this turn**." (Gorma, the Gullet,
            # PAR-60) — a live `continuous.count_selector`, overriding
            # ``count`` when set.
            **({"count_selector": p["count_selector"]} if p.get("count_selector") else {}),
            # PAR-139: "each [other] <subtype> creature you control enters with …" — see
            # `continuous.extra_etb_counters_for`.
            **({"filter": dict(p["filter"]), "other": bool(p.get("other", True))} if p.get("filter") else {}),
            # "**Nontoken** creatures you control enter with…" (Gorma) —
            # RULE 111.9 filter on the entering object.
            **({"nontoken": True} if p.get("nontoken") else {}),
            # Runadi: "creature spell you *cast* with mana value 5 or greater … X additional counters,
            # where X is its mana value minus 4".
            **({"cast_only": True} if p.get("cast_only") else {}),
            **({"count_per_artifact_mana": True} if p.get("count_per_artifact_mana") else {}),
            **({"min_mana_value": int(p["min_mana_value"])} if p.get("min_mana_value") is not None else {}),
            **({"count_mana_value_minus": int(p["count_mana_value_minus"])}
               if p.get("count_mana_value_minus") is not None else {}),
        },
    ),
)
EffectRegistry.register(
    # MEC-61: "Room abilities of dungeons you own trigger an additional
    # time." (Dungeon Delver, PAR-32) — RULE 603.3d trigger doubling, the
    # `TriggerDoublerEffect`/`trigger_doubler_bonus` idiom (Roaming
    # Throne, `Done_Backend.md`) narrowed to dungeon-room triggers
    # specifically rather than "any triggered ability of a permanent you
    # control": a dungeon's RULE 309.4c room trigger is built in its own
    # source-less path (`RulesEngine._collect_dungeon_room_triggers`, off
    # a `Dungeon` in the command zone, never a battlefield `GameObject`),
    # which `trigger_doubler_bonus`'s own `obj: GameObject` signature has
    # no way to reach — a bare marker `StaticAbility`, the same
    # `grant_escape`/`grant_retrace`/`extra_etb_counter` out-of-band idiom,
    # consulted by `continuous.dungeon_room_trigger_doubler_bonus`.
    "dungeon_room_trigger_doubler",
    lambda p: StaticAbility("dungeon_room_trigger_doubler", affects="all", params={}),
)
EffectRegistry.register(
    # MEC-62: "Each player may put two +1/+1 counters on a creature they
    # control. For each opponent who does, you gain protection from that
    # player until your next turn." (Noble Heritage, PAR-32) — see
    # `EachPlayerMayCounterThenProtectionEffect`'s own docstring for the
    # MVP "every player accepts" simplification.
    "each_player_counter_then_protection",
    lambda p: EachPlayerMayCounterThenProtectionEffect(),
)
EffectRegistry.register(
    "type_change",  # "Lands you control are 0/0 creatures" (layer 4)
    lambda p: StaticAbility(
        "type",
        affects=p.get("affects", "self"),
        params={
            "from_linked_exile": bool(p.get("from_linked_exile", False)),  # Duplicant
            "add_types": list(p.get("add_types", [])),
            # "…and loses all other card types…" (Vraska, Betrayal's
            # Sting's -2) — the removal-side mirror of `add_types`.
            "remove_types": list(p.get("remove_types", [])),
            # RULE 601.2b/613.4a "~ is the chosen type in addition to its
            # other types" (Adaptive Automaton/A-Thran Portal-shaped) — a
            # literal `add_subtypes` list and/or the dynamic
            # `add_subtypes_from_source` flag (reads the ability source's
            # own `chosen_type` fresh every recompute); *adds* alongside the
            # object's printed subtypes, unlike `set_subtypes` below.
            "add_subtypes": list(p.get("add_subtypes", [])),
            "add_subtypes_from_source": bool(p.get("add_subtypes_from_source", False)),
            # PAR-49: Mistform's chosen creature type replaces (rather than
            # supplements) the affected object's creature subtypes.
            "set_subtypes_from_source": bool(p.get("set_subtypes_from_source", False)),
            # RULE 205.4a: "it becomes a **legendary** creature…" (Tenth
            # District Hero) — sets `GameObject._granted_legendary` in the
            # layer-4 pass so the legend rule (RULE 704.5j) applies.
            "legendary": bool(p.get("legendary", False)),
            "power": p.get("power"),
            "toughness": p.get("toughness"),
            # "…becomes an artifact creature with power and toughness each
            # equal to its mana value." (Karn, the Great Creator-shaped) —
            # a dynamic sibling of the literal ``power``/``toughness`` ints
            # above, resolved fresh every recompute off the affected
            # object's own printed mana value rather than a fixed number.
            "pt_selector": p.get("pt_selector"),
            # RULE 613.5 full subtype overwrite ("Nonbasic lands are
            # Mountains.", Magus of the Moon/Blood Moon) — unlike
            # `add_types` (only *adds*), this *replaces* the affected
            # object's subtype set (`continuous._has_subtype`), only
            # included when the spec actually sets it so an ordinary
            # "are also creatures" clause is unaffected.
            **({"set_subtypes": list(p["set_subtypes"])} if p.get("set_subtypes") else {}),
            # RULE 613.4a *past* the battlefield — "The same is true for
            # creature spells you control and creature cards you own that
            # aren't on the battlefield" (Arcane Adaptation/Leyline of
            # Transformation, ``"cards_you_own"``) / "Each creature card in
            # your graveyard has the chosen creature type…" (Ashes of the
            # Fallen, ``"your_graveyard"``). The battlefield-side `affects`
            # selector above is independent: Arcane Adaptation sets both
            # (its battlefield half *and* this), Ashes of the Fallen only
            # this. See `continuous._apply_off_battlefield_types`.
            **({"off_battlefield": str(p["off_battlefield"])} if p.get("off_battlefield") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # PAR-79 sixth increment: "~ becomes a `<N>`/`<M>` **blue and black**
    # `<subtype>` creature …" (Dimir Keyrune-shaped) — RULE 613.4b's layer-5
    # colour-changing engine (`continuous._apply_layer_5_color`, reading a
    # `StaticAbility(layer="color", ...)`) already existed with **no
    # `EffectRegistry` factory reaching it at all** — the "type_change"
    # (layer 4) row immediately above this one is the sibling that *does*
    # have one; colour never got its own. ``colors`` is a list of WUBRG
    # letters; ``set`` (default True, mirroring `_apply_layer_5_color`'s own
    # default) replaces the affected object's existing colours rather than
    # adding to them, matching how every printed "becomes a `<colors>`
    # creature" card means "is now exactly these colours", not "is now also
    # these colours".
    "color",
    lambda p: StaticAbility(
        "color",
        affects=p.get("affects", "self"),
        params={
            "colors": [str(c).upper() for c in p.get("colors", [])],
            "set": bool(p.get("set", True)),
        },
    ),
)
EffectRegistry.register(
    # "If you tap a permanent for mana, it produces N times as much of that
    # mana instead." (Nyxbloom Ancient) — not a RULE 613 layer (nothing here
    # is a characteristic), consulted directly by `GameEngine.tap_for_mana`
    # via `continuous.mana_production_multiplier_for`, alongside
    # `activation_prohibition`/`cast_prohibition` in `_NON_RULE_613_LAYERS`.
    "mana_multiplier",
    lambda p: StaticAbility(
        "mana_multiplier",
        affects="self",
        params={"multiplier": int(p.get("multiplier", 2) or 2)},
    ),
)
EffectRegistry.register(
    # "You may spend mana as though it were mana of any color." (Chromatic Orrery) — read by
    # `continuous.standing_mana_wildcard` where a spell's cost is checked and paid.
    "spend_mana_as_any_color",
    lambda p: StaticAbility("mana_wildcard", affects="self", params={"wildcard": "color"}),
)
EffectRegistry.register(
    # "You have hexproof." (Shalai, Voice of Plenty) — a static read by
    # `continuous.player_has_hexproof`; see its docstring.
    "player_hexproof",
    lambda p: StaticAbility("player_hexproof", affects="self", params={}),
)
EffectRegistry.register(
    # "Skip your draw step." (MEC-38, Necropotence) — consulted directly by
    # `RulesEngine.should_skip_step` via `continuous.skipped_steps_for`,
    # the same "not a RULE 613 layer, read live off the battlefield" shape
    # `mana_type_override`/`mana_multiplier` already use.
    "skip_step",
    lambda p: StaticAbility(
        "skip_step",
        affects="self",
        params={"step": p.get("step", "draw")},
    ),
)
EffectRegistry.register(
    # RULE 119.3-adjacent: "Players can't gain life." (Everlasting Torment /
    # Forsaken Wastes / Havoc Festival / Leyline of Punishment / Sulfuric
    # Vortex) — a standing, board-wide rule modification (distinct from
    # `prevent_life_gain`'s turn-scoped, opponent-scoped Roiling Vortex
    # rider). A marker static consulted live by `RulesEngine.gain_life` via
    # `continuous.life_gain_globally_prohibited`, the same "not a RULE 613
    # layer, read off the battlefield" shape as `skip_step` above.
    "prevent_all_life_gain",
    lambda p: StaticAbility(
        "life_gain_prohibition",
        affects="all",
        params={
            # ``"opponents"`` (Erebos, God of the Dead) narrows the ban to
            # the static's controller's opponents; anything else = unscoped
            # (Forsaken Wastes et al., stops everyone).
            **({"scope": "opponents"} if p.get("scope") == "opponents" else {}),
            **({"active_if": p["active_if"]} if p.get("active_if") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Damage can't be prevented." (Everlasting Torment) — a standing,
    # board-wide RULE 615 modification. Marker static consulted live by
    # `RulesEngine._run_replacement_loop` via
    # `continuous.damage_prevention_globally_disabled`, the same "not a RULE
    # 613 layer, read off the battlefield" shape as `prevent_all_life_gain`.
    "damage_cant_be_prevented",
    lambda p: StaticAbility("damage_prevention_prohibition", affects="all", params={}),
)
EffectRegistry.register(
    # "All damage is dealt as though its source had wither." (Everlasting
    # Torment) — RULE 609.4b as-though. Marker static consulted live by
    # `RulesEngine.deal_damage` via `continuous.global_wither_active`.
    "global_wither",
    lambda p: StaticAbility("global_wither", affects="all", params={}),
)
EffectRegistry.register(
    # "While an opponent is searching their library, they exile each card
    # they find. You may play those cards..." (MEC-39, Opposition Agent)
    # — consulted directly by `RulesEngine._finish_search` via
    # `continuous.search_redirect_controller_for`.
    "search_redirect",
    lambda p: StaticAbility("search_redirect", affects="self", params={}),
)
EffectRegistry.register(
    # "Creatures can't attack you unless their controller pays {N} for each
    # creature they control that's attacking you." (Propaganda / Ghostly
    # Prison / Windborn Muse) — RULE 508.1g attack tax. Marker static
    # consulted live by `combat_mixin.declare_attackers` via
    # `continuous.attack_tax_per_creature_for`; scoped to its own controller
    # (the "you"), so ``affects="self"``.
    #
    # ``attacker_filter`` / ``amount_per_attacker_counter`` (Nils, Discipline
    # Enforcer, PAR-60) narrow the tax to attackers matching a
    # `_defender_attack_ban_matches`-shaped filter and set each such
    # attacker's own tax to its counter count ("unless its controller pays
    # {X}, where X is the number of counters on that creature") —
    # ``"any"`` sums every counter kind, otherwise a specific kind.
    "attack_tax",
    lambda p: StaticAbility(
        "attack_tax", affects="self", params={
            "amount": int(p.get("amount", 0)),
            "amount_count_selector": p.get("amount_count_selector"),
            "defender_scope": p.get("defender_scope", "player"),
            "attacker_filter": p.get("attacker_filter"),
            "amount_per_attacker_counter": p.get("amount_per_attacker_counter"),
            # RULE 613.6 gate ("As long as ~ is untapped, creatures can't attack you unless…", Archangel of
            # Tithes) — read by `continuous.attack_tax_per_creature_for`; it used to be dropped here.
            **({"active_if": dict(p["active_if"])} if isinstance(p.get("active_if"), dict) else {}),
        }
    ),
)
EffectRegistry.register(
    # "…creatures can't block unless their controller pays {N} for each of
    # those creatures." (Archangel of Tithes) — RULE 509.1c block tax, the
    # mirror of ``attack_tax``. Marker static read live by
    # `combat_mixin.declare_blockers` via `continuous.block_tax_per_creature`;
    # a creature of *any* controller is taxed, so ``amount`` is per blocker
    # and the gate (``active_if``, e.g. "as long as ~ is attacking") is the
    # only scope.
    "block_tax",
    lambda p: StaticAbility(
        "block_tax", affects="self", params={
            "amount": int(p.get("amount", 0)),
            **({"active_if": dict(p["active_if"])} if isinstance(p.get("active_if"), dict) else {}),
        }
    ),
)
EffectRegistry.register(
    # RULE 104.3b: "You can't lose the game and your opponents can't win the game." (Herald of Eternal Dawn) —
    # two marker statics read live by `RulesEngine._loss_prevented`/`_player_loses` and `player_wins`
    # (`continuous.player_cant_lose` / `player_cant_win`); the Platinum Angel family.
    "cant_lose_game",
    lambda p: StaticAbility("cant_lose_game", affects="self", params={**_selectors(p)}),
)
EffectRegistry.register(
    "opponents_cant_win",
    lambda p: StaticAbility("opponents_cant_win", affects="self", params={**_selectors(p)}),
)
EffectRegistry.register(
    "counter_placement_prohibition",
    lambda p: StaticAbility("counter_placement_prohibition", affects=p.get("affects", "self"),
        params={**_selectors(p), "counter_kind": p.get("counter_kind", "all")}),
)
EffectRegistry.register(
    # "Each creature that's enchanted by an Aura you control can't attack you
    # or planeswalkers you control." (Eriette of the Charmed Apple, PAR-60) /
    # "Inklings can't attack you or planeswalkers you control." (Combat
    # Calligrapher) — RULE 508.1, an absolute bar on which player a matching
    # creature may be declared against, scoped to this static's own
    # controller (``affects="self"``). Consulted live by
    # `combat_mixin._can_attack` via `continuous.defender_attack_prohibited`;
    # ``attacker_filter`` (empty = every creature) narrows which attackers it
    # bites — ``subtype`` / ``has_counter_kind`` / ``has_any_counter`` /
    # ``enchanted_by_controller_aura``.
    "cant_attack_defender",
    lambda p: StaticAbility(
        "cant_attack_defender", affects="self", params={
            "defender_scope": p.get("defender_scope", "player_or_planeswalker"),
            "attacker_filter": dict(p.get("attacker_filter") or {}),
        }
    ),
)
EffectRegistry.register(
    # "If a card would be put into an opponent's graveyard from anywhere,
    # instead exile it with a void counter on it." (Dauthi Voidwalker,
    # MEC-42) — consulted by `continuous.void_counter_redirect_controller_
    # for` (`RulesEngine._move_to_graveyard`'s own redirect chain, same
    # choke point Yawgmoth's Will/Lurrus already use).
    "void_counter_redirect",
    lambda p: StaticAbility("void_counter_redirect", affects="self", params={}),
)
EffectRegistry.register(
    # "If a card would be put into an opponent's graveyard from anywhere,
    # exile it instead." (Leyline of the Void)/"If a card or token would be
    # put into a graveyard from anywhere, exile it instead." (Rest in
    # Peace, MEC-43) — the plain-exile sibling of `void_counter_redirect`
    # just above (no counter, no holder tracking); ``scope`` is
    # ``"opponent"`` (default) or ``"any"``. Consulted by `continuous.
    # graveyard_redirect_active`.
    "graveyard_redirect",
    lambda p: StaticAbility(
        "graveyard_redirect", affects="self",
        params={
            "scope": p.get("scope", "opponent"),
            # "…**black or red**…" (Sanctifier en-Vec, MEC-43 round 2) — a
            # colour-scoped redirect instead of/alongside a graveyard-owner
            # one; see `continuous.graveyard_redirect_active`.
            **({"colors": [str(c).upper() for c in p["colors"]]} if p.get("colors") else {}),
        },
    ),
)
EffectRegistry.register(
    # "Each opponent can cast spells only any time they could cast a
    # sorcery." (Teferi, Time Raveler, MEC-42) — consulted by
    # `continuous.forced_sorcery_speed_only` (`GameEngine.can_cast`'s own
    # timing computation).
    "sorcery_speed_only",
    lambda p: StaticAbility("sorcery_speed_only", affects="opponents", params={}),
)
EffectRegistry.register(
    # "Lands you control enter untapped." (Horizon Explorer) — consulted by `continuous.enters_untapped_from_static`.
    "lands_enter_untapped",
    lambda p: StaticAbility("enters_untapped", affects="self", params={}),
)
EffectRegistry.register(
    # "If you would proliferate, proliferate twice instead." (Tekuthal, Inquiry Dominus) — a marker
    # static consumed by `continuous.proliferate_multiplier` from `ProliferateEffect`.
    "proliferate_twice",
    lambda p: StaticAbility("proliferate_twice", affects="self", params={}),
)
EffectRegistry.register(
    # "As an additional cost to cast green permanent spells, you may pay 2 life. Those spells cost {G}
    # less to cast if you paid life this way." (Defiler of Vigor) — consulted by
    # `continuous.pip_life_options_for` from `GameEngine._adjust_cost`.
    "pip_life_option",
    lambda p: StaticAbility(
        "pip_life_option", affects="self",
        params={
            "color": str(p.get("color", "G")), "pips": int(p.get("pips", 1)),
            **({"spell_color": p["spell_color"]} if p.get("spell_color") else {}),
            **({"spell_type": p["spell_type"]} if p.get("spell_type") else {}),
        },
    ),
)
EffectRegistry.register(
    # "As an additional cost to cast this spell, you may exile any number
    # of blue cards from your hand. This spell costs {2} less to cast for
    # each card exiled this way." (March of Swirling Mist, MEC-42) —
    # consulted by `continuous.exile_discount_spec_for`, read straight off
    # the spell's own `static_effects` (still in hand) the same way
    # Delve/Affinity's own `self_cost_reduction_for` static is.
    "exile_discount_cost",
    lambda p: StaticAbility(
        "exile_discount_cost", affects="self",
        params={
            "color": p.get("color", "U"),
            "generic_per_card": int(p.get("generic_per_card", 2)),
        },
    ),
)
EffectRegistry.register(
    # "If a land is tapped for 2 or more mana, it produces {C} instead of
    # any other type and amount." (MEC-36, Damping Sphere) — unscoped
    # (``affects="all_lands"``, matching every land regardless of
    # controller, the same "unqualified reach" `cost_reduction`'s own
    # ``affects="all_spells"`` uses), consulted directly by `GameEngine.
    # tap_for_mana` via `continuous.mana_type_override_for`, alongside
    # `mana_multiplier` above.
    "mana_type_override",
    lambda p: StaticAbility(
        "mana_type_override",
        affects="all_lands",
        params={
            "min_amount": int(p.get("min_amount", 2) or 2),
            "to": p.get("to", "C"),
        },
    ),
)
EffectRegistry.register("aminatous_augury", lambda p: AminatousAuguryEffect())
EffectRegistry.register(
    # "Until end of turn, you may play cards exiled with ~. Spells you cast this way cost {2} less." (Urianger Augurelt)
    "play_cards_exiled_with_source",
    lambda p: PlayCardsExiledWithSourceEffect(spell_discount=int(p.get("spell_discount", 0) or 0)),
)
EffectRegistry.register(
    # "When ~ dies, you may cast it from your graveyard as an Adventure until the end of your next turn."
    "grant_self_adventure_cast_from_graveyard",
    lambda p: GrantSelfAdventureCastFromGraveyardEffect(),
)
EffectRegistry.register(
    # RULE 601.2f for the rest of the turn, owned by a player (Rowan, Scion of
    # War; Hardened Berserker's "the next spell") — `GameState.turn_cost_reductions`.
    "reduce_spell_costs_this_turn",
    lambda p: ReduceSpellCostsThisTurnEffect(
        amount=p.get("amount", 0),
        spell_type=p.get("spell_type"),
        spell_colors=p.get("spell_colors"),
        face_down=bool(p.get("face_down", False)),
        next_only=bool(p.get("next_only", False)),
        increase=bool(p.get("increase", False)),
    ),
)
EffectRegistry.register(
    "cost_reduction",  # "Spells you cast cost {N} less" (RULE 601.2f)
    lambda p: StaticAbility(
        "cost",
        # ``affects="your_spells"`` (default) is self-scoped — see
        # `continuous.cost_reduction_for`'s ownership check. ``"all_spells"``
        # (Thalia, Guardian of Thraben/Thorn of Amethyst/Vryn Wingmare-shaped:
        # an unqualified "<type> spells cost {N} more to cast") isn't scoped
        # by that check at all, so it taxes/discounts *every* player's
        # matching spells, its own controller's included.
        affects=p.get("affects", "your_spells"),
        params={
            "generic": p.get("generic", 1),
            **({"card_name_from_source": True} if p.get("card_name_from_source") else {}),
            **({"colored": p["colored"]} if p.get("colored") else {}),
            "increase": bool(p.get("increase", False)),
            # Delve/Affinity-shaped "{N} less for each <count_selector>"
            # (`affects="self"`, printed on the spell itself) — see
            # `continuous._cost_static_amount`/`self_cost_reduction_for`.
            **({"per": p["per"]} if p.get("per") else {}),
            # A card-type filter on the spell *being cast* ("noncreature
            # spells…") — `continuous._spell_type_matches`; distinct from
            # `card_type` (a *permanent*-selector filter the other static
            # families above use) since this checks the object on the stack,
            # not a battlefield selector.
            **({"spell_type": p["spell_type"]} if p.get("spell_type") else {}),
            # Emet-Selch: only a spell cast from the caster's graveyard.
            **({"from_graveyard": True} if p.get("from_graveyard") else {}),
            # The Ur-Sphinx's Eminence: functions from the command zone too (`continuous._battlefield_static_abilities`),
            # and "other" spells excludes the source itself.
            **({"from_command_zone": True} if p.get("from_command_zone") else {}),
            **({"other_spells": True} if p.get("other_spells") else {}),
            # Cloud Key: the type is the one chosen as the source entered (`chosen_mode`).
            **({"spell_type_from_source_mode": True} if p.get("spell_type_from_source_mode") else {}),
            # "Red spells you cast cost {1} less to cast." (the Medallion
            # cycle) — `continuous.cost_reduction_for`'s own colour filter,
            # orthogonal to `spell_type`. ``"colorless"`` is its own special
            # value (Eye of Ugin), an empty-identity check rather than a
            # membership one.
            **({"spell_color": p["spell_color"]} if p.get("spell_color") else {}),
            # "Colorless Eldrazi spells you cast cost {2} less to cast."
            # (Eye of Ugin) — a creature-subtype filter, orthogonal to both
            # `spell_type` (main card types only) and `spell_color` above.
            **({"spell_subtype": p["spell_subtype"]} if p.get("spell_subtype") else {}),
            # ``scope="activation"`` (Power Artifact-shaped "Enchanted
            # artifact's activated abilities cost {2} less to activate.") —
            # a *different* cost this same "cost" layer/StaticAbility shape
            # adjusts: an activated ability's own activation cost (RULE
            # 601.2f-adjacent) rather than a spell's cast cost, consulted by
            # `continuous.activation_cost_reduction_for`/`GameEngine.
            # _reduced_activation_mana` instead of `cost_reduction_for` (which
            # explicitly skips these). ``min_total`` is the "can't reduce the
            # mana in that cost to less than N mana" floor.
            **({"scope": p["scope"]} if p.get("scope") else {}),
            **({"min_total": p["min_total"]} if p.get("min_total") else {}),
            # "Equipment you control have equip {0}" (Puresteel Paladin): ``scope="activation"`` plus ``set_to_zero`` for the named
            # ``attach_kind`` (`continuous.activation_cost_reduction_for`).
            **({"set_to_zero": True, "attach_kind": str(p.get("attach_kind", "equip"))} if p.get("set_to_zero") else {}),
            # Professor Hojo: the first activation each turn that targets a creature you control (needs ``scope="activation"``).
            **({"first_targeting_own_creature": True} if p.get("first_targeting_own_creature") else {}),
            # "Activated abilities of Foods you control cost {1} less to
            # activate." (Sam, Loyal Attendant) — the subtype-scoped
            # ``scope="activation"`` variant `continuous.
            # activation_cost_reduction_for` reads, unlike its "attached
            # Permanent" sibling above.
            **({"subtype": p["subtype"]} if p.get("subtype") else {}),
            # "Activated abilities of creatures you control cost {2} less
            # to activate." (Training Grounds) — the same ``scope=
            # "activation"`` group scope as ``subtype`` above, narrowed by
            # a main card type (`continuous._has_card_type`) instead of a
            # creature subtype.
            **({"card_type": p["card_type"]} if p.get("card_type") else {}),
            # "This spell costs {N} less to cast if `<condition>`."
            # (Ghostfire Slice) — RULE 613.6's ordinary ability-source-
            # relative gate, read both by `self_cost_reduction_for` (a
            # spell's own printed reduction, ``affects="self"``) and — MEC-12
            # fixed a latent gap here — `cost_reduction_for` itself, which had
            # never consulted ``active_if`` at all despite `cost_floor_for`
            # (the very next function) already doing so for the same
            # ``"cost"`` layer. Needed for Tithe Taker's "**during your
            # turn**, spells your opponents cast cost {1} more…".
            **({"active_if": p["active_if"]} if p.get("active_if") else {}),
            # "This spell costs {N} less to cast **if it targets a
            # `<criteria>`**." (Ajani's Response / Knockout Blow cycle) — a
            # criteria dict checked against the spell's chosen targets at
            # cast time (RULE 601.2c precedes 601.2f), by `continuous.
            # _obj_matches_target_criteria`; only meaningful with
            # ``affects="self"``.
            **({"reduce_if_targets": p["reduce_if_targets"]} if p.get("reduce_if_targets") else {}),
            **({"per_target": True} if p.get("per_target") else {}),
            # "…of the chosen type cost {1} less" (Herald's Horn).
            **({"spell_subtype_from_source": True} if p.get("spell_subtype_from_source") else {}),
            # "Legendary spells you cast cost {1} less to cast." (Kethis, the Hidden Hand)
            **({"spell_legendary": True} if p.get("spell_legendary") else {}),
            # "Creature spells you cast with power 4 or greater cost {2} less to cast." (Goreclaw)
            **({"spell_min_power": int(p["spell_min_power"])} if p.get("spell_min_power") is not None else {}),
            # "Spells your opponents cast **that target ~** cost {N} more to
            # cast." (Icefall Regent / Boreal Elemental / Charix / Elderwood
            # Scion / Pursued Whale) — a battlefield permanent taxing spells
            # aimed at *itself*; `continuous.cost_reduction_for` checks the
            # caster's already-chosen targets (RULE 601.2c precedes 601.2f)
            # against this static's own source.
            **({"targets_source": True} if p.get("targets_source") else {}),
            # "Spells your opponents cast that target you or a permanent you
            # control cost {N} more to cast." (Monastery Siege / Esior /
            # Kasmina) — the general sibling of ``targets_source``: an OR-list
            # of what a chosen target may be (`continuous._spell_targets_hit`).
            **({"if_targets": p["if_targets"]} if p.get("if_targets") else {}),
            # "…cost an additional {N} life to cast." (Terror of the Peaks) —
            # life, not generic mana; read by `continuous.cast_life_tax_for`
            # and paid by `GameEngine._pay_cast_life_tax`.
            **({"life": int(p["life"])} if p.get("life") else {}),
            # "Each spell that would cost less than N mana to cast costs N
            # mana to cast instead." (Trinisphere) — a floor rather than a
            # delta, read separately by `continuous.cost_floor_for` (not
            # part of the additive ``generic``/``increase`` net above).
            **({"min_generic": p["min_generic"]} if p.get("min_generic") else {}),
            # "Each spell costs {N} more to cast **except during its
            # controller's turn**." (MEC-12, Defense Grid) — unlike
            # ``active_if``'s ``your_turn``/``not_your_turn`` (evaluated
            # against *this static's own* controller), "its controller" here
            # means whichever player is actually casting the taxed spell —
            # so `cost_reduction_for` checks it directly against its own
            # ``player`` argument rather than routing it through the
            # ability-source-relative `static_conditions` vocabulary at all.
            **({"except_caster_own_turn": True} if p.get("except_caster_own_turn") else {}),
            # "…unless they're mana abilities." (MEC-12, Suppression Field/
            # Tithe Taker) — the ``scope="activation"`` cost-tax sibling of
            # `activation_prohibition`'s own identically-named rider; read by
            # `activation_cost_reduction_for`'s new ``is_mana_ability`` param.
            **({"except_mana_abilities": True} if p.get("except_mana_abilities") else {}),
            # "Spells you cast from anywhere other than your hand cost {N}
            # less to cast." (Advanced Reconstruction level 3, PAR-60) —
            # `continuous.cost_reduction_for` checks the spell's own
            # cast-origin flags (``cast_from_exile`` / ``cast_via_flashback``
            # / ``cast_via_escape``). Documented simplification: a
            # command-zone commander cast isn't covered by those flags.
            **({"not_from_hand": True} if p.get("not_from_hand") else {}),
            # "A spell cast by an opponent this way costs {2} more to
            # cast." (MEC-12, Soul Partition) — a per-*instance* tax built
            # dynamically at exile time (`ExileEffect`'s new
            # ``grant_owner_play_permission``/``owner_play_permission_tax``)
            # and stamped straight onto the exiled card's own
            # ``affects="self"`` static, exempting only the value named
            # here (the exiler's own player id) — read by
            # `self_cost_reduction_for`'s new ``caster_id`` param, since
            # "an opponent" is relative to whoever is actually casting,
            # not to this static's own (largely meaningless, off-
            # battlefield) ``controller_id``.
            **(
                {"except_same_controller_as": p["except_same_controller_as"]}
                if p.get("except_same_controller_as") is not None else {}
            ),
        },
    ),
)
EffectRegistry.register(
    # "Activated abilities of artifacts can't be activated." (RULE 602,
    # Collector Ouphe/Stony Silence/Null Rod) — reuses the ordinary
    # `affects`/selector vocabulary (default "all_permanents", global) purely
    # to pick out *which* permanents' activated abilities are silenced;
    # `game/continuous.activation_prohibited` is the actual consult point
    # (`GameEngine.can_activate`), there's no P/T/type/ability layer effect
    # to fold into `continuous.recompute` here.
    "activation_prohibition",
    lambda p: StaticAbility(
        "activation_prohibition",
        affects=p.get("affects", "all_permanents"),
        params={
            # RULE 605.1a's carve-out ("…and its activated abilities can't be
            # activated **unless they're mana abilities**" — Kasmina's
            # Transmutation/Imprisoned in the Moon). Without it the
            # prohibition covers mana abilities too, which is what makes Null
            # Rod stop an artifact's "{T}: Add {C}".
            "except_mana_abilities": bool(p.get("except_mana_abilities", False)),
            **({"player_id": p["player_id"]} if p.get("player_id") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # RULE 508.1a/509.1b's *qualified* combat restrictions — "~ can't be
    # blocked by creatures with power 2 or less", "…except by Walls", "…by
    # more than one creature", "~ can't attack unless defending player
    # controls an Island", "~ can't attack alone". Their unqualified siblings
    # ride synthetic `grant_keyword` flags (`cant_attack`/`cant_block`/
    # `cant_be_blocked`); these carry a parameter a flag can't, so the whole
    # entry is stamped onto `GameObject.combat_restrictions` by
    # `continuous.recompute` and evaluated at *combat* time instead — see
    # `game/combat.py`'s `COMBAT_RESTRICTIONS` for the ``kind`` whitelist and
    # `GameEngine._combat_condition_met` for the ``condition`` one.
    #
    # Not a RULE 613 layer (nothing here is a characteristic), so it sits in
    # `continuous._NON_RULE_613_LAYERS` alongside `activation_prohibition`.
    "combat_restriction",
    lambda p: StaticAbility(
        "combat_restriction",
        affects=p.get("affects", "self"),
        params={
            "kind": str(p.get("kind", "")),
            **({"defender_kind": str(p["defender_kind"])} if p.get("defender_kind") else {}),
            **({"filter": dict(p["filter"])} if p.get("filter") else {}),
            **({"condition": dict(p["condition"])} if p.get("condition") else {}),
            **({"count": int(p["count"])} if p.get("count") is not None else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Each player can't cast more than N spells each turn." (RULE 601-area,
    # Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat, global cap,
    # not scoped to any particular player's spells; consulted by
    # `continuous.max_spells_per_turn` (`GameEngine.can_cast`).
    "cast_limit",
    lambda p: StaticAbility(
        "cast_limit",
        affects="all",
        params={
            "max_per_turn": p.get("max_per_turn", 1),
            # "…more than N **noncreature** spells…" (Deafening Silence) —
            # `continuous.max_noncreature_spells_per_turn`'s own scope flag.
            "noncreature": bool(p.get("noncreature", False)),
        },
    ),
)
EffectRegistry.register(
    # "Each opponent can't cast noncreature spells with mana value greater
    # than the number of lands that player controls." (Lavinia, Azorius
    # Renegade) — a *conditional* prohibition on a specific spell, unlike
    # `cast_limit`'s flat count; consulted by `continuous.cast_prohibited`.
    # `**_selectors(p)` carries ``active_if`` through ("During your turn,
    # your opponents can't cast spells …" — Grand Abolisher/Myrel, Shield of
    # Argive, RULE 613.6) — omitted before ENG-28, which silently dropped any
    # gate a `cast_prohibition` spec tried to carry.
    "cast_prohibition",
    lambda p: StaticAbility(
        "cast_prohibition",
        affects="all",
        params={
            "scope": p.get("scope", "opponents"),
            "noncreature": bool(p.get("noncreature", False)),
            "max_mana_value_selector": p.get("max_mana_value_selector"),
            # MEC-43: `max_mana_value_selector`'s literal sibling (Gaddock
            # Teeg's flat "4 or greater", or the ``"chosen_number"``
            # sentinel for Sanctum Prelate's RULE 601.2b pick), plus the
            # ``cmp`` mode both knobs share and the two independent
            # restriction families (`has_x_cost`/`nonartifact` +
            # `min_count_selector`) — see `continuous.cast_prohibited`'s
            # own docstring for the full vocabulary.
            **({"max_mana_value": p["max_mana_value"]} if p.get("max_mana_value") is not None else {}),
            "cmp": p.get("cmp", "gt"),
            "has_x_cost": bool(p.get("has_x_cost", False)),
            "nonartifact": bool(p.get("nonartifact", False)),
            # "Your opponents can't cast spells with even mana values.
            # (Zero is even.)" (Void Winnower, MEC-12) — latent bug found
            # while widening this factory for MEC-43: this key was already
            # written by that catalogue entry but never captured here, so
            # it silently fell through `_selectors`' whitelist and the
            # clause prohibited *every* opponent spell regardless of mana
            # value (`cast_prohibited` had no ``max_mana_value``/
            # ``max_mana_value_selector`` to check, so it returned ``True``
            # unconditionally the moment scope/noncreature matched).
            "even_mana_value": bool(p.get("even_mana_value", False)),
            **({"min_count_selector": p["min_count_selector"]} if p.get("min_count_selector") else {}),
            # "…can't cast spells from anywhere other than their hands."
            # (Drannith Magistrate) — `continuous.cast_prohibited`'s own
            # zone check.
            "hand_only": bool(p.get("hand_only", False)),
            # "…can't cast **blue creature** spells." (Llawan, Cephalid
            # Empress, MEC-43) — the first cast_prohibition needing *both* a
            # card-type restriction *and* a colour one at once:
            # ``creature_only`` (the mirror image of ``noncreature`` above)
            # combined with ``color`` (a single WUBRG letter, checked
            # against the spell's own printed `Card.color_identity`).
            "creature_only": bool(p.get("creature_only", False)),
            **({"color": str(p["color"]).upper()} if p.get("color") else {}),
            # "…spells from graveyards or exile." (Soulless Jailer, MEC-43)
            # — a zone allowlist, the sibling of ``hand_only`` above.
            **({"zones": list(p["zones"])} if p.get("zones") else {}),
            # "Players can't cast spells of the chosen type." (MEC-43 round
            # 4D, Archon of Valor's Reach) — RULE 601.2b's own answer, read
            # live off `GameObject.chosen_mode` (`continuous.
            # cast_prohibited`'s own ``type_from_source_mode`` gate).
            "type_from_source_mode": bool(p.get("type_from_source_mode", False)),
            **({"player_id": p["player_id"]} if p.get("player_id") else {}),
            **({"spell_types": list(p["spell_types"])} if p.get("spell_types") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Players can't pay life or sacrifice nonland permanents to cast
    # spells or activate abilities." (Yasharn, Implacable Earth, MEC-40) —
    # consulted by `continuous.cost_restricted` at every cost-payment
    # choke point that offers a pay-life/sacrifice component.
    "cost_restriction",
    lambda p: StaticAbility(
        "cost_restriction", affects="all", params={"kinds": list(p.get("kinds", []))},
    ),
)
EffectRegistry.register(
    # "Each player can't draw more than N cards each turn." (RULE 121.5-
    # adjacent, Spirit of the Labyrinth-shaped) — the draw-side mirror of
    # `cast_limit`, a flat global cap consulted by `continuous.
    # max_draws_per_turn` (`RulesEngine._single_draw`).
    "draw_limit",
    lambda p: StaticAbility(
        "draw_limit",
        # "Each opponent can't draw more than one card each turn." (Narset,
        # Parter of Veils) is ``affects="opponents"``, skipping the static's
        # own controller — Spirit of the Labyrinth's unqualified "each
        # player" stays the default ``"all"``.
        affects=p.get("affects", "all"),
        params={"max_per_turn": p.get("max_per_turn", 1)},
    ),
)
EffectRegistry.register(
    # "~ doesn't untap during your untap step." (RULE 502.3-adjacent, Basalt
    # Monolith/Grim Monolith/Mana Vault — self-scoped) or "Enchanted creature
    # doesn't untap during its controller's untap step." (Paralyzing Grasp —
    # ``affects="attached_permanent"``); consulted by
    # `continuous.has_no_untap_static` (`GameEngine._step_untap`). Also the
    # unattached group shape "Creatures with power N or greater don't untap
    # during their controllers' untap steps." (Meekstone —
    # ``affects="all_creatures"`` + the ordinary ``min_power`` selector),
    # forwarded via ``_selectors`` like every other group-scoped static.
    "no_untap",
    lambda p: StaticAbility("no_untap", affects=p.get("affects", "self"), params={**_selectors(p)}),
)
EffectRegistry.register(
    # "You may activate abilities of creatures you control as though those creatures had haste." (PAR-109 —
    # Thousand-Year Elixir, Shang-Chi, Tyvar); consulted by `continuous.activates_as_though_haste`.
    "activate_as_though_haste",
    lambda p: StaticAbility("activate_as_though_haste", affects=p.get("affects", "creatures_you_control"),
                            params={**_selectors(p)}),
)
EffectRegistry.register(
    # "Untap ~ during each other player's untap step." (PAR-109 — Bender's Waterskin, Thousand Moons Infantry,
    # Endbringer, Victory Chimes); consulted by `continuous.untaps_in_every_untap_step`.
    "untap_each_untap_step",
    lambda p: StaticAbility("untap_each_untap_step", affects=p.get("affects", "self"), params={**_selectors(p)}),
)
EffectRegistry.register(
    # "As long as this artifact is untapped, players can't untap more than
    # one land during their untap steps." (Winter Orb) — a flat, unscoped
    # cap consulted by `continuous.active_untap_caps`/`GameEngine.
    # _step_untap`. ``card_type`` (default ``"land"``, Winter Orb's own
    # shape) and ``nonbasic`` (Winter Moon's "…one nonbasic land…") widen
    # the scope beyond lands; any tap-state gate ("as long as this artifact
    # is untapped") rides the ordinary ``active_if`` RULE 613.6 wrapper
    # rather than a hardcoded tapped check, same as every other conditional
    # static.
    "untap_cap",
    lambda p: StaticAbility(
        "untap_cap", affects="all_players", params={"count": p.get("count", 1), **_selectors(p)}
    ),
)
EffectRegistry.register(
    # "You may choose not to untap ~ during your untap step." (RULE 502.1
    # self-scoped opt-out, Rubinia Soulsinger/Hivis of the Scale/The
    # Pandorica-shaped) — unlike `no_untap` (unconditional), this only
    # actually skips untapping once the controller has separately toggled
    # `GameObject.skip_untap` on (`GameEngine.set_skip_untap`, since the
    # engine has no mid-untap-step pause to ask fresh every turn — a
    # standing toggle instead); consulted by `continuous.has_no_untap_static`.
    "no_untap_optional",
    lambda p: StaticAbility("no_untap_optional", affects="self", params={}),
)
EffectRegistry.register(
    # "You may play an additional land on each of your turns." (RULE 305.2,
    # Exploration/Dryad of the Ilysian Grove/Azusa-shaped, ``count`` for
    # Azusa's "two additional lands") or, unscoped, "Each player may play an
    # additional land on each of their turns." (Rites of Flourishing/Ghirapur
    # Orrery/Storm Cauldron, ``affects="each_player"``); consulted by
    # `continuous.extra_land_plays_for` (`GameEngine.can_play_land`). The
    # one-turn, resolve-time sibling is `ExtraLandPlayEffect`/``extra_land_play``.
    "extra_land_drop",
    lambda p: StaticAbility(
        "extra_land_drop", affects=p.get("affects", "you"),
        params={"count": p.get("count", 1), "active_if": _top_library_gate(p)}
    ),
)
EffectRegistry.register(
    # "You have no maximum hand size." (RULE 402.2, A-Wizard Class/Body of
    # Knowledge-shaped) or "Players have no maximum hand size." (Anvil of
    # Bogardan/Folio of Fancies, ``affects="each_player"``); consulted by
    # `continuous.has_no_maximum_hand_size` (`GameEngine._step_cleanup`). The
    # durational "…for the rest of the game"/"…until your next turn" one-shot
    # variants are a different, resolve-time-granted shape, not modeled here.
    "no_max_hand_size",
    lambda p: StaticAbility("no_max_hand_size", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "Each opponent's maximum hand size is reduced by seven." (RULE 402.2,
    # Jin-Gitaxias, Core Augur, MEC-43) — the numeric sibling of
    # `no_max_hand_size` just above; consulted by `continuous.
    # hand_size_modifier_for` (`GameEngine._step_cleanup`). ``amount`` is
    # always a non-negative *magnitude* — `EffectSpec._clamp_params` floors
    # any ``"amount"`` param at 0, so a literal negative int here would
    # silently become 0 — with a separate ``increase`` flag choosing the
    # sign, the same "magnitude + direction flag" idiom `cost_reduction`'s
    # own ``increase`` param already uses for exactly this reason.
    # ``affects`` defaults to ``"you"`` like every sibling static here, but
    # this key's real cards always print ``"opponents"``.
    "hand_size_modifier",
    lambda p: StaticAbility(
        "hand_size_modifier", affects=p.get("affects", "you"),
        params={"amount": int(p.get("amount", 0)), "increase": bool(p.get("increase", False))},
    ),
)
EffectRegistry.register(
    # "The 'legend rule' doesn't apply to permanents you control." (RULE
    # 704.5j, Sakashima of a Thousand Faces-shaped); consulted by
    # `continuous.player_ignores_legend_rule` (`RulesEngine.
    # _apply_legend_rule`). Same ``affects`` convention as `no_max_hand_size`
    # just above.
    "ignore_legend_rule",
    lambda p: StaticAbility("ignore_legend_rule", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "Elemental permanent spells you cast from your hand gain evoke {4} as
    # you cast them." (Ashling, the Limitless, MEC-42) — consulted by
    # `continuous.granted_evoke_cost_for` (`GameEngine.can_cast`/
    # `effective_cast_cost`'s ``evoke`` branch), the hand-cast-cost sibling
    # of ``flash_permission`` right below.
    "grant_evoke",
    lambda p: StaticAbility(
        "grant_evoke",
        affects="self",
        params={
            "cost": str(p.get("cost")) if p.get("cost") else None,
            "subtype": p.get("subtype"),
        },
    ),
)
EffectRegistry.register(
    # "Creature spells you cast gain offspring {2} as you cast them." (Zinnia, Valley's Voice) — consulted by
    # `continuous.granted_offspring_cost_for` (`GameEngine._kicker_cost`, the shared optional-additional-cost
    # announcement Offspring rides on), the offspring sibling of ``grant_evoke`` above.
    "grant_offspring",
    lambda p: StaticAbility(
        "grant_offspring",
        affects="self",
        params={"cost": str(p.get("cost")) if p.get("cost") else None},
    ),
)
EffectRegistry.register(
    # "You may cast spells as though they had flash." (High Fae Trickster/
    # Valley Floodcaller-shaped) — consulted by `continuous.has_standing_
    # flash_permission` (`GameEngine.can_cast`'s timing check).
    "flash_permission",
    lambda p: StaticAbility(
        "flash_permission",
        affects="self",
        params={
            "noncreature_only": bool(p.get("noncreature_only", False)),
            "creature_only": bool(p.get("creature_only", False)),
            # "You may cast **legendary spells and artifact spells** as
            # though they had flash." (Gandalf the White, MEC-40) — a
            # closed word list ("legendary"/"artifact"/"creature"), union
            # semantics: a spell qualifies if it matches *any* word.
            "type_filter": list(p["type_filter"]) if p.get("type_filter") else None,
            **({"color": str(p["color"])} if p.get("color") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Any player may cast creature spells with mana value N or less
    # without paying their mana costs and as though they had flash."
    # (Aluren, MEC-43 round 4G) — a standing, board-wide free-cast (+
    # bundled flash) permission, consulted by `continuous.has_standing_
    # free_cast_permission`/`standing_free_cast_grants_flash`
    # (`GameEngine.can_cast`'s ``free=True`` branch and its own
    # ``free``-gated flash exemption). Deliberately its own static kind,
    # not a widening of ``flash_permission`` above — see `continuous.
    # _active_free_cast_permission`'s docstring for why.
    "free_cast_permission",
    lambda p: StaticAbility(
        "free_cast_permission",
        affects="self",
        params={
            "creature_only": bool(p.get("creature_only", False)),
            "max_mana_value": p.get("max_mana_value"),
            # "**Any player** may cast …" (Aluren) rather than the usual
            # "you may …" scoping every other permission static in this
            # family defaults to — skips the granting permanent's own
            # controller check entirely when set.
            "any_player": bool(p.get("any_player", False)),
            "grants_flash": bool(p.get("grants_flash", False)),
            "from_hand": bool(p.get("from_hand", False)),
            # "Once during each of your turns, you may cast a spell from your hand or the top of your library
            # without paying its mana cost." (One with the Multiverse) — ``zones`` limits where it may be cast from.
            "once_per_turn": bool(p.get("once_per_turn", False)),
            **({"zones": list(p["zones"])} if p.get("zones") else {}),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "You may collect evidence N rather than pay the mana cost for spells
    # you cast." (Conspiracy Unraveler — PAR-30) — a standing, board-wide
    # RULE 118.9 *alternative cost* grant: unlike `free_cast_permission`
    # (Aluren) the replacement isn't free, it's a payable non-mana cost.
    # Consulted by `continuous.granted_alt_cast_cost_for` from the engine's
    # ``alt_cost=True`` cast path (`can_cast` / `cast_spell` /
    # legal-actions `_offer_cast`). Controller-scoped ("spells **you**
    # cast"); ``max_mana_value``/``creature_only`` unused by the only real
    # card but kept for parity with `free_cast_permission`.
    "granted_alt_cast_cost",
    lambda p: StaticAbility(
        "granted_alt_cast_cost",
        affects="self",
        params={
            "collect_evidence": int(p.get("collect_evidence", 0)),
            "pay_energy": int(p.get("pay_energy", 0)),
            # "…cast an enchantment spell by paying life equal to its mana value" (Demon of Fate's Design).
            "pay_life_equal_mv": bool(p.get("pay_life_equal_mv", False)),
            "card_type": str(p.get("card_type", "")),
            "once_per_turn": bool(p.get("once_per_turn", False)),
            "from_hand": bool(p.get("from_hand", False)),
            "permanent_only": bool(p.get("permanent_only", False)),
            "creature_only": bool(p.get("creature_only", False)),
            "max_mana_value": p.get("max_mana_value"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    # "Stun counters can't be removed from permanents your opponents control." (Fear of Sleep Paralysis) — read by
    # `continuous.stun_counters_locked`, which `RulesEngine.set_tapped` consults before spending a stun counter.
    "stun_counters_cant_be_removed",
    lambda p: StaticAbility("stun_lock", affects="self", params={}),
)
EffectRegistry.register(
    # "Each enchantment card in your hand has miracle. Its miracle cost is equal to its mana cost reduced by {4}."
    # (Aminatou, Veil Piercer — RULE 702.94) — a granted Miracle onto *hand* cards no battlefield selector reaches;
    # read by `draw_discard_mixin._arm_miracle` through `continuous.granted_miracle_cost_for`.
    "grant_miracle",
    lambda p: StaticAbility(
        "grant_miracle",
        affects="self",
        params={"card_type": str(p.get("card_type", "")), "reduce_generic": int(p.get("reduce_generic", 0) or 0)},
    ),
)
EffectRegistry.register(
    # "You gain life rather than lose life from radiation." (RULE 728.1a,
    # Strong, the Brutish Thespian) — consulted by `RulesEngine.lose_life`
    # (`continuous.has_radiation_life_gain`) before applying a
    # ``cause="radiation"`` life loss, redirecting it into a life *gain* of
    # the same amount instead. A per-player permission static, the same
    # "outside the layer engine proper" treatment as `no_max_hand_size`/
    # `no_untap_optional`.
    "radiation_life_gain",
    lambda p: StaticAbility("radiation_life_gain", affects=p.get("affects", "you"), params={}),
)
EffectRegistry.register(
    # "For each {B} in a cost, you may pay 2 life rather than pay that
    # mana." (MEC-43 — K'rrik, Son of Yawgmoth) — a standing alternative-
    # payment permission over *any* cost, broader than every existing
    # wildcard-color mechanism (those all substitute *color*, never
    # *whether mana is needed at all*). ``color`` (default ``"B"``, every
    # printed card so far) is the one WUBRG letter this grants a life
    # option for; consulted by `continuous.life_for_mana_pip_color`
    # (`ManaPool.can_pay`/`pay`'s ``extra_life_color`` param). Named
    # ``grant_…`` like `grant_any_color_for_activation` just above — same
    # "mana-payment permission static" family.
    "grant_life_for_mana_pip",
    lambda p: StaticAbility(
        "life_for_mana_pip", affects=p.get("affects", "you"), params={"color": p.get("color", "B")}
    ),
)
EffectRegistry.register(
    # "Players skip their untap steps." (RULE 502.3-adjacent, Stasis) — the
    # last open member of the "players can't `<verb>`" family
    # (`docs/implementation-state/BACKLOG.md`'s MEC-12 entry; untap's own
    # *capped* sibling already shipped as `"untap_cap"`/`active_untap_caps`).
    # Unlike a cap, this is unconditional and total: every player's whole
    # untap step does nothing, themselves included, which is why it's
    # unscoped by ``affects`` (there is no printed "you"-only phrasing of
    # this clause) — consulted by `continuous.all_untap_steps_skipped`
    # (`GameEngine._step_untap`).
    "skip_untap_step",
    lambda p: StaticAbility("skip_untap_step", affects="each_player", params={}),
)
EffectRegistry.register(
    # "Players can't cast spells from graveyards or libraries." (RULE
    # 601.3a-adjacent, Grafdigger's Cage/Weathered Runestone) — a flat,
    # unscoped prohibition over every standing graveyard/library-cast
    # *permission* this engine has (`continuous.
    # graveyard_library_cast_prohibited`, `GameEngine.can_cast`'s single
    # choke point for Flashback/Escape/Jump-start, a Lurrus-shaped grant,
    # and `game/top_library.py`'s play/cast-from-the-top permission alike).
    "graveyard_library_cast_prohibition",
    lambda p: StaticAbility(
        "graveyard_library_cast_prohibition", affects="each_player",
        # MEC-43 round 2 (Kunoros, Hound of Athreos): "Players can't cast
        # spells from **graveyards**" — no "or libraries" — narrows the
        # otherwise-unscoped prohibition to just the named zone(s).
        params={**({"zones": list(p["zones"])} if p.get("zones") else {})},
    ),
)
EffectRegistry.register(
    # "`<type>` cards in graveyards and libraries can't enter the
    # battlefield." (Grafdigger's Cage's "creature", Weathered Runestone's
    # "nonland permanent") — checked at the two real reanimation/tutor-to-
    # battlefield choke points (`continuous.graveyard_library_entry_
    # prohibited`; see its own docstring for why this isn't a universal
    # `add_to_battlefield` hook).
    "graveyard_library_entry_prohibition",
    lambda p: StaticAbility(
        "graveyard_library_entry_prohibition", affects="each_player",
        params={
            "card_type": p.get("card_type", "creature"),
            # MEC-43 round 2 (Kunoros): "creature cards in **graveyards**
            # can't enter the battlefield" — no "and libraries".
            **({"zones": list(p["zones"])} if p.get("zones") else {}),
        },
    ),
)
EffectRegistry.register(
    # "If a nontoken creature would enter and it wasn't cast, exile it
    # instead." (MEC-43 round 4D, Containment Priest) — the exile-redirect
    # sibling of `graveyard_library_entry_prohibition` just above, checked
    # at the same two choke points (`continuous.uncast_creature_entry_
    # exiled`) rather than a plain no-op.
    "uncast_creature_entry_exile",
    lambda p: StaticAbility("uncast_creature_entry_exile", affects="each_player", params={}),
)
EffectRegistry.register(
    # "Creatures entering don't cause abilities to trigger." (RULE 603,
    # Tocatli Honor Guard/Hushwing Gryff/Torpor Orb) — global: silences every
    # triggered ability (including the entering object's own) that would fire
    # off a matching event; consulted by `continuous.trigger_suppressed`
    # (`RulesEngine._collect_triggers`), not a `continuous.recompute` layer.
    "trigger_prohibition",
    lambda p: StaticAbility(
        "trigger_prohibition",
        affects="all",
        params={
            "event": p.get("event"), "subject_type": p.get("subject_type"),
            # "Permanents entering don't cause abilities of **permanents
            # your opponents control** to trigger." (Elesh Norn, Mother of
            # Machines, MEC-40) — narrows the otherwise-global suppression
            # to just the entering-object's controller's opponents,
            # relative to this static's own source.
            "scope": p.get("scope", "all"),
        },
    ),
)
EffectRegistry.register(
    # "Artifacts your opponents control enter tapped." (RULE 614.1, board-
    # wide — Manglehorn/Dauntless Dismantler; Archon of Emeria's "Nonbasic
    # lands…" narrows further with ``nonbasic``) — distinct from
    # `card_registry.enters_tapped` (a card's own printed clause about
    # itself): this is a *different* permanent's standing effect, consulted
    # by `continuous.enters_tapped_from_static`
    # (`RulesEngine._resolve_permanent_spell`/token creation).
    "enters_tapped_static",
    lambda p: StaticAbility(
        "enters_tapped",
        affects=p.get("affects", "opponents_permanents"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    "color_change",  # "Enchanted creature is black" / "All creatures are red" (layer 5)
    lambda p: StaticAbility(
        "color",
        affects=p.get("affects", "attached_permanent"),
        params={
            "colors": [str(c).upper() for c in p.get("colors", [])],
            "set": bool(p.get("set", True)),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "control_change",  # "You control enchanted creature" (Mind Control, layer 2)
    lambda p: StaticAbility(
        "control",
        affects=p.get("affects", "attached_permanent"),
        # No explicit "controller" defaults to the effect's own source's
        # controller (continuous.recompute), which is exactly "you" for a
        # hand-authored "you control enchanted/equipped permanent" clause.
        params={"controller": p.get("controller")},
    ),
)
EffectRegistry.register(
    "pt_cda",  # "*/* creature with power/toughness equal to …" (layer 7a, RULE 604.3)
    lambda p: StaticAbility(
        "pt_cda",
        affects=p.get("affects", "self"),
        params={
            "power_count": p.get("power_count"),
            "toughness_count": p.get("toughness_count"),
            **_selectors(p),
        },
    ),
)
EffectRegistry.register(
    "pt_switch",  # "Switch this creature's power and toughness" (layer 7e, RULE 613.4d/701.28)
    lambda p: StaticAbility(
        "pt_switch",
        affects=p.get("affects", "self"),
        params={**_selectors(p)},
    ),
)
EffectRegistry.register(
    # Runadi grants entry counters to the particular spell that fired its trigger.
    "grant_entry_counters_to_triggering_spell",
    lambda p: GrantEntryCountersToTriggeringSpellEffect(
        mana_value_minus=int(p.get("mana_value_minus", 0)), kind=str(p.get("kind", "+1/+1")),
    ),
)
EffectRegistry.register(
    "grant_sunburst_to_triggering_spell",
    lambda p: GrantSunburstToTriggeringSpellEffect(),
)
EffectRegistry.register(
    # PAR-81: "Switch target creature's power and toughness until end of
    # turn." (Twisted Image-shaped) — the resolving one-shot sibling of
    # "pt_switch" just above; see `SwitchPowerToughnessEffect`.
    "switch_power_toughness",
    lambda p: SwitchPowerToughnessEffect(
        target_kind=p.get("target_kind"),
        target=p.get("target"),
        count=int(p.get("count", 1) or 1),
        count_max=p.get("count_max"),
        optional=bool(p.get("optional", False)),
        selector=p.get("selector"),
    ),
)
EffectRegistry.register(
    "win_game",  # "you win the game" (Jace, Wielder of Mysteries' -8 tail)
    lambda p: WinGameEffect(if_empty_library=bool(p.get("if_empty_library", False))),
)
EffectRegistry.register(
    "become_monarch",  # "you become the monarch" (RULE 725.1, Palace Jailer-shaped)
    lambda p: BecomeMonarchEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    "gift_give",  # a permanent's gift ETB effect (RULE 702.174b); MEC-106
    lambda p: GiftGiveEffect(),
)
EffectRegistry.register(
    "take_initiative",  # "you take the initiative" (RULE 726.1)
    lambda p: TakeInitiativeEffect(target_kind=p.get("target_kind")),
)
EffectRegistry.register(
    # RULE 709.5f/709.5g (MEC-111): "unlock a locked door of a Room you control", "lock or unlock a door of target Room".
    "unlock_door",
    lambda p: UnlockDoorEffect(
        target_kind=p.get("target_kind"),
        optional=bool(p.get("optional", False)),
        lock_or_unlock=bool(p.get("lock_or_unlock", False)),
    ),
)
EffectRegistry.register(
    "venture",  # "venture into the dungeon" (RULE 701.49)
    lambda p: VentureIntoTheDungeonEffect(dungeon=p.get("dungeon")),
)
EffectRegistry.register(
    # RULE 702.131a: Ascend's spell-ability form — "you get the city's
    # blessing" checked once, at resolution, against the board.
    "get_city_blessing",
    lambda p: GetCityBlessingEffect(),
)
EffectRegistry.register(
    # PAR-28 / RULE 719.3a: "this Case becomes solved" — the resolution of
    # the "To solve — [Condition]" end-step trigger.
    "become_solved",
    lambda p: BecomeSolvedEffect(),
)
EffectRegistry.register(
    # RULE 611 "…until <duration>" — a continuous effect created on
    # resolution, for any duration the turn-scoped ``temp_*`` fields can't
    # express (`game/durations.py`). ``static`` is the underlying static's
    # own registered ``{"type", "params"}``.
    "grant_until",
    lambda p: GrantUntilEffect(
        static=p.get("static"),
        duration=str(p.get("duration") or "end_of_turn"),
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=int(p.get("count", 1) or 1),
        condition=p.get("condition"),
        previous_subject=bool(p.get("previous_subject", False)),
        self_subject=bool(p.get("self_subject", False)),
        extra_statics=p.get("extra_statics"),
        lock_group=bool(p.get("lock_group", False)),
        creature_filter=p.get("creature_filter"),
    ),
)
EffectRegistry.register(
    # RULE 701.37a "monstrosity N" — ``amount`` may be the ``"x"`` sentinel
    # (`RulesEngine._substitute_x`) for "{X}{X}{R}: Monstrosity X".
    "monstrosity",
    lambda p: MonstrosityEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # RULE 701.46a "adapt N".
    "adapt",
    lambda p: AdaptEffect(amount=p.get("amount", 1)),
)
EffectRegistry.register(
    # MEC-79 / RULE 701.64a "Harness ~" — designation flip only, no params.
    "harness",
    lambda p: HarnessEffect(),
)
EffectRegistry.register(
    # MEC-48 "Specialize {cost}" — see `SpecializeEffect`. Digital keyword,
    # designation + event only (no characteristic swap).
    "specialize",
    lambda p: SpecializeEffect(color=p.get("color")),
)
EffectRegistry.register(
    # RULE 701.15a "goad target creature" — ``target_kind=None`` is the
    # "goad it"/"goad that creature" pronoun form, ``selector`` the mass one.
    "goad",
    lambda p: GoadEffect(
        target_kind=p.get("target_kind", "creature") if "target_kind" in p else "creature",
        optional=bool(p.get("optional", False)),
        count=p.get("count", 1),
        selector=p.get("selector"),
        count_selector=p.get("count_selector"),
        referent=p.get("referent", "previous"),
        permanent=bool(p.get("permanent", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.60a (suspect, PAR-29): the creature gains the suspected
    # designation (menace + can't block). ``target_kind=None`` is the bare-
    # self / pronoun forms, ``attached`` the "suspect enchanted creature"
    # Aura shape. See `SuspectEffect` / `RulesEngine.suspect`.
    "suspect",
    lambda p: SuspectEffect(
        target_kind=p.get("target_kind"),
        selection_kind=p.get("selection_kind"),
        previous_subject=bool(p.get("previous_subject")),
        attached=bool(p.get("attached")),
        optional=bool(p.get("optional")),
        count=p.get("count", 1),
        then_specs=p.get("then_specs"),
    ),
)
EffectRegistry.register(
    # RULE 701.60a's reverse: "... is/are no longer suspected." — the mass
    # ``scope="all"`` standalone (Absolving Lammasu), the ``previous_subject``
    # single-creature form (Deadly Complication's optional rider, Airtight
    # Alibi's conditional tail) and the ``attached`` Aura-host form. See
    # `RemoveSuspectedEffect` / `RulesEngine.remove_suspected`.
    "remove_suspected",
    lambda p: RemoveSuspectedEffect(
        scope=str(p.get("scope") or "all"),
        previous_subject=bool(p.get("previous_subject", False)),
        self_subject=bool(p.get("self_subject", False)),
        previous_selector=bool(p.get("previous_selector", False)),
        attached=bool(p.get("attached", False)),
        optional=bool(p.get("optional", False)),
    ),
)
EffectRegistry.register(
    # RULE 701.35a (detain, PAR-29): until the detainer's next turn the
    # target can't attack/block and its activated abilities can't be
    # activated. See `DetainEffect` / `RulesEngine.detain`.
    "detain",
    lambda p: DetainEffect(
        target_kind=p.get("target_kind", "creature_you_dont_control"),
        optional=bool(p.get("optional")),
        count=p.get("count", 1),
    ),
)
EffectRegistry.register(
    # "Do this only once each turn." (PAR-135) — the record half of the action limit; see `ActionStampEffect`.
    "action_stamp",
    lambda p: ActionStampEffect(key=str(p.get("key", ""))),
)
EffectRegistry.register(
    "create_emblem",  # "you get an emblem with '<ability>'" (RULE 114.2)
    lambda p: CreateEmblemEffect(
        ability=p.get("ability"),
        abilities=p.get("abilities"),
        target_kind=p.get("target_kind"),
    ),
)
EffectRegistry.register(
    # "Until your next turn, target player … can't cast noncreature spells."
    # (Hope of Ghirapur) — a player-scoped cast prohibition, RULE 601.3a.
    "player_cast_restriction",
    lambda p: PlayerCastRestrictionEffect(noncreature=bool(p.get("noncreature", True))),
)
EffectRegistry.register(
    # "Look at the top X cards … put up to one on top and the rest on the
    # bottom in a random order." (+ Thassa's Oracle's own RULE 104.2a win)
    "look_top_keep_one_on_top",
    lambda p: LookTopKeepOneOnTopEffect(
        count=int(p.get("count", 0) or 0),
        count_selector=p.get("count_selector"),
        win_if_count_at_least_library=bool(p.get("win_if_count_at_least_library", False)),
    ),
)


# ---------------------------------------------------------------------------
# Replacement-effect registry (RULE 614) — the binder's whitelist
# ---------------------------------------------------------------------------



register(globals())

# RULE 702.152: casting-time statics, queried by game.blitz.
for _blitz_static in ("grant_blitz", "blitz_cost_reduction", "blitz_graveyard_permission"):
    EffectRegistry.register(
        _blitz_static,
        lambda p, kind=_blitz_static: StaticAbility(kind, affects="self", params=dict(p)),
    )


def _choose_perpetual_blitz(params):
    from ..blitz import ChoosePerpetualBlitzEffect

    return ChoosePerpetualBlitzEffect()


EffectRegistry.register("choose_perpetual_blitz", _choose_perpetual_blitz)
