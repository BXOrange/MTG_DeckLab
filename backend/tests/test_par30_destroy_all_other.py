"""PAR-30 (Vote residue) — self-excluding mass destroy.

"Destroy all other creatures." / "…all creatures other than ~" / "…all
creatures except [for] ~" (Novablast Wurm, Mageta the Lion, Magister of
Worth's condemnation vote branch) — RULE 400's "other" = every creature
but this effect's own source, whoever controls it. Plus the
controller-scoped sibling "destroy all other creatures you control"
(Desolation Giant). New `all_other_creatures` / `other_creatures_you_
control` selectors on `effects._mass_selector_objects`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, pid):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse --------------------------------------------------------------


def test_all_other_creatures_phrasings():
    for text in ("destroy all other creatures",
                 "destroy all creatures other than ~",
                 "destroy all creatures except for ~",
                 "destroy all creatures except ~"):
        assert match_clause(text) == [
            EffectSpec("destroy", {"selector": "all_other_creatures"})
        ], text


def test_other_creatures_you_control_phrasing():
    assert match_clause("destroy all other creatures you control") == [
        EffectSpec("destroy", {"selector": "other_creatures_you_control"})
    ]


def test_regen_tail_is_claimed():
    assert match_clause(
        "destroy all creatures except for ~. those creatures can't be regenerated"
    ) == [EffectSpec("destroy", {"selector": "all_other_creatures",
                                 "can_be_regenerated": False})]


def test_plain_destroy_all_creatures_still_includes_the_source():
    assert match_clause("destroy all creatures") == [
        EffectSpec("destroy", {"selector": "all_creatures"})
    ]


def test_novablast_wurm_modeled():
    c = Card(id="NBW", name="Novablast Wurm",
             type_line="Creature — Wurm", is_creature=True, power=7, toughness=7,
             oracle_text=("Flying, trample\nWhenever Novablast Wurm attacks, "
                          "destroy all other creatures."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -----------------------------------------------------------


def test_all_other_creatures_spares_the_source_only():
    eng, state = _engine()
    src = _creature(state, "Novablast Wurm", "p1")
    mine = _creature(state, "Ally", "p1")
    theirs = _creature(state, "Foe", "p2")

    build_effects([EffectSpec("destroy", {"selector": "all_other_creatures"})], src)[0].apply(
        GameContext(state, eng.rules), None
    )

    assert src in state.battlefield
    assert mine not in state.battlefield
    assert theirs not in state.battlefield


def test_other_creatures_you_control_spares_the_source_and_opponents():
    eng, state = _engine()
    src = _creature(state, "Desolation Giant", "p1")
    mine = _creature(state, "Ally", "p1")
    theirs = _creature(state, "Foe", "p2")

    build_effects(
        [EffectSpec("destroy", {"selector": "other_creatures_you_control"})], src
    )[0].apply(GameContext(state, eng.rules), None)

    assert src in state.battlefield
    assert mine not in state.battlefield
    assert theirs in state.battlefield
