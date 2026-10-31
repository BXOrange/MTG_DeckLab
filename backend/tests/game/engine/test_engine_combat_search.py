"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest

from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.game.effects.core import DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine


from engine_test_helpers import land, creature, instant, make_engine, obj_on_battlefield, planeswalker, _search_one


def test_summoning_sick_creature_cannot_attack():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature())
    bear.summoning_sick = True
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [bear])


def test_attackers_deal_damage_to_opponent():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.tapped
    assert bear.attacking
    # The sole opponent is auto-assigned as the defender (no ambiguity).
    assert bear.combat_defender == {"kind": "player", "id": "p2", "label": "Bob"}
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p2").life == 17


def test_solo_goldfish_swing_has_no_defender_and_deals_no_damage():
    eng = make_engine([land()], hand=0)  # one player, no opponent
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    assert eng.legal_defenders_for(eng.state.active_player) == []
    eng.declare_attackers(eng.state.active_player, [bear])
    assert bear.attacking and bear.tapped
    assert bear.combat_defender is None  # bare swing
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()


def test_ambiguous_defender_requires_explicit_choice():
    # Two opponents → the engine won't guess; a bare declaration is illegal.
    libs = [("p1", "A", [land()]), ("p2", "B", [land()]), ("p3", "C", [land()])]
    eng = GameEngine.new_game(libs, starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    with pytest.raises(ValueError):
        eng.declare_attackers(eng.state.active_player, [bear])
    # Naming a defender resolves it; that opponent takes the damage.
    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": bear, "defender": {"kind": "player", "id": "p3", "label": "C"}}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    assert eng.state.player_by_id("p3").life == 17
    assert eng.state.player_by_id("p2").life == 20


def test_attack_planeswalker_removes_loyalty():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    walker = obj_on_battlefield(eng.state, eng, planeswalker(loyalty=5), controller="p2")
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    defenders = eng.legal_defenders_for(eng.state.active_player)
    # The opponent AND their planeswalker are both legal defenders.
    assert {d["kind"] for d in defenders} == {"player", "planeswalker"}
    eng.declare_attackers(
        eng.state.active_player,
        [{"attacker": bear, "defender": {"kind": "planeswalker", "instance_id": walker.instance_id}}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # RULE 306.9: 3 combat damage removes 3 loyalty counters (5 → 2).
    assert walker.loyalty == 2
    assert eng.state.player_by_id("p2").life == 20


def test_blocked_attacker_hits_blocker_not_player():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=3, toughness=3))
    blocker = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    eng.declare_attackers(eng.state.active_player, [attacker])

    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}])
    assert blocker.blocking == attacker.instance_id
    assert attacker.blocked_by == [blocker.instance_id]

    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # Player took no damage; the 2/2 blocker died to 3 damage; the 3/3
    # attacker survived with 2 marked.
    assert eng.state.player_by_id("p2").life == 20
    assert blocker not in eng.state.battlefield
    assert attacker in eng.state.battlefield
    assert attacker.damage_marked == 2


def test_blockers_can_gang_up_and_trade():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=4, toughness=4))
    b1 = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    b2 = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2), controller="p2")
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    p2 = eng.state.player_by_id("p2")
    eng.declare_blockers(
        p2,
        [{"blocker": b1, "attacker": attacker}, {"blocker": b2, "attacker": attacker}],
    )
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()
    # 4 power split 2+2 kills both blockers; 4 toughness takes 4 → attacker dies too.
    assert b1 not in eng.state.battlefield
    assert b2 not in eng.state.battlefield
    assert attacker not in eng.state.battlefield


def test_attacking_player_cannot_declare_blockers():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    attacker = obj_on_battlefield(eng.state, eng, creature(power=2))
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    blocker = obj_on_battlefield(eng.state, eng, creature(), controller="p1")
    with pytest.raises(ValueError):
        # p1 is the attacker; it can't block its own attack.
        eng.declare_blockers(eng.state.active_player, [{"blocker": blocker, "attacker": attacker}])


def test_counters_annihilate_via_sba():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    frog = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2))
    frog.add_counters("+1/+1", 2)
    frog.add_counters("-1/-1", 1)
    eng.rules.check_state_based_actions()
    # 704.5q removes one of each → net +1/+1; a 3/3 survivor.
    assert frog.counters == {"+1/+1": 1}
    assert frog.power == 3 and frog.toughness == 3


def test_minus_counters_can_be_lethal():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    frog = obj_on_battlefield(eng.state, eng, creature(power=2, toughness=2))
    frog.add_counters("-1/-1", 2)  # 0 toughness
    eng.rules.check_state_based_actions()
    assert frog not in eng.state.battlefield


def test_commander_combat_damage_is_tracked_and_21_is_lethal():
    eng = make_engine([land()], [land()], life=40, hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    cmdr = obj_on_battlefield(eng.state, eng, creature(name="Cmdr", power=7, toughness=7))
    cmdr.is_commander = True
    p2 = eng.state.player_by_id("p2")
    # Three 7-damage swings = 21 commander damage → p2 loses to commander
    # damage while still at 19 life (nowhere near dead on life alone).
    for _ in range(3):
        cmdr.tapped = False
        # RULE 511.3: end the previous fake "combat" before starting the
        # next one — `declare_attackers` (2026-09-04 fix) now refuses to
        # redeclare a creature still marked `attacking` from an uncleared
        # combat, same as the real engine's own `_clear_combat` would have
        # done between two genuine combats.
        cmdr.attacking = False
        eng.state.current_step = "declare_attackers"
        eng.declare_attackers(eng.state.active_player, [cmdr])
        eng.state.current_step = "combat_damage"
        eng._step_combat_damage()
    entry = next(iter(p2.commander_damage.values()))
    assert entry["amount"] == 21 and entry["name"] == "Cmdr"
    assert p2.has_lost and p2.loss_reason == "commander_damage"


def test_noncombat_damage_is_not_commander_damage():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    cmdr = obj_on_battlefield(eng.state, eng, creature(name="Cmdr", power=3))
    cmdr.is_commander = True
    p2 = eng.state.player_by_id("p2")
    eng.rules.deal_damage(p2, 5, source=cmdr, combat=False)  # a burn spell, say
    assert p2.commander_damage == {}
    assert p2.life == 15


def test_first_turn_draw_can_be_toggled():
    # Two players (so 103.7a applies); default skip, then opt onto the draw.
    eng = make_engine([land("Forest")] * 5, [land("Forest")] * 5, hand=0)
    eng.state.skip_first_draw = True
    eng.start()
    for _ in range(3):  # untap, upkeep, draw (skipped)
        eng.advance_step()
    assert len(eng.state.player_by_id("p1").hand) == 0

    eng2 = make_engine([land("Forest")] * 5, [land("Forest")] * 5, hand=0)
    eng2.state.skip_first_draw = False
    eng2.start()
    for _ in range(3):  # untap, upkeep, draw (happens)
        eng2.advance_step()
    assert len(eng2.state.player_by_id("p1").hand) == 1


def test_end_combat_removes_creatures_from_combat():
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    bear = obj_on_battlefield(eng.state, eng, creature(power=3))
    eng.declare_attackers(eng.state.active_player, [bear])
    assert eng.attackers == [bear]
    eng._step_end_combat()
    eng._finish_end_combat()  # RULE 511.3: removal happens as the step ends (BUG-30)
    assert eng.attackers == []
    assert not bear.attacking and bear.combat_defender is None


def test_goldfish_plays_lands_and_attacks_over_several_turns():
    lib = [land("Forest")] * 20 + [creature()] + [land("Forest")] * 6
    eng = make_engine(lib, [land("Forest")] * 40, life=20, hand=7)
    for _ in range(6):
        if eng.state.game_over:
            break
        eng.run_goldfish_turn()
    # The bear is drawn early, cast, and eventually swings for 2.
    creatures = [o.name for o in eng.state.battlefield if o.is_creature]
    assert "Grizzly Bears" in creatures
    assert eng.state.player_by_id("p2").life < 20


def test_rules_engine_can_be_constructed_standalone():
    state = GameState(players=[Player(id="p1")])
    engine = RulesEngine(state)
    assert engine.state is state


def test_search_opens_a_choice_then_moves_the_chosen_card():
    lib = [land("Forest"), creature("Bear A"), land("Forest"), creature("Bear B")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player

    eng.rules._request_search(p1, "Creature", "hand")
    choice = eng.state.pending_choice
    assert choice["kind"] == "search"
    assert {e["name"] for e in choice["eligible"]} == {"Bear A", "Bear B"}

    chosen = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    assert eng.state.pending_choice is None
    assert any(o.instance_id == chosen for o in p1.hand)
    assert len(p1.library) == 3


def test_search_with_no_match_just_shuffles_no_choice():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand")  # no creatures in library
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_search_can_be_declined():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand")
    eng.rules.resolve_choice(None)  # decline
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0


def test_resolve_until_stable_stops_on_pending_choice():
    from mtg_analyzer.game.effects.core import SearchLibraryEffect
    from mtg_analyzer.models.game.game_state import StackItem

    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    ability = SearchLibraryEffect(type_restriction="Creature", player=p1)
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[ability]))

    eng.resolve_until_stable()
    # Resolving the ability opened a search — the loop paused for the choice.
    assert eng.state.pending_choice is not None
    assert not eng.state.stack


def test_search_for_a_basic_land():
    lib = [creature("Bear"), land("Forest"), land("Island", produces="Island")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Forest", "Island"}


def test_search_for_a_subtype_or_list_like_farseek():
    lib = [land("Forest"), land("Island", produces="Island"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"type": ["Plains", "Island"]}, "battlefield_tapped")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Island"}


def test_search_for_any_card():
    lib = [land("Forest"), creature("Bear"), instant("Shock")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "", "hand")  # "search for a card"
    assert len(eng.state.pending_choice["eligible"]) == 3


def test_search_bounded_by_mana_value():
    lib = [creature("Bear", cost="{1}{G}"), creature("Dragon", cost="{4}{R}{R}")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"type": "Creature", "max_mana_value": 3}, "battlefield")
    names = {e["name"] for e in eng.state.pending_choice["eligible"]}
    assert names == {"Bear"}


def test_search_to_battlefield_tapped():
    eng = make_engine([land("Forest")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, {"basic": True}, "battlefield_tapped")
    obj = eng.state.find_object(chosen)
    assert obj in eng.state.battlefield and obj.tapped


def test_search_to_top_of_library_shuffles_first_then_places():
    lib = [land("Forest"), land("Forest"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "library_top")
    assert p1.library[-1].instance_id == chosen  # end of list == top of deck
    assert len(p1.library) == 3


def test_search_to_bottom_of_library():
    lib = [land("Forest"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "library_bottom")
    assert p1.library[0].instance_id == chosen


def test_search_to_graveyard_like_entomb():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "graveyard")
    assert any(o.instance_id == chosen for o in p1.graveyard)


def test_search_to_exile():
    eng = make_engine([creature("Bear")], hand=0)
    p1 = eng.state.active_player
    chosen = _search_one(eng, p1, "Creature", "exile")
    assert any(o.instance_id == chosen for o in p1.exile)


def test_search_for_up_to_two_cards_reopens_the_choice():
    lib = [land("Forest"), land("Island", produces="Island"), creature("Bear")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand", count=2)

    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(first)
    # Still one to go: the choice re-opened, excluding the first pick.
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["remaining"] == 1
    assert first not in {e["instance_id"] for e in eng.state.pending_choice["eligible"]}

    second = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(second)
    assert eng.state.pending_choice is None
    hand_ids = {o.instance_id for o in p1.hand}
    assert {first, second} <= hand_ids


def test_up_to_n_can_stop_early_by_declining():
    lib = [land("Forest"), land("Island", produces="Island")]
    eng = make_engine(lib, hand=0)
    p1 = eng.state.active_player
    eng.rules._request_search(p1, {"basic": True}, "hand", count=2)
    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(first)
    eng.rules.resolve_choice(None)  # stop after one
    assert eng.state.pending_choice is None
    assert len(p1.hand) == 1


def test_search_reopen_stops_when_library_exhausted():
    eng = make_engine([creature("Bear")], hand=0)  # only one match
    p1 = eng.state.active_player
    eng.rules._request_search(p1, "Creature", "hand", count=3)
    only = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(only)
    # No further eligible cards, so the search finishes rather than looping.
    assert eng.state.pending_choice is None
    assert any(o.instance_id == only for o in p1.hand)


def test_shuffle_library_fires_a_shuffle_event():
    eng = make_engine([land("Forest")] * 5, hand=0)
    p1 = eng.state.active_player
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.type))
    eng.rules.shuffle_library(p1)
    assert EventType.SHUFFLE in seen


def test_search_announces_and_shuffles():
    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    seen = []
    eng.state.subscribe(lambda e: seen.append(e.type))
    eng.rules._request_search(p1, "Creature", "hand")  # nothing matches
    assert EventType.LIBRARY_SEARCHED in seen
    assert EventType.SHUFFLE in seen


def test_gain_life_effect():
    eng = make_engine([land()], hand=0)
    p1 = eng.state.active_player
    before = p1.life
    eng.rules.gain_life(p1, 5)
    assert p1.life == before + 5


def test_counter_spell_removes_it_from_the_stack():
    from mtg_analyzer.models.game.game_state import StackItem

    eng = make_engine([land()], hand=0)
    bear = GameObject(creature(), owner_id="p1", zone=Zone.STACK)
    item = StackItem(kind="spell", controller_id="p1", obj=bear, description="Grizzly Bears")
    eng.state.stack.append(item)

    eng.rules.counter_spell(bear)
    assert item not in eng.state.stack
    assert bear in eng.state.player_by_id("p1").graveyard


def test_pass_priority_resolves_one_stack_object_at_a_time():
    from mtg_analyzer.models.game.game_state import StackItem
    from mtg_analyzer.game.effects.core import DrawCardEffect

    eng = make_engine([land("Forest"), land("Forest")], hand=0)
    p1 = eng.state.active_player
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))
    eng.state.stack.append(StackItem(kind="ability", controller_id="p1", effects=[DrawCardEffect(1, player=p1)]))

    assert eng.pass_priority() is True  # resolves the top one
    assert len(eng.state.stack) == 1
    assert eng.pass_priority() is True
    assert len(eng.state.stack) == 0
    assert eng.pass_priority() is False
