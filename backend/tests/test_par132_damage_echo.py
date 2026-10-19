"""PAR-132 -- damage-echo bodies on the damage-event "that much" axis, executed in the real engine (RULE 120.3).

An Aura's "~ deals that much damage to that creature['s controller]" / "it deals that much damage to its controller"
(Binding Agony, Backfire, Guilty Conscience, Spiteful Shadows) and "each opponent gains that much life" (Grollub).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state, eng.state.players[0], eng.state.players[1]


def _host(state, controller: str, toughness: int = 6) -> GameObject:
    obj = GameObject(Card(id="host", name="Host", type_line="Creature — Ox", is_creature=True, power=2,
                          toughness=toughness), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _aura(state, text: str, host: GameObject, controller: str = "p1") -> GameObject:
    card = Card(id="aura", name="Echo", type_line="Enchantment — Aura", oracle_text=text)
    assert parse_oracle(card).coverage != UNMODELED, parse_oracle(card).unclaimed
    aura = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    aura.controller_id = controller
    aura.attached_to = host.instance_id
    state.add_to_battlefield(aura)
    bind_from_catalogue(aura)
    return aura


def _damage(eng, target, amount: int, source: GameObject) -> None:
    eng.rules.context.deal_damage(target, amount, source)
    eng.resolve_until_stable()


def _ping_source(state) -> GameObject:
    src = GameObject(Card(id="ping", name="Ping", type_line="Instant"), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    return src


def test_binding_agony_damages_the_hosts_controller_for_the_damage_dealt():
    eng, state, p1, p2 = _engine()
    host = _host(state, "p2")
    _aura(state, "Enchant creature\nWhenever enchanted creature is dealt damage, ~ deals that much damage to "
                 "that creature's controller.", host)
    _damage(eng, host, 3, _ping_source(state))
    assert p2.life == 17
    assert p1.life == 20


def test_binding_agony_ignores_damage_to_other_creatures():
    eng, state, p1, p2 = _engine()
    host = _host(state, "p2")
    other = _host(state, "p2")
    _aura(state, "Enchant creature\nWhenever enchanted creature is dealt damage, ~ deals that much damage to "
                 "that creature's controller.", host)
    _damage(eng, other, 3, _ping_source(state))
    assert p2.life == 20


def test_guilty_conscience_damages_the_host_itself():
    eng, state, p1, p2 = _engine()
    host = _host(state, "p2", toughness=10)
    _aura(state, "Enchant creature\nWhenever enchanted creature deals damage, ~ deals that much damage to that "
                 "creature.", host)
    _damage(eng, p1, 3, host)
    assert host.damage_marked == 3
    assert p1.life == 17


def test_spiteful_shadows_host_deals_the_damage_to_its_controller():
    eng, state, p1, p2 = _engine()
    host = _host(state, "p2", toughness=10)
    _aura(state, "Enchant creature\nWhenever enchanted creature is dealt damage, it deals that much damage to "
                 "its controller.", host)
    _damage(eng, host, 4, _ping_source(state))
    assert p2.life == 16


def test_backfire_damages_the_hosts_controller_when_the_host_hurts_the_auras_controller():
    eng, state, p1, p2 = _engine()
    host = _host(state, "p2")
    _aura(state, "Enchant creature\nWhenever enchanted creature deals damage to you, ~ deals that much damage to "
                 "that creature's controller.", host)
    _damage(eng, p1, 2, host)
    assert p1.life == 18
    assert p2.life == 18
    _damage(eng, p2, 2, host)  # damage to its own controller is not "to you"
    assert p1.life == 18


def test_grollub_each_opponent_gains_the_damage_dealt():
    eng, state, p1, p2 = _engine()
    grollub = GameObject(Card(id="gr", name="Grollub", type_line="Creature — Beast", is_creature=True, power=1,
                              toughness=9,
                              oracle_text="Whenever ~ is dealt damage, each opponent gains that much life."),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    grollub.controller_id = "p1"
    assert parse_oracle(grollub.card).coverage != UNMODELED
    state.add_to_battlefield(grollub)
    bind_from_catalogue(grollub)
    _damage(eng, grollub, 3, _ping_source(state))
    assert p2.life == 23
    assert p1.life == 20
