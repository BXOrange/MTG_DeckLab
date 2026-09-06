"""Bug report, 2026-09-04: Equip could be activated at instant speed.

RULE 702.6c/702.32b/702.151c: "Equip [cost]"/"Fortify [cost]"/"Reconfigure
[cost]" each expand to "[Cost]: Attach this permanent to target creature
[/land] you control. **Activate only as a sorcery.**" —
`effect_binder._keyword_activated_ability` parsed the printed cost but
never actually set `ActivationCost.sorcery_speed_only`, so
`GameEngine.can_activate`/`_sorcery_speed_ok` never rejected an
off-turn/non-empty-stack/non-main-phase activation. Fixed by stamping the
flag right alongside the mana-cost parse, for all three attach-style
keywords (`_keyword_activated_ability` builds all of them through the same
code path).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _equipment(name="Colossus Hammer", cost="{2}"):
    return Card(
        id=name, name=name, type_line="Artifact — Equipment", keywords=["Equip"],
        oracle_text=f"Equipped creature gets +10/+10.\nEquip {cost}",
    )


def _fortification(name="Bastion Protector"):
    return Card(
        id=name, name=name, type_line="Artifact — Fortification", keywords=["Fortify"],
        oracle_text="Enchanted land has \"{T}: Add one mana of any color.\"\nFortify {2}",
    )


def _reconfigurable(name="Kellan's Lightblades"):
    return Card(
        id=name, name=name, type_line="Artifact Creature — Equipment", keywords=["Reconfigure"],
        is_creature=True, power=1, toughness=1,
        oracle_text="Equipped creature gets +1/+1.\nReconfigure {2}",
    )


def _creature(state, name="Host", controller="p1"):
    card = Card(id=name, name=name, type_line="Creature — Human", is_creature=True,
                power=2, toughness=2)
    return _bf(state, card, controller)


def _land(state, name="Mountain", controller="p1"):
    card = Card(id=name, name=name, type_line="Basic Land — Mountain", is_land=True)
    return _bf(state, card, controller)


def test_equip_keyword_ability_is_sorcery_speed_only():
    eng = _engine()
    equip = _equipment()
    obj = GameObject(equip, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    [ability] = obj.activated_abilities
    assert ability.cost.sorcery_speed_only is True


def test_reconfigure_keyword_ability_is_sorcery_speed_only():
    eng = _engine()
    obj = GameObject(_reconfigurable(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    [ability] = obj.activated_abilities
    assert ability.cost.sorcery_speed_only is True


def test_fortify_keyword_ability_is_sorcery_speed_only():
    eng = _engine()
    obj = GameObject(_fortification(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    [ability] = obj.activated_abilities
    assert ability.cost.sorcery_speed_only is True


def test_equip_is_legal_in_the_controllers_own_main_phase():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    sword = _bf(eng.state, _equipment())
    host = _creature(eng.state)
    p1.mana_pool.add("C", 2)

    [ability] = sword.activated_abilities
    assert eng.can_activate(p1, sword, ability) is True
    eng.activate_ability(p1, sword, 0, targets=[host])
    eng.resolve_until_stable()
    assert sword.attached_to == host.instance_id


def test_equip_is_illegal_with_a_nonempty_stack():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    sword = _bf(eng.state, _equipment())
    _creature(eng.state)
    p1.mana_pool.add("C", 2)
    [ability] = sword.activated_abilities

    # A pointless-but-nonempty stack (RULE 602.5a's "activate only as a
    # sorcery" bars this regardless of what's actually on it).
    eng.state.stack.append(object())
    assert eng.can_activate(p1, sword, ability) is False


def test_equip_is_illegal_outside_a_main_phase():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    sword = _bf(eng.state, _equipment())
    _creature(eng.state)
    p1.mana_pool.add("C", 2)
    [ability] = sword.activated_abilities

    for step in ("upkeep", "draw", "begin_combat", "declare_attackers",
                 "declare_blockers", "combat_damage", "end_combat", "end", "cleanup"):
        eng.state.current_step = step
        assert eng.can_activate(p1, sword, ability) is False, step


def test_equip_is_illegal_on_an_opponents_turn():
    eng = _engine()
    eng.begin_turn()  # p1's turn
    eng.begin_turn()  # p2's turn
    assert eng.state.active_player.id == "p2"
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    sword = _bf(eng.state, _equipment())
    _creature(eng.state)
    p1.mana_pool.add("C", 2)
    [ability] = sword.activated_abilities

    assert eng.can_activate(p1, sword, ability) is False


def test_reconfigure_is_illegal_at_instant_speed():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "combat_damage"
    p1 = eng.state.active_player
    blade = _bf(eng.state, _reconfigurable())
    _creature(eng.state)
    p1.mana_pool.add("C", 2)
    [ability] = blade.activated_abilities
    assert eng.can_activate(p1, blade, ability) is False


def test_fortify_is_illegal_at_instant_speed():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "declare_blockers"
    p1 = eng.state.active_player
    fort = _bf(eng.state, _fortification())
    _land(eng.state)
    p1.mana_pool.add("C", 2)
    [ability] = fort.activated_abilities
    assert eng.can_activate(p1, fort, ability) is False


def test_legal_actions_do_not_offer_equip_outside_a_main_phase():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    p1 = eng.state.active_player
    _bf(eng.state, _equipment())
    _creature(eng.state)
    p1.mana_pool.add("C", 2)

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "activate_ability"]
    assert offered == []
