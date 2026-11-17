"""PAR-315: effect bodies naming the defending player (RULE 506.2 / 508.1b).

Milestone 1: under an attacks / attacks-alone / isn't-blocked / becomes-blocked head, "defending player <verb>" is the
combat event's own "that player" -- the player the attacker attacks, never "an opponent" (three-player cases where the
two opponents differ prove it).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _three_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(name, oracle="", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Test", oracle_text=oracle, is_creature=True, power=power,
                toughness=toughness)


def _drain(eng):
    eng.resolve_until_stable()
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(choice["options"][0]["id"])
        eng.resolve_until_stable()


def _attack(eng, attackers, defender_id, *, blocker=None, alone_event=False):
    state = eng.state
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [
        {"attacker": a, "defender": {"kind": "player", "id": defender_id}} for a in attackers
    ])
    if alone_event:
        eng._fire_attacks_alone_event()  # fired by `advance_step` in a real turn
    _drain(eng)
    state.current_step = "declare_blockers"
    if blocker is not None:
        eng.declare_blockers(state.player_by_id(blocker.controller_id), [{"blocker": blocker, "attacker": attackers[0]}])
    else:
        eng._fire_unblocked_events()
    _drain(eng)


def _lives(state):
    return {p.id: p.life for p in state.players}


def _stock_library(state, pid, n=8):
    player = state.player_by_id(pid)
    for i in range(n):
        player.library.append(GameObject(_creature(f"Lib {pid} {i}"), owner_id=pid, zone=Zone.LIBRARY))
    return player


# -- parser -----------------------------------------------------------------------------------------------------------


def _modeled(text):
    return parse_oracle(_creature("Zed", text)).coverage == "MODELED"


@pytest.mark.parametrize("text", [
    "Whenever ~ attacks, defending player loses 2 life.",
    "Whenever ~ attacks and isn't blocked, it assigns no combat damage this turn and defending player loses 2 life.",
    "Whenever ~ becomes blocked, defending player loses 4 life.",
    "Whenever ~ becomes blocked, defending player mills 3 cards.",
    "Whenever ~ attacks alone, defending player sacrifices a creature of their choice.",
    "Whenever a creature you control attacks, defending player loses 1 life and you gain 1 life.",
    "Whenever equipped creature attacks alone, defending player loses 2 life and you gain 2 life.",
])
def test_combat_trigger_bodies_are_claimed(text):
    assert _modeled(text)


@pytest.mark.parametrize("text", [
    "Whenever ~ dies, defending player loses 2 life.",  # no combat event names a defending player
    "Whenever ~ deals combat damage to a player, defending player loses 2 life.",
    "Whenever a creature an opponent controls attacks, if you're the defending player, you gain 1 life.",
])
def test_heads_without_a_defending_player_stay_unclaimed(text):
    assert not _modeled(text)


def test_the_printed_wording_is_kept_on_the_spec():
    spec = parse_oracle(_creature("Zed", "Whenever ~ attacks, defending player loses 2 life.")).specs[0]
    assert "defending player" in spec.raw_text


def test_group_attack_head_reads_the_attacked_player_not_the_attackers_controller():
    spec = parse_oracle(_creature("Zed", "Whenever a creature you control attacks, defending player loses 1 life.")).specs[0]
    assert spec.effects[0].params["player"] == {"of": "attacked_player"}


# -- engine: three players, the two opponents differ ------------------------------------------------------------------


def test_attack_trigger_hits_the_attacked_player_only():
    eng, state = _three_player()
    atk = _put(state, _creature("Drainer", "Whenever ~ attacks, defending player loses 2 life."))
    _attack(eng, [atk], "p3")
    assert _lives(state) == {"p1": 20, "p2": 20, "p3": 18}


def test_attack_trigger_follows_a_second_attacker_to_another_defender():
    eng, state = _three_player()
    text = "Whenever ~ attacks, defending player loses 2 life."
    one, two = _put(state, _creature("A", text)), _put(state, _creature("B", text))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [
        {"attacker": one, "defender": {"kind": "player", "id": "p2"}},
        {"attacker": two, "defender": {"kind": "player", "id": "p3"}},
    ])
    _drain(eng)
    assert _lives(state) == {"p1": 20, "p2": 18, "p3": 18}  # RULE 506.2: each attacker has its own defender


def test_group_attack_trigger_drains_the_defender_and_gains_for_you():
    eng, state = _three_player()
    _put(state, Card(id="c", name="Campaign", type_line="Enchantment",
                     oracle_text="Whenever a creature you control attacks, defending player loses 1 life and you gain 1 life."))
    atk = _put(state, _creature("Grunt"))
    _attack(eng, [atk], "p2")
    assert _lives(state) == {"p1": 21, "p2": 19, "p3": 20}


def test_becomes_blocked_trigger_hits_the_blockers_controller():
    eng, state = _three_player()
    atk = _put(state, _creature("Ghoul", "Whenever ~ becomes blocked, defending player loses 4 life."))
    wall = _put(state, _creature("Wall"), "p3")
    _attack(eng, [atk], "p3", blocker=wall)
    assert _lives(state) == {"p1": 20, "p2": 20, "p3": 16}


def test_unblocked_trigger_hits_the_attacked_player():
    eng, state = _three_player()
    atk = _put(state, _creature(
        "Keeper", "Whenever ~ attacks and isn't blocked, it assigns no combat damage this turn and defending player loses 2 life."))
    _attack(eng, [atk], "p2")
    assert _lives(state) == {"p1": 20, "p2": 18, "p3": 20}


def test_becomes_blocked_mill_takes_cards_from_the_defender():
    eng, state = _three_player()
    p2, p3 = _stock_library(state, "p2"), _stock_library(state, "p3")
    atk = _put(state, _creature("Golem", "Whenever ~ becomes blocked, defending player mills 3 cards."))
    wall = _put(state, _creature("Wall"), "p3")
    _attack(eng, [atk], "p3", blocker=wall)
    assert (len(p2.library), len(p3.library)) == (8, 5)


def test_attacks_alone_sacrifice_is_the_defenders():
    eng, state = _three_player()
    atk = _put(state, _creature("Nefarox", "Whenever ~ attacks alone, defending player sacrifices a creature of their choice."))
    mine2, mine3 = _put(state, _creature("Pawn2"), "p2"), _put(state, _creature("Pawn3"), "p3")
    _attack(eng, [atk], "p3", alone_event=True)
    assert mine3.zone is Zone.GRAVEYARD and mine2.zone is Zone.BATTLEFIELD


def test_damage_body_hits_the_attacked_player_not_the_attackers_controller():
    eng, state = _three_player()
    atk = _put(state, _creature("Pinger", "Whenever ~ attacks, it deals 1 damage to defending player."))
    _attack(eng, [atk], "p3")
    assert _lives(state) == {"p1": 20, "p2": 20, "p3": 19}


def test_equipment_blocked_damage_hits_the_blocked_attackers_defender():
    eng, state = _three_player()
    atk = _put(state, _creature("Host"))
    helm = _put(state, Card(id="h", name="Helm", type_line="Artifact — Equipment", keywords=["Equip"],
                            oracle_text="Whenever equipped creature becomes blocked, it deals 1 damage to defending player.\nEquip {1}"))
    helm.attached_to = atk.instance_id
    wall = _put(state, _creature("Wall"), "p2")
    _attack(eng, [atk], "p2", blocker=wall)
    assert _lives(state) == {"p1": 20, "p2": 19, "p3": 20}


def test_aura_attack_trigger_hits_the_defender_not_the_enchanted_creatures_controller():
    eng, state = _three_player()
    atk = _put(state, _creature("Host"))
    aura = _put(state, Card(id="a", name="Curse", type_line="Enchantment — Aura",
                            oracle_text="Enchant creature\nWhenever enchanted creature attacks, defending player loses 2 life."))
    aura.attached_to = atk.instance_id
    _attack(eng, [atk], "p3")
    assert _lives(state) == {"p1": 20, "p2": 20, "p3": 18}


def test_no_defender_does_nothing():
    eng, state = _three_player()
    atk = _put(state, _creature("Idle", "Whenever ~ attacks, defending player loses 2 life."))
    state.fire_event(__import__("mtg_analyzer.models.game.events", fromlist=["GameEvent"]).GameEvent(
        "ATTACKS", instance_id=atk.instance_id, attacker=atk.name, player_id="p1", object_types=["creature"]))
    _drain(eng)
    assert _lives(state) == {"p1": 20, "p2": 20, "p3": 20}


# -- real cards -------------------------------------------------------------------------------------------------------


def _real(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


@pytest.mark.parametrize("name", [
    "Agate-Blade Assassin", "Campaign of Vengeance", "Flint Golem", "Keeper of Tresserhorn", "Nefarox, Overlord of Grixis",
    "Reaper's Talisman", "Thresher Beast", "Vedalken Ghoul", "Leeching Sliver", "Lim-Dûl's Paladin",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True
