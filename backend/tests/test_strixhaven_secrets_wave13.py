"""Secrets of Strixhaven — playability batch, wave 13.

Two small parser widenings (PARSER_VERSION 288 -> 289):

* **"[then] you scry N"** as an effect body — `handlers.scry_or_surveil`'s
  regex gained an optional leading ``you `` so a trigger body that spells
  out the redundant subject folds to the same self `scry` EffectSpec.
* **"<subtype> spells you cast cost {N} less/more to cast"** — the
  `_SPELL_COST_TAX_YOU_CAST_RE` handler routes a single curated
  creature/Aura/Equipment/Arcane subtype word to ``spell_subtype`` (already
  resolved by `continuous.cost_reduction_for` via `has_subtype`), staying
  fail-closed on groupings ("historic", "commander").
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.continuous import cost_reduction_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- (a) "you scry N" as a body -------------------------------------------

@pytest.mark.parametrize("clause", ["you scry 2", "scry 2"])
def test_scry_body_claims_with_optional_you(clause):
    specs = match_clause(clause)
    assert [s.type for s in specs] == ["scry"]
    assert specs[0].params["count"] == 2


def test_you_surveil_body_claims():
    specs = match_clause("you surveil 1")
    assert [s.type for s in specs] == ["surveil"]
    assert specs[0].params["count"] == 1


def test_target_player_scry_still_unclaimed():
    # only the bare / "you" subject folds; a different subject must not.
    assert not match_clause("target player scry 2")


def test_psychic_impetus_modeled():
    r = parse_oracle(_db().get_card("Psychic Impetus"))
    assert r.coverage != UNMODELED, r.unclaimed


# --- (b) subtype-scoped "spells you cast cost {N} less" ------------------

@pytest.mark.parametrize("clause,sub", [
    ("aura spells you cast cost {1} less to cast", "aura"),
    ("dragon spells you cast cost {2} less to cast", "dragon"),
    ("equipment spells you cast cost {1} less to cast", "equipment"),
])
def test_subtype_cost_reduction_claimed(clause, sub):
    specs = static_effect_specs(clause)
    assert specs is not None
    assert specs[0].type == "cost_reduction"
    assert specs[0].params["spell_subtype"] == sub
    assert specs[0].params["generic"] in (1, 2)


@pytest.mark.parametrize("clause", [
    "historic spells you cast cost {1} less to cast",
    "commander spells you cast cost {1} less to cast",
])
def test_grouping_words_stay_fail_closed(clause):
    assert static_effect_specs(clause) is None


def test_main_type_and_compound_unchanged():
    assert static_effect_specs("noncreature spells you cast cost {1} more to cast")[0] \
        .params["spell_type"] == "noncreature"
    assert static_effect_specs("instant and sorcery spells you cast cost {1} less to cast")[0] \
        .params["spell_type"] == ["instant", "sorcery"]


def test_transcendent_envoy_modeled():
    r = parse_oracle(_db().get_card("Transcendent Envoy"))
    assert r.coverage != UNMODELED, r.unclaimed


def test_subtype_cost_reduction_applies_at_runtime():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    envoy = GameObject(
        card=Card(id="te", name="Transcendent Envoy",
                  type_line="Creature — Human Cleric", is_creature=True,
                  power=2, toughness=2,
                  oracle_text="Aura spells you cast cost {1} less to cast."),
        owner_id=p1.id, zone=Zone.BATTLEFIELD)
    envoy.controller_id = p1.id
    eng.state.add_to_battlefield(envoy)
    bind_from_catalogue(envoy)
    eng.recompute_continuous_effects()
    aura = GameObject(card=Card(id="au", name="A", type_line="Enchantment — Aura",
                                mana_cost_string="{2}{W}"),
                      owner_id=p1.id, zone=Zone.STACK)
    aura.controller_id = p1.id
    bear = GameObject(card=Card(id="b", name="B", type_line="Creature — Bear",
                                mana_cost_string="{1}{G}"),
                      owner_id=p1.id, zone=Zone.STACK)
    bear.controller_id = p1.id
    assert cost_reduction_for(eng.state, p1, aura)[0] == 1
    assert cost_reduction_for(eng.state, p1, bear)[0] == 0
