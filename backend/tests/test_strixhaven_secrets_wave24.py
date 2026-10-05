"""Secrets of Strixhaven — playability batch, wave 24 (PAR-60).

Quandrix "Unlimited" singletons (+ Emeria, a Lorehold land), hand-authored in
`game/card_registry/commander_cards.py` on existing primitives. Engine change:
``times`` added to `RulesEngine._substitute_x`'s attr list so
``EffectSpec("proliferate", {"times": "x"})`` resolves an announced {X}.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

WAVE24 = [
    "Lotus Field", "Staff of the Storyteller", "Emeria, the Sky Ruin",
    "Hangarback Walker", "Ingenious Prodigy", "Zimone, Quandrix Prodigy",
    "Expansion Algorithm", "Mana Bloom",
]


@pytest.mark.parametrize("name", WAVE24)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Artifact"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


@pytest.mark.parametrize("name", WAVE24)
def test_deck_coverage_sees_them(name):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    assert card is not None
    # registered -> specs_for turns the parser off; is_registered is what
    # deck_coverage.py counts.
    assert is_registered(card.name)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player


def _mk(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", "").replace(",", ""), name=name,
                             type_line=tl, **kw), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_hangarback_walker_death_makes_thopters_per_counter():
    eng, p1 = _eng()
    hb = _mk(eng, p1.id, "Hangarback Walker", "Artifact Creature — Construct",
             is_creature=True, power=0, toughness=0)
    hb.counters["+1/+1"] = 3
    spec = [s for s in _REGISTRY["hangarback walker"]() if s.ability_kind == "triggered"][0]
    effs = build_effects(spec.effects, hb)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    ctx.trigger_event = {"counters": {"+1/+1": 3}}
    for e in effs:
        e.apply(ctx, [])
    thopters = [o for o in eng.state.battlefield
                if o.card.name == "Thopter" and o.controller_id == p1.id]
    assert len(thopters) == 3


def test_expansion_algorithm_proliferates_x_times():
    eng, p1 = _eng()
    creature = _mk(eng, p1.id, "Guy", "Creature — Bear", is_creature=True,
                   power=1, toughness=1)
    creature.counters["+1/+1"] = 1
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    effs = build_effects([EffectSpec("proliferate", {"times": "x"})], creature)
    eng.rules._substitute_x(effs, 3)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    assert creature.counters["+1/+1"] == 4  # 1 + 3 proliferate passes


def test_lotus_field_etb_is_a_two_land_self_sacrifice_trigger():
    spec = _REGISTRY["lotus field"]()[0]
    assert spec.ability_kind == "triggered"
    assert str(spec.trigger["event"]) == "ENTERS_BATTLEFIELD"
    assert spec.trigger["condition"] == {"subject": "self"}
    (eff,) = spec.effects
    assert eff.type == "sacrifice"
    assert eff.params["what"] == "land" and eff.params["count"] == 2
