"""PAR-284 milestone 20: combat-relation counts a creature reads about itself (RULE 506.3, 509.1a, 509.3, 107.1b).

"for each other attacking ~" (the attackers sharing the source's name), "for each creature it's blocking" and "for each
creature blocking it beyond the first" (the blockers minus the one every block has, never below zero).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_this_way_windows import _card


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.start()
    while eng.state.current_step != "declare_attackers":
        eng.advance_step()
    return eng


def _put(eng, name, oracle, owner, power=2, toughness=2):
    card = _card(name, "Creature — Beast", oracle, is_creature=True, power=power, toughness=toughness)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    attach_to_object(obj, result.specs)
    eng.state.add_to_battlefield(obj)
    return obj


AUROCHS = "Whenever this creature attacks, it gets +1/+0 until end of turn for each other attacking Aurochs."
JOHTULL = "Whenever this creature becomes blocked, it gets -2/-1 until end of turn for each creature blocking it beyond the first."
JUNGLE = "Whenever this creature becomes blocked, it gets -1/-1 until end of turn for each creature blocking it beyond the first."
GUARDIAN = "Whenever this creature blocks, it gets +1/+1 until end of turn for each creature it's blocking."


@pytest.mark.parametrize("oracle", [AUROCHS, JOHTULL, JUNGLE, GUARDIAN])
def test_real_wordings_are_modeled(oracle):
    assert parse_oracle(_card("Probe", "Creature — Beast", oracle, is_creature=True, power=2, toughness=2)).modeled


def test_aurochs_counts_only_other_attacking_namesakes():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    first = _put(eng, "Aurochs", AUROCHS, "p1")
    second = _put(eng, "Aurochs", AUROCHS, "p1")
    stranger = _put(eng, "Bison", "", "p1")
    idle = _put(eng, "Aurochs", AUROCHS, "p1")  # a namesake that does not attack is not counted
    eng.declare_attackers(p1, [first, second, stranger])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (first.power, second.power, stranger.power, idle.power) == (3, 3, 2, 2)


def _block(eng, attacker, blockers):
    p2 = eng.state.player_by_id("p2")
    eng.advance_step()  # declare_blockers
    eng.declare_blockers(p2, [{"blocker": b, "attacker": attacker} for b in blockers])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()


@pytest.mark.parametrize("oracle, blockers, power, toughness", [
    (JUNGLE, 1, 5, 5),   # one blocker is "the first": no shrink
    (JUNGLE, 3, 3, 3),   # two beyond the first: -2/-2
    (JOHTULL, 1, 5, 5),
    (JOHTULL, 3, 1, 3),  # two beyond the first: -4/-2
])
def test_beyond_the_first_blocker_shrinks_the_attacker(oracle, blockers, power, toughness):
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    wurm = _put(eng, "Wurm", oracle, "p1", power=5, toughness=5)
    guards = [_put(eng, f"Guard{i}", "", "p2", power=1, toughness=5) for i in range(blockers)]
    eng.declare_attackers(p1, [wurm])
    eng.resolve_until_stable()
    _block(eng, wurm, guards)
    assert (wurm.power, wurm.toughness) == (power, toughness)


def test_guardian_grows_for_each_creature_it_blocks():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    guardian = _put(eng, "Guardian", GUARDIAN, "p2", power=1, toughness=5)
    a = _put(eng, "A", "", "p1", power=1, toughness=5)
    b = _put(eng, "B", "", "p1", power=1, toughness=5)
    eng.declare_attackers(p1, [a, b])
    eng.advance_step()
    eng.declare_blockers(p2, [{"blocker": guardian, "attacker": a}, {"blocker": guardian, "attacker": b}])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (guardian.power, guardian.toughness) == (3, 7) or (guardian.power, guardian.toughness) == (2, 6)


@pytest.mark.parametrize("oracle", [
    "Whenever a creature you control attacks, it gets +1/+0 until end of turn for each creature it's blocking.",
    "Whenever a creature you control becomes blocked, it gets -1/-1 until end of turn for each creature blocking it beyond the first.",
])
def test_a_pronoun_that_is_not_the_source_stays_unclaimed(oracle):
    assert not parse_oracle(_card("Odd", "Enchantment", oracle)).modeled


def test_bare_blocks_is_once_per_blocker_and_blocks_a_creature_is_per_creature():
    # RULE 509.3a vs 509.3b: the second head keeps firing for each creature blocked.
    bare = parse_oracle(_card("Bare", "Creature — Beast", "Whenever this creature blocks, you gain 1 life.", is_creature=True))
    each = parse_oracle(_card("Each", "Creature — Beast", "Whenever this creature blocks a creature, you gain 1 life.", is_creature=True))
    assert not bare.specs[0].trigger.get("per_blocked_creature")
    assert each.specs[0].trigger["per_blocked_creature"] is True
