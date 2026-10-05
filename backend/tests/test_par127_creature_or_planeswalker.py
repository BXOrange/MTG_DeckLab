"""PAR-127 — "target creature or planeswalker" names both halves of the union.

The shared TARGET grammar used to drop "or planeswalker" onto a `creature` kind: 83
parser-MODELED cards (Hero's Downfall, Dreadbore, Bite Down, Eliminate, …) that could
never target a planeswalker. The rows now resolve to `creature_or_planeswalker` and its
opponent-scoped sibling `creature_or_planeswalker_you_dont_control`, both mapped onto
`permanent` for the verb whitelists (`subgrammars.SCOPED_TARGET_BASE`), and the frames
keep the mana-value bound the plain `creature` branch applied.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_kind
from mtg_analyzer.services.card_database import CardDatabase

pytestmark = pytest.mark.full_cache


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, owner):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _walker(state, owner, name="Walker", loyalty=4, mv=3):
    obj = _bf(state, Card(id=name, name=name, type_line="Legendary Planeswalker — Test",
                          loyalty=loyalty, converted_mana_cost=mv), owner)
    obj.counters["loyalty"] = loyalty
    return obj


def _bear(state, owner, name="Bear", power=2, mv=2):
    return _bf(state, Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                           power=power, toughness=2, converted_mana_cost=mv), owner)


def _cast(engine, name, targets):
    p1 = engine.state.player_by_id("p1")
    obj = GameObject(_named(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"B": 5, "R": 5, "G": 5, "W": 5, "U": 5})
    engine.state.active_player_index = 0
    engine.state.current_step = "main1"
    engine.cast_spell(p1, obj, targets=targets)
    engine.resolve_until_stable()


def _offered(state, kind, **spec):
    return {d["instance_id"] for d in targeting.legal_targets(
        state, "p1", targeting.TargetSpec(kind=kind, **spec))}


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, kind", [
    ("target creature or planeswalker", "creature_or_planeswalker"),
    ("target creature or planeswalker you don't control",
     "creature_or_planeswalker_you_dont_control"),
    ("target creature or planeswalker an opponent controls",
     "creature_or_planeswalker_you_dont_control"),
])
def test_the_phrase_resolves_to_the_union(phrase, kind):
    assert resolve_target_kind(phrase) == kind


@pytest.mark.parametrize("name, effect, kind", [
    ("Hero's Downfall", "destroy", "creature_or_planeswalker"),
    ("Dreadbore", "destroy", "creature_or_planeswalker"),
    ("Bite Down", "damage_equal_to_power", "creature_or_planeswalker_you_dont_control"),
    ("Eliminate", "destroy", "creature_or_planeswalker"),
])
def test_real_cards_keep_the_planeswalker_half(name, effect, kind):
    result = parse_oracle(_named(name))
    assert result.modeled
    [spec] = [e for s in result.specs for e in s.effects if e.type == effect]
    assert spec.params["target_kind"] == kind


# ---------------------------------------------------------------------------
# Targets offered
# ---------------------------------------------------------------------------


def test_the_union_offers_creatures_and_planeswalkers_on_both_sides():
    engine = _engine()
    state = engine.state
    mine, theirs = _bear(state, "p1", "Mine"), _bear(state, "p2", "Theirs")
    my_walker, their_walker = _walker(state, "p1", "MyWalker"), _walker(state, "p2", "TheirWalker")
    _bf(state, Card(id="Rock", name="Rock", type_line="Artifact"), "p2")
    assert _offered(state, "creature_or_planeswalker") == {
        mine.instance_id, theirs.instance_id, my_walker.instance_id, their_walker.instance_id}
    assert _offered(state, "creature_or_planeswalker_you_dont_control") == {
        theirs.instance_id, their_walker.instance_id}


def test_the_mana_value_bound_still_applies():
    engine = _engine()
    state = engine.state
    small = _walker(state, "p2", "Small", mv=3)
    _walker(state, "p2", "Big", mv=5)
    assert _offered(state, "creature_or_planeswalker", max_mana_value=3) == {small.instance_id}


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_heros_downfall_destroys_a_planeswalker():
    engine = _engine()
    walker = _walker(engine.state, "p2")
    _cast(engine, "Hero's Downfall", [walker])
    assert walker not in engine.state.battlefield
    assert walker in engine.state.player_by_id("p2").graveyard


def test_bite_down_damages_an_opponents_planeswalker():
    engine = _engine()
    biter = _bear(engine.state, "p1", "Biter", power=3)
    walker = _walker(engine.state, "p2", loyalty=5)
    _cast(engine, "Bite Down", [biter, walker])
    assert walker.counters["loyalty"] == 2  # RULE 120.3c: damage removes loyalty
