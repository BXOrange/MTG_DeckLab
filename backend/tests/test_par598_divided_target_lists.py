"""Contiguous target-count lists retain divided totals and target restrictions."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


@pytest.mark.parametrize("counts,minimum,maximum", [
    ("1 or 2", 1, 2), ("1, 2, or 3", 1, 3), ("1, 2 or 3", 1, 3),
    ("2, 3, 4, or 5", 2, 5),
])
def test_contiguous_count_lists_use_the_existing_target_range(counts, minimum, maximum):
    specs = parse_effect_body(f"~ deals 5 damage divided as you choose among {counts} targets")
    assert len(specs) == 1
    assert specs[0].params == {"amount": 5, "target_kind": "any", "count": minimum,
                               "count_max": maximum, "divided": True}


@pytest.mark.parametrize("counts", ["0, 1, or 2", "1, 3, or 4", "1, 2, or 2", "2, 1, or 3"])
def test_noncontiguous_or_invalid_lists_fail_closed(counts):
    assert parse_effect_body(f"~ deals 5 damage divided as you choose among {counts} targets") is None


@pytest.mark.parametrize("name", ["Arc Lightning", "Flames of the Firebrand", "Flameshot",
                                  "Forked Lightning", "Magic Missile", "Inferno Titan",
                                  "Gang of Devils", "Aerial Volley", "Deft Dismissal", "Fire at Will",
                                  "Arrow Volley Trap", "Hail of Arrows"])
def test_real_cards_are_fully_modeled(name):
    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None
    assert parse_oracle(card).modeled


def _game():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.players[0], engine.state.players[1]


def _hand(engine, player, name):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.hand.append(obj)
    return obj


def test_arc_lightning_cast_divides_three_damage_between_three_announced_targets():
    engine, p1, p2 = _game()
    victims = [battlefield_object(engine, "p2", f"Soldier {i}", "Creature",
                                 is_creature=True, power=1, toughness=1) for i in range(3)]
    spell = _hand(engine, p1, "Arc Lightning")
    p1.mana_pool.add_many({"C": 2, "R": 1})
    engine.cast_spell(p1, spell, targets=victims)
    engine.resolve_until_stable()
    assert all(v in p2.graveyard for v in victims)
    assert p2.life == 20


def test_aerial_volley_restricts_every_target_to_a_flying_creature():
    engine, p1, p2 = _game()
    flyer = battlefield_object(engine, "p2", "Flyer", "Creature", is_creature=True, power=1, toughness=1)
    flyer.intrinsic_keywords.add("flying")
    ground = battlefield_object(engine, "p2", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    spell = _hand(engine, p1, "Aerial Volley")
    spec = spell.spell_effects[0].target_spec
    assert [o["instance_id"] for o in legal_targets(engine.state, "p1", spec, source=spell)] == [flyer.instance_id]
    p1.mana_pool.add_many({"G": 1})
    engine.cast_spell(p1, spell, targets=[flyer])
    engine.resolve_until_stable()
    assert flyer in p2.graveyard and ground in engine.state.battlefield


def test_inferno_titan_real_cast_and_attack_each_offer_the_full_target_range():
    engine, p1, p2 = _game()
    victims = [battlefield_object(engine, "p2", f"Soldier {i}", "Creature",
                                 is_creature=True, power=1, toughness=1) for i in range(3)]
    titan = _hand(engine, p1, "Inferno Titan")
    p1.mana_pool.add_many({"C": 4, "R": 2})
    engine.cast_spell(p1, titan)
    engine.resolve_until_stable()
    for i, victim in enumerate(victims):
        choice = engine.state.pending_choice
        assert choice is not None and choice["kind"] == "trigger_target_multi"
        assert any(o.get("id") == "stop" for o in choice["options"]) == (i > 0)
        engine.resolve_pending_choice(str(victim.instance_id))
        engine.resolve_until_stable()
    assert all(v in p2.graveyard for v in victims)
    titan.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [titan])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice("p2")
    engine.resolve_until_stable()
    assert any(o.get("id") == "stop" for o in engine.state.pending_choice["options"])
    engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    assert p2.life == 17
