"""Hand-authored cards of the saved "World Shaper" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def _battlefield_card(engine, name, player_id="p1"):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player_id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player_id
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def test_eumidian_hatchery_collects_hatchling_counters_and_hatches_one_insect_each_when_it_dies():
    engine, p1, p2 = _game()
    hatchery = _battlefield_card(engine, "Eumidian Hatchery")
    life = p1.life
    for expected in (1, 2):
        hatchery.tapped = False
        engine.tap_for_mana(p1, hatchery)
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
        assert hatchery.counters.get("hatchling") == expected
    assert p1.life == life - 2  # "pay 1 life" each time

    engine.rules.destroy(hatchery)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    insects = [o for o in engine.state.battlefield if o.name == "Insect"]
    assert len(insects) == 2  # one per hatchling counter


def test_centaur_vinecrasher_enters_with_a_counter_per_land_card_in_all_graveyards():
    engine, p1, p2 = _game("Centaur Vinecrasher")
    for player, n in ((p1, 2), (p2, 3)):
        for i in range(n):
            player.graveyard.append(GameObject(
                Card(id=f"G{player.id}{i}", name=f"Land {player.id}{i}", type_line="Land", is_land=True),
                owner_id=player.id, zone=Zone.GRAVEYARD,
            ))
    p2.graveyard.append(GameObject(Card(id="Bolt", name="Bolt", type_line="Instant"), owner_id="p2", zone=Zone.GRAVEYARD))
    p1.mana_pool.add_many({"G": 2, "C": 4})
    centaur = p1.hand[0]
    engine.cast_spell(p1, centaur)
    engine.resolve_until_stable()
    assert centaur.zone == Zone.BATTLEFIELD and centaur.counters.get("+1/+1") == 5  # 2 + 3 lands, not the Bolt


def test_groundskeeper_returns_only_a_basic_land_card_from_the_graveyard():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, p1, p2 = _game()
    keeper = _battlefield_card(engine, "Groundskeeper")
    forest = GameObject(Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.GRAVEYARD)
    cave = GameObject(Card(id="C", name="Hidden Cave", type_line="Land", is_land=True), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.extend([forest, cave])
    pool = legal_targets(engine.state, "p1", TargetSpec(kind="graveyard_basic_land"), source=keeper)
    assert {o["name"] for o in pool} == {"Forest"}  # basic only
    keeper.summoning_sick = False
    p1.mana_pool.add_many({"G": 1, "C": 1})
    engine.activate_ability(p1, keeper, 0, targets=[forest])
    engine.resolve_until_stable()
    assert forest in p1.hand and cave in p1.graveyard


def test_formless_genesis_makes_an_x_x_shapeshifter_for_the_land_cards_in_my_graveyard():
    from mtg_analyzer.game import combat

    engine, p1, p2 = _game("Formless Genesis")
    for i in range(3):
        p1.graveyard.append(GameObject(Card(id=f"L{i}", name=f"Land {i}", type_line="Land", is_land=True), owner_id="p1", zone=Zone.GRAVEYARD))
    p1.graveyard.append(GameObject(Card(id="Bolt", name="Bolt", type_line="Instant"), owner_id="p1", zone=Zone.GRAVEYARD))
    p2.graveyard.append(GameObject(Card(id="OL", name="Their Land", type_line="Land", is_land=True), owner_id="p2", zone=Zone.GRAVEYARD))
    p1.mana_pool.add_many({"G": 2, "C": 8})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    tokens = [o for o in engine.state.battlefield if o.name == "Shapeshifter"]
    assert len(tokens) == 1
    token = tokens[0]
    assert (token.power, token.toughness) == (3, 3)  # my graveyard's three lands only
    assert combat.has(token, "deathtouch") and not token.colors


def test_multani_counts_lands_i_control_and_land_cards_in_my_graveyard():
    engine, p1, p2 = _game()
    multani = _battlefield_card(engine, "Multani, Yavimaya's Avatar")
    engine.recompute_continuous_effects()
    base = (multani.power, multani.toughness)
    for i in range(3):
        battlefield_object(engine, "p1", f"Forest {i}", "Basic Land — Forest", is_land=True)
    battlefield_object(engine, "p2", "Their Island", "Basic Land — Island", is_land=True)  # not mine
    for i in range(2):
        p1.graveyard.append(GameObject(Card(id=f"G{i}", name=f"Dead Land {i}", type_line="Land", is_land=True), owner_id="p1", zone=Zone.GRAVEYARD))
    p2.graveyard.append(GameObject(Card(id="OG", name="Their Dead Land", type_line="Land", is_land=True), owner_id="p2", zone=Zone.GRAVEYARD))
    engine.recompute_continuous_effects()
    assert (multani.power, multani.toughness) == (base[0] + 5, base[1] + 5)  # 3 lands + 2 graveyard lands (mine only)


def test_worldsouls_rage_deals_x_and_puts_up_to_x_lands_from_hand_and_graveyard_tapped():
    engine, p1, p2 = _game("Worldsoul's Rage")
    hand_land = GameObject(Card(id="HL", name="Hand Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.HAND)
    grave_land = GameObject(Card(id="GL", name="Grave Mountain", type_line="Basic Land — Mountain", is_land=True), owner_id="p1", zone=Zone.GRAVEYARD)
    extra = GameObject(Card(id="XL", name="Extra Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.HAND)
    p1.hand.extend([hand_land, extra])
    p1.graveyard.append(grave_land)
    p1.mana_pool.add_many({"R": 1, "G": 1, "C": 3})
    life = p2.life
    engine.cast_spell(p1, p1.hand[0], x=2, targets=[p2])
    engine.resolve_until_stable()
    assert p2.life == life - 2  # X damage to the chosen target
    for name in ("Grave Mountain", "Hand Forest"):  # "up to X": two picks (X = 2), from either zone
        choice = engine.state.pending_choice
        assert choice is not None
        option = next(o for o in choice["options"] if o.get("label") == name)
        engine.resolve_pending_choice(option["id"])
        engine.resolve_until_stable()
    assert grave_land.zone == Zone.BATTLEFIELD and hand_land.zone == Zone.BATTLEFIELD
    assert grave_land.tapped and hand_land.tapped  # "onto the battlefield tapped"
    assert extra.zone == Zone.HAND  # only X = 2 lands


def test_horizon_explorer_lands_enter_untapped_and_attacking_makes_a_lander():
    engine, p1, p2 = _game("Tranquil Cove")
    explorer = _battlefield_card(engine, "Horizon Explorer")
    explorer.summoning_sick = False
    cove = p1.hand[0]  # a land that enters tapped on its own
    engine.play_land(p1, cove)
    assert cove.zone == Zone.BATTLEFIELD and not cove.tapped  # Horizon Explorer overrides the tapped entry

    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": explorer, "defender": engine.legal_defenders_for(p1)[0]}])
    engine._fire_player_attacked_events()  # what the turn loop does once attackers are declared (RULE 506.4)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    landers = [o for o in engine.state.battlefield if o.name == "Lander"]
    assert len(landers) == 1 and landers[0].card.is_artifact


def test_without_horizon_explorer_the_same_land_enters_tapped():
    engine, p1, p2 = _game("Tranquil Cove")
    cove = p1.hand[0]
    engine.play_land(p1, cove)
    assert cove.tapped


def test_the_lander_token_fetches_a_basic_land_tapped_when_sacrificed():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    explorer = _battlefield_card(engine, "Horizon Explorer")
    forest = GameObject(Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    other = GameObject(Card(id="N", name="Nonbasic", type_line="Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([other, forest])
    engine.state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1", defending_player_id="p2", count=1))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    lander = next(o for o in engine.state.battlefield if o.name == "Lander")
    lander.summoning_sick = False
    p1.mana_pool.add_many({"C": 2})
    engine.activate_ability(p1, lander, 0)
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"Forest"}  # basic lands only
        engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == "Forest"))
        engine.resolve_until_stable()
    assert forest.zone == Zone.BATTLEFIELD and forest.tapped and lander.zone != Zone.BATTLEFIELD


def _graveyard_lands(player, n):
    for i in range(n):
        player.graveyard.append(GameObject(
            Card(id=f"GL{player.id}{i}", name=f"Dead Land {i}", type_line="Land", is_land=True),
            owner_id=player.id, zone=Zone.GRAVEYARD,
        ))


def _sacrifice_a_land(engine, p1):
    land = battlefield_object(engine, "p1", "Doomed Land", "Land", is_land=True)
    engine.rules.put_into_graveyard(land)  # the single choke point every genuine sacrifice funnels through
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def test_scouring_swarm_makes_an_insect_below_seven_land_cards_and_a_copy_at_seven():
    engine, p1, p2 = _game()
    swarm = _battlefield_card(engine, "Scouring Swarm")
    _graveyard_lands(p1, 5)  # the sacrificed land will be the 6th: not enough
    _sacrifice_a_land(engine, p1)
    insects = [o for o in engine.state.battlefield if o.name == "Insect"]
    assert len(insects) == 1 and insects[0].tapped and (insects[0].power, insects[0].toughness) == (1, 1)
    assert [o.name for o in engine.state.battlefield].count("Scouring Swarm") == 1

    _sacrifice_a_land(engine, p1)  # the 7th land card in the graveyard
    copies = [o for o in engine.state.battlefield if o.name == "Scouring Swarm" and o is not swarm]
    assert len(copies) == 1 and copies[0].tapped
    assert [o.name for o in engine.state.battlefield].count("Insect") == 1  # no second Insect


def test_szarel_puts_counters_equal_to_its_power_when_i_sacrifice_another_nontoken_permanent():
    engine, p1, p2 = _game()
    szarel = _battlefield_card(engine, "Szarel, Genesis Shepherd")
    engine.recompute_continuous_effects()
    power = szarel.power
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    rock = battlefield_object(engine, "p1", "Rock", "Artifact")
    engine.rules.put_into_graveyard(rock)
    engine.rules.put_triggers_on_stack()
    choice = engine.state.pending_choice
    assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"Bear"}  # another creature, not Szarel
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == "Bear"))
    engine.resolve_until_stable()
    assert bear.counters.get("+1/+1") == power and power > 0
