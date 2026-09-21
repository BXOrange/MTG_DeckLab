"""PAR-30 iteration 3 — three small grammar widenings:

- **"those creatures"/"each of those creatures"** alongside "they" as the
  RULE 115 previous-target-group pronoun (`_PREV_GROUP_SUBJECT` in the
  `_PUMP_PREVIOUS_TARGETS_*` / `_PUMP_PREVIOUS_SELECTOR` rows) — Cauldron
  Haze / Cauldron of Souls ("choose any number of target creatures. Each of
  those creatures gains persist until end of turn.").
- **"each creature you control with a counter on it"** as a group selector
  (`_GROUP` + `_GROUP_SELECTORS` + `continuous.group_selector_objects`'
  new `creatures_you_control_with_a_counter`) — Iroh, Dragon of the West's
  "gains firebending 2 until end of turn" (ENG-31 parametric-keyword grant
  over a group).
- **"whenever you cast a spell during an opponent's turn"** — an optional
  turn qualifier on `_CAST_SPELL_TRIGGER_PLAIN_RE` mapping to the trigger's
  existing `not_controllers_turn` gate (RULE 603.4). Fire Nation Occupation
  + the "flash matters" cluster (Brineborn Cutthroat, Dream Spoilers, …).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, pid="p1", power=2, toughness=2):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=power, toughness=toughness),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse ----------------------------------------------------------------


def test_those_creatures_pronoun_parses_like_they():
    # `previous_subject_only` rows need the referent flag set (the connector
    # split does this after a target-choosing clause).
    assert match_clause(
        "each of those creatures gains persist until end of turn", previous_subject=True
    ) == [EffectSpec("pump", {"keywords": ["persist"], "previous_subject": True})]
    assert match_clause(
        "those creatures gain vigilance until end of turn", previous_subject=True
    ) == [EffectSpec("pump", {"keywords": ["vigilance"], "previous_subject": True})]


def test_group_selector_with_a_counter_parses():
    assert match_clause(
        "each creature you control with a counter on it gains firebending 2 until end of turn"
    ) == [EffectSpec("pump", {
        "parametric_keywords": [{"name": "firebending", "n": 2}],
        "selector": "creatures_you_control_with_a_counter",
    })]


def test_cast_spell_during_opponents_turn_sets_not_controllers_turn():
    c = Card(id="bc", name="Brineborn Cutthroat", type_line="Creature — Merfolk Rogue",
             is_creature=True, power=2, toughness=1,
             oracle_text=("Whenever you cast a spell during an opponent's turn, "
                          "put a +1/+1 counter on this creature."))
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    trig = r.specs[0].trigger
    assert trig["event"] == "SPELL_CAST"
    assert trig["not_controllers_turn"] is True


def test_cast_spell_during_your_turn_is_modeled():
    # PAR-119: the composed cast-trigger head reads "during your turn" as the
    # event-agnostic controller-relative `phase_relation` gate.
    c = Card(id="x", name="X", type_line="Enchantment",
             oracle_text="Whenever you cast a spell during your turn, draw a card.")
    r = parse_oracle(c)
    assert r.coverage != UNMODELED, r.unclaimed
    assert r.specs[0].trigger["phase_relation"] == "you"


def test_real_cards_modeled():
    for name, tl, text in [
        ("Iroh, Dragon of the West", "Legendary Creature — Dragon",
         "At the beginning of combat on your turn, each creature you control "
         "with a counter on it gains firebending 2 until end of turn."),
        ("Fire Nation Occupation", "Enchantment",
         "Whenever you cast a spell during an opponent's turn, create a 2/2 "
         "red Soldier creature token with firebending 1."),
        ("Cauldron Haze", "Instant",
         "Choose any number of target creatures. Each of those creatures "
         "gains persist until end of turn."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature="Creature" in tl, is_instant="Instant" in tl,
                 power=4 if "Creature" in tl else None,
                 toughness=4 if "Creature" in tl else None)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ------------------------------------------------------------


def test_group_selector_with_a_counter_picks_only_counter_bearers():
    eng, state = _engine()
    a = _creature(state, "Has")
    a.counters["+1/+1"] = 1
    b = _creature(state, "HasCharge")
    b.counters["charge"] = 2
    _creature(state, "Bare")

    picked = continuous.group_selector_objects(state, "p1", "creatures_you_control_with_a_counter")
    assert {o.name for o in picked} == {"Has", "HasCharge"}


def test_iroh_grants_firebending_over_the_counter_group():
    eng, state = _engine()
    src = _creature(state, "Iroh")
    withc = _creature(state, "Counted")
    withc.counters["+1/+1"] = 1
    bare = _creature(state, "Bare")
    bind_from_catalogue(src)

    build_effects([EffectSpec("pump", {
        "parametric_keywords": [{"name": "firebending", "n": 2}],
        "selector": "creatures_you_control_with_a_counter",
    })], src)[0].apply(GameContext(state, eng.rules), None)
    eng.recompute_continuous_effects()

    assert withc.parametric_keyword_value("firebending") == 2
    assert bare.parametric_keyword_value("firebending") is None
