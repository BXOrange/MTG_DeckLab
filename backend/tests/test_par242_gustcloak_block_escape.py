"""PAR-242 -- "Whenever ~ becomes blocked, you may untap it and remove it from combat" (Gustcloak cycle, RULE 506.4)."""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle import parse_oracle

from tests.test_par119_attack_batch_head import _attackers
from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _put

ORACLE = "Whenever ~ becomes blocked, you may untap it and remove it from combat."


@pytest.mark.parametrize("name", ["Gustcloak Harrier", "Gustcloak Runner", "Gustcloak Sentinel", "Gustcloak Skirmisher"])
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def _blocked_combat(accept):
    engine, state = _engine()
    cloak = _put(state, ORACLE, name="Cloak", types="Creature — Soldier")
    cloak.summoning_sick = False
    blocker = _attackers(state, [("Wall", "Creature — Bear", ())], owner="p2")[0]
    state.current_step = "declare_attackers"
    engine.declare_attackers(state.active_player, [cloak])
    assert cloak.tapped
    state.current_step = "declare_blockers"
    engine.declare_blockers(state.player_by_id("p2"), [{"blocker": blocker, "attacker": cloak}])
    return engine, state, cloak, blocker


def _resolve(engine, state, answer):
    engine.resolve_until_stable()
    assert state.pending_choice is not None and state.pending_choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(answer)  # RULE 603.5's "you may"
    engine.resolve_until_stable()


def test_yes_untaps_and_removes_from_combat_blocker_stays_blocking():
    engine, state, cloak, blocker = _blocked_combat(True)
    _resolve(engine, state, "do")
    assert not cloak.tapped and not cloak.attacking
    assert blocker.blocking is None  # RULE 506.4: nothing blocks a creature that left combat
    assert blocker in state.battlefield
    state.current_step = "combat_damage"
    engine._deal_combat_damage_step(False)
    assert cloak.damage_marked == 0 and blocker.damage_marked == 0
    assert cloak in state.battlefield and blocker in state.battlefield


def test_declining_leaves_it_tapped_attacking_and_blocked():
    engine, state, cloak, blocker = _blocked_combat(False)
    _resolve(engine, state, "decline")
    assert cloak.tapped and cloak.attacking
    assert blocker.blocking == cloak.instance_id
    state.current_step = "combat_damage"
    engine._deal_combat_damage_step(False)
    assert cloak.damage_marked == 2 and blocker.damage_marked == 2  # the 2/2s trade blows
