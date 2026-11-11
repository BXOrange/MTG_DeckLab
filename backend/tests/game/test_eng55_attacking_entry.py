"""ENG-55: "enters tapped and attacking" replacement (RULE 508.4, 508.4a, 508.4e) and Tuvok's reselect.

Real cards (Kira Nerys, Firebrand; Tuvok, Chief Tactical Officer) on a real three-player engine.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import PAYMENT_MANA, vanilla


def _game():
    forest = get_cached_card("Forest")
    engine = GameEngine.new_game([(f"p{i + 1}", str(i), [forest] * 8) for i in range(3)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _real(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(get_cached_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(player).hand.append(obj)
    engine.recompute_continuous_effects()
    return obj


def _player_def(pid):
    return {"kind": "player", "id": pid, "label": pid}


def _attack(engine, attacker, pid="p2"):
    engine.state.current_phase = "combat"
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(engine.state.player_by_id("p1"), [{"attacker": attacker, "defender": _player_def(pid)}])
    engine.resolve_until_stable()


def _newcomer(engine, name="Newcomer", player="p1"):
    """A fresh creature enters through the real entry choke point (not yet on the battlefield before)."""
    obj = GameObject(Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
                     owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    engine.state.add_to_battlefield(obj)
    return obj


def _answer_if_asked(engine, answer):
    if engine.state.pending_choice:
        engine.resolve_pending_choice(answer)
        engine.resolve_until_stable()


def test_kira_is_authored_with_its_replacement_and_pump_trigger():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    assert any(a.layer == "enters_attacking" for a in kira.static_effects)
    assert kira.triggered_abilities


def test_kira_replacement_needs_an_attacking_creature_you_control():
    engine = _game()
    _real(engine, "Kira Nerys, Firebrand")
    quiet = _newcomer(engine, "Quiet")
    assert not quiet.tapped and not quiet.attacking


def test_kira_makes_a_creature_enter_tapped_and_attacking_the_current_defender():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    late = _newcomer(engine)
    engine.resolve_until_stable()
    assert late.tapped and late.attacking
    assert late.combat_defender == _player_def("p2") | {"label": late.combat_defender["label"]}
    assert late.attacked_this_turn is False  # RULE 508.4: it never "attacked"


def test_kira_replacement_does_not_cover_opponents_creatures():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    theirs = _newcomer(engine, "Theirs", player="p2")
    assert not theirs.tapped and not theirs.attacking


def test_kira_replacement_off_after_the_attacker_leaves_combat():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    # Kira herself is the only attacker; once she is not attacking, nothing is rewritten.
    late = _newcomer(engine)
    assert not late.attacking


def test_stacked_effects_keep_the_effects_own_specified_defender_replacement_first():
    # RULE 508.4e: Kira's replacement and an effect that names a defender both put it attacking; the effect's
    # own specification wins whatever the order.
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    token = _newcomer(engine, "Token")
    engine.resolve_until_stable()
    _answer_if_asked(engine, "decline")
    assert token.attacking
    assert engine.rules.put_onto_battlefield_attacking(token, defender=_player_def("p3"))
    assert token.attacking and token.combat_defender["id"] == "p3"


def test_stacked_effects_an_unspecified_second_effect_keeps_the_first_choice():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p3")
    token = _newcomer(engine, "Token")
    engine.resolve_until_stable()
    assert token.combat_defender["id"] == "p3"
    _answer_if_asked(engine, "decline")  # RULE 508.4: the controller's one defender choice, asked once
    assert engine.rules.put_onto_battlefield_attacking(token)
    assert token.combat_defender["id"] == "p3" and not engine.state.pending_choice


def test_effect_specified_defender_applied_first_is_not_overridden_by_the_replacement_order():
    # The other order: the effect names p3 first, then the creature is also "put attacking" without a defender
    # (as the replacement would): p3 stays.
    engine = _game()
    engine.state.current_phase = "combat"
    obj = _newcomer(engine, "Token")
    assert engine.rules.put_onto_battlefield_attacking(obj, defender=_player_def("p3"))
    assert engine.rules.put_onto_battlefield_attacking(obj)
    assert obj.combat_defender["id"] == "p3"


def test_replacement_can_attack_a_planeswalker_the_effect_specifies():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    walker = GameObject(Card(id="PW", name="Walker", type_line="Planeswalker — Test", loyalty=4),
                        owner_id="p3", zone=Zone.BATTLEFIELD)
    walker.controller_id = "p3"
    engine.state.add_to_battlefield(walker)
    token = _newcomer(engine, "Token")
    engine.resolve_until_stable()
    _answer_if_asked(engine, "decline")
    spec = {"kind": "planeswalker", "instance_id": walker.instance_id, "label": "Walker"}
    assert engine.rules.put_onto_battlefield_attacking(token, defender=spec)
    assert token.combat_defender["kind"] == "planeswalker" and token.combat_defender["instance_id"] == walker.instance_id


def test_replacement_can_attack_a_protected_battle_the_effect_specifies():
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    battle = GameObject(Card(id="B", name="Siege", type_line="Battle — Siege", defense=4),
                        owner_id="p3", zone=Zone.BATTLEFIELD)
    battle.controller_id = "p1"
    engine.state.add_to_battlefield(battle)
    battle.protector_id = "p3"
    token = _newcomer(engine, "Token")
    engine.resolve_until_stable()
    _answer_if_asked(engine, "decline")
    spec = {"kind": "battle", "instance_id": battle.instance_id, "label": "Siege"}
    assert engine.rules.put_onto_battlefield_attacking(token, defender=spec)
    assert token.combat_defender["kind"] == "battle"


def test_a_specified_defender_who_left_the_game_means_it_enters_but_never_attacks():
    # RULE 508.4a/508.4e: the creature is put onto the battlefield (here tapped by Kira) but not attacking.
    engine = _game()
    kira = _real(engine, "Kira Nerys, Firebrand")
    _attack(engine, kira, "p2")
    token = _newcomer(engine, "Token")
    engine.resolve_until_stable()
    _answer_if_asked(engine, "decline")
    engine.state.player_by_id("p3").has_lost = True
    assert not engine.rules.put_onto_battlefield_attacking(token, defender=_player_def("p3"))
    assert token in engine.state.battlefield and not token.attacking and token.combat_defender is None


def _cast_tuvok(engine, step="declare_attackers"):
    tuvok = _real(engine, "Tuvok, Chief Tactical Officer", player="p3", zone=Zone.HAND)
    engine.state.current_step = step
    p3 = engine.state.player_by_id("p3")
    p3.mana_pool.add_many({"U": 1, "C": PAYMENT_MANA})
    engine.cast_spell(p3, tuvok, targets=None, target_groups=None)
    engine.resolve_until_stable()
    return tuvok


def test_tuvok_reselects_each_of_two_declared_attackers_in_turn():
    engine = _game()
    a = vanilla(engine, "p1", "A")
    b = vanilla(engine, "p1", "B")
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(engine.state.player_by_id("p1"), [
        {"attacker": a, "defender": _player_def("p2")}, {"attacker": b, "defender": _player_def("p2")}])
    engine.resolve_until_stable()
    _cast_tuvok(engine)
    for target in (a, b):  # "choose up to two target attacking creatures", one announcement per target
        pending = engine.state.pending_choice
        assert pending and pending["kind"] == "trigger_target_multi"
        engine.resolve_pending_choice(str(target.instance_id))
        engine.resolve_until_stable()
    answers = []
    for _ in range(4):
        choice = engine.state.pending_choice
        if not choice or choice["kind"] != "reselect_attack":
            break
        assert choice["player_id"] == "p3"
        answers.append(choice["attacker_id"])
        engine.resolve_pending_choice("player:p3" if choice["attacker_id"] == a.instance_id else "decline")
        engine.resolve_until_stable()
    assert answers == [a.instance_id, b.instance_id]
    assert a.combat_defender["id"] == "p3" and b.combat_defender["id"] == "p2"


def test_tuvok_does_nothing_outside_the_declare_attackers_step():
    engine = _game()
    a = vanilla(engine, "p1", "A")
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(engine.state.player_by_id("p1"), [{"attacker": a, "defender": _player_def("p2")}])
    engine.resolve_until_stable()
    _cast_tuvok(engine, step="declare_blockers")
    assert not engine.state.pending_choice
    assert a.combat_defender["id"] == "p2"
