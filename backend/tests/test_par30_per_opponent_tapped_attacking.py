"""PAR-30 "Tapped and attacking" — the per-opponent distributive form.

"**For each opponent**, [you] create a … token[ that's tapped and attacking
that opponent]." (Endless Foot Assault, Stampede Surfer). The effect's
controller makes one token per opponent; with `attacking`, each token is
put into combat against a *distinct* opponent — RULE 508.4a's defender
choice made per token rather than by the shared auto-pick.

New `CreateTokenEffect.per_opponent`; a leading `for each opponent, ` group
on the inline `create_token` handler row.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine(n=3):
    seats = [(f"p{i+1}", name, []) for i, name in enumerate(["Alice", "Bob", "Cara", "Dave"][:n])]
    eng = GameEngine.new_game(seats, starting_life=20, starting_hand=0)
    return eng, eng.state


# --- parse ----------------------------------------------------------------


def test_for_each_opponent_tapped_attacking_parses():
    specs = match_clause(
        "for each opponent, create a 1/1 black ninja creature token "
        "that's tapped and attacking that player"
    )
    assert specs is not None
    p = specs[0].params
    assert p["per_opponent"] is True
    assert p["tapped"] is True and p["attacking"] is True


def test_for_each_opponent_you_create_parses():
    specs = match_clause(
        "for each opponent, you create a 2/2 green boar creature token "
        "that's tapped and attacking that opponent"
    )
    assert specs is not None and specs[0].params["per_opponent"] is True


def test_plain_for_each_opponent_no_attacking_parses():
    specs = match_clause("for each opponent, create a 2/1 black zombie creature token")
    assert specs == [EffectSpec("create_token", {
        "count": 1, "power": 2, "toughness": 1, "colors": ["B"],
        "subtypes": ["Zombie"], "keywords": [], "token_name": "Zombie",
        "per_opponent": True,
    })]


def test_ordinary_create_token_unaffected():
    specs = match_clause("create a 1/1 white soldier creature token")
    assert specs is not None
    assert "per_opponent" not in specs[0].params


# --- real cards ---------------------------------------------------------


def test_endless_foot_assault_modeled():
    c = Card(id="efa", name="Endless Foot Assault", type_line="Enchantment",
             oracle_text=("Whenever you attack, for each opponent, create a 1/1 "
                          "black Ninja creature token that's tapped and attacking "
                          "that player."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_stampede_surfer_modeled():
    c = Card(id="ss", name="Stampede Surfer", type_line="Creature — Merfolk",
             is_creature=True, oracle_text=(
                 "Whenever Stampede Surfer attacks, for each opponent, you create "
                 "a 2/2 green Boar creature token that's tapped and attacking that "
                 "opponent."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute ----------------------------------------------------------


def test_one_token_per_opponent_each_attacking_its_own():
    eng, st = _engine(n=3)
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    build_effects([EffectSpec("create_token", {
        "count": 1, "power": 1, "toughness": 1, "colors": ["B"],
        "subtypes": ["Ninja"], "keywords": [],
        "per_opponent": True, "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(st, eng.rules), [])

    toks = [o for o in st.battlefield if o.name == "Ninja"]
    assert len(toks) == 2  # p2, p3 — not p1
    assert all(t.controller_id == "p1" for t in toks)
    assert all(t.tapped and getattr(t, "attacking", False) for t in toks)
    assert {(t.combat_defender or {}).get("id") for t in toks} == {"p2", "p3"}


def test_two_player_game_single_token():
    eng, st = _engine(n=2)
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    build_effects([EffectSpec("create_token", {
        "count": 1, "power": 2, "toughness": 2, "colors": ["G"],
        "subtypes": ["Boar"], "keywords": [],
        "per_opponent": True, "tapped": True, "attacking": True,
    })], src)[0].apply(GameContext(st, eng.rules), [])

    toks = [o for o in st.battlefield if o.name == "Boar"]
    assert len(toks) == 1
    assert (toks[0].combat_defender or {}).get("id") == "p2"
