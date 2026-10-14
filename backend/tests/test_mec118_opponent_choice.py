"""MEC-118 - "target <X> of an opponent's choice" (RULE 115.1 / 601.2c).

The controller announces the spell or ability; the chosen opponent picks the marked target through an ordinary
`pending_choice` (kind ``opponent_target``) while the object is already on the stack.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import requirements_with_targets, spell_target_specs
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

REAL_CARDS = (
    "Diaochan, Artful Beauty", "Cuombajj Witches", "Karplusan Minotaur", "Evangelize", "Volcanic Offering",
    "Mausoleum Turnkey",
)


def _db_card(name):
    return CardDatabase(DEFAULT_DB_PATH).get_card(name)


def _engine(players=2):
    seats = [(f"p{i + 1}", f"P{i + 1}", []) for i in range(players)]
    eng = GameEngine.new_game(seats, starting_life=20, starting_hand=0)
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller, zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.player_by_id(controller).hand.append(obj)
    elif zone == Zone.GRAVEYARD:
        eng.state.player_by_id(controller).graveyard.append(obj)
    return obj


def _vanilla(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear", power=power, toughness=toughness,
                is_creature=True)


def _answer_with(eng, instance_id):
    choice = eng.state.pending_choice
    eng.resolve_pending_choice(str(instance_id))
    return choice


def test_real_cards_parse_as_modeled():
    for name in REAL_CARDS:
        assert parse_oracle(_db_card(name)).coverage == MODELED, name


def test_phrase_without_a_one_to_one_target_match_stays_unclaimed():
    card = Card(id="x", name="X", type_line="Sorcery",
                oracle_text="Tap target creature and target land of an opponent's choice.")
    assert parse_oracle(card).coverage != MODELED


def test_evangelize_opponent_picks_a_creature_they_control():
    eng = _engine()
    mine = _put(eng, _vanilla("Mine"), "p1")
    theirs_a = _put(eng, _vanilla("Theirs A"), "p2")
    theirs_b = _put(eng, _vanilla("Theirs B", 5, 5), "p2")
    spell = _put(eng, _db_card("Evangelize"), "p1", Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    # The controller is never asked for the opponent's target (RULE 601.2c).
    assert requirements_with_targets(eng.state, "p1", spell) == []
    p1.mana_pool.add("W", 5)
    eng.cast_spell(p1, spell)
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    assert {o["instance_id"] for o in choice["options"]} == {theirs_a.instance_id, theirs_b.instance_id}
    eng.resolve_pending_choice(str(theirs_a.instance_id))
    assert eng.state.pending_choice is None
    item = eng.state.stack[-1]
    assert item.targets == [theirs_a]
    eng.resolve_until_stable()
    assert theirs_a.controller_id == "p1" and theirs_b.controller_id == "p2" and mine.controller_id == "p1"


def test_spell_with_no_creature_for_the_opponent_cannot_be_cast():
    eng = _engine()
    _put(eng, _vanilla("Mine"), "p1")
    spell = _put(eng, _db_card("Evangelize"), "p1", Zone.HAND)
    reqs = requirements_with_targets(eng.state, "p1", spell)
    assert len(reqs) == 1 and reqs[0]["options"] == []


def test_chosen_target_that_changes_controller_fizzles_evangelize():
    # "the target is a creature the chosen opponent controls" (Evangelize ruling): stolen away in response, it fizzles.
    eng = _engine(3)
    theirs = _put(eng, _vanilla("Theirs"), "p2")
    spell = _put(eng, _db_card("Evangelize"), "p1", Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("W", 5)
    eng.cast_spell(p1, spell)
    eng.resolve_pending_choice(str(theirs.instance_id))
    theirs.controller_id = "p3"
    eng.resolve_until_stable()
    assert theirs.controller_id == "p3"


def test_cuombajj_controller_picks_first_target_opponent_picks_second():
    eng = _engine()
    witch = _put(eng, _db_card("Cuombajj Witches"), "p1")
    witch.summoning_sick = False
    mine = _put(eng, _vanilla("Mine"), "p1")
    theirs = _put(eng, _vanilla("Theirs", 3, 3), "p2")
    eng.state.current_step = "main1"
    eng.activate_ability(eng.state.player_by_id("p1"), witch, 0, targets=[theirs])
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    ids = {o.get("instance_id") for o in choice["options"]}
    assert mine.instance_id in ids
    eng.resolve_pending_choice(str(mine.instance_id))
    eng.resolve_until_stable()
    assert theirs.damage_marked == 1 and mine.damage_marked == 1


def test_three_player_controller_names_the_opponent_first():
    eng = _engine(3)
    t2 = _put(eng, _vanilla("T2"), "p2")
    t3 = _put(eng, _vanilla("T3"), "p3")
    spell = _put(eng, _db_card("Evangelize"), "p1", Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("W", 5)
    eng.cast_spell(p1, spell)
    assert eng.state.pending_choice["kind"] == "opponent_chooser"
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice("p3")
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p3"
    assert [o["instance_id"] for o in choice["options"]] == [t3.instance_id]
    eng.resolve_pending_choice(str(t3.instance_id))
    eng.resolve_until_stable()
    assert t3.controller_id == "p1" and t2.controller_id == "p2"


def test_mausoleum_turnkey_trigger_opponent_picks_from_your_graveyard():
    eng = _engine()
    a = _put(eng, _vanilla("Gy A"), "p1", Zone.GRAVEYARD)
    b = _put(eng, _vanilla("Gy B"), "p1", Zone.GRAVEYARD)
    turnkey = _put(eng, _db_card("Mausoleum Turnkey"), "p1", Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("B", 4)
    eng.cast_spell(p1, turnkey)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(b.instance_id))
    eng.resolve_until_stable()
    assert b in p1.hand and a in p1.graveyard




def _session_with_evangelize():
    from mtg_analyzer.models.cards.card import Card as _Card
    from mtg_analyzer.services.game_session import GameSessionManager

    land = _Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True)
    session = GameSessionManager().create_multiplayer(
        [{"player_id": "ann", "name": "Ann", "library": [land] * 30, "commanders": []},
         {"player_id": "bob", "name": "Bob", "library": [land] * 30}],
        mulligan_style="none",
    )
    for pid in ("ann", "bob"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
    eng = session.engine
    mine = _put(eng, _vanilla("Ann Bear"), "ann")
    weak = _put(eng, _vanilla("Weak", 1, 1), "bob")
    strong = _put(eng, _vanilla("Strong", 6, 6), "bob")
    spell = _put(eng, _db_card("Evangelize"), "ann", Zone.HAND)
    eng.state.player_by_id("ann").mana_pool.add("W", 5)
    return session, eng, spell, mine, weak, strong


def test_session_only_the_chosen_opponent_may_answer_and_a_bot_picks_its_worst_creature():
    from mtg_analyzer.services.bots import GreedyBot, run_bots
    from mtg_analyzer.services.game_session import GameActionError

    session, eng, spell, mine, weak, strong = _session_with_evangelize()
    assert eng.state.active_player.id == "ann"  # ann is on the play
    eng.state.current_step = "main1"
    session.apply_action({"type": "cast_spell", "instance_id": spell.instance_id}, actor_id="ann")
    pending = eng.state.pending_choice
    assert pending["kind"] == "opponent_target" and pending["player_id"] == "bob"
    assert session.legal_actions(perspective="ann") == []
    bob_actions = session.legal_actions(perspective="bob")
    assert {a["instance_id"] for a in bob_actions} == {weak.instance_id, strong.instance_id}
    with pytest.raises(GameActionError):
        session.apply_action({"type": "choose", "option_id": str(weak.instance_id)}, actor_id="ann")
    bot = GreedyBot("bob", "Bob")
    assert run_bots(session, {"bob": bot}, max_actions=1)
    # The stack object is complete and still waiting for responses (RULE 117.3c).
    assert eng.state.pending_choice is None and eng.state.stack
    assert eng.state.stack[-1].targets == [weak]


def test_karplusan_minotaur_lost_flip_trigger_lets_the_opponent_choose_the_damage_target():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng = _engine()
    minotaur = _put(eng, _db_card("Karplusan Minotaur"), "p1")
    mine = _put(eng, _vanilla("Mine", 3, 3), "p1")
    _put(eng, _vanilla("Theirs", 3, 3), "p2")
    eng.state.fire_event(GameEvent(EventType.COIN_FLIP, player_id="p1", won=False))
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    assert choice["category"] == "triggered_ability"
    eng.resolve_pending_choice(str(mine.instance_id))  # solo-played trigger settles straight away
    assert mine.damage_marked == 1 and minotaur.damage_marked == 0


def test_diaochan_controller_picks_one_creature_and_the_opponent_the_other():
    eng = _engine()
    diaochan = _put(eng, _db_card("Diaochan, Artful Beauty"), "p1")
    diaochan.summoning_sick = False
    mine = _put(eng, _vanilla("Mine"), "p1")
    theirs = _put(eng, _vanilla("Theirs"), "p2")
    eng.activate_ability(eng.state.player_by_id("p1"), diaochan, 0, targets=[theirs])
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    assert mine.instance_id in {o["instance_id"] for o in choice["options"]}
    eng.resolve_pending_choice(str(mine.instance_id))
    eng.resolve_until_stable()
    assert theirs.zone == Zone.GRAVEYARD and mine.zone == Zone.GRAVEYARD and diaochan.zone == Zone.BATTLEFIELD


def test_volcanic_offering_two_opponent_picks_in_a_row():
    eng = _engine()
    my_land = _put(eng, Card(id="Nb", name="Mine Land", type_line="Land", is_land=True), "p1")
    their_land = _put(eng, Card(id="Tb", name="Their Land", type_line="Land", is_land=True), "p2")
    mine = _put(eng, _vanilla("Mine", 3, 3), "p1")
    theirs = _put(eng, _vanilla("Theirs", 3, 3), "p2")
    spell = _put(eng, _db_card("Volcanic Offering"), "p1", Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("R", 5)
    reqs = requirements_with_targets(eng.state, "p1", spell)
    assert [r["kind"] for r in reqs] == ["nonbasic_land_you_dont_control", "creature_you_dont_control"]
    eng.cast_spell(p1, spell, targets=[their_land, theirs])
    assert eng.state.pending_choice["kind"] == "opponent_target"
    assert [o["instance_id"] for o in eng.state.pending_choice["options"]] == [their_land.instance_id]
    eng.resolve_pending_choice(str(their_land.instance_id))
    assert eng.state.pending_choice["kind"] == "opponent_target"
    eng.resolve_pending_choice(str(theirs.instance_id))
    eng.resolve_until_stable()
    assert their_land.zone == Zone.GRAVEYARD and theirs.zone == Zone.GRAVEYARD
    assert my_land.zone == Zone.BATTLEFIELD and mine.zone == Zone.BATTLEFIELD


def test_preacher_steals_the_opponents_pick_only_while_it_stays_tapped():
    eng = _engine()
    preacher = _put(eng, _db_card("Preacher"), "p1")
    preacher.summoning_sick = False
    theirs = _put(eng, _vanilla("Theirs"), "p2")
    eng.activate_ability(eng.state.player_by_id("p1"), preacher, 0)
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(theirs.instance_id))
    eng.resolve_until_stable()
    assert theirs.controller_id == "p1" and preacher.tapped
    eng.set_tapped(preacher, False) if hasattr(eng, "set_tapped") else eng.rules.set_tapped(preacher, False)
    eng.rules.check_state_based_actions()
    assert theirs.controller_id == "p2"


def test_arena_taps_both_and_they_fight_with_the_opponents_pick():
    eng = _engine()
    arena = _put(eng, _db_card("Magus of the Arena"), "p1")
    arena.summoning_sick = False
    mine = _put(eng, _vanilla("Mine", 3, 3), "p1")
    theirs = _put(eng, _vanilla("Theirs", 2, 2), "p2")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("R", 3)
    reqs = [(r["kind"], len(r["options"])) for r in eng._ability_target_requirements(p1, arena.activated_abilities[0], arena)]
    assert reqs == [("creature_you_control", 2)]  # the opponent's creature is not offered to the activator
    eng.activate_ability(p1, arena, 0, targets=[mine])
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2" and [o["instance_id"] for o in choice["options"]] == [theirs.instance_id]
    eng.resolve_pending_choice(str(theirs.instance_id))
    eng.resolve_until_stable()
    assert mine.tapped
    assert theirs.zone == Zone.GRAVEYARD and mine.damage_marked == 2


def test_nova_pentacle_opponent_picks_the_creature_that_takes_the_redirected_damage():
    eng = _engine()
    pentacle = _put(eng, _db_card("Nova Pentacle"), "p1")
    mine = _put(eng, _vanilla("Mine", 1, 9), "p1")
    theirs = _put(eng, _vanilla("Theirs", 4, 4), "p2")
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("C", 3)
    eng.activate_ability(p1, pentacle, 0)
    choice = eng.state.pending_choice
    assert choice["kind"] == "opponent_target" and choice["player_id"] == "p2"
    assert {o["instance_id"] for o in choice["options"]} == {mine.instance_id, theirs.instance_id}  # any creature
    eng.resolve_pending_choice(str(mine.instance_id))
    eng.resolve_until_stable()
    # The activator now chooses the source as the ability resolves.
    assert eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice(str(theirs.instance_id))
    life = p1.life
    eng.rules.deal_damage(p1, 3, source=theirs)
    assert p1.life == life and mine.damage_marked == 3
    eng.rules.deal_damage(mine, 2, source=theirs)  # redirect only rewrites damage headed for the activator
    assert mine.damage_marked == 5


def test_demonic_hordes_unpaid_upkeep_taps_it_and_the_opponent_picks_the_land():
    eng = _engine()
    hordes = _put(eng, _db_card("Demonic Hordes"), "p1")
    land_a = _put(eng, Card(id="La", name="Swamp A", type_line="Basic Land — Swamp", is_land=True), "p1")
    land_b = _put(eng, Card(id="Lb", name="Swamp B", type_line="Basic Land — Swamp", is_land=True), "p1")
    theirs = _put(eng, Card(id="Lc", name="Their Land", type_line="Basic Land — Swamp", is_land=True), "p2")
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", active_player_id="p1"))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    # Nothing to pay {B}{B}{B} with, so the "unless" branch happens straight away.
    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2" and {o["instance_id"] for o in choice["options"]} == {
        land_a.instance_id, land_b.instance_id}  # the sacrificing player's lands, picked by the opponent
    eng.resolve_pending_choice(str(land_b.instance_id))
    assert land_b.zone == Zone.GRAVEYARD and land_a.zone == Zone.BATTLEFIELD and theirs.zone == Zone.BATTLEFIELD
    assert hordes.tapped


def test_destroy_pair_spells_claimed_by_the_split_destroy_row_destroy_both_targets():
    eng = _engine()
    creature = _put(eng, _vanilla("Victim"), "p2")
    land = _put(eng, Card(id="Lv", name="Victim Land", type_line="Land", is_land=True), "p2")
    spell = _put(eng, _db_card("Spiteful Blow"), "p1", Zone.HAND)
    assert parse_oracle(_db_card("Spiteful Blow")).coverage == MODELED
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add("B", 6)
    eng.cast_spell(p1, spell, targets=[creature, land])
    eng.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD and land.zone == Zone.GRAVEYARD


def test_plague_spores_denies_regeneration_to_both_destroyed_permanents():
    from mtg_analyzer.parser.oracle.gate import parse_oracle as parse
    specs = [e for a in parse(_db_card("Plague Spores")).specs for e in a.effects]
    assert [e.type for e in specs] == ["destroy", "destroy"]
    assert all(e.params["can_be_regenerated"] is False for e in specs)
