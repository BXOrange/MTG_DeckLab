"""'When that creature dies this turn, …' after a clause that chose it (PAR-102 family): the "it" subject and
bodies that name the dying creature's controller (Virulent Wound)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


def test_it_names_the_creature_a_previous_clause_chose():
    seg = _segment("target creature gets +3/+0 until end of turn. when it dies this turn, draw a card.")
    assert seg.claimed
    assert not _segment("when it dies this turn, draw a card.").claimed  # nothing chose "it": stays unclaimed


def test_a_body_naming_the_dying_creatures_controller_is_claimed_for_a_chosen_creature():
    seg = _segment("put a -1/-1 counter on target creature. when that creature dies this turn, its controller gets a poison counter.")
    assert seg.claimed
    assert not _segment("when that creature dies this turn, its controller gets a poison counter.").claimed


def test_virulent_wound_is_modeled():
    result = parse_oracle(CardDatabase(DB_PATH).get_card("Virulent Wound"))
    assert result.coverage == "MODELED"


def _cast_wound(toughness):
    cards = [CardDatabase(DB_PATH).get_card("Virulent Wound")]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=1, starting_life=20)
    p1 = engine.state.player_by_id("p1")
    engine.begin_turn()
    engine.state.current_step = "main1"
    wound = p1.hand[0]
    bind_from_catalogue(wound)
    victim = battlefield_object(engine, "p2", "Victim", "Creature — Bear", is_creature=True, power=1, toughness=toughness)
    p1.mana_pool.add_many({"B": 1})
    engine.cast_spell(p1, wound, targets=[victim])
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    return engine, victim


def test_virulent_wound_poisons_the_controller_of_the_creature_that_died():
    engine, victim = _cast_wound(toughness=1)
    assert victim.zone == Zone.GRAVEYARD
    assert engine.state.player_by_id("p2").poison == 1
    assert engine.state.player_by_id("p1").poison == 0


def test_virulent_wound_does_nothing_if_the_creature_survives():
    engine, victim = _cast_wound(toughness=3)
    assert victim.zone == Zone.BATTLEFIELD
    assert engine.state.player_by_id("p2").poison == 0


def test_return_it_in_a_pinned_dies_trigger_returns_the_dead_creature_not_the_source():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject

    text = ("Choose target creature. When that creature dies this turn, return it to the battlefield "
            "tapped under your control.")
    spell = Card(id="Rise Again", name="Rise Again", type_line="Instant", is_instant=True, oracle_text=text,
                 mana_cost_string="{B}", converted_mana_cost=1, mana_cost={"B": 1})
    assert parse_oracle(spell).coverage == "MODELED"
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    p1 = engine.state.player_by_id("p1")
    engine.begin_turn()
    engine.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    victim = battlefield_object(engine, "p2", "Victim", "Creature — Bear", is_creature=True, power=1, toughness=1)
    p1.mana_pool.add_many({"B": 1})
    engine.cast_spell(p1, obj, targets=[victim])
    engine.resolve_until_stable()
    assert obj.zone == Zone.GRAVEYARD and victim.zone == Zone.BATTLEFIELD
    engine.rules.destroy(victim) if hasattr(engine.rules, "destroy") else None
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD and victim.controller_id == "p1" and victim.tapped
    assert obj.zone == Zone.GRAVEYARD  # the spell itself stayed put
