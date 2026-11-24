"""BUG-76 -- a multi-object sacrifice cost's objects leave together (RULE 118.3 / 701.17a), so a batched trigger
("whenever one or more creatures you control die", RULE 603.2c / 603.10a) sees ONE event for the whole cost while a
per-creature trigger ("whenever a creature you control dies") still fires once per creature."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

BATCH = "Whenever one or more creatures you control die, draw a card."
EACH = "Whenever a creature you control dies, draw a card."


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    you = eng.state.player_by_id("p1")
    for i in range(10):
        you.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Instant"), owner_id="p1", zone=Zone.LIBRARY))
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    return eng, you


def _bf(eng, card):
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _bear(eng, name):
    return _bf(eng, Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2))


def _modeled(name, type_line, oracle, **kw):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=oracle, **kw)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return card


def _listener(eng, oracle):
    return _bf(eng, _modeled("Listener", "Enchantment", oracle))


def _hand_size_after(oracle_listener, ability_oracle, picks_of, **ability_kw):
    eng, you = _engine()
    _listener(eng, oracle_listener)
    engine_src = _bf(eng, _modeled("Altar", "Creature — Bear", ability_oracle, is_creature=True, power=1, toughness=1))
    bears = [_bear(eng, "A"), _bear(eng, "B")]
    you.mana_pool.add("C", 3)
    eng.activate_ability(you, engine_src, 0, tap_choices=[b.instance_id for b in picks_of(bears)], **ability_kw)
    eng.resolve_until_stable()
    return len(you.hand), bears


def test_counted_sacrifice_cost_fires_a_batched_trigger_once():
    hand, bears = _hand_size_after(BATCH, "{1}, Sacrifice two other creatures: Scry 1.", lambda b: b)
    assert all(b.zone == Zone.GRAVEYARD for b in bears)
    assert hand == 1


def test_counted_sacrifice_cost_still_fires_a_per_creature_trigger_twice():
    hand, _ = _hand_size_after(EACH, "{1}, Sacrifice two other creatures: Scry 1.", lambda b: b)
    assert hand == 2


def test_any_number_sacrifice_cost_fires_a_batched_trigger_once():
    hand, bears = _hand_size_after(BATCH, "{1}, Sacrifice any number of other creatures: Scry 1.", lambda b: b)
    assert all(b.zone == Zone.GRAVEYARD for b in bears)
    assert hand == 1


def test_group_sacrifice_cost_with_the_source_fires_a_batched_trigger_once():
    eng, you = _engine()
    _listener(eng, BATCH)
    src = _bf(eng, _modeled("Magus", "Creature — Human", "{1}, Sacrifice ~ and another creature: Scry 1.",
                            is_creature=True, power=1, toughness=1))
    bear = _bear(eng, "A")
    you.mana_pool.add("C", 2)
    eng.activate_ability(you, src, 0, tap_choices=[bear.instance_id])
    eng.resolve_until_stable()
    assert src.zone == Zone.GRAVEYARD and bear.zone == Zone.GRAVEYARD
    assert len(you.hand) == 1


def test_a_mana_ability_sacrifice_cost_fires_a_batched_trigger_once():
    # The no-stack mana-ability path (`tap_for_mana`) pays its cost outside `activate_ability`'s own batch scope.
    eng, you = _engine()
    _listener(eng, BATCH)
    src = _bf(eng, _modeled("Pit", "Creature — Bear", "Sacrifice two other creatures: Add {R}{R}.",
                            is_creature=True, power=1, toughness=1))
    bears = [_bear(eng, "A"), _bear(eng, "B")]
    eng.tap_for_mana(you, src, tap_choices=[b.instance_id for b in bears])
    eng.resolve_until_stable()
    assert all(b.zone == Zone.GRAVEYARD for b in bears)
    assert len(you.hand) == 1


@pytest.mark.skipif(not DB_PATH.exists(), reason="needs the local card cache")
def test_a_cast_additional_sacrifice_cost_fires_a_batched_trigger_once():
    # Vicious Betrayal: "As an additional cost ..., sacrifice any number of creatures."
    card = CardDatabase(DB_PATH).get_card("Vicious Betrayal")
    if card is None:
        pytest.skip("Vicious Betrayal not in the local card cache")
    eng, you = _engine()
    _listener(eng, BATCH)
    bears = [_bear(eng, "A"), _bear(eng, "B")]
    target = _bear(eng, "T")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    you.hand.append(spell)
    you.mana_pool.add("B", 5)
    eng.cast_spell(you, spell, targets=[target], sacrifice_choices=[b.instance_id for b in bears])
    eng.resolve_until_stable()
    assert all(b.zone == Zone.GRAVEYARD for b in bears)
    assert len(you.hand) == 1
