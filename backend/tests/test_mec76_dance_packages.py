"""MEC-76 — end-to-end contracts for the remaining Dance packages."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.deckliste_parser import parse_deck_sections
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.deck_database import DeckDatabase, DEFAULT_DECKS_DB_PATH
from mtg_analyzer.services.card_database import CardDatabase


def _engine(library=()):
    engine = GameEngine.new_game(
        [("p1", "p1", list(library)), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine


def _card(name):
    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None, name
    return card


def _permanent(card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    return obj


def test_dance_deck_has_no_remaining_unmodeled_cards():
    """The saved deck remains goldfish-ready as its card pool evolves."""
    deck = next(
        deck for deck in DeckDatabase(DEFAULT_DECKS_DB_PATH).list_decks()
        if deck.name == "Dance of the Elements - Lorwyn Eclipsed Commander Deck"
    )
    cards = CardDatabase(DB_PATH)
    parsed = parse_deck_sections(deck.commander_text, deck.mainboard_text, deck.sideboard_text)
    uncovered = [
        entry.name for entry in parsed.all_cards
        if (card := cards.get_card(entry.name)) is None
        or not (is_registered(card.name) or parse_oracle(card).modeled)
    ]
    assert uncovered == []


def test_return_of_the_wildspeaker_modes_use_nonhuman_derived_board_values():
    library = [Card(id=f"draw-{i}", name=f"Draw {i}", type_line="Instant", is_instant=True)
               for i in range(6)]
    engine = _engine(library)
    state, player = engine.state, engine.state.player_by_id("p1")
    nonhuman = _permanent(Card(id="beast", name="Beast", type_line="Creature — Beast",
                               is_creature=True, power=4, toughness=4))
    human = _permanent(Card(id="human", name="Human", type_line="Creature — Human",
                            is_creature=True, power=9, toughness=9))
    state.add_to_battlefield(nonhuman)
    state.add_to_battlefield(human)

    spell = GameObject(_card("Return of the Wildspeaker"), owner_id="p1", zone=Zone.HAND)
    player.hand.append(spell)
    bind_from_catalogue(spell)
    player.mana_pool.add("G", 1)
    player.mana_pool.add("C", 4)
    engine.cast_spell(player, spell, mode=0)
    engine.resolve_until_stable()
    assert len(player.hand) == 4  # the Human's power must not count

    # A fresh copy verifies the other mode's group filter independently.
    spell2 = GameObject(_card("Return of the Wildspeaker"), owner_id="p1", zone=Zone.HAND)
    player.hand.append(spell2)
    bind_from_catalogue(spell2)
    player.mana_pool.add("G", 1)
    player.mana_pool.add("C", 4)
    engine.cast_spell(player, spell2, mode=1)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert nonhuman.power == 7 and nonhuman.toughness == 7
    assert human.power == 9 and human.toughness == 9


def test_mass_of_mysteries_targets_only_another_elemental_and_grants_myriad():
    engine = _engine()
    state = engine.state
    mass = _permanent(_card("Mass of Mysteries"))
    elemental = _permanent(Card(id="elemental", name="Elemental", type_line="Creature — Elemental",
                                is_creature=True, power=3, toughness=3))
    non_elemental = _permanent(Card(id="bear", name="Bear", type_line="Creature — Bear",
                                    is_creature=True, power=2, toughness=2))
    state.add_to_battlefield(mass)
    state.add_to_battlefield(elemental)
    state.add_to_battlefield(non_elemental)
    bind_from_catalogue(mass)

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    engine.resolve_until_stable()
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    assert [option["instance_id"] for option in choice["options"]] == [elemental.instance_id]
    engine.resolve_pending_choice(elemental.instance_id)
    engine.resolve_until_stable()
    assert "myriad" in elemental.temp_keywords
    assert "myriad" not in mass.temp_keywords


def test_slithermuse_chooses_an_opponent_and_draws_the_live_hand_difference():
    library = [Card(id=f"slither-{i}", name=f"Slither Draw {i}", type_line="Instant", is_instant=True)
               for i in range(5)]
    engine = _engine(library)
    state = engine.state
    p1, p2 = state.players
    slither = _permanent(_card("Slithermuse"))
    state.add_to_battlefield(slither)
    bind_from_catalogue(slither)
    for i in range(3):
        p2.hand.append(GameObject(Card(id=f"opp-{i}", name=f"Opp {i}", type_line="Instant",
                                       is_instant=True), owner_id="p2", zone=Zone.HAND))

    state.fire_event(GameEvent(EventType.LEAVES_BATTLEFIELD, instance_id=slither.instance_id))
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "slithermuse_opponent"
    engine.resolve_pending_choice("p2")
    assert len(p1.hand) == 3


def test_impulsivity_free_casts_any_graveyard_instant_and_exiles_it_after_resolution():
    engine = _engine()
    state = engine.state
    p1, p2 = state.players
    source = _permanent(_card("Impulsivity"))
    state.add_to_battlefield(source)
    bind_from_catalogue(source)
    spell = GameObject(Card(id="spell", name="Spell", type_line="Instant", is_instant=True,
                            oracle_text="Deal 3 damage to any target."), owner_id="p2", zone=Zone.GRAVEYARD)
    bind_from_catalogue(spell)
    p2.graveyard.append(spell)

    state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id))
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(spell.instance_id)
    engine.resolve_until_stable()
    assert spell.zone == Zone.EXILE and spell.instance_id in state.free_cast_instance_ids
    # The controller deliberately casts the offered spell and chooses its
    # target through the normal casting flow.
    engine.cast_spell(p1, spell, targets=[p2])
    engine.resolve_until_stable()
    assert spell.zone == Zone.EXILE and spell in p2.exile
    assert p2.life == 17
