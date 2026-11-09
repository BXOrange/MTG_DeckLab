"""PAR-254: "you may put/exile a <filter> card from among the cards milled this way" as an optional pick with an
"if you don't" / "if you do" follow-up.

RULE 701.17: the candidates are exactly the cards that instruction put into the graveyard, not other graveyard cards.
RULE 608.2d: "if you don't" is true when the player declines AND when no card of the mill qualifies."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter
from tests.test_par120_count_phrase import _put

REMINDER = " (To mill a card, put the top card of your library into your graveyard.)"
COUNTER_TAIL = f" If you don't, put a +1/+1 counter on this creature.{REMINDER}"
ETB = "When this creature enters, mill three cards. You may put "
AIRLIFT = ETB + "a Plains card or a creature card with mana value 3 or less from among the cards milled this way into your hand." + COUNTER_TAIL
FALLAJI = ETB + "a noncreature, nonland card from among the cards milled this way into your hand." + COUNTER_TAIL
GIGAMOLE = ETB + "a creature card from among the cards milled this way into your hand." + COUNTER_TAIL
TOMAKUL = ETB + "an artifact card from among the cards milled this way into your hand." + COUNTER_TAIL
SZAREKH = ("Flying\nMy Will Be Done — Whenever Szarekh attacks, mill three cards. You may put an artifact creature card "
           "or Vehicle card from among the cards milled this way into your hand.")
HARVEST = ("Mill five cards. You may put a permanent card from among the cards milled this way into your hand." + REMINDER)
SHADOW_KIN = ("Flash\nAt the beginning of your upkeep, each player mills three cards. You may exile a creature card from "
              "among the cards milled this way. If you do, this creature becomes a copy of that card, except it has this ability.")


def _card(name, types, mv=0, oracle="", **kw):
    # Scryfall lists Szarekh's flavor label as a keyword; the parser strips an unregistered label only by that signal.
    kw.setdefault("keywords", ["Flying", "My Will Be Done", "Mill"] if name.startswith("Szarekh") else [])
    return Card(id=name, name=name, type_line=types, converted_mana_cost=mv, oracle_text=oracle,
                is_creature="Creature" in types, power=1 if "Creature" in types else None,
                toughness=1 if "Creature" in types else None, **kw)


def _stack_library(state, owner, cards):
    """Put ``cards`` on top of ``owner``'s library; the first listed ends up deepest of the milled ones."""
    player = state.player_by_id(owner)
    objs = []
    for card in cards:
        obj = GameObject(card, owner_id=owner, zone=Zone.LIBRARY)
        player.library.append(obj)
        objs.append(obj)
    return objs


def _old_graveyard_creature(state, owner="p1"):
    obj = GameObject(_card("Old Ogre", "Creature — Ogre", 1), owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


def _offered(state):
    return {o["id"] for o in state.pending_choice["options"] if o["id"] != "decline"}


def _enter_source(engine, state, oracle, name):
    source = _put(state, oracle, name=name, types="Creature — Bear")
    _fire_enter(engine, state, source)
    return source


MILL3 = lambda: [  # noqa: E731
    _card("Island", "Basic Land — Island"),
    _card("Grizzly", "Creature — Bear", 2),
    _card("Plains", "Basic Land — Plains"),
]


@pytest.mark.parametrize("name,oracle", [
    ("Airlift Chaplain", AIRLIFT), ("Fallaji Archaeologist", FALLAJI), ("Ravenous Gigamole", GIGAMOLE),
    ("Tomakul Scrapsmith", TOMAKUL),
])
def test_the_counter_cards_are_modeled(name, oracle):
    assert parse_oracle(_card(name, "Creature — Bear", oracle=oracle)).modeled


def test_remaining_cards_are_modeled():
    assert parse_oracle(_card("Szarekh, the Silent King", "Legendary Artifact Creature — Necron", oracle=SZAREKH)).modeled
    assert parse_oracle(_card("Wasteful Harvest", "Instant", oracle=HARVEST, is_instant=True)).modeled
    assert parse_oracle(_card("Shadow Kin", "Creature — Shapeshifter", oracle=SHADOW_KIN)).modeled


def test_lookalike_with_an_unmodeled_else_branch_stays_unclaimed():
    assert parse_effect_body(
        "mill 3 cards. you may put a creature card from among the cards milled this way into your hand. "
        "if you don't, do something undefined to ~") is None


def test_airlift_chaplain_offers_only_milled_cards_that_match_the_filter():
    engine, state = _engine()
    old = _old_graveyard_creature(state)  # an older graveyard creature of mana value 1 would match, but was not milled
    island, bear, plains = _stack_library(state, "p1", MILL3())
    big = _stack_library(state, "p1", [_card("Big Ogre", "Creature — Ogre", 5)])[0]
    source = _enter_source(engine, state, AIRLIFT, "Airlift Chaplain")
    offered = _offered(state)
    # Plains and the cheap creature qualify; the mana value 5 creature and the Island do not; the old card was not milled.
    assert offered == {str(bear.instance_id), str(plains.instance_id)}
    assert str(old.instance_id) not in offered and str(big.instance_id) not in offered
    assert str(island.instance_id) not in offered
    engine.resolve_pending_choice(str(plains.instance_id))
    engine.resolve_until_stable()
    hand = state.player_by_id("p1").hand
    assert plains in hand and bear.zone == Zone.GRAVEYARD and old.zone == Zone.GRAVEYARD
    assert source.counters.get("+1/+1", 0) == 0  # a card was taken: "if you don't" is false


def test_declining_the_pick_puts_the_counter_on_the_source():
    engine, state = _engine()
    _stack_library(state, "p1", [_card("Grizzly", "Creature — Bear", 2)])
    source = _enter_source(engine, state, GIGAMOLE, "Ravenous Gigamole")
    assert state.pending_choice is not None
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert source.counters.get("+1/+1", 0) == 1
    assert not state.player_by_id("p1").hand


def test_no_eligible_milled_card_also_means_the_counter_without_asking():
    engine, state = _engine()
    _old_graveyard_creature(state)  # an old creature card must not count as a candidate
    _stack_library(state, "p1", [_card("Island", "Basic Land — Island") for _ in range(3)])
    source = _enter_source(engine, state, GIGAMOLE, "Ravenous Gigamole")
    engine.resolve_until_stable()
    assert state.pending_choice is None
    assert source.counters.get("+1/+1", 0) == 1
    assert not state.player_by_id("p1").hand


def test_empty_library_mills_nothing_and_still_counts_as_not_taking():
    engine, state = _engine()
    _old_graveyard_creature(state)
    source = _enter_source(engine, state, GIGAMOLE, "Ravenous Gigamole")
    engine.resolve_until_stable()
    assert state.pending_choice is None and source.counters.get("+1/+1", 0) == 1


def test_fallaji_filter_is_noncreature_and_nonland_together():
    engine, state = _engine()
    land, creature, artifact_creature, instant = _stack_library(state, "p1", [
        _card("Island", "Basic Land — Island"), _card("Grizzly", "Creature — Bear", 2),
        _card("Golem", "Artifact Creature — Golem", 3), _card("Bolt", "Instant", 1)])
    # three of the four are milled (the top three): land is the deepest and stays in the library
    _enter_source(engine, state, FALLAJI, "Fallaji Archaeologist")
    assert land.zone == Zone.LIBRARY
    assert _offered(state) == {str(instant.instance_id)}  # not "noncreature OR nonland"
    assert str(creature.instance_id) not in _offered(state) and str(artifact_creature.instance_id) not in _offered(state)


def test_tomakul_scrapsmith_takes_an_artifact_and_skips_the_counter():
    engine, state = _engine()
    _, artifact, _ = _stack_library(state, "p1", [
        _card("Island", "Basic Land — Island"), _card("Rock", "Artifact", 1), _card("Grizzly", "Creature — Bear", 2)])
    source = _enter_source(engine, state, TOMAKUL, "Tomakul Scrapsmith")
    assert _offered(state) == {str(artifact.instance_id)}
    engine.resolve_pending_choice(str(artifact.instance_id))
    engine.resolve_until_stable()
    assert artifact in state.player_by_id("p1").hand and source.counters.get("+1/+1", 0) == 0


def _resolve_effects(engine, state, oracle, name, type_line):
    parsed = parse_oracle(_card(name, type_line, oracle=oracle, is_instant=type_line == "Instant"))
    assert parsed.modeled
    source = _put(state, "", name=name, types=type_line)
    ability = next(a for a in parsed.specs if a.ability_kind in ("spell_effect", "triggered"))
    engine.rules._apply_effect_specs([e.to_dict() for e in ability.effects], source)
    return source


def test_wasteful_harvest_offers_any_milled_permanent_card_but_no_instants_or_old_cards():
    engine, state = _engine()
    old = _old_graveyard_creature(state)
    cards = _stack_library(state, "p1", [
        _card("Bolt", "Instant", 1), _card("Rock", "Artifact", 1), _card("Isle", "Land"),
        _card("Aura", "Enchantment — Aura", 2), _card("Grizzly", "Creature — Bear", 2)])
    _resolve_effects(engine, state, HARVEST, "Wasteful Harvest", "Instant")
    assert all(o.zone == Zone.GRAVEYARD for o in cards)
    assert _offered(state) == {str(o.instance_id) for o in cards[1:]}
    assert str(old.instance_id) not in _offered(state)
    engine.resolve_pending_choice(str(cards[1].instance_id))
    engine.resolve_until_stable()
    assert cards[1] in state.player_by_id("p1").hand


def test_szarekh_filter_is_artifact_creature_or_vehicle():
    engine, state = _engine()
    plain, golem, vehicle = _stack_library(state, "p1", [
        _card("Grizzly", "Creature — Bear", 2), _card("Golem", "Artifact Creature — Golem", 3),
        _card("Truck", "Artifact — Vehicle", 2)])
    _resolve_effects(engine, state, SZAREKH, "Szarekh, the Silent King", "Legendary Artifact Creature — Necron")
    assert _offered(state) == {str(golem.instance_id), str(vehicle.instance_id)}
    assert str(plain.instance_id) not in _offered(state)


def test_declining_with_no_else_branch_leaves_everything_in_the_graveyard():
    engine, state = _engine()
    cards = _stack_library(state, "p1", [_card("Rock", "Artifact", 1)])
    _resolve_effects(engine, state, HARVEST, "Wasteful Harvest", "Instant")
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert cards[0].zone == Zone.GRAVEYARD and not state.player_by_id("p1").hand


# --- Shadow Kin -----------------------------------------------------------------------------------------------------

def _upkeep(engine, state):
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1"))
    engine.resolve_until_stable()


def test_shadow_kin_offers_both_players_milled_creatures_and_copies_the_exiled_one_keeping_its_ability():
    engine, state = _engine()
    old = _old_graveyard_creature(state)
    mine = _stack_library(state, "p1", [_card("Island", "Basic Land — Island"), _card("Mine Bear", "Creature — Bear", 2),
                                        _card("Mine Rock", "Artifact", 1)])
    theirs = _stack_library(state, "p2", [_card("Their Wall", "Creature — Wall", 2, oracle="Defender"),
                                          _card("Isle", "Land"), _card("Isle2", "Land")])
    kin = _put(state, SHADOW_KIN, name="Shadow Kin", types="Creature — Shapeshifter")
    own_abilities = [a.printed_line for a in kin.triggered_abilities]
    assert len(own_abilities) == 1
    _upkeep(engine, state)
    wall = theirs[0]
    # Both libraries were milled: the opponent's creature is as eligible as mine; the old graveyard card is not.
    assert _offered(state) == {str(mine[1].instance_id), str(wall.instance_id)}
    assert str(old.instance_id) not in _offered(state)
    engine.resolve_pending_choice(str(wall.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert wall in state.player_by_id("p2").exile  # exiled, not just copied
    assert kin.name == "Their Wall"
    # RULE 707.9a: "it has this ability" -- the copy still triggers at the next upkeep.
    assert [a.printed_line for a in kin.triggered_abilities] == own_abilities


def test_shadow_kin_declined_or_without_creature_does_nothing():
    engine, state = _engine()
    mine = _stack_library(state, "p1", [_card("Mine Bear", "Creature — Bear", 2)] + [_card("I", "Land")] * 2)
    _stack_library(state, "p2", [_card("L", "Land")] * 3)
    kin = _put(state, SHADOW_KIN, name="Shadow Kin", types="Creature — Shapeshifter")
    _upkeep(engine, state)
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert kin.name == "Shadow Kin" and mine[0].zone == Zone.GRAVEYARD


def test_shadow_kin_with_no_milled_creature_asks_nothing():
    engine, state = _engine()
    _old_graveyard_creature(state)
    _stack_library(state, "p1", [_card("L", "Land")] * 3)
    _stack_library(state, "p2", [_card("L", "Land")] * 3)
    kin = _put(state, SHADOW_KIN, name="Shadow Kin", types="Creature — Shapeshifter")
    _upkeep(engine, state)
    assert state.pending_choice is None and kin.name == "Shadow Kin"
