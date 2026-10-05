"""Hand-authored cards of the saved "World Shaper" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

import pytest

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
        assert hatchery.counters.get("hatchling") == expected
        engine.rules.put_triggers_on_stack()
        assert not engine.state.stack
        engine.resolve_until_stable()
        assert hatchery.counters.get("hatchling") == expected
    assert p1.life == life - 2  # "pay 1 life" each time

    engine.rules.destroy(hatchery)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    insects = [o for o in engine.state.battlefield if o.name == "Insect"]
    assert len(insects) == 2  # one per hatchling counter


@pytest.mark.parametrize("mode", ["decline_own", "decline_opponents", "sacrifice_matching"])
def test_braids_retains_all_sacrificed_types_for_each_opponents_choice(mode):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    p1, p2, p3 = engine.state.players
    for i in range(3):
        p1.library.append(GameObject(Card(id=str(i), name="Filler", type_line="Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    braids = _battlefield_card(engine, "Braids, Arisen Nightmare")
    own = battlefield_object(engine, "p1", "Construct", "Artifact Creature", is_creature=True, power=2, toughness=2)
    rock = battlefield_object(engine, "p2", "Rock", "Artifact")
    bear = battlefield_object(engine, "p3", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    battlefield_object(engine, "p2", "Land", "Land", is_land=True)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    engine.resolve_pending_choice("decline" if mode == "decline_own" else str(own.instance_id))
    engine.resolve_until_stable()
    if mode == "decline_own":
        assert own.zone == Zone.BATTLEFIELD and not engine.state.pending_choice
        assert p2.life == p3.life == 20 and not p1.hand
        return
    for player, permanent in ((p2, rock), (p3, bear)):
        if player is p3 and mode == "sacrifice_matching":
            assert rock.zone == Zone.BATTLEFIELD  # all choices precede the simultaneous sacrifices
        choice = engine.state.pending_choice
        assert choice["player_id"] == player.id
        assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {permanent.instance_id}
        engine.resolve_pending_choice("decline" if mode == "decline_opponents" else str(permanent.instance_id))
        engine.resolve_until_stable()
    assert own.zone == Zone.GRAVEYARD and braids.zone == Zone.BATTLEFIELD
    assert not engine.state.pending_choice
    assert (p2.life, p3.life, len(p1.hand)) == ((18, 18, 2) if mode == "decline_opponents" else (20, 20, 0))


def test_braids_can_sacrifice_itself_and_penalizes_an_opponent_without_a_matching_permanent():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    braids = _battlefield_card(engine, "Braids, Arisen Nightmare")
    battlefield_object(engine, "p2", "Rock", "Artifact")
    p1.library.append(GameObject(Card(id="f", name="Filler", type_line="Land", is_land=True), owner_id="p1", zone=Zone.LIBRARY))
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(braids.instance_id))
    engine.resolve_until_stable()
    assert braids.zone == Zone.GRAVEYARD
    assert p2.life == 18 and len(p1.hand) == 1
    assert not engine.state.pending_choice


@pytest.mark.parametrize("lands", [0, 1, 2])
@pytest.mark.parametrize("exile_replacement", [False, True])
def test_wastewaker_collects_both_choices_before_moving_cards_and_draws_for_lands(lands, exile_replacement):
    engine, p1, p2 = _game()
    wastewaker = _battlefield_card(engine, "Eumidian Wastewaker")
    wastewaker.summoning_sick = False
    if exile_replacement:
        _battlefield_card(engine, "Rest in Peace", "p2")
    for i in range(3):
        p1.library.append(GameObject(Card(id=str(i), name="Filler", type_line="Artifact"), owner_id="p1", zone=Zone.LIBRARY))
    discarded = GameObject(Card(id="hand", name="Hand card", type_line="Land" if lands else "Artifact",
                                is_land=lands > 0), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(discarded)
    land = battlefield_object(engine, "p2", "Land", "Land", is_land=True)
    rock = battlefield_object(engine, "p2", "Rock", "Artifact")
    sacrificed = land if lands == 2 else rock
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": wastewaker, "defender": {"kind": "player", "id": "p2"}}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice(str(discarded.instance_id))
    engine.resolve_until_stable()
    assert discarded.zone == Zone.HAND and sacrificed.zone == Zone.BATTLEFIELD
    assert len(p1.library) == 3
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice(str(sacrificed.instance_id))
    engine.resolve_until_stable()
    assert discarded.zone == sacrificed.zone == (Zone.EXILE if exile_replacement else Zone.GRAVEYARD)
    drawn = 0 if exile_replacement else lands
    assert len(p1.hand) == drawn and len(p1.library) == 3 - drawn
    assert "encore" in wastewaker.parametric_keywords


def test_wastewaker_asks_the_active_player_first_when_the_second_seat_attacks():
    engine, p1, p2 = _game()
    engine.state.active_player_index = 1
    wastewaker = _battlefield_card(engine, "Eumidian Wastewaker", "p2")
    wastewaker.summoning_sick = False
    rock = battlefield_object(engine, "p1", "Rock", "Artifact")
    for player in (p1, p2):
        player.hand.append(GameObject(Card(id=player.id, name="Card", type_line="Artifact"), owner_id=player.id, zone=Zone.HAND))
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p2, [{"attacker": wastewaker, "defender": {"kind": "player", "id": "p1"}}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice(str(p2.hand[0].instance_id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p1"
    engine.resolve_pending_choice(str(rock.instance_id))
    engine.resolve_until_stable()
    assert not engine.state.pending_choice and rock.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("specific", [False, True])
def test_discard_paths_apply_graveyard_exile_replacement(specific):
    engine, p1, p2 = _game()
    _battlefield_card(engine, "Rest in Peace", "p2")
    card = GameObject(Card(id="card", name="Card", type_line="Land", is_land=True), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(card)
    if specific:
        engine.rules.discard_specific(card)
    else:
        engine.rules.discard(p1, 1)
    assert card in p1.exile and card not in p1.hand and card not in p1.graveyard


def test_evendo_exile_permission_is_linked_and_gated_by_turn_and_nontoken_sacrifice():
    engine, p1, p2 = _game()
    brushrazer = _battlefield_card(engine, "Evendo Brushrazer")
    forest = GameObject(Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.LIBRARY)
    rock = GameObject(Card(id="R", name="Rock", type_line="Artifact", mana_cost_string="{1}"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([rock, forest])
    token = battlefield_object(engine, "p1", "Token", "Artifact")
    token.is_token = True
    engine.rules.put_into_graveyard(token)
    engine.rules.put_triggers_on_stack()
    assert not engine.state.stack
    land = battlefield_object(engine, "p1", "Land", "Land", is_land=True)
    engine.rules.put_into_graveyard(land)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert forest in p1.exile and rock in p1.library
    assert engine.can_play_land(p1, forest)
    engine.state.active_player_index = 1
    assert not engine.can_play_land(p1, forest)
    engine.state.active_player_index = 0
    engine.rules.destroy(brushrazer)
    assert not engine.can_play_land(p1, forest)


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


def test_god_eternal_bontu_sacrifices_any_number_of_others_to_draw_that_many_then_returns_third_from_top():
    engine, p1, p2 = _game("God-Eternal Bontu")
    keep = battlefield_object(engine, "p1", "Keeper", "Artifact")
    sac_a = battlefield_object(engine, "p1", "Fodder A", "Artifact")
    sac_b = battlefield_object(engine, "p1", "Fodder B", "Artifact")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    bontu = p1.hand[0]
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, bontu)
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    hand_before = len(p1.hand)
    for victim in (sac_a, sac_b):
        choice = engine.state.pending_choice
        assert choice is not None
        assert bontu.name not in {o["label"] for o in choice["options"] if "instance_id" in o}  # "other permanents"
        engine.resolve_pending_choice(str(victim.instance_id))
        engine.resolve_until_stable()
    while engine.state.pending_choice:  # "any number": stop after two
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert sac_a.zone == Zone.GRAVEYARD and sac_b.zone == Zone.GRAVEYARD and keep.zone == Zone.BATTLEFIELD
    assert len(p1.hand) == hand_before + 2  # drew that many

    engine.rules.destroy(bontu)
    engine.rules.put_triggers_on_stack()
    while engine.state.pending_choice:  # "you may put her ... third from the top"
        engine.resolve_pending_choice(next(o["id"] for o in engine.state.pending_choice["options"] if o["id"] != "decline"))
        engine.resolve_until_stable()
    engine.resolve_until_stable()
    assert bontu in p1.library and p1.library.index(bontu) == len(p1.library) - 3  # third from the top


def test_loamcrafter_faun_discards_lands_then_returns_that_many_nonland_permanent_cards():
    engine, p1, p2 = _game("Loamcrafter Faun")
    lands = [
        GameObject(Card(id=f"HL{i}", name=f"Hand Land {i}", type_line="Basic Land — Forest", is_land=True), owner_id="p1", zone=Zone.HAND)
        for i in range(3)
    ]
    p1.hand.extend(lands)
    grave = {}
    for name, type_line, flags in (
        ("Dead Rock", "Artifact", {}), ("Dead Bear", "Creature — Bear", {"is_creature": True, "power": 2, "toughness": 2}),
        ("Dead Bolt", "Instant", {"is_instant": True}), ("Dead Land", "Land", {"is_land": True}),
    ):
        grave[name] = GameObject(Card(id=name, name=name, type_line=type_line, **flags), owner_id="p1", zone=Zone.GRAVEYARD)
        p1.graveyard.append(grave[name])
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    for land in lands[:2]:  # discard two of the three land cards
        engine.resolve_pending_choice(str(land.instance_id))
        engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")  # "one or more": stop at two
    engine.resolve_until_stable()
    assert lands[0].zone == Zone.GRAVEYARD and lands[1].zone == Zone.GRAVEYARD and lands[2] in p1.hand
    engine.rules.put_triggers_on_stack()  # the reflexive "when you do" trigger
    choice = engine.state.pending_choice
    assert choice is not None
    offered = {o["label"] for o in choice["options"] if "instance_id" in o}
    assert offered == {"Dead Rock", "Dead Bear"}  # nonland permanent cards only (not the instant, not lands)
    for name in ("Dead Rock", "Dead Bear"):
        option = next(o for o in engine.state.pending_choice["options"] if o.get("label") == name)
        engine.resolve_pending_choice(option["id"])
    while engine.state.pending_choice:
        engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    assert grave["Dead Rock"] in p1.hand and grave["Dead Bear"] in p1.hand


def test_planetary_annihilation_leaves_each_player_six_lands_and_damages_every_creature():
    engine, p1, p2 = _game("Planetary Annihilation")
    for i in range(8):
        battlefield_object(engine, "p1", f"My Land {i}", "Land", is_land=True)
    for i in range(8):
        battlefield_object(engine, "p2", f"Their Land {i}", "Land", is_land=True)
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    giant = battlefield_object(engine, "p2", "Giant", "Creature — Giant", is_creature=True, power=7, toughness=7)
    p1.mana_pool.add_many({"R": 2, "C": 8})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    guard = 0
    while engine.state.pending_choice and guard < 30:  # each player picks which lands go
        choice = engine.state.pending_choice
        engine.resolve_pending_choice(choice["options"][0]["id"])
        engine.resolve_until_stable()
        guard += 1
    lands = lambda pid: [o for o in engine.state.battlefield if o.is_land and o.controller_id == pid]
    assert len(lands("p1")) == 6 and len(lands("p2")) == 6  # all but six sacrificed (8 -> 6 each)
    assert bear.zone == Zone.GRAVEYARD  # 6 damage to each creature
    assert giant.zone == Zone.BATTLEFIELD and giant.damage_marked == 6  # a 7/7 survives


def _tear_asunder_board():
    engine, p1, p2 = _game("Tear Asunder")
    rock = battlefield_object(engine, "p2", "Their Rock", "Artifact")
    bear = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    land = battlefield_object(engine, "p2", "Their Land", "Land", is_land=True)
    return engine, p1, rock, bear, land


def test_tear_asunder_targets_only_artifacts_and_enchantments_unless_kicked():
    from mtg_analyzer.game.targeting import legal_targets

    engine, p1, rock, bear, land = _tear_asunder_board()
    spell = p1.hand[0]
    spec = spell.spell_effects[0].target_spec

    names = lambda: {o["name"] for o in legal_targets(engine.state, "p1", spec, source=spell)}
    assert names() == {"Their Rock"}  # unkicked: artifact or enchantment
    spell.kicker_count = 1
    assert names() == {"Their Rock", "Their Bear"}  # kicked: any nonland permanent (not the land)


def test_a_kicked_tear_asunder_really_exiles_a_creature():
    engine, p1, rock, bear, land = _tear_asunder_board()
    p1.mana_pool.add_many({"G": 1, "B": 1, "C": 2})  # {1}{G} plus the kicker {1}{B}
    engine.cast_spell(p1, p1.hand[0], targets=[bear], kicked=1)
    engine.resolve_until_stable()
    assert bear.zone == Zone.EXILE and rock.zone == Zone.BATTLEFIELD


def test_moraug_pumps_a_creature_for_each_time_it_attacked_this_turn():
    engine, p1, p2 = _game()
    moraug = _battlefield_card(engine, "Moraug, Fury of Akoum")
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    bear.summoning_sick = False
    engine.recompute_continuous_effects()
    assert bear.power == 2  # no attack yet

    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": bear, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.recompute_continuous_effects()
    assert bear.power == 3  # +1/+0 for the one attack

    bear.attacking, bear.tapped = False, False  # the first combat is over; an additional combat follows
    engine.declare_attackers(p1, [{"attacker": bear, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.recompute_continuous_effects()
    assert bear.power == 4 and bear.toughness == 2  # two attacks this turn
    assert moraug.power == moraug.card.power  # Moraug itself never attacked


def test_moraug_landfall_grants_an_extra_combat_only_in_my_main_phase_and_untaps_my_creatures():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    def play_land(step):
        engine, p1, p2 = _game()
        _battlefield_card(engine, "Moraug, Fury of Akoum")
        bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
        bear.tapped = True
        engine.state.current_step = step
        land = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
        engine.state.fire_event(GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=land.instance_id, controller_id="p1",
            object_types=["land"], player_id="p1",
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
        return engine, bear

    engine, bear = play_land("main1")
    assert len(engine.state.pending_extra_combats) == 1 and not bear.tapped  # extra combat + untap

    engine, bear = play_land("declare_attackers")
    assert not engine.state.pending_extra_combats and bear.tapped  # not a main phase: nothing happens


def _broodship_game(charges=8):
    engine, p1, p2 = _game("Llanowar Elves")
    spell = p1.hand.pop()
    spell.zone = Zone.GRAVEYARD
    p1.graveyard.append(spell)
    ship = _battlefield_card(engine, "Exploration Broodship")
    ship.counters["charge"] = charges
    engine.recompute_continuous_effects()
    p1.mana_pool.add_many({"G": 2})
    return engine, p1, p2, ship, spell


@pytest.mark.parametrize("charges", [0, 2, 3, 7, 8, 9])
def test_broodship_station_thresholds_and_graveyard_permission(charges):
    from mtg_analyzer.game import continuous

    engine, p1, p2, ship, spell = _broodship_game(charges)
    land = _battlefield_card(engine, "Forest")
    assert continuous.extra_land_plays_for(engine.state, p1) == (1 if charges >= 3 else 0)
    assert ship.is_creature == (charges >= 8)
    from mtg_analyzer.game import combat
    assert combat.has(ship, "flying") == (charges >= 8)
    if charges >= 8:
        assert (ship.power, ship.toughness) == (4, 4)
    assert engine.can_cast(p1, spell) == (charges >= 8)
    assert any(a.cost.station for a in ship.activated_abilities)


def test_broodship_pays_selected_land_before_resolution_and_spends_its_use():
    engine, p1, p2, ship, spell = _broodship_game()
    first = _battlefield_card(engine, "Forest")
    chosen = _battlefield_card(engine, "Forest")
    enemy = _battlefield_card(engine, "Forest", "p2")
    assert not engine.can_cast(p1, spell, graveyard_sacrifice_choice=enemy.instance_id)
    engine.cast_spell(p1, spell, graveyard_sacrifice_choice=chosen.instance_id)
    assert chosen in p1.graveyard and first in engine.state.battlefield
    assert spell.zone == Zone.STACK
    assert ship.graveyard_casts_this_turn == 1
    engine.resolve_until_stable()
    engine.rules.put_into_graveyard(spell)
    assert not engine.can_cast(p1, spell)


def test_broodship_requires_a_sacrificable_land_and_own_turn_and_active_source():
    engine, p1, p2, ship, spell = _broodship_game()
    _battlefield_card(engine, "Forest", "p2")
    assert not engine.can_cast(p1, spell)
    own = _battlefield_card(engine, "Forest")
    own.cant_be_sacrificed_this_turn = True
    assert not engine.can_cast(p1, spell)
    own.cant_be_sacrificed_this_turn = False
    assert engine.can_cast(p1, spell)
    engine.state.active_player_index = 1
    spell.intrinsic_keywords.add("flash")
    assert not engine.can_cast(p1, spell)
    engine.state.active_player_index = 0
    ship.counters["charge"] = 7
    assert not engine.can_cast(p1, spell)
    ship.counters["charge"] = 8
    engine.rules.put_into_graveyard(ship)
    assert not engine.can_cast(p1, spell)


def test_broodship_does_not_charge_an_overlapping_free_permission():
    engine, p1, p2, ship, spell = _broodship_game()
    land = _battlefield_card(engine, "Forest")
    lurrus = _battlefield_card(engine, "Lurrus of the Dream-Den")
    engine.cast_spell(p1, spell)
    assert land in engine.state.battlefield
    assert ship.graveyard_casts_this_turn == 0
    assert lurrus.graveyard_casts_this_turn == 1


def test_broodship_requires_distinct_objects_for_two_sacrifice_costs():
    from mtg_analyzer.game.costs import ActivationCost

    engine, p1, p2, ship, spell = _broodship_game()
    spell.additional_cast_cost = ActivationCost(sacrifice="land")
    first = _battlefield_card(engine, "Forest")
    assert not engine.can_cast(p1, spell)
    second = _battlefield_card(engine, "Forest")
    assert not engine.can_cast(p1, spell, sacrifice_choice=first.instance_id,
                               graveyard_sacrifice_choice=first.instance_id)
    engine.cast_spell(p1, spell, sacrifice_choice=first.instance_id,
                      graveyard_sacrifice_choice=second.instance_id)
    assert first in p1.graveyard and second in p1.graveyard



def test_broodship_finds_a_joint_payment_and_preserves_printed_sacrifice_measurements():
    from mtg_analyzer.game.costs import ActivationCost

    engine, p1, p2, ship, spell = _broodship_game()
    spell.additional_cast_cost = ActivationCost(sacrifice="creature_or_land")
    ship.cant_be_sacrificed_this_turn = True
    land = _battlefield_card(engine, "Forest")
    bear = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    assert engine.can_cast(p1, spell)
    engine.cast_spell(p1, spell)
    assert land in p1.graveyard and bear in p1.graveyard
    assert spell.sacrificed_cost_power == 2
