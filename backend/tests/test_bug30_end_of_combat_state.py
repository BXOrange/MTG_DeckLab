"""BUG-30: combat state survives the end of combat step's priority window (RULE 511.2-3)."""
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.counters_tokens import GrantUntilEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import EventType

LAND = Card(id="Forest", name="Forest", type_line="Basic Land - Forest", is_land=True)


def _bear(name):
    return Card(id=name, name=name, type_line="Creature - Bear", is_creature=True, power=2, toughness=5)


def _setup():
    eng = GameEngine.new_game([("p1", "p1", [LAND]), ("p2", "p2", [LAND])], starting_life=20, starting_hand=0)
    eng.start()
    objs = []
    for name, ctrl in (("Attacker", "p1"), ("Blocker", "p2")):
        obj = GameObject(_bear(name), owner_id=ctrl, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        eng.state.add_to_battlefield(obj)
        bind_from_catalogue(obj)
        objs.append(obj)
    return eng, objs[0], objs[1]


def _advance_to(eng, step):
    for _ in range(60):
        if eng.state.current_step == step:
            return
        eng.advance_step()
    raise AssertionError(step)


def _attack(eng, attacker, blocker=None):
    _advance_to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])
    if blocker is not None:
        _advance_to(eng, "declare_blockers")
        eng.declare_blockers(eng.state.player_by_id("p2"), [{"blocker": blocker, "attacker": attacker}])


def _flying_until_eoc(eng, creature):
    GrantUntilEffect(static={"type": "grant_keyword", "params": {"keywords": ["flying"]}},
                     duration="end_of_combat", target_kind="creature").apply(eng.rules.context, [creature])
    eng.recompute_continuous_effects()


def _has_flying(eng, creature):
    eng.recompute_continuous_effects()
    return any(k.lower() == "flying" for k in creature.granted_keywords)


def test_end_of_combat_trigger_and_priority_still_see_attackers_and_blockers():
    eng, attacker, blocker = _setup()
    seen = []
    eng.state.subscribe(lambda e: seen.append((attacker.attacking, blocker.blocking is not None))
                        if e.type == EventType.STEP_BEGIN and e.get("step") == "end_combat" else None)
    _attack(eng, attacker, blocker)
    _advance_to(eng, "end_combat")
    assert seen == [(True, True)]
    # The priority window itself: still in combat.
    assert attacker.attacking and blocker.blocking == attacker.instance_id
    assert eng.state.end_combat_cleanup_pending


def test_until_end_of_combat_effect_active_in_step_and_gone_at_next_step():
    eng, attacker, _ = _setup()
    _attack(eng, attacker)
    _flying_until_eoc(eng, attacker)
    assert _has_flying(eng, attacker)
    _advance_to(eng, "end_combat")
    assert _has_flying(eng, attacker)
    eng.advance_step()
    assert eng.state.current_step == "main2"
    assert not _has_flying(eng, attacker)


def test_combat_cleared_after_leaving_step_and_turn_history_kept():
    eng, attacker, blocker = _setup()
    _attack(eng, attacker, blocker)
    _advance_to(eng, "end_combat")
    eng.advance_step()
    assert not attacker.attacking and attacker.combat_defender is None
    assert blocker.blocking is None and not attacker.blocked_by
    assert not eng.state.end_combat_cleanup_pending
    assert attacker.attacked_this_turn  # "attacked this turn" history is unchanged
    assert attacker.last_combat_attacked_ids == {"p2"}


def test_second_combat_starts_clean():
    eng, attacker, _ = _setup()
    _attack(eng, attacker)
    _advance_to(eng, "end_combat")
    eng.insert_additional_combat_phase()
    eng.advance_step()
    assert not attacker.attacking
    _advance_to(eng, "begin_combat")
    assert not attacker.attacking and attacker.combat_defender is None
    assert not eng.state.end_combat_cleanup_pending
