"""MEC-87 — Horsemanship (RULE 702.31), the PAR-22 evasion family's own
one-keyword-later sibling: already a recognized flag keyword (a real row
in `parser/oracle/catalogue/keywords.py`) but with zero engine enforcement
before this ticket. One-directional unlike Shadow: a horsemanship
attacker can't be blocked by a non-horsemanship creature, but a
horsemanship creature can itself block anything.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, keywords=None, power=2, toughness=2, oracle_text=""):
    return Card(
        id=name, name=name, type_line="Creature — Human", is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_horsemanship_still_parses_as_a_flag_keyword():
    card = _creature("Shu Cavalry", keywords=["Horsemanship"])
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert "horsemanship" in combat._obj_keywords(obj)


def test_horsemanship_attacker_cannot_be_blocked_by_plain_creature():
    attacker = GameObject(_creature("Wu Scout", keywords=["Horsemanship"]), owner_id="p1")
    blocker = GameObject(_creature("Grizzly Bears"), owner_id="p2")
    bind_from_catalogue(attacker)
    bind_from_catalogue(blocker)
    assert not combat.can_block(attacker, blocker)


def test_horsemanship_attacker_can_be_blocked_by_horsemanship_creature():
    attacker = GameObject(_creature("Wu Scout", keywords=["Horsemanship"]), owner_id="p1")
    blocker = GameObject(_creature("Shu Cavalry", keywords=["Horsemanship"]), owner_id="p2")
    bind_from_catalogue(attacker)
    bind_from_catalogue(blocker)
    assert combat.can_block(attacker, blocker)


def test_horsemanship_creature_can_block_a_plain_attacker():
    # One-directional (unlike Shadow): a horsemanship creature is not
    # restricted in what it can itself block.
    attacker = GameObject(_creature("Grizzly Bears"), owner_id="p1")
    blocker = GameObject(_creature("Shu Cavalry", keywords=["Horsemanship"]), owner_id="p2")
    bind_from_catalogue(attacker)
    bind_from_catalogue(blocker)
    assert combat.can_block(attacker, blocker)


def test_engine_declare_blockers_refuses_illegal_horsemanship_block():
    eng = _engine()
    state = eng.state
    attacker = _put(state, _creature("Wu Scout", keywords=["Horsemanship"]))
    blocker = _put(state, _creature("Grizzly Bears"), controller="p2")
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()
    assert state.current_step == "declare_blockers"
    defender = state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker}])


def test_riding_the_dilu_horse_permanent_pump_and_grant():
    card = Card(
        id="Riding the Dilu Horse", name="Riding the Dilu Horse",
        type_line="Sorcery", mana_cost_string="{2}{W}", converted_mana_cost=3,
        is_sorcery=True,
        oracle_text=(
            "Target creature gets +2/+2 and gains horsemanship. "
            "(It can't be blocked except by creatures with horsemanship. "
            "This effect lasts indefinitely.)"
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    specs = result.specs
    assert len(specs) == 1
    effect = specs[0].effects[0]
    assert effect.type == "grant_until"
    assert effect.params["duration"] == "rest_of_game"
    assert effect.params["static"]["params"]["power"] == 2
    assert effect.params["static"]["params"]["toughness"] == 2
    assert effect.params["extra_statics"][0]["params"]["keywords"] == ["horsemanship"]
