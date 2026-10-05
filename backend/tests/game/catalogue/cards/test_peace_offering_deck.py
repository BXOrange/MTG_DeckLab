"""Real gameplay for the Family Matters (Bloomburrow Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * 8) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _enter(engine, obj, from_cast=False):
    """Announce ``obj`` entering (the fillers are placed without the ENTERS_BATTLEFIELD event)."""
    from mtg_analyzer.models.game.events import EventType, GameEvent

    obj.was_cast = from_cast
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object_types=sorted(obj.type_words),
                                      object=obj.name))
    engine.resolve_until_stable()


def _cast(engine, card, pool, **kw):
    p1 = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many(pool)
    engine.cast_spell(p1, card, targets=None, target_groups=None, **kw)
    engine.resolve_until_stable()


def _library_top(engine, card_name, type_line, player="p1"):
    p = engine.state.player_by_id(player)
    p.library.clear()
    return _filler(engine, card_name, type_line, player=player, zone=Zone.LIBRARY)


@pytest.mark.parametrize("type_line,zone", [("Land", Zone.BATTLEFIELD), ("Sorcery", Zone.HAND)])
def test_coiling_oracle_puts_a_land_onto_the_battlefield_otherwise_into_hand(type_line, zone):
    engine = _game()
    top = _library_top(engine, "Top Card", type_line)
    oracle = _card(engine, "Coiling Oracle")
    _enter(engine, oracle)
    assert top.zone == zone


def test_triskaidekaphile_wins_at_upkeep_with_exactly_thirteen_cards():
    for n, wins in ((12, False), (13, True), (14, False)):
        engine = _game()
        p1, p2 = engine.state.players
        _card(engine, "Triskaidekaphile")
        for i in range(n):
            _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
        engine.state.active_player_index = 0
        engine.state.current_step = "upkeep"
        from mtg_analyzer.models.game.events import EventType, GameEvent
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id=p1.id,
                                          controller_id=p1.id))
        engine.resolve_until_stable()
        assert (p2.has_lost or engine.state.winner_id == p1.id) is wins, n


@pytest.mark.parametrize("counters,hand,wins", [(5, 3, False), (20, 0, True), (2, 20, True)])
def test_twenty_toed_toad_wins_on_attack_with_twenty_counters_or_cards(counters, hand, wins):
    engine = _game()
    p1, p2 = engine.state.players
    toad = _card(engine, "Twenty-Toed Toad")
    toad.plus_one_counters = counters
    for i in range(hand):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    engine.state.active_player_index = 0
    engine.state.current_step = "declare_attackers"
    engine.state.current_phase = "combat"
    toad.summoning_sick = False
    engine.declare_attackers(p1, [toad])
    engine.resolve_until_stable()
    assert (p2.has_lost or engine.state.winner_id == p1.id) is wins


def test_twenty_toed_toad_raises_the_maximum_hand_size_to_twenty():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Twenty-Toed Toad")
    for i in range(20):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    engine.state.active_player_index = 0
    engine._step_cleanup()
    assert len(p1.hand) == 20


def _stock_libraries(engine, n=4):
    for pl in engine.state.players:
        pl.library.clear()
        for i in range(n):
            _filler(engine, f"{pl.id}-lib{i}", "Sorcery", player=pl.id, zone=Zone.LIBRARY)


def _rabbits(engine, player):
    return [o for o in engine.state.battlefield if o.controller_id == player.id and o.name == "Rabbit"]


def test_tempt_with_bunnies_pays_you_once_per_accepting_opponent():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    _stock_libraries(engine)
    _cast(engine, _card(engine, "Tempt with Bunnies", zone=Zone.HAND), {"W": 1, "C": 2})
    pending = engine.state.pending_choice
    assert pending["player_id"] == "p2"
    assert [o["label"] for o in pending["options"]] == ["Ja", "Nein"]
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p3"
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert (len(p1.hand), len(p2.hand), len(p3.hand)) == (2, 1, 0)
    assert (len(_rabbits(engine, p1)), len(_rabbits(engine, p2)), len(_rabbits(engine, p3))) == (2, 1, 0)


def test_tempt_with_bunnies_gives_you_only_your_own_card_when_everyone_declines():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    _cast(engine, _card(engine, "Tempt with Bunnies", zone=Zone.HAND), {"W": 1, "C": 2})
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert (len(p1.hand), len(p2.hand)) == (1, 0)
    assert (len(_rabbits(engine, p1)), len(_rabbits(engine, p2))) == (1, 0)


def _stock_lands(engine, player):
    return [_filler(engine, f"{player}-Land{i}", "Basic Land — Forest", player=player, zone=Zone.LIBRARY)
            for i in range(2)]


def _pick_first(engine, expected_player):
    pending = engine.state.pending_choice
    assert pending["player_id"] == expected_player, pending
    first = pending["options"][0]
    engine.resolve_pending_choice(str(first.get("id", first.get("instance_id"))))
    engine.resolve_until_stable()


@pytest.mark.parametrize("accept", [True, False])
def test_tempt_with_discovery_searches_for_you_and_each_accepting_opponent(accept):
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    mine = _stock_lands(engine, "p1")
    theirs = _stock_lands(engine, "p2")
    _cast(engine, _card(engine, "Tempt with Discovery", zone=Zone.HAND), {"G": 1, "C": 3})
    _pick_first(engine, "p1")  # your own search comes first
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    assert engine.state.pending_choice["player_id"] == "p2"
    if accept:
        engine.resolve_pending_choice("pay")
        engine.resolve_until_stable()
        _pick_first(engine, "p2")  # the opponent finds their own land
        _pick_first(engine, "p1")  # then your bonus search
    else:
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    on_bf = lambda objs: sum(1 for o in objs if o.zone == Zone.BATTLEFIELD)
    assert (on_bf(mine), on_bf(theirs)) == ((2, 1) if accept else (1, 0))


def _activate_tap(engine, obj):
    obj.summoning_sick = False
    engine.state.current_step = "main1"
    for i, action in enumerate(engine.legal_actions(engine.state.players[0])):
        pass
    p = engine.state.player_by_id(obj.controller_id)
    engine.activate_ability(p, obj, 0)
    engine.resolve_until_stable()


def test_kwain_lets_each_player_draw_and_gain_one_life_if_they_accept():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    _stock_libraries(engine)
    kwain = _card(engine, "Kwain, Itinerant Meddler")
    _activate_tap(engine, kwain)
    answers = {"p1": "pay", "p2": "decline", "p3": "pay"}
    seen = []
    while engine.state.pending_choice:
        pending = engine.state.pending_choice
        seen.append(pending["player_id"])
        engine.resolve_pending_choice(answers[pending["player_id"]])
        engine.resolve_until_stable()
    assert seen == ["p1", "p2", "p3"]
    assert [len(p.hand) for p in (p1, p2, p3)] == [1, 0, 1]
    assert [p.life for p in (p1, p2, p3)] == [21, 20, 21]


def test_selvala_adds_green_and_gains_life_per_nonland_reveal_then_everyone_draws():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    # top of each library is the *last* element: p1 reveals a nonland, p2 a land
    p1.library.append(_filler(engine, "My Sorcery", "Sorcery", zone=Zone.LIBRARY))
    p2.library.append(_filler(engine, "Their Land", "Land", player="p2", zone=Zone.LIBRARY))
    selvala = _card(engine, "Selvala, Explorer Returned")
    life, hand1, hand2 = p1.life, len(p1.hand), len(p2.hand)
    _activate_tap(engine, selvala)
    assert p1.mana_pool.total() == 1 and p2.mana_pool.total() == 0
    assert (p1.life, p2.life) == (life + 1, 20)
    assert (len(p1.hand), len(p2.hand)) == (hand1 + 1, hand2 + 1)


def test_intellectual_offering_draws_three_each_and_untaps_both_boards_with_one_opponent():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine, 6)
    mine = _filler(engine, "My Rock", "Artifact", mv=1)
    my_land = _filler(engine, "My Forest", "Land")
    theirs = _filler(engine, "Their Rock", "Artifact", player="p2", mv=1)
    for o in (mine, my_land, theirs):
        o.tapped = True
    _cast(engine, _card(engine, "Intellectual Offering", zone=Zone.HAND), {"U": 1, "C": 4})
    assert engine.state.pending_choice is None
    assert (len(p1.hand), len(p2.hand)) == (3, 3)
    assert not mine.tapped and not theirs.tapped
    assert my_land.tapped  # lands stay tapped


def test_intellectual_offering_asks_which_opponent_in_a_multiplayer_game():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    _stock_libraries(engine, 6)
    _cast(engine, _card(engine, "Intellectual Offering", zone=Zone.HAND), {"U": 1, "C": 4})
    pending = engine.state.pending_choice
    assert pending["player_id"] == "p1" and [o["id"] for o in pending["options"]] == ["p2", "p3"]
    engine.resolve_pending_choice("p3")
    engine.resolve_until_stable()
    assert (len(p1.hand), len(p2.hand), len(p3.hand)) == (3, 0, 3)
    engine.resolve_pending_choice("p2")  # the second "choose an opponent" is independent
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_jolrael_sets_base_power_and_toughness_to_the_hand_size_until_end_of_turn():
    engine = _game()
    p1, p2 = engine.state.players
    jolrael = _card(engine, "Jolrael, Mwonvuli Recluse")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", "Creature", player="p2", power=5, toughness=5)
    for i in range(3):
        _filler(engine, f"H{i}", "Sorcery", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 2, "C": 4})
    engine.activate_ability(p1, jolrael, 0)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)
    assert (jolrael.power, jolrael.toughness) == (3, 3)
    assert (theirs.power, theirs.toughness) == (5, 5)
    _filler(engine, "H3", "Sorcery", zone=Zone.HAND)  # live read: follows the hand
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)
    late = _filler(engine, "Latecomer", "Creature", power=1, toughness=1)  # entered after resolution
    engine.recompute_continuous_effects()
    assert (late.power, late.toughness) == (1, 1)


def test_bloodroot_apothecary_gives_treasure_to_you_and_a_target_opponent_and_has_toxic():
    engine = _game(2)
    p1, p2 = engine.state.players
    apothecary = _card(engine, "Bloodroot Apothecary")
    _enter(engine, apothecary)
    pending = engine.state.pending_choice
    if pending:  # a multi-target prompt: pick the opponent
        engine.resolve_pending_choice(str(pending["options"][0].get("id", pending["options"][0].get("instance_id"))))
        engine.resolve_until_stable()
    treasures = lambda p: [o for o in engine.state.battlefield if o.controller_id == p.id and o.name == "Treasure"]
    assert len(treasures(p1)) == 1 and len(treasures(p2)) == 1
    from mtg_analyzer.game import combat
    assert combat.toxic_value(apothecary) == 2


@pytest.mark.parametrize("controller,is_token,type_line,poisoned", [
    ("p2", True, "Artifact — Treasure", True),
    ("p2", True, "Creature — Squirrel", False),
    ("p2", False, "Artifact", False),
    ("p1", True, "Artifact — Treasure", False),
])
def test_bloodroot_apothecary_poisons_an_opponent_who_sacrifices_a_noncreature_token(
        controller, is_token, type_line, poisoned):
    engine = _game(2)
    p1, p2 = engine.state.players
    _card(engine, "Bloodroot Apothecary")
    victim = _filler(engine, "Victim", type_line, player=controller)
    victim.is_token = is_token
    before = (p1.poison, p2.poison)
    engine.rules.put_into_graveyard(victim)  # RULE 701.17: a genuine sacrifice
    engine.resolve_until_stable()
    gained = (p2.poison - before[1]) + (p1.poison - before[0])
    assert gained == (2 if poisoned else 0)
    if poisoned:
        assert p2.poison - before[1] == 2


@pytest.mark.parametrize("picks,ingredients,drawers", [
    (["stop"], 1, ()),
    (["p2", "stop"], 2, ("p2",)),
    (["p2", "p3"], 3, ("p2", "p3")),
])
def test_communal_brewing_counts_one_ingredient_plus_one_per_opponent_who_drew(picks, ingredients, drawers):
    engine = _game(3)
    _stock_libraries(engine)
    brewing = _card(engine, "Communal Brewing")
    _enter(engine, brewing)
    for pick in picks:
        pending = engine.state.pending_choice
        assert pending["kind"] == "trigger_target_multi"
        engine.resolve_pending_choice(pick)
        engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert brewing.counters.get("ingredient", 0) == ingredients
    assert {p.id for p in engine.state.players if len(p.hand) == 1} == set(drawers)
    assert len(engine.state.player_by_id("p1").hand) == 0


def test_communal_brewing_pumps_creature_spells_as_they_enter():
    engine = _game(2)
    p1, _ = engine.state.players
    brewing = _card(engine, "Communal Brewing")
    brewing.counters["ingredient"] = 3
    bear = _filler(engine, "Bear", "Creature — Bear", mv=2, power=2, toughness=2, zone=Zone.HAND)
    _cast(engine, bear, {"C": 2})
    assert bear.zone == Zone.BATTLEFIELD and bear.plus_one_counters == 3
    token_like = _filler(engine, "Put Directly", "Creature", power=1, toughness=1)  # not cast: no counters
    assert token_like.plus_one_counters == 0


@pytest.mark.parametrize("gift", [None, "p2"])
def test_perch_protection_makes_four_birds_and_only_a_promised_gift_phases_everything_out(gift):
    engine = _game(2)
    p1, p2 = engine.state.players
    spell = _card(engine, "Perch Protection", zone=Zone.HAND)
    _cast(engine, spell, {"W": 2, "C": 4}, gift_opponent_id=gift)
    birds = [o for o in engine.state.battlefield if o.name == "Bird"]
    assert len(birds) == 4
    assert all(b.card.power == 2 and "flying" in combat._obj_keywords(b) for b in birds)
    assert spell.zone == Zone.EXILE
    assert all(b.phased_out for b in birds) is bool(gift)
    life = p1.life
    engine.rules.lose_life(p1, 3)
    assert p1.life == (life if gift else life - 3)  # "your life total can't change" only when promised
    assert engine.state.extra_turns == (["p2"] if gift else [])


def _truce(engine, host="p2", controller="p1"):
    truce = _card(engine, "Tenuous Truce", player=controller)
    truce.attached_to = host
    return truce


def _attack(engine, attacker_id, defender):
    """``attacker_id`` attacks ``defender`` (a player id, or a planeswalker object)."""
    attacker = _filler(engine, "Attacker", power=2, toughness=2, player=attacker_id)
    attacker.summoning_sick = False
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == attacker_id)
    engine.state.current_step = "declare_attackers"
    engine.state.current_phase = "combat"
    attacker.attacking = True
    attacker.combat_defender = (
        {"kind": "player", "id": defender} if isinstance(defender, str)
        else {"kind": "planeswalker", "instance_id": defender.instance_id, "label": defender.name}
    )
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def test_tenuous_truce_draws_for_both_at_the_enchanted_players_end_step_only():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    for active, draws in (("p2", True), ("p1", False)):
        engine = _game(2)
        p1, p2 = engine.state.players
        _stock_libraries(engine)
        _truce(engine)
        engine.state.active_player_index = 0 if active == "p1" else 1
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id=active))
        engine.resolve_until_stable()
        assert (len(p1.hand), len(p2.hand)) == ((1, 1) if draws else (0, 0))


@pytest.mark.parametrize("attacker,defender,sacrificed", [
    ("p1", "p2", True),     # you attack the enchanted opponent
    ("p2", "p1", True),     # they attack you
    ("p1", "p3", False),    # you attack someone else
    ("p3", "p2", False),    # a third player attacks the enchanted opponent
    ("p2", "p3", False),    # they attack a third player
])
def test_tenuous_truce_is_sacrificed_by_attacks_between_controller_and_enchanted_player(
        attacker, defender, sacrificed):
    engine = _game(3)
    truce = _truce(engine)
    _attack(engine, attacker, defender)
    assert (truce.zone == Zone.GRAVEYARD) is sacrificed


@pytest.mark.parametrize("walker_owner,attacker,sacrificed", [
    ("p2", "p1", True),     # you attack a planeswalker the enchanted opponent controls
    ("p1", "p2", True),     # they attack a planeswalker you control
    ("p3", "p1", False),
])
def test_tenuous_truce_counts_attacks_on_planeswalkers(walker_owner, attacker, sacrificed):
    engine = _game(3)
    truce = _truce(engine)
    walker = _filler(engine, "Walker", "Legendary Planeswalker — Test", player=walker_owner)
    _attack(engine, attacker, walker)
    assert (truce.zone == Zone.GRAVEYARD) is sacrificed


def test_tenuous_truce_is_cast_onto_an_opponent_and_stays_attached():
    engine = _game(3)
    p1, p2, p3 = engine.state.players
    truce = _card(engine, "Tenuous Truce", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"W": 1, "C": 1})
    from mtg_analyzer.game.targeting import spell_target_specs
    assert [s.kind for s in spell_target_specs(truce)] == ["opponent"]
    engine.cast_spell(p1, truce, targets=[p2], target_groups=None)
    engine.resolve_until_stable()
    assert truce.zone == Zone.BATTLEFIELD and truce.attached_to == "p2"
    engine.resolve_until_stable()
    assert truce.zone == Zone.BATTLEFIELD  # state-based actions keep a legal player host


def _unblocked_attack(engine, attacker_id, defender_id, count=1):
    attackers = []
    for i in range(count):
        a = _filler(engine, f"Raider{i}", power=2, toughness=2, player=attacker_id)
        a.attacking = True
        a.combat_defender = {"kind": "player", "id": defender_id}
        attackers.append(a)
    engine._fire_unblocked_events()
    engine.resolve_until_stable()
    return attackers


def test_coveted_jewel_draws_three_on_entering_and_taps_for_three_mana_of_one_color():
    engine = _game(2)
    p1, _ = engine.state.players
    _stock_libraries(engine)
    jewel = _card(engine, "Coveted Jewel")
    _enter(engine, jewel)
    assert len(p1.hand) == 3
    jewel.summoning_sick = False
    produced = engine.tap_for_mana(p1, jewel)
    assert jewel.tapped and p1.mana_pool.total() == 3
    assert len({c for c, n in p1.mana_pool.pool.items() if n}) == 1  # three mana of one colour


def test_coveted_jewel_goes_to_an_opponent_whose_creatures_attack_you_unblocked_once():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    jewel = _card(engine, "Coveted Jewel")
    jewel.tapped = True
    _unblocked_attack(engine, "p2", "p1", count=2)  # two unblocked attackers: still one trigger
    assert jewel.controller_id == "p2"
    assert not jewel.tapped
    assert (len(p1.hand), len(p2.hand)) == (0, 3)


@pytest.mark.parametrize("attacker,defender", [("p1", "p2"), ("p2", "p3"), ("p3", "p2")])
def test_coveted_jewel_ignores_attacks_not_aimed_at_its_controller(attacker, defender):
    engine = _game(3)
    _stock_libraries(engine)
    jewel = _card(engine, "Coveted Jewel")
    _unblocked_attack(engine, attacker, defender)
    assert jewel.controller_id == "p1"


def test_coveted_jewel_ignores_blocked_attackers():
    engine = _game(2)
    _stock_libraries(engine)
    jewel = _card(engine, "Coveted Jewel")
    blocker = _filler(engine, "Wall", power=0, toughness=4)
    raider = _filler(engine, "Raider", power=2, toughness=2, player="p2")
    raider.attacking = True
    raider.combat_defender = {"kind": "player", "id": "p1"}
    raider.blocked_by = [blocker.instance_id]
    engine._fire_unblocked_events()
    engine.resolve_until_stable()
    assert jewel.controller_id == "p1"


def _foxglove_attack(engine, foxglove, defender_id="p2"):
    foxglove.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.state.current_phase = "combat"
    engine.declare_attackers(engine.state.players[0], [foxglove])
    engine.resolve_until_stable()


@pytest.mark.parametrize("mine,theirs,drawn", [(1, 4, 3), (0, 2, 2), (3, 3, 0)])
def test_mr_foxglove_draws_the_hand_size_difference(mine, theirs, drawn):
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine, 8)
    foxglove = _card(engine, "Mr. Foxglove")
    for i in range(mine):
        _filler(engine, f"M{i}", "Sorcery", zone=Zone.HAND)
    for i in range(theirs):
        _filler(engine, f"T{i}", "Sorcery", player="p2", zone=Zone.HAND)
    _foxglove_attack(engine, foxglove)
    assert len(p1.hand) == mine + drawn and len(p2.hand) == theirs


def test_mr_foxglove_may_put_a_creature_from_hand_when_it_drew_nothing():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    foxglove = _card(engine, "Mr. Foxglove")
    ogre = _filler(engine, "Ogre", "Creature — Ogre", power=3, toughness=3, mv=3, zone=Zone.HAND)
    _filler(engine, "Spell", "Sorcery", zone=Zone.HAND)
    _foxglove_attack(engine, foxglove)
    pending = engine.state.pending_choice
    assert pending is not None
    answer = next((o for o in pending["options"] if o.get("instance_id") == ogre.instance_id), pending["options"][0])
    engine.resolve_pending_choice(str(answer["id"]))
    engine.resolve_until_stable()
    assert ogre.zone == Zone.BATTLEFIELD
    assert len(p1.hand) == 1  # nothing was drawn


@pytest.mark.parametrize("active", ["p1", "p2"])
def test_octomancer_copies_a_creature_token_that_entered_this_turn_at_each_end_step(active):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine = _game(2)
    _card(engine, "Octomancer")
    engine.state.active_player_index = 0 if active == "p1" else 1
    token = _filler(engine, "Frog Token", "Creature — Frog", power=1, toughness=1, player="p2")
    token.is_token = True
    _enter(engine, token)
    old = _filler(engine, "Old Token", "Creature — Frog", power=4, toughness=4)
    old.is_token = True
    old.turn_entered = -5  # entered on an earlier turn
    nontoken = _filler(engine, "Real Bear", "Creature — Bear", power=2, toughness=2)
    _enter(engine, nontoken)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id=active))
    engine.rules.put_triggers_on_stack()
    pending = engine.state.pending_choice
    options = [o.get("instance_id") for o in pending["options"]]
    assert options == [token.instance_id]  # not the older token, not the nontoken creature
    engine.resolve_pending_choice(str(token.instance_id))
    engine.resolve_until_stable()
    frogs = [o for o in engine.state.battlefield if o.name == "Frog Token"]
    assert len(frogs) == 2 and all(f.is_token for f in frogs)
    assert sorted(f.controller_id for f in frogs) == ["p1", "p2"]  # the copy is Octomancer's controller's


def _upkeep(engine, player_id="p1"):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == player_id)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id=player_id))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


@pytest.mark.parametrize("top_type,answer,fish", [
    ("Land", "reveal", 1), ("Land", "decline", 0), ("Sorcery", "ok", 0),
])
def test_fisher_s_talent_upkeep_reveals_a_land_for_a_fish_then_draws(top_type, answer, fish):
    engine = _game(2)
    p1, _ = engine.state.players
    _stock_libraries(engine, 4)
    top = _filler(engine, "Top Card", top_type, zone=Zone.LIBRARY)
    talent = _card(engine, "Fisher's Talent")
    _upkeep(engine)
    pending = engine.state.pending_choice
    assert pending["kind"] == "peek_top_land" and [o["id"] for o in pending["options"]][0] in ("reveal", "ok")
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()
    fishes = [o for o in engine.state.battlefield if o.is_token and o.name == "Fish"]
    assert len(fishes) == fish
    assert (fishes[0].power, fishes[0].toughness) == (1, 1) if fish else True
    assert top.zone == Zone.HAND  # the draw happens after the look, so the same card is drawn
    assert len(p1.hand) == 1


@pytest.mark.parametrize("level,name,power", [(1, "Fish", 1), (2, "Shark", 3), (3, "Octopus", 8)])
def test_fisher_s_talent_class_levels_upgrade_fish_tokens(level, name, power):
    engine = _game(2)
    p1, _ = engine.state.players
    talent = _card(engine, "Fisher's Talent")
    talent.counters["class_level"] = level
    from mtg_analyzer.services.token_database import synthesize_token_card
    fish = synthesize_token_card(name="Fish", power=1, toughness=1, colors=["U"], subtypes=["Fish"], keywords=[])
    made = engine.rules.create_token("p1", fish, 2)
    assert [o.name for o in made] == [name, name]
    assert all(o.card.power == power and o.is_token for o in made)
    other = engine.rules.create_token("p2", fish, 1)  # only your tokens
    assert other[0].name == "Fish"


def _walker(engine, loyalty=7):
    tamiyo = _card(engine, "Tamiyo, Field Researcher")
    tamiyo.counters["loyalty"] = loyalty
    engine.state.current_step = "main1"
    engine.state.current_phase = "main"
    return tamiyo


def _loyalty_index(walker, cost):
    return next(i for i, a in enumerate(walker.activated_abilities) if a.cost.loyalty == cost)


def test_tamiyo_plus_one_draws_for_you_when_either_chosen_creature_deals_combat_damage_until_your_next_turn():
    engine = _game(2)
    p1, p2 = engine.state.players
    _stock_libraries(engine)
    tamiyo = _walker(engine)
    mine = _filler(engine, "Mine", power=2, toughness=2)
    theirs = _filler(engine, "Theirs", power=2, toughness=2, player="p2")
    engine.activate_ability(p1, tamiyo, _loyalty_index(tamiyo, 1), targets=[mine, theirs])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    from mtg_analyzer.models.game.events import EventType, GameEvent
    for creature in (mine, theirs):  # an opponent's creature draws for *Tamiyo's* controller
        before = len(p1.hand), len(p2.hand)
        engine.state.fire_event(GameEvent(
            EventType.DAMAGE, source_id=creature.instance_id, instance_id=creature.instance_id,
            target_id="p2" if creature is mine else "p1", amount=2, combat=True, is_player=True,
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
        assert (len(p1.hand) - before[0], len(p2.hand) - before[1]) == (1, 0), creature.name


def test_tamiyo_minus_two_taps_up_to_two_nonland_permanents_that_skip_their_next_untap():
    engine = _game(2)
    p1, p2 = engine.state.players
    tamiyo = _walker(engine)
    rock = _filler(engine, "Rock", "Artifact", mv=1, player="p2")
    bear = _filler(engine, "Bear", power=2, toughness=2, player="p2")
    land = _filler(engine, "Forest", "Land", player="p2")
    engine.activate_ability(p1, tamiyo, _loyalty_index(tamiyo, -2), targets=[rock, bear])
    engine.resolve_until_stable()
    assert rock.tapped and bear.tapped and not land.tapped
    engine.state.active_player_index = 1
    engine._step_untap()
    assert rock.tapped and bear.tapped  # skipped this untap step
    engine._step_untap()
    assert not rock.tapped and not bear.tapped


def test_tamiyo_minus_seven_draws_three_and_gives_a_hand_only_free_cast_emblem():
    engine = _game(2)
    p1, _ = engine.state.players
    _stock_libraries(engine, 6)
    tamiyo = _walker(engine)
    engine.activate_ability(p1, tamiyo, _loyalty_index(tamiyo, -7))
    engine.resolve_until_stable()
    assert len(p1.hand) == 3 and len(p1.emblems) == 1
    big = p1.hand[0]
    big.card.converted_mana_cost = 6
    assert engine.can_cast(p1, big, free=True)  # from hand: free
    from mtg_analyzer.models.game.game_object import Zone as Z
    other = _filler(engine, "From Elsewhere", "Sorcery", mv=6, zone=Z.GRAVEYARD)
    assert not engine.can_cast(p1, other, free=True)  # not from the hand: no permission


def _declare_blockers_setup(engine, attackers=2):
    """p2 (the active player) attacks p1 with ``attackers`` creatures; p1 blocks the first one."""
    p1, p2 = engine.state.players[:2]
    engine.state.active_player_index = 1
    raiders = []
    for i in range(attackers):
        raider = _filler(engine, f"Raider{i}", power=2, toughness=2, player="p2")
        raider.attacking = True
        raider.tapped = True
        raider.combat_defender = {"kind": "player", "id": "p1"}
        raiders.append(raider)
    blocker = _filler(engine, "Wall", power=0, toughness=3, player="p1")
    blocker.blocking = raiders[0].instance_id
    raiders[0].blocked_by = [blocker.instance_id]
    engine.state.current_step = "declare_blockers"
    engine.state.current_phase = "combat"
    return raiders, blocker


def test_illusionist_s_gambit_pulls_attackers_out_of_combat_and_sets_up_a_forced_second_combat():
    engine = _game(2)
    p1, p2 = engine.state.players
    raiders, blocker = _declare_blockers_setup(engine)
    gambit = _card(engine, "Illusionist's Gambit", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "C": 2})
    engine.cast_spell(p1, gambit, targets=None, target_groups=None)  # in the declare blockers step
    engine.resolve_until_stable()
    assert gambit.zone == Zone.GRAVEYARD
    for raider in raiders:
        assert not raider.attacking and not raider.tapped and raider.combat_defender is None
        assert "attacks_if_able" in combat._obj_keywords(raider) or combat.has(raider, "attacks_if_able")
    assert blocker.blocking is None and not raiders[0].blocked_by
    assert engine.state.pending_extra_combats == [False]
    assert ("p2", "p1") in engine.state.no_attack_pairs_this_turn


def test_illusionist_s_gambit_can_only_be_cast_in_the_declare_blockers_step_on_an_opponents_turn():
    engine = _game(2)
    p1, p2 = engine.state.players
    _declare_blockers_setup(engine)
    gambit = _card(engine, "Illusionist's Gambit", zone=Zone.HAND)
    p1.mana_pool.add_many({"U": 2, "C": 2})
    assert engine.can_cast(p1, gambit)
    engine.state.current_step = "declare_attackers"
    assert not engine.can_cast(p1, gambit)  # wrong step
    engine.state.current_step = "declare_blockers"
    engine.state.active_player_index = 0
    assert not engine.can_cast(p1, gambit)  # your own turn
