"""Deck-first coverage work for Dance of the Elements.

These tests deliberately construct the relevant cards instead of relying on
the disposable Scryfall cache, so they remain an end-to-end contract for the
hand-authored cards in this saved Commander deck.
"""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _crib_swap() -> Card:
    return Card(
        id="Crib Swap", name="Crib Swap", type_line="Kindred Instant — Shapeshifter",
        mana_cost_string="{2}{W}", converted_mana_cost=3, is_instant=True,
        oracle_text=("Changeling (This card is every creature type.)\n"
                     "Exile target creature. Its controller creates a 1/1 colorless "
                     "Shapeshifter creature token with changeling."),
    )


def _engine(cards: list[Card]) -> GameEngine:
    engine = GameEngine.new_game(
        [("p1", "Alice", cards), ("p2", "Bob", [])], starting_life=20,
        starting_hand=len(cards),
    )
    for obj in engine.state.active_player.hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine


def _lamentation() -> Card:
    return Card(
        id="Lamentation", name="Lamentation", type_line="Creature — Elemental Incarnation",
        mana_cost_string="{5}{B}", converted_mana_cost=6, is_creature=True, power=6, toughness=6,
        oracle_text=("When this creature enters, destroy target creature an opponent controls. "
                     "You gain 3 life.\nEncore {6}{B}{B}"),
    )


def _shimmercreep() -> Card:
    return Card(
        id="Shimmercreep", name="Shimmercreep", type_line="Creature — Elemental",
        mana_cost_string="{4}{B}", converted_mana_cost=5, is_creature=True, power=4, toughness=4,
        color_identity={"B"}, keywords=["Vivid"],
        oracle_text=("Menace\nVivid — When this creature enters, each opponent loses X life "
                     "and you gain X life, where X is the number of colors among permanents you control."),
    )


def _elemental_spectacle() -> Card:
    return Card(
        id="Elemental Spectacle", name="Elemental Spectacle", type_line="Sorcery",
        mana_cost_string="{3}{R}{G}", converted_mana_cost=5, is_sorcery=True,
        keywords=["Vivid"],
        oracle_text=("Vivid — Create a number of 5/5 red and green Elemental creature tokens "
                     "equal to the number of colors among permanents you control. Then you gain "
                     "life equal to the number of creatures you control."),
    )


def _springleaf_parade() -> Card:
    return Card(
        id="Springleaf Parade", name="Springleaf Parade", type_line="Enchantment",
        mana_cost_string="{X}{G}{G}", converted_mana_cost=2,
        oracle_text=("When this enchantment enters, create X 1/1 colorless Shapeshifter creature "
                     "tokens with changeling.\nCreature tokens you control have \"{T}: Add one mana "
                     "of any color.\""),
    )


def _fury() -> Card:
    return Card(
        id="Fury", name="Fury", type_line="Creature — Elemental Incarnation",
        mana_cost_string="{3}{R}{R}", converted_mana_cost=5, is_creature=True,
        power=3, toughness=3, color_identity={"R"}, keywords=["Double strike", "Evoke"],
        oracle_text=("Double strike\nWhen this creature enters, it deals 4 damage divided as you "
                     "choose among any number of target creatures and/or planeswalkers.\n"
                     "Evoke—Exile a red card from your hand."),
    )


def _poison_the_cup() -> Card:
    return Card(
        id="Poison the Cup", name="Poison the Cup", type_line="Instant",
        mana_cost_string="{1}{B}{B}", converted_mana_cost=3, is_instant=True,
        oracle_text=("Destroy target creature. If this spell was foretold, scry 2.\n"
                     "Foretell {1}{B}"),
    )


def _haunting_voyage() -> Card:
    return Card(
        id="Haunting Voyage", name="Haunting Voyage", type_line="Sorcery",
        mana_cost_string="{4}{B}{B}", converted_mana_cost=6, is_sorcery=True,
        oracle_text=("Choose a creature type. Return up to two creature cards of that type "
                     "from your graveyard to the battlefield. If this spell was foretold, "
                     "return all creature cards of that type from your graveyard to the battlefield instead.\n"
                     "Foretell {5}{B}{B}"),
    )


def _grave_creature(name: str, subtype: str, owner: str) -> GameObject:
    return GameObject(
        Card(id=name, name=name, type_line=f"Creature — {subtype}", is_creature=True,
             power=2, toughness=2), owner_id=owner, zone=Zone.GRAVEYARD,
    )


def test_haunting_voyage_chooses_type_then_returns_up_to_two_or_all_if_foretold():
    engine = _engine([_haunting_voyage()])
    state = engine.state
    p1 = state.active_player
    elf_a, elf_b, elf_c = (_grave_creature(n, "Elf", p1.id) for n in ("Elf A", "Elf B", "Elf C"))
    goblin = _grave_creature("Goblin", "Goblin", p1.id)
    for obj in (elf_a, elf_b, elf_c, goblin):
        p1.add_to_zone(obj, Zone.GRAVEYARD)
    spell = p1.hand[0]
    p1.mana_pool.add_many({"B": 2, "C": 4})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    assert state.pending_choice["kind"] == "choose_type_for_source"
    engine.resolve_pending_choice("Elf")
    assert state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(elf_a.instance_id)
    engine.resolve_pending_choice(elf_b.instance_id)
    assert elf_a in state.battlefield and elf_b in state.battlefield
    assert elf_c in p1.graveyard and goblin in p1.graveyard

    # The conditional replaces the bounded chooser with every matching card.
    spell.foretold = True
    engine.rules._apply_effect_specs(
        [{"type": "return_chosen_creature_type_from_graveyard", "params": {}}], spell,
    )
    assert elf_c in state.battlefield and goblin in p1.graveyard


def test_horde_of_notions_opens_a_free_cast_window_for_the_targeted_elemental():
    horde = Card(
        id="Horde of Notions", name="Horde of Notions", type_line="Legendary Creature — Elemental",
        mana_cost_string="{W}{U}{B}{R}{G}", converted_mana_cost=5, is_creature=True,
        power=5, toughness=5,
    )
    engine = _engine([])
    state = engine.state
    p1 = state.active_player
    horde_obj = GameObject(horde, owner_id=p1.id, zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(horde_obj)
    bind_from_catalogue(horde_obj)
    elemental = _grave_creature("Returned Elemental", "Elemental", p1.id)
    p1.add_to_zone(elemental, Zone.GRAVEYARD)
    p1.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})

    engine.activate_ability(p1, horde_obj, 0, targets=[elemental])
    engine.resolve_until_stable()
    assert elemental in p1.exile
    assert elemental.instance_id in state.free_cast_instance_ids
    engine.cast_spell(p1, elemental)
    engine.resolve_until_stable()
    assert elemental in state.battlefield

    # Horde grants no Flashback-style redirect; later zone changes are normal.
    engine.rules.put_into_graveyard(elemental)
    assert elemental in p1.graveyard

    # "Elemental card" also includes the older Tribal spell card type.
    tribal = GameObject(
        Card(id="Tribal Spark", name="Tribal Spark", type_line="Tribal Instant — Elemental",
             mana_cost_string="{R}", converted_mana_cost=1, is_instant=True),
        owner_id=p1.id, zone=Zone.GRAVEYARD,
    )
    p1.add_to_zone(tribal, Zone.GRAVEYARD)
    p1.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1})
    engine.activate_ability(p1, horde_obj, 0, targets=[tribal])
    engine.resolve_until_stable()
    assert tribal in p1.exile
    engine.cast_spell(p1, tribal)
    engine.resolve_until_stable()
    assert tribal.was_cast and tribal in p1.graveyard


def test_foretell_exiles_face_down_then_casts_for_its_alt_cost_on_a_later_turn():
    engine = _engine([_poison_the_cup()])
    state = engine.state
    p1, p2 = state.players
    spell = p1.hand[0]
    victim = GameObject(
        Card(id="Foretell victim", name="Foretell victim", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2), owner_id=p2.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(victim)

    p1.mana_pool.add_many({"C": 2})
    assert any(a["type"] == "foretell" for a in engine.legal_actions(p1))
    engine.foretell(p1, spell)
    assert spell in p1.exile and spell.face_down_in_exile and spell.foretold
    assert not engine.can_cast(p1, spell)  # never on the same turn

    state.internal_turn.number += 1
    p1.mana_pool.add_many({"B": 1, "C": 1})
    cast_action = next(
        a for a in engine.legal_actions(p1)
        if a["type"] == "cast_spell" and a["instance_id"] == spell.instance_id
    )
    assert cast_action["foretell"] is True
    assert cast_action["foretell_cost_label"] == "{1}{B}"
    engine.cast_spell(p1, spell, targets=[victim])
    assert spell.foretold and spell.cast_from_exile
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD


def test_crib_swap_is_registered_with_a_full_spell_effect():
    (spec,) = specs_for(_crib_swap())
    assert spec.ability_kind == "spell_effect"
    # ENG-37 B3: retired `exile_create_token` -> a `seq` of `exile` then
    # `create_token` for the exiled object's last-known controller.
    node = spec.effects[0]
    assert node.type == "seq"
    body = node.params["effects"]
    assert body[0]["type"] == "exile"
    assert body[1]["type"] == "create_token"
    assert body[1]["params"]["keywords"] == ["changeling"]
    assert body[1]["params"]["creators"] == "previous_target_controller"


def test_crib_swap_exiles_target_and_creates_changeling_for_its_controller():
    engine = _engine([_crib_swap()])
    state = engine.state
    p1, p2 = state.players
    victim = GameObject(
        Card(id="Victim", name="Victim", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id=p2.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(victim)

    spell = p1.hand[0]
    p1.mana_pool.add_many({"W": 1, "C": 2})
    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()

    assert victim.zone == Zone.EXILE
    [token] = [obj for obj in state.battlefield if obj.name == "Shapeshifter"]
    assert token.controller_id == p2.id
    assert (token.power, token.toughness) == (1, 1)
    assert "changeling" in token.intrinsic_keywords


def test_lamentation_etb_destroys_an_opponent_creature_and_gains_life():
    engine = _engine([_lamentation()])
    state = engine.state
    p1, p2 = state.players
    victim = GameObject(
        Card(id="LamentVictim", name="LamentVictim", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id=p2.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(victim)

    spell = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 5})
    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(victim.instance_id)
    engine.resolve_until_stable()

    assert victim.zone == Zone.GRAVEYARD
    assert p1.life == 23


def test_shimmercreep_parser_counts_colours_and_drains_each_opponent():
    card = _shimmercreep()
    assert parse_oracle(card).modeled

    engine = _engine([card])
    state = engine.state
    p1, p2 = state.players
    # The black Shimmercreep plus this red permanent make two colours.
    red = GameObject(
        Card(id="Red", name="Red", type_line="Creature — Goblin", is_creature=True,
             power=1, toughness=1, color_identity={"R"}),
        owner_id=p1.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(red)

    spell = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 4})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    assert p1.life == 22
    assert p2.life == 18


def test_elemental_spectacle_creates_per_colour_then_counts_created_creatures():
    card = _elemental_spectacle()
    assert parse_oracle(card).modeled

    engine = _engine([card])
    state = engine.state
    p1 = state.active_player
    for identity in ({"R"}, {"G"}):
        label = next(iter(identity))
        state.add_to_battlefield(GameObject(
            Card(id=label, name=label, type_line="Creature — Bear", is_creature=True,
                 power=1, toughness=1, color_identity=identity),
            owner_id=p1.id, zone=Zone.BATTLEFIELD,
        ))

    spell = p1.hand[0]
    p1.mana_pool.add_many({"R": 1, "G": 1, "C": 3})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    tokens = [obj for obj in state.battlefield if obj.name == "Elemental"]
    assert len(tokens) == 2
    assert p1.life == 24  # two original creatures plus two new tokens


def test_springleaf_parade_creates_x_changelings_and_grants_them_any_colour_mana():
    engine = _engine([_springleaf_parade()])
    state = engine.state
    p1 = state.active_player
    spell = p1.hand[0]
    p1.mana_pool.add_many({"G": 4})
    engine.cast_spell(p1, spell, x=2)
    engine.resolve_until_stable()

    tokens = [obj for obj in state.battlefield if obj.name == "Shapeshifter"]
    assert len(tokens) == 2
    assert all("changeling" in token.intrinsic_keywords for token in tokens)
    assert all(token.granted_mana_options for token in tokens)


def test_fury_can_be_evoked_by_exiling_a_red_card_then_deals_divided_damage():
    fury, red_payment = _fury(), Card(
        id="Red payment", name="Red payment", type_line="Creature — Goblin", is_creature=True,
        power=1, toughness=1, color_identity={"R"},
    )
    assert parse_oracle(fury).modeled
    engine = _engine([fury, red_payment])
    state = engine.state
    p1, p2 = state.players
    fury_obj = next(obj for obj in p1.hand if obj.name == "Fury")
    payment = next(obj for obj in p1.hand if obj.name == "Red payment")
    victim = GameObject(
        Card(id="Fury victim", name="Fury victim", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=5), owner_id=p2.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(victim)

    assert any(action.get("evoke") for action in engine.legal_actions(p1))
    engine.cast_spell(p1, fury_obj, evoke=True)
    engine.resolve_until_stable()
    assert payment.zone == Zone.EXILE
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target_multi"
    engine.resolve_pending_choice(victim.instance_id)
    engine.resolve_until_stable()

    assert fury_obj.zone == Zone.GRAVEYARD
    assert victim.damage_marked == 4


def test_hoofprint_counter_draw_trigger_parses_with_its_existing_token_activation():
    card = Card(
        id="Hoofprints of the Stag", name="Hoofprints of the Stag", type_line="Enchantment",
        mana_cost_string="{1}{W}", converted_mana_cost=2,
        oracle_text=("Whenever you draw a card, you may put a hoofprint counter on this enchantment.\n"
                     "{2}{W}, Remove four hoofprint counters from this enchantment: Create a 4/4 "
                     "white Elemental creature token with flying. Activate only during your turn."),
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    trigger = next(spec for spec in result.specs if spec.ability_kind == "triggered")
    assert trigger.effects[0].params == {"count": 1, "kind": "hoofprint"}


def test_fertile_ground_reuses_attached_land_triggered_mana_with_a_colour_choice():
    specs = specs_for(Card(
        id="Fertile Ground", name="Fertile Ground", type_line="Enchantment — Aura",
        oracle_text="Enchant land\nWhenever enchanted land is tapped for mana, its controller adds an additional one mana of any color.",
    ))
    spec = next(spec for spec in specs if spec.ability_kind == "triggered")
    assert spec.trigger == {
        "event": "TAPPED_FOR_MANA", "condition": {"subject": "attached_permanent"},
        "mana_ability": True,
    }
    assert spec.effects[0].params == {"colors": ["ANY"], "recipient": "event_controller"}


def test_greenwarden_dies_can_exile_it_then_return_a_graveyard_card():
    greenwarden = Card(
        id="Greenwarden of Murasa", name="Greenwarden of Murasa",
        type_line="Creature — Elemental", mana_cost_string="{4}{G}{G}",
        converted_mana_cost=6, is_creature=True, power=5, toughness=4,
        oracle_text=("When this creature enters, you may return target card from your graveyard to your hand.\n"
                     "When this creature dies, you may exile it. If you do, return target card from your graveyard to your hand."),
    )
    regrowth_target = Card(id="Regrowth target", name="Regrowth target", type_line="Sorcery", is_sorcery=True)
    engine = _engine([greenwarden, regrowth_target])
    state = engine.state
    p1 = state.active_player
    target = next(obj for obj in p1.hand if obj.name == "Regrowth target")
    p1.hand.remove(target)
    p1.add_to_zone(target, Zone.GRAVEYARD)
    greenwarden_obj = next(obj for obj in p1.hand if obj.name == "Greenwarden of Murasa")
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.cast_spell(p1, greenwarden_obj)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(None)
    engine.resolve_until_stable()
    engine.rules.destroy(greenwarden_obj)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "exile_source_then"
    engine.resolve_pending_choice("exile")
    engine.resolve_until_stable()
    assert greenwarden_obj.zone == Zone.EXILE
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(target.instance_id)
    engine.resolve_until_stable()
    assert target.zone == Zone.HAND


def test_risen_reef_puts_a_top_land_tapped_or_a_nonland_into_hand():
    reef = Card(
        id="Risen Reef", name="Risen Reef", type_line="Creature — Elemental",
        mana_cost_string="{1}{G}{U}", converted_mana_cost=3, is_creature=True,
        power=1, toughness=1,
        oracle_text="Whenever this creature or another Elemental enters under your control, look at the top card of your library. If it's a land card, you may put it onto the battlefield tapped. If you don't put the card onto the battlefield, put it into your hand.",
    )
    engine = _engine([reef])
    state, p1 = engine.state, engine.state.active_player
    land = GameObject(Card(id="Island", name="Island", type_line="Basic Land — Island", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.add_to_zone(land, Zone.LIBRARY)
    reef_obj = p1.hand[0]
    p1.mana_pool.add_many({"G": 1, "U": 1, "C": 1})
    engine.cast_spell(p1, reef_obj)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "peek_top_land"
    engine.resolve_pending_choice("put")
    engine.resolve_until_stable()
    assert land.zone == Zone.BATTLEFIELD and land.tapped


def test_muldrotha_allows_one_graveyard_permanent_of_each_type_and_a_land():
    muldrotha = Card(
        id="Muldrotha, the Gravetide", name="Muldrotha, the Gravetide",
        type_line="Legendary Creature — Elemental Avatar", is_creature=True,
        power=6, toughness=6,
        oracle_text="During each of your turns, you may play a land and cast a permanent spell of each permanent type from your graveyard.",
    )
    artifact = Card(id="GY Artifact", name="GY Artifact", type_line="Artifact", mana_cost_string="{1}", converted_mana_cost=1)
    creature = Card(id="GY Creature", name="GY Creature", type_line="Creature — Bear", mana_cost_string="{1}", converted_mana_cost=1, is_creature=True, power=1, toughness=1)
    land_card = Card(id="GY Land", name="GY Land", type_line="Land", is_land=True)
    engine = _engine([muldrotha, artifact, creature, land_card])
    state, p1 = engine.state, engine.state.active_player
    muldrotha_obj = next(o for o in p1.hand if o.name == "Muldrotha, the Gravetide")
    p1.hand.remove(muldrotha_obj)
    state.add_to_battlefield(muldrotha_obj)
    for obj in list(p1.hand):
        p1.hand.remove(obj)
        p1.add_to_zone(obj, Zone.GRAVEYARD)
    artifact_obj = next(o for o in p1.graveyard if o.name == "GY Artifact")
    creature_obj = next(o for o in p1.graveyard if o.name == "GY Creature")
    land_obj = next(o for o in p1.graveyard if o.name == "GY Land")
    p1.mana_pool.add_many({"C": 2})
    assert engine.can_cast(p1, artifact_obj) and engine.can_cast(p1, creature_obj)
    engine.cast_spell(p1, artifact_obj)
    engine.resolve_until_stable()
    engine.cast_spell(p1, creature_obj)
    engine.resolve_until_stable()
    assert engine.can_play_land(p1, land_obj)
    engine.play_land(p1, land_obj)
    assert {"artifact", "creature", "land"} <= muldrotha_obj.graveyard_cast_types_this_turn


def test_distant_melody_chooses_a_type_then_draws_for_matching_creatures():
    melody = Card(id="Distant Melody", name="Distant Melody", type_line="Sorcery", mana_cost_string="{3}{U}", converted_mana_cost=4, is_sorcery=True,
                  oracle_text="Choose a creature type. Draw a card for each permanent you control of that type.")
    engine = _engine([melody])
    state, p1 = engine.state, engine.state.active_player
    for n in range(3):
        state.add_to_battlefield(GameObject(Card(id=f"Elf {n}", name=f"Elf {n}", type_line="Creature — Elf", is_creature=True, power=1, toughness=1), owner_id=p1.id, zone=Zone.BATTLEFIELD))
        p1.add_to_zone(GameObject(Card(id=f"Draw {n}", name=f"Draw {n}", type_line="Sorcery", is_sorcery=True), owner_id=p1.id, zone=Zone.LIBRARY), Zone.LIBRARY)
    spell = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 3})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "choose_type_for_source"
    engine.resolve_pending_choice("Elf")
    engine.resolve_until_stable()
    assert len(p1.hand) == 3


def test_bane_of_progress_destroys_artifacts_and_enchantments_then_grows():
    bane = Card(id="Bane of Progress", name="Bane of Progress", type_line="Creature — Elemental", mana_cost_string="{4}{G}{G}", converted_mana_cost=6, is_creature=True, power=2, toughness=2,
                oracle_text="When this creature enters, destroy all artifacts and enchantments. Put a +1/+1 counter on this creature for each permanent destroyed this way.")
    engine = _engine([bane])
    state, p1, p2 = engine.state, engine.state.players[0], engine.state.players[1]
    for name, typ in (("Artifact", "Artifact"), ("Enchantment", "Enchantment")):
        state.add_to_battlefield(GameObject(Card(id=name, name=name, type_line=typ), owner_id=p2.id, zone=Zone.BATTLEFIELD))
    obj = p1.hand[0]
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.cast_spell(p1, obj)
    engine.resolve_until_stable()
    assert obj.counters.get("+1/+1") == 2
    assert all(o.zone == Zone.GRAVEYARD for o in p2.graveyard)


def test_titan_of_industry_registers_its_four_choose_two_modes():
    card = Card(id="Titan of Industry", name="Titan of Industry", type_line="Creature — Elemental", is_creature=True,
                oracle_text="When this creature enters, choose two — Destroy target artifact or enchantment; target player gains 5 life; create a 4/4 green Rhino Warrior creature token; put a shield counter on a creature you control.")
    (spec,) = specs_for(card)
    assert spec.modes["choose"] == 2
    assert len(spec.modes["options"]) == 4


def test_yarok_uses_the_shared_etb_trigger_doubler():
    card = Card(id="Yarok, the Desecrated", name="Yarok, the Desecrated", type_line="Legendary Creature — Elemental Horror", is_creature=True,
                oracle_text="If a permanent entering the battlefield causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.")
    (spec,) = specs_for(card)
    assert spec.effects[0].type == "trigger_doubler"
    assert spec.effects[0].params["cause_filter"] == ["ENTERS_BATTLEFIELD"]


def test_reality_shift_exiles_then_manifests_for_the_exiled_creatures_controller():
    card = Card(
        id="Reality Shift", name="Reality Shift", type_line="Instant", is_instant=True,
        mana_cost_string="{1}{U}", converted_mana_cost=2,
        oracle_text="Exile target creature. Its controller manifests the top card of their library.",
    )
    engine = _engine([card])
    state = engine.state
    p1, p2 = state.players
    victim = GameObject(Card(id="Victim", name="Victim", type_line="Creature — Bear", is_creature=True,
                             power=2, toughness=2), owner_id=p2.id, zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(victim)
    top = GameObject(Card(id="Top", name="Top", type_line="Sorcery", is_sorcery=True), owner_id=p2.id, zone=Zone.LIBRARY)
    p2.library.append(top)
    spell = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 1})
    engine.cast_spell(p1, spell, targets=[victim])
    engine.resolve_until_stable()

    assert victim.zone == Zone.EXILE
    assert top.zone == Zone.BATTLEFIELD and top.controller_id == p2.id


def test_shatter_the_sky_draws_only_qualifying_players_before_destroying_creatures():
    card = Card(id="Shatter the Sky", name="Shatter the Sky", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{2}{W}{W}", converted_mana_cost=4,
                oracle_text="Each player who controls a creature with power 4 or greater draws a card. Then destroy all creatures.")
    engine = _engine([card])
    state = engine.state
    p1, p2 = state.players
    big = GameObject(Card(id="Big", name="Big", type_line="Creature", is_creature=True, power=4, toughness=4), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    small = GameObject(Card(id="Small", name="Small", type_line="Creature", is_creature=True, power=2, toughness=2), owner_id=p2.id, zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(big); state.add_to_battlefield(small)
    p1.library.append(GameObject(Card(id="Draw", name="Draw", type_line="Land", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))
    spell = p1.hand[0]; p1.mana_pool.add_many({"W": 2, "C": 2})
    engine.cast_spell(p1, spell); engine.resolve_until_stable()
    assert len(p1.hand) == 1 and not p2.hand
    assert big.zone == Zone.GRAVEYARD and small.zone == Zone.GRAVEYARD


def _descendants_fury() -> Card:
    return Card(
        id="Descendants' Fury", name="Descendants' Fury", type_line="Enchantment",
        mana_cost_string="{3}{R}", converted_mana_cost=4,
        oracle_text=("Whenever one or more creatures you control deal combat damage to a player, "
                     "you may sacrifice one of them. If you do, reveal cards from the top of your "
                     "library until you reveal a creature card that shares a creature type with "
                     "the sacrificed creature. Put that card onto the battlefield and the rest on "
                     "the bottom of your library in a random order."),
    )


def _kindred_summons() -> Card:
    return Card(
        id="Kindred Summons", name="Kindred Summons", type_line="Instant",
        mana_cost_string="{5}{G}{G}", converted_mana_cost=7, is_instant=True,
        oracle_text=("Choose a creature type. Reveal cards from the top of your library until you "
                     "reveal X creature cards of the chosen type, where X is the number of "
                     "creatures you control of that type. Put those cards onto the battlefield, "
                     "then shuffle the rest of the revealed cards into your library."),
    )


def _eclipsed_flamekin() -> Card:
    return Card(
        id="Eclipsed Flamekin", name="Eclipsed Flamekin", type_line="Creature — Elemental Scout",
        mana_cost_string="{2}{U}", converted_mana_cost=3, is_creature=True, power=2, toughness=2,
        oracle_text=("When this creature enters, look at the top four cards of your library. "
                     "You may reveal an Elemental, Island, or Mountain card from among them and "
                     "put it into your hand. Put the rest on the bottom of your library in a random order."),
    )


def _cream_of_the_crop() -> Card:
    return Card(
        id="Cream of the Crop", name="Cream of the Crop", type_line="Enchantment",
        mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text=("Whenever a creature you control enters, you may look at the top X cards of "
                     "your library, where X is that creature's power. If you do, put one of those "
                     "cards on top of your library and the rest on the bottom of your library in any order."),
    )


def _cavalier_of_thorns() -> Card:
    return Card(
        id="Cavalier of Thorns", name="Cavalier of Thorns", type_line="Creature — Elemental Knight",
        mana_cost_string="{2}{G}{G}{G}", converted_mana_cost=5, is_creature=True, power=5, toughness=6,
        oracle_text=("Reach\nWhen this creature enters, reveal the top five cards of your library. "
                     "Put a land card from among them onto the battlefield and the rest into your graveyard.\n"
                     "When this creature dies, you may exile it. If you do, put another target card "
                     "from your graveyard on top of your library."),
    )


def test_descendants_fury_sacrifices_combat_dealer_and_reveals_sharing_type():
    fury_card = _descendants_fury()
    engine = _engine([fury_card])
    state = engine.state
    p1, p2 = state.players

    fury_obj = p1.hand[0]
    p1.mana_pool.add_many({"R": 1, "C": 3})
    engine.cast_spell(p1, fury_obj)
    engine.resolve_until_stable()
    assert fury_obj in state.battlefield

    # Two attacking creatures dealing combat damage to p2
    elemental_warrior = GameObject(
        Card(id="Flamekin", name="Flamekin", type_line="Creature — Elemental Warrior", is_creature=True, power=2, toughness=2),
        owner_id=p1.id, zone=Zone.BATTLEFIELD,
    )
    bear = GameObject(
        Card(id="Grizzly Bears", name="Grizzly Bears", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
        owner_id=p1.id, zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(elemental_warrior)
    state.add_to_battlefield(bear)

    # Deck setup: top has Forest, Air Elemental (creature — Elemental), Llanowar Elves
    forest = GameObject(Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    air_elem = GameObject(Card(id="Air Elemental", name="Air Elemental", type_line="Creature — Elemental", is_creature=True, power=4, toughness=4), owner_id=p1.id, zone=Zone.LIBRARY)
    elves = GameObject(Card(id="Llanowar Elves", name="Llanowar Elves", type_line="Creature — Elf", is_creature=True, power=1, toughness=1), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.library.clear()
    p1.library.extend([elves, air_elem, forest])  # forest is top (index -1)

    # Simulate combat damage step
    engine._apply_combat_damage([
        (p2, 2, elemental_warrior),
        (p2, 2, bear),
    ])
    engine.resolve_until_stable()

    # Descendants' Fury triggers and asks to sacrifice one of the contributors
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    assert state.pending_choice["action"] == "sacrifice_for_descendants_fury"

    # Choose to sacrifice elemental_warrior
    engine.resolve_pending_choice(elemental_warrior.instance_id)

    assert elemental_warrior.zone == Zone.GRAVEYARD
    assert air_elem in state.battlefield
    assert air_elem.zone == Zone.BATTLEFIELD
    assert forest.zone == Zone.LIBRARY
    # Forest was put at bottom (index 0)
    assert p1.library[0] == forest


def test_kindred_summons_reveals_x_chosen_type_creatures_and_shuffles_rest():
    card = _kindred_summons()
    engine = _engine([card])
    state = engine.state
    p1 = state.active_player

    # Control 2 Elementals and 1 Goblin
    e1 = _grave_creature("Elem1", "Elemental", p1.id)
    e2 = _grave_creature("Elem2", "Elemental", p1.id)
    gob = _grave_creature("Gob1", "Goblin", p1.id)
    for obj in (e1, e2, gob):
        state.add_to_battlefield(obj)

    # Library setup: from bottom to top:
    # Goblin2, ElemHit1, Island, ElemHit2, Mountain
    # Top card is Mountain
    mtn = GameObject(Card(id="Mountain", name="Mountain", type_line="Basic Land — Mountain", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    elem_hit2 = _grave_creature("ElemHit2", "Elemental", p1.id)
    isl = GameObject(Card(id="Island", name="Island", type_line="Basic Land — Island", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    elem_hit1 = _grave_creature("ElemHit1", "Elemental", p1.id)
    gob2 = _grave_creature("Gob2", "Goblin", p1.id)
    p1.library.clear()
    p1.library.extend([gob2, elem_hit1, isl, elem_hit2, mtn])

    spell = p1.hand[0]
    p1.mana_pool.add_many({"G": 2, "C": 5})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    # Choice 1: choose creature type
    assert state.pending_choice["kind"] == "choose_type_for_source"
    engine.resolve_pending_choice("Elemental")

    # X=2: reveals top until 2 Elementals found (ElemHit2 and ElemHit1).
    assert elem_hit1 in state.battlefield
    assert elem_hit2 in state.battlefield
    # Remaining revealed cards (mtn, isl) were shuffled back into library
    assert mtn in p1.library and isl in p1.library


def test_eclipsed_flamekin_inspects_four_filters_elemental_island_mountain_to_hand():
    flamekin_card = _eclipsed_flamekin()
    engine = _engine([flamekin_card])
    state = engine.state
    p1 = state.active_player

    c1 = GameObject(Card(id="Forest", name="Forest", type_line="Land", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    c2 = GameObject(Card(id="Volcanic Island", name="Volcanic Island", type_line="Land — Island Mountain", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    c3 = GameObject(Card(id="Air Elemental", name="Air Elemental", type_line="Creature — Elemental", is_creature=True, power=4, toughness=4), owner_id=p1.id, zone=Zone.LIBRARY)
    c4 = GameObject(Card(id="Disenchant", name="Disenchant", type_line="Instant", is_instant=True), owner_id=p1.id, zone=Zone.LIBRARY)
    c_bottom = GameObject(Card(id="Deep Card", name="Deep Card", type_line="Sorcery", is_sorcery=True), owner_id=p1.id, zone=Zone.LIBRARY)
    # top 4: c4, c3, c2, c1 (c4 is top)
    p1.library.clear()
    p1.library.extend([c_bottom, c1, c2, c3, c4])

    spell = p1.hand[0]
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    # ETB triggers: inspect top 4 cards. Filter: Elemental, Island, Mountain -> c2, c3 match!
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    # Choose c2 (Volcanic Island) to put into hand
    engine.resolve_pending_choice(c2.instance_id)

    assert c2 in p1.hand
    assert c2.zone == Zone.HAND
    # Other 3 cards (c1, c3, c4) were put on bottom of library
    assert c1 in p1.library and c3 in p1.library and c4 in p1.library
    # c_bottom is still in library
    assert c_bottom in p1.library


def test_cream_of_the_crop_triggers_on_creature_power_and_puts_one_on_top():
    crop_card = _cream_of_the_crop()
    engine = _engine([crop_card])
    state = engine.state
    p1 = state.active_player

    crop_obj = p1.hand[0]
    p1.mana_pool.add_many({"G": 1, "C": 1})
    engine.cast_spell(p1, crop_obj)
    engine.resolve_until_stable()
    assert crop_obj in state.battlefield

    # Library setup: top 3 cards
    c_base = GameObject(Card(id="Bottom Card", name="Bottom Card", type_line="Land", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    card_a = GameObject(Card(id="Card A", name="Card A", type_line="Sorcery", is_sorcery=True), owner_id=p1.id, zone=Zone.LIBRARY)
    card_b = GameObject(Card(id="Card B", name="Card B", type_line="Instant", is_instant=True), owner_id=p1.id, zone=Zone.LIBRARY)
    card_c = GameObject(Card(id="Card C", name="Card C", type_line="Creature", is_creature=True, power=1, toughness=1), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.library.clear()
    p1.library.extend([c_base, card_a, card_b, card_c])  # card_c is top

    # A 3-power creature enters
    big = GameObject(Card(id="Big Beast", name="Big Beast", type_line="Creature — Beast", is_creature=True, power=3, toughness=3), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(big)
    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=p1.id, instance_id=big.instance_id, object=big.name, object_types=["creature"]))
    engine.resolve_until_stable()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    # Choose card_b to be on top
    engine.resolve_pending_choice(card_b.instance_id)

    # card_b is at top of library
    assert p1.library[-1] == card_b
    assert card_a in p1.library and card_c in p1.library


def test_cavalier_of_thorns_etb_land_to_battlefield_and_rest_to_graveyard_and_dies_trigger():
    cav_card = _cavalier_of_thorns()
    engine = _engine([cav_card])
    state = engine.state
    p1 = state.active_player

    # Library top 5: Land1, Spell1, Land2, Spell2, Spell3
    s3 = GameObject(Card(id="S3", name="S3", type_line="Instant", is_instant=True), owner_id=p1.id, zone=Zone.LIBRARY)
    s2 = GameObject(Card(id="S2", name="S2", type_line="Sorcery", is_sorcery=True), owner_id=p1.id, zone=Zone.LIBRARY)
    land2 = GameObject(Card(id="Forest2", name="Forest2", type_line="Basic Land — Forest", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    s1 = GameObject(Card(id="S1", name="S1", type_line="Instant", is_instant=True), owner_id=p1.id, zone=Zone.LIBRARY)
    land1 = GameObject(Card(id="Forest1", name="Forest1", type_line="Basic Land — Forest", is_land=True), owner_id=p1.id, zone=Zone.LIBRARY)
    p1.library.clear()
    p1.library.extend([land2, s3, s2, s1, land1])  # top 5

    spell = p1.hand[0]
    p1.mana_pool.add_many({"G": 3, "C": 2})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()

    # ETB choice among the lands (land1 and land2)
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(land1.instance_id)

    assert land1 in state.battlefield
    assert land1.zone == Zone.BATTLEFIELD
    # The rest (s1, s2, s3, land2) went into graveyard
    for obj in (s1, s2, s3, land2):
        assert obj in p1.graveyard
        assert obj.zone == Zone.GRAVEYARD

    # Dies trigger: Cavalier dies -> may exile it, then put target card from graveyard on top of library
    cav_obj = spell
    engine.rules.put_into_graveyard(cav_obj)
    engine.resolve_until_stable()

    # Offer to exile Cavalier
    assert state.pending_choice is not None
    engine.resolve_pending_choice("exile")
    engine.resolve_until_stable()

    # Target choice from graveyard: pick land2
    assert state.pending_choice is not None
    engine.resolve_pending_choice(str(land2.instance_id))
    engine.resolve_until_stable()

    assert cav_obj.zone == Zone.EXILE
    assert p1.library[-1] == land2
    assert land2.zone == Zone.LIBRARY


def test_cavalier_of_thorns_does_not_trigger_on_another_creature_entering():
    cav_card = _cavalier_of_thorns()
    engine = _engine([cav_card])
    state = engine.state
    p1 = state.active_player
    cav_obj = p1.hand[0]
    bind_from_catalogue(cav_obj)
    state.add_to_battlefield(cav_obj)

    other = GameObject(
        Card(id="Other Creature", name="Other Creature", type_line="Creature — Beast", is_creature=True),
        owner_id=p1.id,
        zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(other)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD,
        controller_id=p1.id,
        instance_id=other.instance_id,
        object=other.name,
        object_types=["creature"],
    ))

    assert state.pending_choice is None
