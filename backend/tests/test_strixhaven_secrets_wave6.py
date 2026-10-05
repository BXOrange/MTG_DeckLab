"""Secrets of Strixhaven — playability batch, wave 6.

Wave 6: the **"target nonbasic land"** target-kind gap.
- `subgrammars._TARGET_ROWS` + `handlers._SINGLE_TYPE_PERMANENT_KINDS` learn
  `nonbasic_land` / `nonbasic_land_you_dont_control` (the engine's
  `targeting.legal_targets` already had the branch).
- Ghost-Quarter follow-up widened for "…put it onto the battlefield
  **tapped**, then shuffle" (White Orchid Phantom).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_resolve_target_kind_nonbasic_land():
    assert resolve_target_kind("target nonbasic land") == "nonbasic_land"
    assert resolve_target_kind("target nonbasic land an opponent controls") == \
        "nonbasic_land_you_dont_control"
    assert resolve_target_kind("target nonbasic land you don't control") == \
        "nonbasic_land_you_dont_control"


@pytest.mark.parametrize("name", [
    "Fulminator Mage", "Dust Bowl", "Ravenous Baboons", "Wasteland",
    "White Orchid Phantom",
])
def test_nonbasic_land_cards_now_modeled(name):
    c = _db().get_card(name)
    if c is None:
        pytest.skip(f"{name} not cached")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, (name, r.unclaimed)


def test_white_orchid_phantom_search_destination_tapped():
    r = parse_oracle(_db().get_card("White Orchid Phantom"))
    trig = [s for s in r.specs if s.trigger][0]
    types = [e.type for e in trig.effects]
    assert "destroy" in types and "search" in types
    search = [e for e in trig.effects if e.type == "search"][0]
    assert search.params["destination"] == "battlefield_tapped"
    assert search.params["player"] == "previous_target_controller"


def _land(state, name, pid, basic=False):
    tl = f"Basic Land — {name}" if basic else "Land"
    o = GameObject(Card(id=name + pid, name=name, type_line=tl, is_land=True),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_legal_targets_nonbasic_land_excludes_basics():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    plains = _land(eng.state, "Plains", p2.id, basic=True)
    nonbasic_opp = _land(eng.state, "Command Tower", p2.id)
    nonbasic_own = _land(eng.state, "Bojuka Bog", p1.id)

    any_nb = {t["instance_id"] for t in legal_targets(
        eng.state, p1.id, TargetSpec(kind="nonbasic_land"))}
    assert nonbasic_opp.instance_id in any_nb
    assert nonbasic_own.instance_id in any_nb
    assert plains.instance_id not in any_nb

    opp_nb = {t["instance_id"] for t in legal_targets(
        eng.state, p1.id, TargetSpec(kind="nonbasic_land_you_dont_control"))}
    assert opp_nb == {nonbasic_opp.instance_id}
