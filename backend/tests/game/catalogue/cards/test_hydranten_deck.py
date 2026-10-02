"""Hand-authored cards of the saved "Hydranten" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
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


def _icy_blast_game(my_power):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Icy Blast")
    engine = GameEngine.new_game([("p1", "A", [card]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    battlefield_object(engine, "p1", "My Beast", "Creature — Beast", is_creature=True, power=my_power, toughness=my_power)
    victims = [
        battlefield_object(engine, "p2", f"Victim {i}", "Creature — Bear", is_creature=True, power=2, toughness=2)
        for i in range(2)
    ]
    engine.recompute_continuous_effects()
    p1.mana_pool.add_many({"U": 1, "C": 2})  # {X}{U}, X = 2
    engine.cast_spell(p1, p1.hand[0], targets=victims, x=2)
    engine.resolve_until_stable()
    return victims


def test_icy_blast_taps_x_creatures_and_freezes_them_only_with_ferocious():
    ferocious = _icy_blast_game(my_power=4)
    assert all(v.tapped and v.skip_next_untap for v in ferocious)

    plain = _icy_blast_game(my_power=3)
    assert all(v.tapped and not v.skip_next_untap for v in plain)


def test_simic_ascendancy_counts_plus_one_counters_on_my_creatures_and_wins_at_twenty():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, player = two_player_game()
    ascendancy = battlefield_object(engine, "p1", "Simic Ascendancy", "Enchantment")
    bind_from_catalogue(ascendancy)
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)

    engine.rules.add_counters(mine, 3, "+1/+1")
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert ascendancy.counters.get("growth", 0) == 3  # "that many"

    engine.rules.add_counters(theirs, 2, "+1/+1")  # not a creature I control
    engine.rules.add_counters(mine, 1, "-1/-1")  # not a +1/+1 counter
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert ascendancy.counters.get("growth", 0) == 3

    def upkeep():
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning", player_id="p1"))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    ascendancy.counters["growth"] = 19
    upkeep()
    assert not engine.state.game_over
    ascendancy.counters["growth"] = 20
    upkeep()
    assert engine.state.game_over and engine.state.winner_id == "p1"


def test_geometers_arthropod_looks_at_the_top_x_cards_when_an_x_spell_is_cast():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    db = CardDatabase(DB_PATH)
    engine = GameEngine.new_game(
        [("p1", "A", [db.get_card("Genesis Wave")]), ("p2", "B", [])], starting_hand=1, starting_life=20,
    )
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    arthropod = battlefield_object(engine, "p1", "Geometer's Arthropod", "Creature — Insect", is_creature=True, power=2, toughness=3)
    bind_from_catalogue(arthropod)
    p1.library.clear()
    cards = {}
    for name in ["Bottom", "Third", "Second", "First"]:  # the end of the list is the top
        cards[name] = GameObject(Card(id=name, name=name, type_line="Artifact"), owner_id="p1", zone=Zone.LIBRARY)
        p1.library.append(cards[name])
    p1.mana_pool.add_many({"G": 3, "C": 2})
    engine.cast_spell(p1, p1.hand[0], x=2)  # a {X}{G}{G}{G} spell with X = 2
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"First", "Second"}  # exactly the top X
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == "Second"))
    engine.resolve_until_stable()
    assert cards["Second"] in p1.hand
    assert p1.library[0] is cards["First"]  # the unpicked card went to the bottom of the library (index 0)


def _power_sink_setup(pool_after_cast):
    """p1 casts a 1-mana bear, then Power Sink (X = 2) on it; p1 owns two untapped Forests."""
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    from mtg_analyzer.services.card_database import CardDatabase

    sink = CardDatabase(DB_PATH).get_card("Power Sink")
    engine = GameEngine.new_game([("p1", "A", [sink]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    forests = [
        battlefield_object(engine, "p1", f"Forest {i}", "Basic Land — Forest", is_land=True) for i in range(2)
    ]
    bear = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", mana_cost_string="{1}", converted_mana_cost=1,
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.hand.append(bear)
    p1.mana_pool.add_many({"C": 1})
    engine.cast_spell(p1, bear)
    p1.mana_pool.add_many({"U": 2, "C": 2})  # exactly {X}{U}{U} for X = 2
    engine.cast_spell(p1, p1.hand[0], x=2, targets=[bear])
    p1.mana_pool.add_many(pool_after_cast)  # what is left to pay the {X} with
    engine.resolve_until_stable()
    return engine, p1, bear, forests


def test_power_sink_taps_lands_and_empties_the_pool_when_the_controller_cannot_pay():
    engine, p1, bear, forests = _power_sink_setup({})
    assert bear.zone == Zone.GRAVEYARD  # countered: nothing left to pay {2}
    assert all(f.tapped for f in forests)
    assert p1.mana_pool.total() == 0


def test_power_sink_penalises_a_declined_payment_but_not_a_paid_one():
    engine, p1, bear, forests = _power_sink_setup({"C": 2, "G": 1})
    assert engine.state.pending_choice["kind"] == "counter_unless_pays"
    engine.resolve_pending_choice("decline")
    assert bear.zone == Zone.GRAVEYARD and all(f.tapped for f in forests) and p1.mana_pool.total() == 0

    engine, p1, bear, forests = _power_sink_setup({"C": 2, "G": 1})
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert bear.zone == Zone.BATTLEFIELD  # paid {2}: the bear resolves
    assert not any(f.tapped for f in forests) and p1.mana_pool.total() > 0  # no penalty: lands untapped, pool kept
