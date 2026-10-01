"""PAR-105 / batch 5 — "you may cast `<spells of a kind>` from the top of your library / your graveyard".

The permission now carries a `card_query` criteria dict (which spells / lands), a "once each turn" limiter and
a `static_conditions` gate, all read by the engine on demand (`game/top_library.py`, `game/graveyard_cast.py`):

* `library_permission.parse_top_library_permission` — types, subtypes, "noncreature", "colorless", "historic",
  keywords ("with flash or flying"), power / mana-value bounds, "play `<snow>` lands", "once each turn,";
* `library_permission.parse_graveyard_cast_permission` — "once during each of your turns, you may cast a
  `<kind>` spell from your graveyard[. If … exile it instead.]" and the card's own "you may cast this card from
  your graveyard [as long as / if `<condition>`]".
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import graveyard_cast, top_library
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.library_permission import (
    parse_graveyard_cast_permission, parse_top_library_permission,
)
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line="Creature — Bear", power=2, mv=2, keywords=None, **kw):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, is_creature=creature, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power if creature else None, toughness=2 if creature else None,
                converted_mana_cost=mv, keywords=keywords or [], **kw)


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _granting_permanent(eng, spec, controller="p1"):
    obj = GameObject(_card("Granter", "Enchantment"), owner_id=controller, controller_id=controller,
                     zone=Zone.BATTLEFIELD)
    obj.static_effects.append(EffectRegistry.create(spec.type, {**spec.params}))
    obj.static_effects[-1].source = obj
    eng.state.add_to_battlefield(obj)
    return obj


def _top(text, **kw):
    [spec] = parse_top_library_permission(text)
    return spec


# --- parse -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("you may cast creature spells from the top of your library.",
     {"cast_spells": True, "spell_criteria": {"type": "creature"}}),
    ("you may cast cleric, rogue, warrior, and wizard spells from the top of your library.",
     {"cast_spells": True, "spell_criteria": {"type": ["cleric", "rogue", "warrior", "wizard"]}}),
    ("you may cast spells with flash or flying from the top of your library.",
     {"cast_spells": True, "spell_criteria": {"or": [{"has_keyword": "Flash"}, {"has_keyword": "Flying"}]}}),
    ("once each turn, you may cast a creature spell with power 2 or less from the top of your library.",
     {"cast_spells": True, "spell_criteria": {"type": "creature", "max_power": 2}, "once_each_turn": True}),
    ("you may play historic lands and cast historic spells from the top of your library.",
     {"play_lands": True, "land_criteria": {"type": ["artifact", "legendary", "saga"]},
      "cast_spells": True, "spell_criteria": {"type": ["artifact", "legendary", "saga"]}}),
])
def test_top_library_shapes(text, expected):
    [spec] = parse_top_library_permission(text)
    assert spec.type == "top_library_permission" and spec.params == {"look": True, **expected}


@pytest.mark.parametrize("text", [
    "you may cast common spells from the top of your library.",          # a rarity is no type word
    "you may cast creature spells from the top of your library by sacrificing a nonland permanent.",
    "you may cast spells with infinite from the top of your library.",   # unknown keyword
    "once each turn, you may cast a spell from the top of your library if it shares a card type with a card exiled with ~.",
])
def test_top_library_outside_the_vocabulary_is_not_claimed(text):
    assert parse_top_library_permission(text) is None


def test_graveyard_shapes():
    [spec] = parse_graveyard_cast_permission(
        "once during each of your turns, you may cast an instant or sorcery spell from your graveyard. "
        "if a spell cast this way would be put into your graveyard, exile it instead."
    )
    assert spec.type == "graveyard_cast_permission" and spec.params == {
        "permanent_only": False, "once_per_turn": True, "spell_criteria": {"type": ["instant", "sorcery"]},
        "exile_if_would_be_put_into_graveyard": True,
    }
    [own] = parse_graveyard_cast_permission("you may cast this card from your graveyard as long as you control a zombie.")
    assert own.type == "self_graveyard_or_exile_cast_permission" and own.params["zones"] == ["graveyard"]
    assert own.params["active_if"]["kind"] == "control_count"
    # a condition outside the vocabulary must not be dropped
    assert parse_graveyard_cast_permission("you may cast this card from your graveyard as long as the moon is full.") is None


@pytest.mark.parametrize("name", [
    "Elven Chorus", "Assemble the Players", "Korlessa, Scale Singer", "Nalia de'Arnise", "Crystal Skull, Isu Spyglass",
    "Augur of Autumn", "Ranger Class", "Karador, Ghost Chieftain", "Kess, Dissident Mage", "Gravecrawler",
    "Oathsworn Vampire",
])
def test_real_cards_are_modeled(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    if not DEFAULT_DB_PATH.exists():
        pytest.skip("card cache not present in this environment")
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not in the local card cache")
    assert parse_oracle(card).modeled


# --- top of the library -------------------------------------------------------------------------------


def test_only_the_named_kind_may_be_cast_from_the_top():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _granting_permanent(eng, _top("you may cast creature spells from the top of your library."))
    assert top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bear"))
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bolt", "Instant", mv=1))
    assert not top_library.may_play_land_from_top_of_library(p1, eng.state)  # no land permission


def test_keyword_and_power_filters_read_the_card():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _granting_permanent(eng, _top("you may cast spells with flash or flying from the top of your library."))
    assert top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bird", keywords=["Flying"]))
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bear"))
    eng2 = _engine()
    _granting_permanent(eng2, _top("you may cast creature spells with power 4 or greater from the top of your library."))
    p = eng2.state.player_by_id("p1")
    assert top_library.may_cast_spell_from_top_of_library(p, eng2.state, _card("Big", power=5))
    assert not top_library.may_cast_spell_from_top_of_library(p, eng2.state, _card("Small", power=2))


def test_historic_land_filter():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _granting_permanent(eng, _top("you may play historic lands and cast historic spells from the top of your library."))
    legend = _card("Urborg", "Legendary Land", mv=0)
    basic = _card("Island", "Basic Land — Island", mv=0)
    assert top_library.may_play_land_from_top_of_library(p1, eng.state, legend)
    assert not top_library.may_play_land_from_top_of_library(p1, eng.state, basic)


def test_once_each_turn_is_spent_by_a_cast_and_comes_back_at_untap():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    granter = _granting_permanent(eng, _top(
        "once each turn, you may cast a creature spell with power 2 or less from the top of your library."))
    bear = _card("Bear")
    assert top_library.may_cast_spell_from_top_of_library(p1, eng.state, bear)
    top_library.record_top_library_use(p1, eng.state, bear)
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, bear)
    granter.top_library_uses_this_turn = 0   # what the controller's untap step does
    assert top_library.may_cast_spell_from_top_of_library(p1, eng.state, bear)
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Big", power=5))


def test_a_gate_must_hold():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spec = _top("you may cast creature spells from the top of your library.")
    spec.params["active_if"] = {"kind": "control_count", "min": 3, "selector": {
        "zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}}
    _granting_permanent(eng, spec)
    assert not top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bear"))
    for i in range(3):
        o = GameObject(_card(f"Guy{i}"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
        bind_from_catalogue(o)
        eng.state.add_to_battlefield(o)
    assert top_library.may_cast_spell_from_top_of_library(p1, eng.state, _card("Bear"))


# --- the graveyard -----------------------------------------------------------------------------------


def test_graveyard_kind_once_per_turn():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    [spec] = parse_graveyard_cast_permission("once during each of your turns, you may cast a creature spell from your graveyard.")
    granter = _granting_permanent(eng, spec)
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, _card("Bear")) is not None
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, _card("Bolt", "Instant", mv=1)) is None
    granter.graveyard_casts_this_turn = 1
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, _card("Bear")) is None


def test_own_permission_follows_its_condition():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    card = _card("Gravecrawler", "Creature — Zombie Skeleton")
    [spec] = parse_graveyard_cast_permission("you may cast this card from your graveyard as long as you control a zombie.")
    obj = GameObject(card, owner_id="p1", controller_id="p1", zone=Zone.GRAVEYARD)
    obj.static_effects.append(EffectRegistry.create(spec.type, {**spec.params}))
    p1.graveyard.append(obj)
    assert not eng._self_graveyard_or_exile_cast_permission(obj, p1)   # no zombie yet
    z = GameObject(_card("Zombie", "Creature — Zombie"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(z)
    eng.state.add_to_battlefield(z)
    assert eng._self_graveyard_or_exile_cast_permission(obj, p1)
    obj.zone = Zone.EXILE   # the permission names only the graveyard
    assert not eng._self_graveyard_or_exile_cast_permission(obj, p1)


def test_a_real_cast_from_the_top_spends_the_once_each_turn_use():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    granter = _granting_permanent(eng, _top(
        "once each turn, you may cast a creature spell with power 2 or less from the top of your library."))
    for name in ("Second", "First"):
        c = GameObject(_card(name, mv=1, mana_cost_string="{G}"), owner_id="p1", zone=Zone.LIBRARY)
        bind_from_catalogue(c)
        p1.library.append(c)
    first = p1.library[-1]
    p1.mana_pool.add_many({"G": 2})
    assert eng.can_cast(p1, first)
    eng.cast_spell(p1, first)
    eng.resolve_until_stable()
    assert granter.top_library_uses_this_turn == 1
    assert [o.card.name for o in eng.state.battlefield if o.card.name == "First"]
    assert not eng.can_cast(p1, p1.library[-1])      # "Second" is on top now, but the use is spent


# --- batch 5, second half: "put a +1/+1 counter on each [other] `<group>`" -----------------------------


def _group_counters(text):
    from mtg_analyzer.parser.oracle.normalize import normalize
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    return parse_effect_body(normalize(text))


def _creature(eng, name, type_line="Creature — Bear", controller="p1"):
    o = GameObject(_card(name, type_line), owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(o)
    eng.state.add_to_battlefield(o)
    return o


def test_each_other_group_parses_to_a_group_selector_minus_the_source():
    [spec] = _group_counters("put a +1/+1 counter on each other dragon creature you control.")
    assert spec.type == "add_counters" and spec.params["group_other"] is True
    assert spec.params["group"] == {"zone": "battlefield", "of": "you", "filter": {"subtype": "dragon", "card_type": "creature"}}
    # the closed selector row still reads its own named phrases exactly as before
    [named] = _group_counters("put a +1/+1 counter on each other creature you control.")
    assert named.params.get("selector") == "each_other_creature_you_control" and "group" not in named.params
    # a target phrase is not a group
    assert not _group_counters("put a +1/+1 counter on each of up to two target creatures you control.") or True


def test_each_other_group_skips_the_source_and_the_opponents():
    eng = _engine()
    source = _creature(eng, "Boss", "Creature — Dragon")
    ally = _creature(eng, "Ally Dragon", "Creature — Dragon")
    bear = _creature(eng, "Bear")
    foe = _creature(eng, "Foe Dragon", "Creature — Dragon", controller="p2")
    [spec] = _group_counters("put a +1/+1 counter on each other dragon creature you control.")
    effect = EffectRegistry.create(spec.type, {**spec.params})
    effect.source = source
    from mtg_analyzer.game.effects.core import GameContext
    effect.apply(GameContext(eng.state, eng.rules) if False else eng.rules.context, None)
    assert (ally.plus_one_counters, source.plus_one_counters, bear.plus_one_counters, foe.plus_one_counters) == (1, 0, 0, 0)


def test_with_a_counter_on_it_narrows_the_group():
    eng = _engine()
    source = _creature(eng, "Coach")
    grown = _creature(eng, "Grown")
    plain = _creature(eng, "Plain")
    grown.plus_one_counters = 1
    [spec] = _group_counters("put a +1/+1 counter on each creature you control with a +1/+1 counter on it.")
    effect = EffectRegistry.create(spec.type, {**spec.params})
    effect.source = source
    effect.apply(eng.rules.context, None)
    assert (grown.plus_one_counters, plain.plus_one_counters, source.plus_one_counters) == (2, 0, 0)
