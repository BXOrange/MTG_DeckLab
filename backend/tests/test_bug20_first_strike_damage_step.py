"""BUG-20: RULE 510.4 -- first-strike damage is its own combat damage step.

A combat with a first or double striker gets a distinct ``first_strike_damage`` step before the
regular ``combat_damage`` step; each ends with SBAs (510.3a), trigger placement and a full priority
round (510.3b/117.3), so a spell cast between the two can change the second hit.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.services.game_session import MULTIPLAYER, GameSession

FIRST_STRIKE_STEP = "first_strike_damage"
START_LIFE = 20
LIFEGAIN_AMOUNT = 3
PUMP_AMOUNT = 3


def _creature(name, power, toughness, *keywords, text=""):
    return Card(id=name, name=name, type_line="Creature — Test", is_creature=True, power=power,
                toughness=toughness, keywords=list(keywords), oracle_text=text,
                mana_cost_string="{1}", converted_mana_cost=1)


def _instant(name, cost, text):
    return Card(id=name, name=name, type_line="Instant", is_instant=True, oracle_text=text,
                mana_cost_string=cost, converted_mana_cost=ManaCost.parse(cost).converted_mana_cost)


def _engine(interactive=True):
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_life=START_LIFE, starting_hand=0)
    eng.interactive_priority = interactive
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _attack(eng, attacker, blocker=None):
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.declare_attackers(p1, [attacker])
    eng.advance_step()  # declare_blockers
    eng.declare_blockers(p2, [{"blocker": blocker, "attacker": attacker}] if blocker else [])


def _life(eng, pid="p2"):
    return eng.state.player_by_id(pid).life


def _step_names(eng):
    return [s.name for _, s in eng._turn_steps]


def test_unblocked_double_striker_deals_first_hit_then_opens_priority():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    assert FIRST_STRIKE_STEP not in _step_names(eng)

    assert eng.advance_step() == ("combat", FIRST_STRIKE_STEP)
    assert eng.state.current_step == FIRST_STRIKE_STEP
    assert _life(eng) == START_LIFE - 2, "only the first-strike hit has landed"
    assert eng.state.priority_player is eng.state.active_player, "a priority window is open"
    assert eng.state.first_strike_step_combatants == [(ds.instance_id, ds.zone_incarnation)]

    assert eng.advance_step() == ("combat", "combat_damage")
    assert _life(eng) == START_LIFE - 4
    assert _step_names(eng).count("combat_damage") == 1


def test_instant_between_the_steps_changes_the_second_hit():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    pump = GameObject(_instant("Surge", "{R}", f"Target creature gets +{PUMP_AMOUNT}/+0 until end of turn."),
                      owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(pump)
    p1 = eng.state.player_by_id("p1")
    p1.hand.append(pump)
    _attack(eng, ds)
    eng.advance_step()
    assert _life(eng) == START_LIFE - 2

    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, pump, targets=[ds])
    eng.state.priority_passed.clear()
    while eng.state.stack:
        eng.pass_priority(eng.state.priority_player)
    assert ds.power == 2 + PUMP_AMOUNT

    eng.advance_step()
    assert _life(eng) == START_LIFE - 2 - (2 + PUMP_AMOUNT)


def test_first_striker_kills_blocker_before_it_deals_damage():
    eng = _engine()
    fs = _put(eng, _creature("Knight", 2, 2, "First strike"))
    blocker = _put(eng, _creature("Bear", 2, 2), "p2")
    _attack(eng, fs, blocker)

    eng.advance_step()
    assert blocker not in eng.state.battlefield, "SBAs ran before the window opened"
    assert fs.damage_marked == 0
    eng.advance_step()
    assert fs.damage_marked == 0, "the dead blocker deals nothing in the regular step"
    assert fs in eng.state.battlefield
    assert _life(eng) == START_LIFE, "a blocked first striker deals no regular damage"


def test_death_trigger_goes_on_the_stack_between_the_steps():
    eng = _engine()
    fs = _put(eng, _creature("Knight", 2, 2, "First strike"))
    blocker = _put(eng, _creature("Martyr", 2, 2,
                                  text="When Martyr dies, you gain 3 life."), "p2")
    _attack(eng, fs, blocker)

    eng.advance_step()
    assert blocker not in eng.state.battlefield
    assert eng.state.stack, "the death trigger is on the stack during the first-strike window"
    assert eng.state.current_step == FIRST_STRIKE_STEP
    while eng.state.stack:
        eng.pass_priority(eng.state.priority_player)
        eng.pass_priority(eng.state.priority_player)
    assert _life(eng) == START_LIFE + LIFEGAIN_AMOUNT


def test_combat_without_first_or_double_strike_has_a_single_damage_step():
    eng = _engine()
    bear = _put(eng, _creature("Bear", 2, 2))
    _attack(eng, bear)
    assert eng.advance_step() == ("combat", "combat_damage")
    assert FIRST_STRIKE_STEP not in _step_names(eng)
    assert eng.state.first_strike_step_combatants is None
    assert _life(eng) == START_LIFE - 2


def test_first_strike_step_survives_clone_between_the_steps():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    eng.advance_step()
    cursor = eng.step_cursor

    restored = GameEngine(eng.state.clone())
    restored.resume_at(cursor)
    assert restored.state.current_step == FIRST_STRIKE_STEP
    assert restored.state.first_strike_step_combatants == [(ds.instance_id, ds.zone_incarnation)]
    assert restored.advance_step() == ("combat", "combat_damage")
    assert restored.state.player_by_id("p2").life == START_LIFE - 4
    assert _life(eng) == START_LIFE - 2, "the original is untouched"


def test_session_undo_returns_to_the_window_between_the_steps():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    eng.advance_step()
    snapshot, cursor = eng.state.clone(), eng.step_cursor
    eng.advance_step()
    assert _life(eng) == START_LIFE - 4
    back = GameEngine(snapshot)
    back.resume_at(cursor)
    assert back.state.current_step == FIRST_STRIKE_STEP
    assert back.state.player_by_id("p2").life == START_LIFE - 2


def test_non_interactive_walk_completes_combat_with_both_hits():
    eng = _engine(interactive=False)
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    seen = []
    while eng.state.current_step != "main2":
        seen.append(eng.advance_step()[1])
    assert seen[:3] == [FIRST_STRIKE_STEP, "combat_damage", "end_combat"]
    assert _life(eng) == START_LIFE - 4


def test_direct_step_call_without_the_scheduled_step_still_deals_both_hits():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    eng._step_combat_damage()
    assert _life(eng) == START_LIFE - 4


def test_first_strike_step_shares_the_combat_damage_stop():
    from mtg_analyzer.services.game_session import STOP_STEPS
    assert FIRST_STRIKE_STEP not in STOP_STEPS and "combat_damage" in STOP_STEPS


def _pass_round(session):
    """Both seats pass in turn (RULE 117.4): with an empty stack the step ends."""
    state = session.engine.state
    for _ in range(len(state.players)):
        holder = state.priority_player
        if holder is None:
            return
        step = state.current_step
        session.apply_action({"type": "pass_priority"}, holder.id)
        if session.engine.state.current_step != step:
            return


def test_multiplayer_session_walks_both_windows_and_undo_restores_between_them():
    eng = _engine()
    ds = _put(eng, _creature("Duelist", 2, 2, "Double strike"))
    _attack(eng, ds)
    session = GameSession(eng, mode=MULTIPLAYER)
    assert session.interactive_priority

    _pass_round(session)  # declare_blockers window ends
    st = session.engine.state
    assert st.current_step == FIRST_STRIKE_STEP
    assert st.priority_player is st.active_player
    assert _life(session.engine) == START_LIFE - 2

    _pass_round(session)  # first-strike window ends
    st = session.engine.state
    assert st.current_step == "combat_damage"
    assert _life(session.engine) == START_LIFE - 4
    assert st.priority_player is st.active_player

    session.rewind(1)
    st = session.engine.state
    assert st.current_step == FIRST_STRIKE_STEP
    assert _life(session.engine) == START_LIFE - 2
    _pass_round(session)
    assert session.engine.state.current_step == "combat_damage"
    assert _life(session.engine) == START_LIFE - 4
