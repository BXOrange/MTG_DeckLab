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
        is_instant="instant" in type_line.lower(), is_sorcery="sorcery" in type_line.lower(),
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


def test_battlefield_thaumaturge_discounts_one_per_creature_targeted():
    engine, player = two_player_game()
    thaum = battlefield_object(
        engine, player.id, "Battlefield Thaumaturge", "Creature — Human Wizard",
        is_creature=True, power=1, toughness=3,
    )
    bind_from_catalogue(thaum)
    bear_a = battlefield_object(engine, "p2", "Bear A", "Creature — Bear", is_creature=True, power=2, toughness=2)
    bear_b = battlefield_object(engine, "p2", "Bear B", "Creature — Bear", is_creature=True, power=2, toughness=2)
    land = battlefield_object(engine, "p2", "Plains", "Land", is_land=True)
    spell = _spell(player, "Two Bolts", "Instant", "{2}{R}", 3, "R")
    creature_spell = _spell(player, "Fat Bear", "Creature — Bear", "{2}{G}", 3, "G")

    cost = lambda obj, targets: continuous.cost_reduction_for(engine.state, player, obj, targets)[0]
    assert cost(spell, [bear_a, bear_b]) == 2
    assert cost(spell, [bear_a, land]) == 1  # only creatures count
    assert cost(spell, [land]) == 0
    assert cost(creature_spell, [bear_a]) == 0  # instants and sorceries only


def test_sygg_draws_at_end_step_only_after_an_opponent_lost_3_life():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Sygg, River Cutthroat")
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    sygg = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    sygg.controller_id = "p1"
    bind_from_catalogue(sygg)
    engine.state.add_to_battlefield(sygg)
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    for i in range(2):
        p1.library.append(GameObject(Card(id=f"F{i}", name=f"Filler {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))

    engine.rules.lose_life(p2, 2)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and not engine.state.stack  # 2 < 3

    engine.rules.lose_life(p2, 1)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    _answer_may(engine)
    assert len(p1.hand) == 1


def test_case_of_the_ransacked_lab_solves_after_four_instants_or_sorceries():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Case of the Ransacked Lab")
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    case = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    case.controller_id = "p1"
    bind_from_catalogue(case)
    engine.state.add_to_battlefield(case)
    p1 = engine.state.player_by_id("p1")

    def cast(n):
        for i in range(n):
            engine.state.fire_event(GameEvent(
                EventType.SPELL_CAST, player_id="p1", object=f"Bolt {i}",
                object_types=["instant"], mana_value=1,
            ))

    def end_step():
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending", player_id="p1"))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    cast(3)
    end_step()
    assert not case.is_solved  # only 3 this turn

    cast(1)
    end_step()
    assert case.is_solved


def _fandaniel_game(opp_creatures):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.events import EventType, GameEvent
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Fandaniel, Telophoroi Ascian")
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    fandaniel = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    fandaniel.controller_id = "p1"
    bind_from_catalogue(fandaniel)
    engine.state.add_to_battlefield(fandaniel)
    p1 = engine.state.player_by_id("p1")
    for i in range(3):  # two instants/sorceries and a creature in p1's graveyard
        type_line = "Creature — Bear" if i == 2 else "Instant"
        p1.graveyard.append(GameObject(
            Card(id=f"G{i}", name=f"Grave {i}", type_line=type_line, is_instant=i < 2, is_creature=i == 2),
            owner_id="p1", zone=Zone.GRAVEYARD,
        ))
    victims = [
        battlefield_object(engine, "p2", f"Bear {i}", "Creature — Bear", is_creature=True, power=2, toughness=2)
        for i in range(opp_creatures)
    ]
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending", player_id="p1"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine, victims


def test_fandaniel_opponent_who_declines_loses_two_life_per_instant_or_sorcery():
    engine, victims = _fandaniel_game(opp_creatures=1)
    choice = engine.state.pending_choice
    assert choice is not None
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 16  # 2 instants x 2
    assert victims[0] in engine.state.battlefield


def test_fandaniel_opponent_who_sacrifices_keeps_their_life():
    engine, victims = _fandaniel_game(opp_creatures=1)
    choice = engine.state.pending_choice
    assert choice is not None
    answer = next(o["id"] for o in choice["options"] if o["id"] != "decline")
    engine.resolve_pending_choice(answer)
    for _ in range(3):
        if engine.state.pending_choice is None:
            break
        pc = engine.state.pending_choice
        engine.resolve_pending_choice(pc["options"][0]["id"])
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 20
    assert victims[0] not in engine.state.battlefield


def test_leadership_vacuum_sends_the_targets_commanders_home_and_draws():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    vacuum = CardDatabase(DB_PATH).get_card("Leadership Vacuum")
    engine = GameEngine.new_game([("p1", "A", [vacuum]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for i in range(3):
        engine.state.player_by_id("p1").library.append(GameObject(
            Card(id=f"L{i}", name=f"Library {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY,
        ))
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    commander = battlefield_object(
        engine, "p2", "Their Commander", "Legendary Creature — Bear", is_creature=True, power=3, toughness=3,
    )
    commander.is_commander = True
    commander.counters["+1/+1"] = 2
    bystander = battlefield_object(engine, "p2", "Bystander", "Creature — Bear", is_creature=True, power=1, toughness=1)
    own = battlefield_object(engine, "p1", "My Commander", "Legendary Creature — Bear", is_creature=True, power=1, toughness=1)
    own.is_commander = True

    spell = next(o for o in p1.hand if o.name == "Leadership Vacuum")
    hand_before = len(p1.hand)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    engine.cast_spell(p1, spell, targets=[p2])
    engine.resolve_until_stable()

    assert commander not in engine.state.battlefield and commander in p2.command
    assert not commander.counters  # RULE 400.7: a new object
    assert bystander in engine.state.battlefield  # not a commander
    assert own in engine.state.battlefield  # only the target player's commanders
    assert len(p1.hand) == hand_before  # -1 for the cast spell, +1 for the draw


def _real_game(*deck_names):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    db = CardDatabase(DB_PATH)
    engine = GameEngine.new_game(
        [("p1", "A", [db.get_card(n) for n in deck_names]), ("p2", "B", [])],
        starting_hand=len(deck_names), starting_life=20,
    )
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.player_by_id("p1")


def test_dragons_prey_costs_two_more_only_when_it_targets_a_dragon():
    engine, p1 = _real_game("Dragon's Prey")
    prey = p1.hand[0]
    dragon = battlefield_object(engine, "p2", "Test Dragon", "Creature — Dragon", is_creature=True, power=5, toughness=5)
    bear = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    base = engine.effective_cast_cost(p1, prey).converted_mana_cost  # offer-time probe: no targets chosen
    assert engine.effective_cast_cost(p1, prey, targets=[bear]).converted_mana_cost == base
    assert engine.effective_cast_cost(p1, prey, targets=[dragon]).converted_mana_cost == base + 2


def test_defiler_of_dreams_pays_life_for_blue_and_draws_only_for_blue_permanent_spells():
    engine, p1 = _real_game()
    defiler = battlefield_object(engine, "p1", "Defiler of Dreams", "Creature — Phyrexian Wurm", is_creature=True, power=6, toughness=6)
    bind_from_catalogue(defiler)

    def hand_card(name, type_line, **kw):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}{U}", converted_mana_cost=2,
                 color_identity={"U"}, **kw),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.hand.append(obj)
        return obj

    for i in range(3):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    trick = hand_card("Blue Trick", "Instant")
    cub = hand_card("Blue Cub", "Creature — Fish", is_creature=True, power=1, toughness=1)
    p1.mana_pool.add_many({"C": 1})
    life, hand_before = p1.life, len(p1.hand)
    assert not engine.can_cast(p1, trick)  # no life option for an instant
    engine.cast_spell(p1, cub)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert cub.zone == Zone.BATTLEFIELD and p1.life == life - 2  # {U} paid with 2 life
    assert len(p1.hand) == hand_before - 1 + 1  # the cub left the hand, the trigger drew a card


def test_baral_loots_when_a_spell_you_control_counters_a_spell():
    engine, p1 = _real_game("Power Sink")
    baral = battlefield_object(engine, "p1", "Baral, Chief of Compliance", "Legendary Creature — Human Wizard", is_creature=True, power=1, toughness=3)
    bind_from_catalogue(baral)
    bear = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", mana_cost_string="{1}", converted_mana_cost=1,
             is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.hand.append(bear)
    for i in range(3):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"C": 1})
    engine.cast_spell(p1, bear)
    p1.mana_pool.add_many({"U": 2, "C": 1})  # Power Sink {X}{U}{U} costs {1} less with Baral: X = 2 -> {1}{U}{U}
    engine.cast_spell(p1, p1.hand[0], x=2, targets=[bear])  # the bear's controller (p1) cannot pay {2}
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert bear.zone == Zone.GRAVEYARD  # countered by my own Power Sink
    choice = engine.state.pending_choice
    assert choice is not None  # "you may draw a card. If you do, discard a card."
    hand_before = len(p1.hand)
    engine.resolve_pending_choice(choice["options"][0]["id"])
    engine.resolve_until_stable()
    while engine.state.pending_choice:  # the discard
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert len(p1.hand) == hand_before  # drew one, discarded one
    assert len(p1.library) == 2  # exactly one card was drawn


def test_emet_selch_grants_a_graveyard_cast_once_per_turn_when_an_opponent_loses_life():
    engine, p1 = _real_game()
    p2 = engine.state.player_by_id("p2")
    emet = battlefield_object(engine, "p1", "Emet-Selch of the Third Seat", "Legendary Creature — Elf Wizard", is_creature=True, power=2, toughness=3)
    bind_from_catalogue(emet)

    def graveyard_spell(name, type_line, **flags):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, mana_cost_string="{2}{R}", converted_mana_cost=3,
                 color_identity={"R"}, **flags),
            owner_id="p1", zone=Zone.GRAVEYARD,
        )
        p1.graveyard.append(obj)
        return obj

    burn = graveyard_spell("Big Burn", "Sorcery", is_sorcery=True)
    other = graveyard_spell("Other Burn", "Instant", is_instant=True)
    assert engine.effective_cast_cost(p1, burn).converted_mana_cost == 1  # "spells you cast from your graveyard cost {2} less"

    engine.rules.lose_life(p2, 3)
    engine.rules.put_triggers_on_stack()
    choice = engine.state.pending_choice
    assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"Big Burn", "Other Burn"}
    engine.resolve_pending_choice(str(burn.instance_id))
    engine.resolve_until_stable()
    assert burn.instance_id in engine.state.temp_flashback_grants  # may be cast from the graveyard this turn
    assert other.instance_id not in engine.state.temp_flashback_grants

    engine.rules.lose_life(p2, 2)  # "do this only once each turn"
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and not engine.state.stack
    engine.rules.lose_life(p1, 1)  # my own life loss never triggers it
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and not engine.state.stack
