"""PAR-268: casting from a non-hand zone with a rider.

* "You may cast this card from exile." (Khan, Vengeful Heart)
* "You may cast this card from your graveyard. If you do, it enters with a finality counter on it." (Storied Veteran)
* "Once during each of your turns, you may cast an artifact creature spell from your graveyard. If you cast a spell
  this way, that artifact creature enters with a finality counter on it." (Overflow Submatrix)
* "Once during each of your turns, you may cast an artifact spell from the top of your library." (Zefram Cochrane)
* "Spacecraft you control enter with two additional charge counters on them." (Zefram Cochrane)

RULE 122.1h: a permanent with a finality counter that would die is exiled instead.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import top_library
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.library_permission import (
    parse_graveyard_cast_permission, parse_top_library_permission,
)
from tests.support.card_cache import get_cached_card

ARTIFACT_CREATURE = "Artifact Creature — Construct"


def _card(name, type_line="Creature — Bear", mv=1, text="", **kw):
    return Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
                power=2 if "Creature" in type_line else None,
                toughness=2 if "Creature" in type_line else None, converted_mana_cost=mv, mana_cost_string="{G}",
                oracle_text=text, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _in_zone(eng, card, zone, rider_text=None, specs=()):
    obj = GameObject(card, owner_id="p1", controller_id="p1", zone=zone)
    bind_from_catalogue(obj)
    for spec in specs:
        obj.static_effects.append(EffectRegistry.create(spec.type, {**spec.params}))
        obj.static_effects[-1].source = obj
    getattr(eng.state.player_by_id("p1"), {Zone.GRAVEYARD: "graveyard", Zone.EXILE: "exile",
                                           Zone.LIBRARY: "library"}[zone]).append(obj)
    return obj


def _granter(eng, specs):
    obj = GameObject(_card("Granter", "Enchantment"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    for spec in specs:
        obj.static_effects.append(EffectRegistry.create(spec.type, {**spec.params}))
        obj.static_effects[-1].source = obj
    eng.state.add_to_battlefield(obj)
    return obj


# --- parse -------------------------------------------------------------------------------------------


def test_self_exile_permission_parses():
    [spec] = parse_graveyard_cast_permission("you may cast this card from exile.")
    assert spec.type == "self_graveyard_or_exile_cast_permission" and spec.params == {"zones": ["exile"]}


def test_self_graveyard_finality_rider_parses():
    [spec] = parse_graveyard_cast_permission(
        "you may cast this card from your graveyard. if you do, it enters with a finality counter on it.")
    assert spec.params == {"zones": ["graveyard"], "enters_with_counter": "finality"}


def test_kind_graveyard_finality_rider_parses():
    [spec] = parse_graveyard_cast_permission(
        "once during each of your turns, you may cast an artifact creature spell from your graveyard. "
        "if you cast a spell this way, that artifact creature enters with a finality counter on it.")
    assert spec.type == "graveyard_cast_permission"
    assert spec.params["enters_with_counter"] == "finality" and spec.params["once_per_turn"] is True
    assert spec.params["spell_criteria"] == {"all_types": ["artifact", "creature"]}


def test_once_during_each_of_your_turns_top_library_is_own_turn_only():
    [spec] = parse_top_library_permission(
        "once during each of your turns, you may cast an artifact spell from the top of your library.")
    assert spec.params["once_each_turn"] is True and spec.params["active_player_only"] is True
    [plain] = parse_top_library_permission("once each turn, you may cast an artifact spell from the top of your library.")
    assert "active_player_only" not in plain.params


def _extra_etb_spec():
    result = parse_oracle(get_cached_card("Zefram Cochrane, Warp Pioneer"))
    [spec] = [e for a in result.effect_specs for e in a.effects if e.type == "extra_etb_counter"]
    return spec


def test_named_counter_entry_clause_parses():
    spec = _extra_etb_spec()
    assert (spec.params["kind"], spec.params["count"], spec.params["filter"]) == (
        "charge", 2, {"subtype": "Spacecraft"})


@pytest.mark.parametrize("text", [
    "you may cast this card from your graveyard. if you do, it enters tapped.",
    "you may cast this card from your library.",
])
def test_unrelated_riders_are_not_claimed(text):
    assert parse_graveyard_cast_permission(text) is None


@pytest.mark.parametrize("name", [
    "Khan, Vengeful Heart", "Overflow Submatrix", "Storied Veteran", "Zefram Cochrane, Warp Pioneer",
])
def test_real_cards_are_modeled(name):
    card = get_cached_card(name)
    assert parse_oracle(card).modeled


# --- engine ------------------------------------------------------------------------------------------


def test_exile_cast_of_the_card_itself():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    [spec] = parse_graveyard_cast_permission("you may cast this card from exile.")
    khan = _in_zone(eng, _card("Khan"), Zone.EXILE, specs=[spec])
    hand_clone = _in_zone(eng, _card("Plain"), Zone.EXILE)
    p1.mana_pool.add_many({"G": 2})
    assert eng.can_cast(p1, khan)
    assert not eng.can_cast(p1, hand_clone)
    eng.cast_spell(p1, khan)
    eng.resolve_until_stable()
    assert khan in eng.state.battlefield
    assert not khan.counters.get("finality")  # Khan has no rider


def test_storied_veteran_enters_with_finality_and_is_exiled_instead_of_dying():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    [spec] = parse_graveyard_cast_permission(
        "you may cast this card from your graveyard. if you do, it enters with a finality counter on it.")
    vet = _in_zone(eng, _card("Veteran"), Zone.GRAVEYARD, specs=[spec])
    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, vet)
    eng.resolve_until_stable()
    assert vet in eng.state.battlefield and vet.counters.get("finality") == 1
    eng.rules.destroy(vet)
    assert vet in p1.exile and vet not in p1.graveyard  # RULE 122.1h


def test_a_normal_hand_cast_carries_no_finality_counter():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    [spec] = parse_graveyard_cast_permission(
        "you may cast this card from your graveyard. if you do, it enters with a finality counter on it.")
    vet = _in_zone(eng, _card("Veteran"), Zone.GRAVEYARD, specs=[spec])
    p1.graveyard.remove(vet)
    vet.zone = Zone.HAND
    p1.hand.append(vet)
    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, vet)
    eng.resolve_until_stable()
    assert vet in eng.state.battlefield and not vet.counters.get("finality")


def test_overflow_submatrix_once_per_turn_artifact_creature_with_finality():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    [spec] = parse_graveyard_cast_permission(
        "once during each of your turns, you may cast an artifact creature spell from your graveyard. "
        "if you cast a spell this way, that artifact creature enters with a finality counter on it.")
    granter = _granter(eng, [spec])
    first = _in_zone(eng, _card("Golem A", ARTIFACT_CREATURE), Zone.GRAVEYARD)
    second = _in_zone(eng, _card("Golem B", ARTIFACT_CREATURE), Zone.GRAVEYARD)
    bear = _in_zone(eng, _card("Bear"), Zone.GRAVEYARD)
    p1.mana_pool.add_many({"G": 4})
    assert eng.can_cast(p1, first) and not eng.can_cast(p1, bear)   # artifact creatures only
    eng.cast_spell(p1, first)
    eng.resolve_until_stable()
    assert first in eng.state.battlefield and first.counters.get("finality") == 1
    assert granter.graveyard_casts_this_turn == 1
    assert not eng.can_cast(p1, second)   # once during each of your turns
    granter.graveyard_casts_this_turn = 0
    assert eng.can_cast(p1, second)


def test_zefram_top_library_cast_is_once_and_own_turn_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    specs = parse_top_library_permission(
        "once during each of your turns, you may cast an artifact spell from the top of your library.")
    granter = _granter(eng, specs)
    for name in ("Second", "First"):
        _in_zone(eng, _card(name, "Artifact", mv=1), Zone.LIBRARY)
    first = p1.library[-1]
    p1.mana_pool.add_many({"G": 2})
    assert eng.can_cast(p1, first)
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bear"))
    eng.cast_spell(p1, first)
    eng.resolve_until_stable()
    assert granter.top_library_uses_this_turn == 1
    assert not eng.can_cast(p1, p1.library[-1])
    # not on an opponent's turn
    granter.top_library_uses_this_turn = 0
    eng.state.active_player_index = 1
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Third", "Artifact"))


def test_spacecraft_enter_with_two_extra_charge_counters_but_other_permanents_do_not():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    card = get_cached_card("Zefram Cochrane, Warp Pioneer")
    zef = GameObject(card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(zef)
    eng.state.add_to_battlefield(zef)
    ship = GameObject(_card("Cruiser", "Artifact — Spacecraft", mv=1), owner_id="p1", controller_id="p1", zone=Zone.HAND)
    rock = GameObject(_card("Rock", "Artifact", mv=1), owner_id="p1", controller_id="p1", zone=Zone.HAND)
    for o in (ship, rock):
        bind_from_catalogue(o)
        p1.hand.append(o)
    p1.mana_pool.add_many({"G": 4})
    for o in (ship, rock):
        eng.cast_spell(p1, o)
        eng.resolve_until_stable()
    assert ship in eng.state.battlefield and ship.counters.get("charge") == 2
    assert rock in eng.state.battlefield and not rock.counters.get("charge")
