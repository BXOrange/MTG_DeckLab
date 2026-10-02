"""Hand-authored cards of the saved "Hydranten" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from tests.support.catalogue import battlefield_object, two_player_game


def _vigor_game():
    engine, player = two_player_game()
    vigor = battlefield_object(engine, "p1", "Primal Vigor", "Enchantment")
    bind_from_catalogue(vigor)
    return engine


def test_primal_vigor_doubles_every_players_tokens_and_plus_one_counters_on_any_creature():
    engine = _vigor_game()
    token = Card(id="Soldier", name="Soldier", type_line="Token Creature — Soldier", is_creature=True, power=1, toughness=1)
    assert len(engine.rules.create_token("p1", token, count=2)) == 4  # mine
    assert len(engine.rules.create_token("p2", token, count=1)) == 2  # an opponent's too

    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.rules.add_counters(mine, 1, "+1/+1")
    engine.rules.add_counters(theirs, 2, "+1/+1")
    assert mine.counters["+1/+1"] == 2 and theirs.counters["+1/+1"] == 4

    engine.rules.add_counters(mine, 1, "-1/-1")  # other counter kinds are not doubled
    assert mine.counters["-1/-1"] == 1


def test_herald_of_secret_streams_makes_only_countered_creatures_unblockable():
    engine, player = two_player_game()
    defender = engine.state.player_by_id("p2")
    herald = battlefield_object(
        engine, "p1", "Herald of Secret Streams", "Creature — Merfolk", is_creature=True, power=2, toughness=3,
    )
    bind_from_catalogue(herald)
    countered = battlefield_object(engine, "p1", "Grown Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Blocker", "Creature — Bear", is_creature=True, power=2, toughness=2)
    for attacker in (countered, plain):
        attacker.attacking = True
        attacker.combat_defender = {"kind": "player", "id": "p2"}
    countered.counters["+1/+1"] = 1
    engine.recompute_continuous_effects()

    assert not engine.can_block(defender, theirs, countered)  # +1/+1 counter: can't be blocked
    assert engine.can_block(defender, theirs, plain)

    countered.counters["+1/+1"] = 0
    engine.recompute_continuous_effects()
    assert engine.can_block(defender, theirs, countered)  # the counter is the whole condition


def test_mana_reflection_doubles_mana_from_tapping_only_for_its_controller():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    opponent = engine.state.player_by_id("p2")
    reflection = battlefield_object(engine, "p1", "Mana Reflection", "Enchantment")
    bind_from_catalogue(reflection)
    forest_card = CardDatabase(DB_PATH).get_card("Forest")

    def forest_for(player_id):
        land = GameObject(forest_card, owner_id=player_id, zone=Zone.BATTLEFIELD)
        land.controller_id = player_id
        bind_from_catalogue(land)
        engine.state.add_to_battlefield(land)
        return land

    mine, theirs = forest_for("p1"), forest_for("p2")
    engine.tap_for_mana(player, mine)
    assert player.mana_pool.pool.get("G", 0) == 2
    engine.tap_for_mana(opponent, theirs)
    assert opponent.mana_pool.pool.get("G", 0) == 1  # not their Mana Reflection


def _mathemagics_game(x):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Mathemagics")
    engine = GameEngine.new_game([("p1", "A", [card]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    for i in range(20):
        p2.library.append(GameObject(Card(id=f"M{i}", name=f"Card {i}", type_line="Land"), owner_id="p2", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"U": 2, "C": 2 * x})  # {X}{X}{U}{U}
    engine.cast_spell(p1, p1.hand[0], targets=[p2], x=x)
    engine.resolve_until_stable()
    return p2


def test_mathemagics_draws_two_to_the_x_cards():
    assert len(_mathemagics_game(3).hand) == 8
    assert len(_mathemagics_game(0).hand) == 1  # 2^0


def test_power_of_clamps_its_exponent():
    from mtg_analyzer.game import effect_amounts

    assert effect_amounts.MAX_POWER_OF_EXPONENT == 30
    cls = type("C", (), {})
    ctx = cls()
    amount = {"kind": "fixed", "amount": 500, "power_of": 2}
    assert effect_amounts.amount_of(amount, ctx) == 2 ** 30
