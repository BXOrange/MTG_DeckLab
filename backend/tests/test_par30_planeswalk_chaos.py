"""PAR-30 (Vote residue) — "planeswalk" / "chaos ensues" outcome bodies.

The two branch bodies of Path of the Animist / Path of the Enigma's
"Starting with you, each player votes for planeswalk or chaos. …" vote,
reached through `_vote_majority`'s `parse_effect_body`. Two new no-param
effect types wrapping `RulesEngine.planeswalk` (RULE 901.10) and the new
`RulesEngine.trigger_chaos` (RULE 901.13, factored out of
`roll_planar_die`). Both no-op outside a Planechase game.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import variants
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _plane(name, owner_id="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Plane — Dominaria", layout="planar"),
        owner_id=owner_id, zone=Zone.COMMAND,
    )
    bind_from_catalogue(obj)
    return obj


def _engine(fmt="planechase"):
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0, game_format=fmt,
    )


# --- parse ---------------------------------------------------------------


def test_bare_bodies_parse():
    assert match_clause("planeswalk") == [EffectSpec("planeswalk", {})]
    assert match_clause("chaos ensues") == [EffectSpec("chaos_ensues", {})]


def test_qualified_planeswalk_stays_fail_closed():
    assert match_clause("planeswalk to pools of becoming") is None
    assert match_clause("you may planeswalk") is None


def test_path_of_the_animist_vote_outcome_modeled():
    c = Card(id="PoA", name="Path of the Animist", type_line="Sorcery", is_sorcery=True,
             oracle_text=(
                 "Starting with you, each player votes for planeswalk or chaos. "
                 "If planeswalk gets more votes, planeswalk. If chaos gets more "
                 "votes or the vote is tied, chaos ensues."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed
    vote = next(e for s in res.specs for e in s.effects if e.type == "vote")
    assert vote.params["majority_specs"][0] == [{"type": "planeswalk", "params": {}}]
    assert vote.params["majority_specs"][1] == [{"type": "chaos_ensues", "params": {}}]
    assert vote.params["tie_index"] == 1


# --- execute -----------------------------------------------------------------


def test_planeswalk_effect_moves_the_plane():
    eng = _engine()
    eng.state.planar_deck = [_plane("Under"), _plane("Top")]
    src = GameObject(Card(id="s", name="Src", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    assert variants.active_plane(eng.state).name == "Top"
    build_effects([EffectSpec("planeswalk", {})], src)[0].apply(
        GameContext(eng.state, eng.rules), None
    )
    assert variants.active_plane(eng.state).name == "Under"


def test_chaos_ensues_effect_fires_the_event_for_the_active_plane():
    eng = _engine()
    eng.state.planar_deck = [_plane("Top")]
    src = GameObject(Card(id="s", name="Src", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))

    build_effects([EffectSpec("chaos_ensues", {})], src)[0].apply(
        GameContext(eng.state, eng.rules), None
    )
    chaos = [e for e in seen if e.type == EventType.CHAOS_ENSUED]
    assert len(chaos) == 1
    assert chaos[0]["plane"] == "Top"


def test_bodies_are_a_no_op_outside_planechase():
    eng = _engine(fmt=None)
    src = GameObject(Card(id="s", name="Src", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))

    for spec in ("planeswalk", "chaos_ensues"):
        build_effects([EffectSpec(spec, {})], src)[0].apply(
            GameContext(eng.state, eng.rules), None
        )
    assert not [e for e in seen if e.type in
                (EventType.CHAOS_ENSUED, EventType.PLANESWALKED_TO)]


def test_planeswalk_or_chaos_vote_applies_the_leader_branch():
    eng = _engine()
    eng.state.planar_deck = [_plane("Under"), _plane("Top")]
    src = GameObject(Card(id="s", name="Src", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules.request_vote(
        source=src, controller_id="p1", options=["planeswalk", "chaos"],
        majority_specs=[
            [{"type": "planeswalk", "params": {}}],
            [{"type": "chaos_ensues", "params": {}}],
        ],
        tie_index=1,
    )
    eng.resolve_pending_choice("0")   # p1 -> planeswalk
    eng.resolve_pending_choice("0")   # p2 -> planeswalk  => 2-0
    assert variants.active_plane(eng.state).name == "Under"
