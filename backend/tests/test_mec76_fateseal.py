"""MEC-76 — Fateseal (RULE 701.29a).

`RulesEngine.fateseal(player, count, opponent=None, source=None)` is scry
aimed at an opponent's library: `player` looks at the top `count` cards of
an opponent's library and puts any number on the bottom, the rest back on
top in any order. It reuses scry/surveil's whole `_look_at_top` /
`_look_top_choice` / `_resume_look_top` / `_finish_look_top` decision chain,
which now threads a `library_owner` distinct from the choosing `player`
(carried on the choice as `library_owner_id`, absent — and identical to
`player_id` — for scry/surveil). The opponent is auto-picked (first living
opponent), a documented simplification like `ClashEffect`'s.

`effects.FateSealEffect` (registered `fateseal`) is the resolve-time effect;
`EventType.FATESEALED` fires before the decision for convention parity.
Parser: `handlers._fateseal` claims "fateseal N" / "you fateseal N".

Reference: game/rules/search_mixin.py (`fateseal`, `_look_at_top`),
game/effects/core.py (`FateSealEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    eng.state.current_step = "main1"
    return eng


def _fill_library(state, pid, n):
    names = []
    for i in range(n):
        c = Card(id=f"{pid}L{i}", name=f"{pid}-Card{i}", type_line="Sorcery", is_sorcery=True)
        o = GameObject(c, owner_id=pid, zone=Zone.LIBRARY)
        state.player_by_id(pid).add_to_zone(o, Zone.LIBRARY)
        names.append(c.name)
    return names  # index 0 = bottom, index -1 = top (Player.library is bottom-first)


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- primitive -----------------------------------------------------------


def test_fateseal_looks_at_the_opponents_library_not_your_own():
    eng = _engine()
    _fill_library(eng.state, "p1", 3)
    opp_names = _fill_library(eng.state, "p2", 4)
    p1_before = [o.card.name for o in eng.state.player_by_id("p1").library]

    eng.rules.fateseal(eng.state.player_by_id("p1"), 2)

    pc = eng.state.pending_choice
    assert pc["kind"] == "fateseal"
    assert pc["player_id"] == "p1"          # the fatesealer decides
    assert pc["library_owner_id"] == "p2"   # the opponent's library
    # options are p2's top two cards, top first
    assert [o["label"] for o in pc["options"] if o["id"] != "decline"] == \
        [opp_names[-1], opp_names[-2]]
    # p1's own library is untouched
    assert [o.card.name for o in eng.state.player_by_id("p1").library] == p1_before


def test_fateseal_bottoms_the_chosen_card_on_the_opponents_library():
    eng = _engine()
    opp = _fill_library(eng.state, "p2", 4)  # bottom→top: C0,C1,C2,C3
    eng.rules.fateseal(eng.state.player_by_id("p1"), 2)

    pc = eng.state.pending_choice
    top_card = next(o for o in pc["options"] if o.get("label") == opp[-1])
    eng.resolve_pending_choice(int(top_card["instance_id"]))  # send C3 to the bottom
    if eng.state.pending_choice:                              # order phase for C2
        eng.resolve_pending_choice(None)                      # leave it on top

    after = [o.card.name for o in eng.state.player_by_id("p2").library]
    assert after[0] == opp[-1]        # C3 now on the bottom
    assert after[-1] == opp[-2]       # C2 still on top


def test_fateseal_fires_fatesealed_event_with_opponent_id():
    eng = _engine()
    _fill_library(eng.state, "p2", 3)
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.FATESEALED else None
    )
    eng.rules.fateseal(eng.state.player_by_id("p1"), 2)
    assert len(fired) == 1
    assert fired[0].data == {"player_id": "p1", "count": 2, "opponent_id": "p2"}


def test_fateseal_with_empty_opponent_library_is_a_noop_but_still_fires():
    eng = _engine()  # p2's library left empty
    fired = []
    eng.state.subscribe(
        lambda e: fired.append(e) if e.type == EventType.FATESEALED else None
    )
    eng.rules.fateseal(eng.state.player_by_id("p1"), 3)
    assert fired[0].data["count"] == 0
    assert eng.state.pending_choice is None


def test_fateseal_count_larger_than_library_looks_at_what_is_there():
    eng = _engine()
    _fill_library(eng.state, "p2", 2)
    eng.rules.fateseal(eng.state.player_by_id("p1"), 5)
    pc = eng.state.pending_choice
    assert len([o for o in pc["options"] if o["id"] != "decline"]) == 2


def test_scry_still_looks_at_your_own_library_unchanged():
    eng = _engine()
    _fill_library(eng.state, "p1", 3)
    eng.rules.scry(eng.state.player_by_id("p1"), 2)
    pc = eng.state.pending_choice
    assert pc["kind"] == "scry"
    assert pc["player_id"] == "p1"
    assert "library_owner_id" not in pc  # absent for scry — same person


# --- effect + parser ---------------------------------------------------


def test_fateseal_effect_registered_and_classified():
    assert EffectRegistry.is_registered("fateseal")
    assert isa.EFFECT_TYPES["fateseal"].instruction == "fateseal"


def test_fateseal_clause_parses():
    assert match_clause("fateseal 2") == [EffectSpec("fateseal", {"count": 2})]
    assert match_clause("you fateseal 1") == [EffectSpec("fateseal", {"count": 1})]
    assert match_clause("fateseal") is None


def test_spin_into_myth_modeled_end_to_end():
    card = _db().get_card("Spin into Myth")
    assert card is not None
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert any(e.type == "fateseal" for s in result.specs for e in s.effects)


def test_mesmeric_sliver_quoted_grant_parses_with_a_fateseal_body():
    # "All Slivers have \"When this permanent enters, you may fateseal 1.\""
    # — the quoted-ability grant reaches MODELED because the inner
    # "you may fateseal 1" body now parses. (Whether the *group* quoted-grant
    # then executes end to end is separate `grant_triggered_ability`
    # machinery, exercised elsewhere; MEC-76 only added the fateseal body.)
    card = _db().get_card("Mesmeric Sliver")
    assert card is not None
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    import json
    blob = json.dumps([s.to_dict() for s in result.specs])
    assert '"fateseal"' in blob
