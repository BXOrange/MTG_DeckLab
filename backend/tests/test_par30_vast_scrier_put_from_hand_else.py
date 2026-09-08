"""PAR-30 "copy of a named card" body singletons (v196) — The Vast Scrier.

`PutFromHandOntoBattlefieldEffect` / `request_search` gain
`then_specs_if_none` — "If you don't put a card onto the battlefield this
way, `<body>`." runs `<body>` (here `scry 2`) when the from-hand pick
places nothing: declined in `resolve_search_choice`, or nothing eligible
in `request_search`. The "if it has any 'whenever ~ attacks' triggers,
those trigger" reminder sentence is consumed as a no-op (the engine
re-fires ATTACKS for the placed creature via
`put_onto_battlefield_attacking` already).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import EffectSpec, ParserProvenance


def _segment(text):
    return segment_line(
        text, allow_spell_effect=False, provenance=ParserProvenance.from_dict({})
    )


# --- parse -----------------------------------------------------------


def test_vast_scrier_body_threads_miss_effect_specs():
    seg = _segment(
        'whenever ~ attacks a player, you may put a soldier, warrior, or '
        'wizard creature card from your hand onto the battlefield tapped and '
        'attacking that player. if it has any "whenever ~ attacks" triggers, '
        'those trigger. if you don\'t put a card onto the battlefield this '
        "way, scry 2."
    )
    assert seg.claimed
    (eff,) = seg.spec.effects
    assert eff.type == "put_from_hand_onto_battlefield"
    assert eff.params["criteria"] == {"type": ["soldier", "warrior", "wizard"]}
    assert eff.params["tapped"] and eff.params["attacking"]
    assert eff.params["miss_effect_specs"] == [{"type": "scry", "params": {"count": 2}}]


def test_plain_put_from_hand_still_has_no_miss_specs():
    seg = _segment(
        "whenever ~ attacks an opponent, you may put an angel, demon, or "
        "dragon creature card from your hand onto the battlefield tapped and "
        "attacking that opponent."
    )
    assert seg.claimed
    assert "miss_effect_specs" not in seg.spec.effects[0].params


def test_vast_scrier_modeled():
    c = Card(
        id="vs", name="The Vast Scrier", type_line="Legendary Creature — Spirit",
        is_creature=True,
        oracle_text=(
            "Flying\nWhenever The Vast Scrier attacks a player, you may put a "
            "Soldier, Warrior, or Wizard creature card from your hand onto the "
            "battlefield tapped and attacking that player. If it has any "
            '"Whenever this creature attacks" triggers, those trigger. If you '
            "don't put a card onto the battlefield this way, scry 2."
        ),
    )
    assert parse_oracle(c).coverage != UNMODELED


# --- execute -------------------------------------------------------


def _mk():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    src = GameObject(
        Card(id="vs", name="The Vast Scrier",
             type_line="Legendary Creature — Spirit", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    for i in range(3):
        o = GameObject(Card(id=f"lib{i}", name=f"Lib{i}",
                            type_line="Creature — Bear"),
                       owner_id="p1", zone=Zone.LIBRARY)
        o.controller_id = "p1"
        eng.state.player_by_id("p1").library.append(o)
    return eng, src


_SPEC = [EffectSpec("put_from_hand_onto_battlefield", {
    "criteria": {"type": ["soldier", "warrior", "wizard"]},
    "count": 1, "tapped": True, "attacking": True,
    "miss_effect_specs": [{"type": "scry", "params": {"count": 2}}],
})]


def test_scry_fires_when_nothing_eligible():
    eng, src = _mk()  # empty hand
    build_effects(_SPEC, src)[0].apply(eng.rules.context, None)
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["kind"] == "scry"


def test_scry_fires_when_player_declines():
    eng, src = _mk()
    sol = GameObject(Card(id="s", name="Grunt", type_line="Creature — Soldier",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.HAND)
    sol.controller_id = "p1"
    eng.state.player_by_id("p1").hand.append(sol)
    build_effects(_SPEC, src)[0].apply(eng.rules.context, None)
    assert eng.state.pending_choice["kind"] == "search"
    eng.rules.resolve_search_choice(None)  # decline
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["kind"] == "scry"


def test_no_scry_when_a_card_is_placed():
    eng, src = _mk()
    sol = GameObject(Card(id="s", name="Grunt", type_line="Creature — Soldier",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.HAND)
    sol.controller_id = "p1"
    eng.state.player_by_id("p1").hand.append(sol)
    build_effects(_SPEC, src)[0].apply(eng.rules.context, None)
    eng.rules.resolve_search_choice(sol.instance_id)
    assert sol in eng.state.battlefield and sol.attacking and sol.tapped
    assert eng.state.pending_choice is None


def test_search_without_miss_specs_is_unaffected():
    eng, src = _mk()
    spec = [EffectSpec("put_from_hand_onto_battlefield", {
        "criteria": {"type": ["soldier"]}, "count": 1, "tapped": True,
        "attacking": True,
    })]
    build_effects(spec, src)[0].apply(eng.rules.context, None)
    # empty hand, no miss specs → nothing pending, no crash
    assert eng.state.pending_choice is None
