"""BUG-67 -- "Whenever you attack" triggers once per attack declaration, not once per defending player.

RULE 508.3d: "Whenever you attack" triggers once when one or more of your creatures are declared as attackers,
however many players, planeswalkers or battles they attack.  RULE 508.3e: "Whenever you attack a player" is the
per-player form (one trigger for each player attacked).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

WAR_EFFORT = (
    "Creatures you control get +1/+0.\n"
    "Whenever you attack, create a 1/1 red Warrior creature token that's tapped and attacking. "
    "Sacrifice it at the beginning of the next end step."
)
ALORA = (
    "Whenever you attack, up to one target attacking creature can't be blocked this turn. "
    "Return that creature to its owner's hand at the beginning of the next end step."
)
DRAW_PER_ATTACK = "Whenever you attack, you gain 1 life."
DRAW_PER_PLAYER = "Whenever you attack a player, you gain 1 life."


def _engine(players=("p1", "p2", "p3")):
    eng = GameEngine.new_game([(p, p, []) for p in players], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_phase, eng.state.current_step = "combat", "declare_attackers"
    return eng


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _enchant(name, text):
    return Card(id=name, name=name, type_line="Enchantment", oracle_text=text)


def _player(pid):
    return {"kind": "player", "id": pid, "label": pid}


def _attack(eng, pairs):
    eng.declare_attackers(eng.state.active_player, [{"attacker": a, "defender": d} for a, d in pairs])
    eng._fire_player_attacked_events()


def _life(eng, pid="p1"):
    return eng.state.player_by_id(pid).life


def test_gain_life_fires_once_when_two_opponents_are_attacked():
    eng = _engine()
    _put(eng, _enchant("Probe", DRAW_PER_ATTACK))
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p3"))])
    eng.resolve_until_stable()
    assert _life(eng) == 21


def test_attack_a_player_fires_once_per_player_attacked():
    # RULE 508.3e
    eng = _engine()
    _put(eng, _enchant("Probe", DRAW_PER_PLAYER))
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p3"))])
    eng.resolve_until_stable()
    assert _life(eng) == 22


@pytest.mark.parametrize("name, text", [("War Effort", WAR_EFFORT), ("Alora, Merry Thief", ALORA)])
def test_cards_stay_modeled(name, text):
    res = parse_oracle(Card(id=name, name=name, type_line="Legendary Creature — Test", oracle_text=text))
    assert res.modeled, res.unclaimed


def test_war_effort_makes_one_token_attacking_two_opponents():
    eng = _engine()
    _put(eng, _enchant("War Effort", WAR_EFFORT))
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p3"))])
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].attacking and tokens[0].tapped


def test_alora_triggers_once_when_two_opponents_are_attacked():
    eng = _engine()
    alora = _put(eng, Card(id="Alora", name="Alora, Merry Thief", type_line="Legendary Creature — Halfling Rogue",
                           is_creature=True, power=2, toughness=2, oracle_text=ALORA))
    b = _put(eng, _bear("b"))
    _attack(eng, [(alora, _player("p2")), (b, _player("p3"))])
    eng.resolve_until_stable()
    answered = 0
    while eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        answered += 1
        eng.resolve_pending_choice(eng.state.pending_choice["options"][0]["id"])
        eng.resolve_until_stable()
    # One declaration, one trigger, so one target announcement (two would mean one per defender).
    assert answered == 1


def test_one_attacker_against_one_opponent_still_triggers():
    eng = _engine()
    _put(eng, _enchant("Probe", DRAW_PER_ATTACK))
    a = _put(eng, _bear("a"))
    _attack(eng, [(a, _player("p2"))])
    eng.resolve_until_stable()
    assert _life(eng) == 21


def test_attacking_one_opponent_with_two_creatures_fires_once():
    eng = _engine()
    _put(eng, _enchant("Probe", DRAW_PER_ATTACK))
    a, b = _put(eng, _bear("a")), _put(eng, _bear("b"))
    _attack(eng, [(a, _player("p2")), (b, _player("p2"))])
    eng.resolve_until_stable()
    assert _life(eng) == 21


GOBLIN_GROUP = "Whenever one or more Goblins you control attack, you gain 1 life."


def test_one_or_more_group_head_fires_once_across_two_defenders():
    # RULE 508.3d / 603.2c: the group-filtered head is the same once-per-declaration shape.
    eng = _engine()
    _put(eng, _enchant("Probe", GOBLIN_GROUP))
    a = _put(eng, Card(id="g1", name="G1", type_line="Creature — Goblin", is_creature=True, power=1, toughness=1))
    b = _put(eng, Card(id="g2", name="G2", type_line="Creature — Goblin", is_creature=True, power=1, toughness=1))
    _attack(eng, [(a, _player("p2")), (b, _player("p3"))])
    eng.resolve_until_stable()
    assert _life(eng) == 21
