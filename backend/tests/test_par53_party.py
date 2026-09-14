"""PAR-53 — Party (RULE 700.8/702.129, Zendikar Rising).

`continuous.count_selector`'s `"creatures_in_your_party"` branch (the RULE
700.8 bipartite Cleric/Rogue/Warrior/Wizard matcher) already existed but was
never wired to any parser row. Two small additions close the named cluster:

* `static_handlers._SELF_COST_REDUCTION_PARTY_RE` — "This spell costs `<N>`
  less to cast for each creature in your party." — the exact same
  `per`-scaled `cost_reduction` shape `_SELF_COST_REDUCTION_ATTACKING_RE`/
  `_SELF_COST_REDUCTION_GY_RE` already use, just a new selector name.
* `"you have a full party"` → `{"kind": "control_count", "selector":
  "creatures_in_your_party", "min": 4}` — no new condition *kind* needed,
  since "full" is exactly 4 (the cap `creatures_in_your_party` can ever
  return) and `control_count` already means "N or more".

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous, static_conditions
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    engine = GameEngine(state)
    return engine, state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _creature(name, subtype, power=1, toughness=1):
    return Card(
        id=f"Bench {name}", name=f"Bench {name}", type_line=f"Creature — {subtype}",
        is_creature=True, power=power, toughness=toughness,
    )


# ---------------------------------------------------------------------------
# creatures_in_your_party — the RULE 700.8 count selector (already built,
# never wired to a parser row before this ticket)
# ---------------------------------------------------------------------------


def test_party_count_selector_bipartite_matching():
    engine, state = _engine("p1")
    _bf(state, _creature("Cleric", "Human Cleric"))
    _bf(state, _creature("Rogue", "Human Rogue"))
    assert continuous.count_selector(state, "p1", "creatures_in_your_party") == 2
    # A dual-typed creature can only ever fill one role at a time.
    _bf(state, _creature("Cleric-Rogue", "Human Cleric Rogue"))
    assert continuous.count_selector(state, "p1", "creatures_in_your_party") == 2


def test_full_party_is_four():
    engine, state = _engine("p1")
    for subtype in ("Human Cleric", "Human Rogue", "Human Warrior", "Human Wizard"):
        _bf(state, _creature(subtype, subtype))
    assert continuous.count_selector(state, "p1", "creatures_in_your_party") == 4


# ---------------------------------------------------------------------------
# "This spell costs {N} less to cast for each creature in your party."
# ---------------------------------------------------------------------------


def test_party_cost_reduction_parses():
    specs = static_effect_specs("This spell costs {1} less to cast for each creature in your party.")
    assert specs == [
        EffectSpec("cost_reduction", {"affects": "self", "generic": 1, "per": "creatures_in_your_party"})
    ]


def test_party_cost_reduction_execute():
    engine, state = _engine("p1")
    spell = _to_hand(state, Card(
        id="Bench Colossus", name="Bench Colossus", type_line="Artifact",
        mana_cost_string="{6}", converted_mana_cost=6,
        oracle_text="This spell costs {1} less to cast for each creature in your party.",
    ))
    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 0

    _bf(state, _creature("Cleric", "Human Cleric"))
    _bf(state, _creature("Wizard", "Human Wizard"))
    engine.recompute_continuous_effects()
    net, _ = continuous.self_cost_reduction_for(spell, state)
    assert net == 2


@pytest.mark.parametrize("name", ["Sea Gate Colossus", "Shatterskull Minotaur", "Deadly Alliance"])
def test_party_cost_reduction_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


# ---------------------------------------------------------------------------
# "you have a full party" condition
# ---------------------------------------------------------------------------


def test_static_condition_recognizes_full_party_phrase():
    assert static_condition("you have a full party") == {
        "kind": "control_count", "selector": "creatures_in_your_party", "min": 4,
    }


def test_condition_full_party_holds_only_at_four():
    engine, state = _engine("p1")
    assert static_conditions.condition_holds(
        {"kind": "control_count", "selector": "creatures_in_your_party", "min": 4},
        state, controller_id="p1",
    ) is False
    for subtype in ("Human Cleric", "Human Rogue", "Human Warrior", "Human Wizard"):
        _bf(state, _creature(subtype, subtype))
    assert static_conditions.condition_holds(
        {"kind": "control_count", "selector": "creatures_in_your_party", "min": 4},
        state, controller_id="p1",
    ) is True


def test_trailing_as_long_as_full_party_self_anthem():
    specs = static_effect_specs("~ gets +1/+1 as long as you have a full party.")
    assert specs is not None
    assert specs[0].type == "anthem"
    assert specs[0].params["active_if"] == {
        "kind": "control_count", "selector": "creatures_in_your_party", "min": 4,
    }


def test_coveted_prize_modeled():
    # Needs BOTH the cost-reduction row (its first ability) and the full-party
    # condition (its resolve-time "if you have a full party, you may cast…"
    # rider, which reuses the exact same `control_count` kind for free).
    r = parse_oracle(_db().get_card("Coveted Prize"))
    assert r.coverage != UNMODELED, r.unclaimed
