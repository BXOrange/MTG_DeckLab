"""PAR-34 — two RULE 613.6 / 613.4 static shapes.

1. "Each creature you control with a +1/+1 counter on it has `<keyword>`."
   (the Abzan "outlast" cycle — Abzan Falconer / Abzan Battle Priest /
   Ainok Bond-Kin / Duskshell Crawler / Tuskguard Captain). A
   `grant_keyword` static scoped to `creatures_you_control` **filtered by
   counter presence** — `continuous.affected_objects`' `has_counter_kind`
   param (MEC-21) already narrows the group, so no engine change.
   `static_handlers._GROUP_COUNTER_GRANT_RE`.

2. The Odyssey-block **Threshold** phrasing: "Threshold — As long as seven
   or more cards are in your graveyard, ~ gets +N/+N …" — `normalize.
   _ABILITY_WORD_RE` now strips the "Threshold —" label, and
   `_STATIC_CONDITION_RES` gained the subject-verb "N or more cards are in
   your graveyard" variant of the existing "there are N or more cards …"
   `control_count` condition.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


# --- parse ---------------------------------------------------------------


def test_counter_lord_parses():
    assert static_effect_specs(
        "each creature you control with a +1/+1 counter on it has flying"
    ) == [
        EffectSpec("grant_keyword", {
            "keywords": ["flying"],
            "affects": "creatures_you_control",
            "has_counter_kind": "+1/+1",
        })
    ]
    # multi-keyword
    assert static_effect_specs(
        "each creature you control with a +1/+1 counter on it has trample, lifelink"
    )[0].params["keywords"] == ["trample", "lifelink"]


def test_threshold_label_and_are_in_graveyard_phrasing():
    specs = static_effect_specs(
        "as long as 7 or more cards are in your graveyard, ~ gets +2/+2"
    )
    assert specs is not None
    assert specs[0].params["active_if"] == {
        "kind": "control_count", "selector": "cards_in_your_graveyard", "min": 7,
    }


def test_real_cards_modeled():
    for name, text, tl in [
        ("Abzan Falconer",
         "Outlast {W}\nEach creature you control with a +1/+1 counter on it has flying.",
         "Creature — Human Soldier"),
        ("Nimble Mongoose",
         "Trample\nThreshold — As long as seven or more cards are in your graveyard, "
         "Nimble Mongoose gets +2/+2.",
         "Creature — Mongoose"),
    ]:
        c = Card(id=name[:3], name=name, type_line=tl, is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -----------------------------------------------------------


def _counter_creature(state, eng, name, counters=0, controller="p1"):
    obj = obj_on_battlefield(state, eng, creature(name), controller=controller)
    if counters:
        obj.counters["+1/+1"] = counters
        obj.plus_one_counters = counters
    return obj


def test_counter_lord_only_grants_to_counter_bearers_you_control():
    eng = make_engine([creature("x")], [creature("y")])
    state = eng.state
    lord = obj_on_battlefield(
        state, eng,
        Card(id="af", name="Abzan Falconer", type_line="Creature — Soldier",
             is_creature=True, power=1, toughness=3,
             oracle_text="Each creature you control with a +1/+1 counter on it has flying."),
        controller="p1",
    )
    bind_from_catalogue(lord)

    buffed = _counter_creature(state, eng, "Buffed Ally", counters=1)
    plain = _counter_creature(state, eng, "Plain Ally", counters=0)
    their_buffed = _counter_creature(state, eng, "Their Buffed", counters=1, controller="p2")
    eng.recompute_continuous_effects()

    assert "flying" in buffed.granted_keywords
    assert "flying" not in plain.granted_keywords
    assert "flying" not in their_buffed.granted_keywords

    # remove the counter → the grant drops on the next recompute
    buffed.counters["+1/+1"] = 0
    buffed.plus_one_counters = 0
    eng.recompute_continuous_effects()
    assert "flying" not in buffed.granted_keywords
