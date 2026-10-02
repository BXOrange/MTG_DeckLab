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


def test_mind_into_matter_draws_x_then_puts_a_cheap_permanent_in_tapped():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Mind into Matter")
    engine = GameEngine.new_game([("p1", "A", [card]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")

    def hand_card(name, type_line, cost, cmc, **kw):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=cmc, **kw),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.add_to_zone(obj, Zone.HAND)
        return obj

    cheap = hand_card("Cheap Bear", "Creature — Bear", "{1}{G}", 2, is_creature=True, power=2, toughness=2)
    dear = hand_card("Dear Dragon", "Creature — Dragon", "{4}{R}{R}", 6, is_creature=True, power=5, toughness=5)
    for i in range(3):
        p1.library.append(GameObject(Card(id=f"D{i}", name=f"Drawn {i}", type_line="Instant"), owner_id="p1", zone=Zone.LIBRARY))

    p1.mana_pool.add_many({"G": 1, "U": 1, "C": 2})  # X = 2
    engine.cast_spell(p1, next(o for o in p1.hand if o.name == "Mind into Matter"), x=2)
    engine.resolve_until_stable()

    choice = engine.state.pending_choice
    assert choice is not None
    ids = [o.get("instance_id") for o in choice["options"]]
    assert cheap.instance_id in ids and dear.instance_id not in ids  # mana value 2 or less
    pick = next(o for o in choice["options"] if o.get("instance_id") == cheap.instance_id)
    engine.resolve_pending_choice(pick["id"])
    engine.resolve_until_stable()

    assert cheap in engine.state.battlefield and cheap.tapped
    assert dear in p1.hand
    assert sum(1 for o in p1.hand if o.name.startswith("Drawn")) == 2  # drew X cards


def test_kodama_of_the_west_tree_modified_creatures_trample_and_fetch_a_basic_on_damage():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    p2 = engine.state.player_by_id("p2")
    kodama = battlefield_object(
        engine, "p1", "Kodama of the West Tree", "Legendary Creature — Spirit", is_creature=True, power=1, toughness=3,
    )
    bind_from_catalogue(kodama)
    modified = battlefield_object(engine, "p1", "Grown Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    modified.counters["+1/+1"] = 1
    forest = CardDatabase(DB_PATH).get_card("Forest")
    for _ in range(2):
        player.library.append(GameObject(forest, owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()
    assert "trample" in modified.granted_keywords and "trample" not in plain.granted_keywords

    engine.rules.deal_damage(p2, 2, source=plain, combat=True)
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and not engine.state.stack  # unmodified: nothing

    lands_before = len([o for o in engine.state.battlefield if o.is_land])
    engine.rules.deal_damage(p2, 3, source=modified, combat=True)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        engine.resolve_pending_choice(choice["options"][0]["id"])
        engine.resolve_until_stable()
    lands = [o for o in engine.state.battlefield if o.is_land]
    assert len(lands) == lands_before + 1 and lands[-1].tapped
