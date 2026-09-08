"""PAR-30 — "put a <filter> creature card from your hand onto the
battlefield [tapped and attacking]".

`_put_from_hand` gained a creature-subtype filter ("Soldier creature
card" → `{"type": "soldier"}`, "Angel, Demon, or Dragon creature card" →
`{"type": [...]}`) and a colour filter ("blue or red creature card" →
`{"color": [...]}`), plus an optional "…tapped and attacking" tail (RULE
508.4). `PutFromHandOntoBattlefieldEffect.attacking` routes through the new
`"battlefield_attacking"` search destination.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse -----------------------------------------------------------------


def test_subtype_creature_filter_parses():
    assert match_clause(
        "put a soldier creature card from your hand onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield",
                    {"criteria": {"type": "soldier"}, "count": 1})]


def test_multi_subtype_or_filter_parses():
    assert match_clause(
        "you may put an angel, demon, or dragon creature card from your hand "
        "onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield",
                    {"criteria": {"type": ["angel", "demon", "dragon"]}, "count": 1})]


def test_colour_creature_filter_parses():
    assert match_clause(
        "you may put a blue or red creature card from your hand onto the battlefield"
    ) == [EffectSpec("put_from_hand_onto_battlefield",
                    {"criteria": {"color": ["U", "R"]}, "count": 1})]


def test_tapped_and_attacking_tail_parses():
    assert match_clause(
        "you may put a soldier creature card from your hand onto the "
        "battlefield tapped and attacking"
    ) == [EffectSpec("put_from_hand_onto_battlefield",
                    {"criteria": {"type": "soldier"}, "count": 1,
                     "tapped": True, "attacking": True})]


def test_derived_quality_fails_closed():
    # "historic" / "multicolored" have no clean card_query key.
    assert match_clause(
        "you may put a historic permanent card from your hand onto the battlefield"
    ) is None
    assert match_clause(
        "you may put a multicolored creature card from your hand onto the battlefield"
    ) is None


def test_preeminent_captain_modeled():
    c = Card(id="pc", name="Preeminent Captain",
             type_line="Creature — Kithkin Soldier", is_creature=True,
             power=2, toughness=2, oracle_text=(
                 "First strike\nWhenever Preeminent Captain attacks, you may "
                 "put a Soldier creature card from your hand onto the "
                 "battlefield tapped and attacking."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -------------------------------------------------------------------


def test_battlefield_attacking_destination_enters_tapped_and_attacking():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    src = GameObject(Card(id="src", name="Captain", type_line="Creature — Soldier",
                          is_creature=True, power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    grunt = GameObject(Card(id="g", name="Grunt", type_line="Creature — Soldier",
                            is_creature=True, power=1, toughness=1),
                       owner_id="p1", zone=Zone.HAND)
    p1.hand.append(grunt)

    events: list = []
    state.subscribe(lambda e: events.append(e))
    build_effects([EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": "soldier"}, "count": 1,
        "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(state, eng.rules), None)
    # resolve the "up to one" hand pick — take the one grunt
    pending = state.pending_choice
    assert pending is not None
    opt = next(o for o in pending["options"] if o.get("instance_id") == grunt.instance_id)
    eng.resolve_pending_choice(opt["id"])

    assert grunt in state.battlefield
    assert grunt.tapped is True
    assert grunt.attacking is True
    assert (grunt.combat_defender or {}).get("id") == "p2"
    assert any(e.type == EventType.ATTACKS
               and e.get("instance_id") == grunt.instance_id for e in events)
