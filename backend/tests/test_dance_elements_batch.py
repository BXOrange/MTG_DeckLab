"""Deck-first coverage work for Dance of the Elements.

These tests deliberately construct the relevant cards instead of relying on
the disposable Scryfall cache, so they remain an end-to-end contract for the
hand-authored cards in this saved Commander deck.
"""

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
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


def test_crib_swap_is_registered_with_a_full_spell_effect():
    (spec,) = specs_for(_crib_swap())
    assert spec.ability_kind == "spell_effect"
    assert spec.effects[0].type == "exile_create_token"
    assert spec.effects[0].params["keywords"] == ["changeling"]


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
