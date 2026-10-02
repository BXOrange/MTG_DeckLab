"""Hand-authored cards of the saved "yshtola" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import battlefield_object, two_player_game


def _spell(player, name, type_line, cost, cmc, colors):
    card = Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=cmc, color_identity=set(colors),
        is_creature="creature" in type_line.lower(),
    )
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def test_stormscape_familiar_discounts_white_and_black_spells_only():
    engine, player = two_player_game()
    familiar = battlefield_object(
        engine, player.id, "Stormscape Familiar", "Creature — Bird", is_creature=True, power=1, toughness=1,
    )
    bind_from_catalogue(familiar)
    assert is_registered("Stormscape Familiar")
    white = _spell(player, "White Spell", "Sorcery", "{2}{W}", 3, "W")
    black = _spell(player, "Black Spell", "Creature — Bear", "{2}{B}", 3, "B")
    green = _spell(player, "Green Spell", "Sorcery", "{2}{G}", 3, "G")
    assert continuous.cost_reduction_for(engine.state, player, white)[0] == 1
    assert continuous.cost_reduction_for(engine.state, player, black)[0] == 1
    assert continuous.cost_reduction_for(engine.state, player, green)[0] == 0


def test_generous_gift_destroys_and_gives_its_controller_an_elephant():
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    gift = CardDatabase(DB_PATH).get_card("Generous Gift")
    engine = GameEngine.new_game([("p1", "A", [gift]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    victim = battlefield_object(engine, "p2", "Victim", "Enchantment")
    p1.mana_pool.add_many({"W": 1, "C": 2})
    engine.cast_spell(p1, p1.hand[0], targets=[victim])
    engine.resolve_until_stable()

    assert victim not in engine.state.battlefield
    elephants = [o for o in engine.state.permanents_controlled_by("p2") if "Elephant" in (o.card.type_line or "")]
    assert len(elephants) == 1 and elephants[0].power == 3 and elephants[0].toughness == 3


def test_faebloom_trick_makes_two_fliers_then_taps_an_opposing_creature():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    trick = CardDatabase(DB_PATH).get_card("Faebloom Trick")
    engine = GameEngine.new_game([("p1", "A", [trick]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    bear = battlefield_object(engine, "p2", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, p1.hand[0], targets=[])
    engine.resolve_until_stable()
    # RULE 603.12: the reflexive trigger's target is picked as it goes on the stack.
    choice = engine.state.pending_choice
    assert choice["kind"] == "trigger_target"
    assert [o["instance_id"] for o in choice["options"]] == [bear.instance_id]
    engine.resolve_pending_choice(choice["options"][0]["id"])
    engine.resolve_until_stable()

    faeries = [o for o in engine.state.permanents_controlled_by("p1") if "Faerie" in (o.card.type_line or "")]
    assert len(faeries) == 2
    assert bear.tapped


def _bloodchief_ascension_game():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Bloodchief Ascension")
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    ascension = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ascension.controller_id = "p1"
    bind_from_catalogue(ascension)
    engine.state.add_to_battlefield(ascension)
    return engine, ascension


def _answer_may(engine, answer="do"):
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()


def test_bloodchief_ascension_counts_up_only_after_an_opponent_lost_2_life():
    from mtg_analyzer.models.game.events import GameEvent, EventType

    engine, ascension = _bloodchief_ascension_game()
    p2 = engine.state.player_by_id("p2")
    engine.rules.lose_life(p2, 1)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and not engine.state.stack  # intervening-if false

    engine.rules.lose_life(p2, 1)  # 2 lost in total this turn
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    _answer_may(engine)
    assert ascension.counters.get("quest", 0) == 1


def test_bloodchief_ascension_drains_per_opponent_card_once_it_has_three_quest_counters():
    engine, ascension = _bloodchief_ascension_game()
    victim = battlefield_object(engine, "p2", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)

    engine.state.announce_graveyard_arrivals()  # first call only takes the baseline
    ascension.counters["quest"] = 2
    engine.rules.destroy(victim)
    engine.state.announce_graveyard_arrivals()
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None  # only 2 counters

    ascension.counters["quest"] = 3
    victim2 = battlefield_object(engine, "p2", "Bear 2", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.rules.destroy(victim2)
    engine.state.announce_graveyard_arrivals()
    engine.rules.put_triggers_on_stack()
    _answer_may(engine)
    assert engine.state.player_by_id("p2").life == 18
    assert engine.state.player_by_id("p1").life == 22
