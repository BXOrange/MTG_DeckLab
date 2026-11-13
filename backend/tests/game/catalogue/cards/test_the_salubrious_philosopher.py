"""Printed Oracle categories and real optional draw replacements."""
import pytest

from mtg_analyzer.game.salubrious import matches
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game


NAME = "The Salubrious Philosopher"


def _printed(text, type_line="Instant", mv=0):
    return Card(id=text, name="Example", oracle_text=text, type_line=type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                is_land="Land" in type_line, converted_mana_cost=mv)


@pytest.mark.parametrize("text,type_line,expected", [
    ("{T}: Add {G}.", "Creature — Elf", True),
    ("If you control an artifact, add two mana of any one color.", "Sorcery", True),
    ("Choose one —\n• Add {R}{R}.\n• Draw a card.", "Instant", True),
    ("Whenever a creature dies, add that much {B}.", "Enchantment", True),
    ("{T}: Add one mana of any type that a land you control could produce.", "Artifact", True),
    ("", "Basic Land — Forest", True),
    ("{T}, Sacrifice this land: Search your library for a basic land card.", "Land", False),
    ("Create a Treasure token. (It's an artifact with \"{T}, Sacrifice this token: Add one mana of any color.\")", "Sorcery", False),
    ("Untap target land.", "Instant", False),
])
def test_mana_base_uses_printed_mana_instructions_and_basic_land_types(text, type_line, expected):
    assert matches(_printed(text, type_line), "mana_base") is expected


@pytest.mark.parametrize("text,expected", [
    ("Destroy target creature.", True),
    ("Target opponent exiles a creature or planeswalker they control.", True),
    ("Example deals 4 damage divided as you choose among any number of targets.", True),
    ("Two target creatures fight each other.", True),
    ("Create a 4/4 red Dragon creature token. At the beginning of the next end step, exile that token.", False),
    ("If you control a Wizard, exile target nonland permanent an opponent controls.", True),
    ("Choose one —\n• Draw a card.\n• Destroy target artifact or enchantment.", True),
    ("Destroy all creatures.", True),
    ("Destroy all creatures except creatures you control.", True),
    ("Example deals 3 damage to any target.", True),
    ("Example deals X damage to each creature and each planeswalker.", True),
    ("Target creature you control fights target creature you don't control.", True),
    ("Destroy target creature you control.", False),
    ("Exile target artifact you own.", False),
    ("Exile target creature card from a graveyard.", False),
    ("Exile target creature or planeswalker card from your graveyard.", False),
    ("Exile the top three cards of your library.", False),
    ("Exile this spell.", False),
    ("As an additional cost to cast this spell, exile a creature card from your hand.", False),
    ("Return target permanent to its owner's hand.", False),
    ("Target creature gets -3/-3 until end of turn.", False),
    ("Target opponent sacrifices a creature.", False),
    ("Example deals 3 damage to each opponent.", False),
    ("Example deals 3 damage to target creature you control.", False),
    ("Prevent all damage that would be dealt to target creature this turn.", False),
    ("The next time a source would deal damage to target creature, prevent that damage.", False),
])
def test_removal_uses_the_cards_explicit_definition(text, expected):
    assert matches(_printed(text), "removal") is expected


def test_removal_must_be_an_instant_or_sorcery_even_with_matching_abilities():
    assert not matches(_printed("{T}: Destroy target creature.", "Creature — Wizard"), "removal")


@pytest.mark.parametrize("mv,expected", [(0, False), (5, False), (6, True), (12, True)])
def test_win_condition_uses_printed_mana_value(mv, expected):
    assert matches(_printed("This spell costs {5} less to cast.", mv=mv), "win_condition") is expected


def _board(names=()):
    engine = game(library=0)
    source = card(engine, NAME)
    player = engine.state.player_by_id("p1")
    objects = [card(engine, name, zone=Zone.LIBRARY) for name in reversed(names)]
    return engine, source, player, list(reversed(objects))


@pytest.mark.parametrize("category,names,hit", [
    ("mana_base", ["Lightning Bolt", "Forest", "Opt"], "Forest"),
    ("removal", ["Opt", "Lightning Bolt", "Forest"], "Lightning Bolt"),
    ("win_condition", ["Forest", "Optimus Prime, Hero", "Opt"], "Optimus Prime, Hero // Optimus Prime, Autobot Leader"),
])
def test_each_category_replaces_draw_with_reveal_and_hand_move(category, names, hit):
    engine, source, player, objects = _board(names)
    engine.rules.draw(player)
    pending = engine.state.pending_choice
    assert {option["id"] for option in pending["options"]} == {"decline", "mana_base", "removal", "win_condition"}
    engine.resolve_pending_choice(category)
    assert len(player.hand) == 1 and player.hand[0].name == hit
    assert not any(e.type == EventType.DRAW for e in engine.state.events_this_turn())
    assert objects[-1] == player.library[-1]
    assert not player.exile


def test_declining_draws_normally_and_does_not_reoffer_the_same_replacement():
    engine, source, player, objects = _board(["Opt", "Forest"])
    engine.rules.draw(player)
    engine.resolve_pending_choice("decline")
    assert player.hand == [objects[0]] and engine.state.pending_choice is None
    assert sum(e.type == EventType.DRAW for e in engine.state.events_this_turn()) == 1


def test_each_draw_in_a_multidraw_can_choose_a_different_category():
    engine, source, player, objects = _board(["Forest", "Lightning Bolt", "Opt"])
    engine.rules.draw(player, 2)
    engine.resolve_pending_choice("mana_base")
    assert engine.state.pending_choice["kind"] == "optional_draw_dig"
    engine.resolve_pending_choice("removal")
    assert set(o.name for o in player.hand) == {"Forest", "Lightning Bolt"}
    assert engine.state.pending_choice is None


@pytest.mark.parametrize("names", [[], ["Forest", "Island"]])
def test_missing_category_does_not_attempt_an_empty_draw(names):
    engine, source, player, objects = _board(names)
    engine.rules.draw(player)
    engine.resolve_pending_choice("removal")
    assert not player.hand and not player.attempted_draw_from_empty and not player.has_lost
    assert set(o.instance_id for o in player.library) == {o.instance_id for o in objects}


def test_random_bottom_order_and_pending_choice_survive_clone():
    engine, source, player, objects = _board(["Opt", "Pacifism", "Grizzly Bears", "Sol Ring", "Island"])
    engine.rules.draw(player)
    clone = GameEngine(engine.state.clone())
    engine.resolve_pending_choice("mana_base")
    clone.resolve_pending_choice("mana_base")
    other = clone.state.player_by_id("p1")
    assert player.hand[0].name == other.hand[0].name == "Sol Ring"
    assert [o.instance_id for o in player.library] == [o.instance_id for o in other.library]
    assert player.library[-1].name == "Island"
    assert {o.name for o in player.library[:-1]} == {"Opt", "Pacifism", "Grizzly Bears"}
    assert engine.state.rng_counter == clone.state.rng_counter


def test_opponent_draw_is_not_replaced():
    engine, source, player, objects = _board()
    opponent = engine.state.player_by_id("p2")
    top = card(engine, "Opt", player="p2", zone=Zone.LIBRARY)
    engine.rules.draw(opponent)
    assert opponent.hand == [top] and engine.state.pending_choice is None


def test_invalid_category_keeps_the_decision_pending():
    engine, source, player, objects = _board(["Forest"])
    engine.rules.draw(player)
    with pytest.raises(ValueError):
        engine.resolve_pending_choice("creature")
    assert engine.state.pending_choice["kind"] == "optional_draw_dig" and not player.hand


def test_catalogue_specs_are_fresh_and_reminder_text_is_not_a_mana_ability():
    from mtg_analyzer.game.card_registry import specs_for
    engine, source, player, objects = _board()
    first, second = specs_for(source.card), specs_for(source.card)
    assert first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    assert len(source.replacement_effects) == 1
    assert not matches(source.card, "mana_base")
