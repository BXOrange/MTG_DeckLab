"""RULE 702.53: parsed Transmute must become a playable hand ability."""

from unittest.mock import patch

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _setup(name="Muddle the Mixture", mana_cost="{U}{U}", mana_value=2):
    card = Card(
        id=name, name=name, type_line="Instant", is_instant=True,
        mana_cost_string=mana_cost, converted_mana_cost=mana_value,
        keywords=["Transmute"],
        oracle_text="Counter target instant or sorcery spell.\n"
        "Transmute {1}{U}{U} ({1}{U}{U}, Discard this card: Search your library "
        "for a card with the same mana value as this card, reveal it, put it "
        "into your hand, then shuffle. Activate only as a sorcery.)",
    )
    library = [
        Card(id=str(value), name=f"Artifact {value}", type_line="Artifact",
             mana_cost_string=f"{{{value}}}", converted_mana_cost=value)
        for value in range(7)
    ]
    engine = GameEngine.new_game([("p1", "Alice", library)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    player = engine.state.active_player
    player.mana_pool.add_many({"U": 2, "C": 1})
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    player.add_to_zone(obj, Zone.HAND)
    return engine, player, obj


@pytest.mark.parametrize("name,mana_cost,mana_value", [
    ("Muddle the Mixture", "{U}{U}", 2),
    ("Transmute test card", "{5}{U}", 6),
])
def test_transmute_is_offered_and_searches_for_source_mana_value(name, mana_cost, mana_value):
    engine, player, obj = _setup(name, mana_cost, mana_value)
    assert parse_oracle(obj.card).coverage == MODELED
    assert len(obj.activated_abilities) == 1
    assert obj.spell_effects  # the counterspell remains available separately
    offers = [a for a in engine.legal_actions(player)
              if a.get("type") == "activate_ability" and a.get("instance_id") == obj.instance_id]
    assert len(offers) == 1

    engine.activate_ability(player, obj, 0)
    assert obj in player.graveyard
    assert obj not in player.hand
    assert player.mana_pool.total() == 0
    assert engine.state.stack
    assert engine.state.pending_choice is None
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice["kind"] == "search"
    assert [o["name"] for o in choice["eligible"]] == [f"Artifact {mana_value}"]
    with patch.object(engine.rules, "shuffle_library", wraps=engine.rules.shuffle_library) as shuffle:
        engine.rules.resolve_choice(choice["eligible"][0]["instance_id"])
        shuffle.assert_called_once_with(player)
    assert any(o.name == f"Artifact {mana_value}" for o in player.hand)


@pytest.mark.parametrize("step", ["upkeep", "declare_attackers", "end_step"])
def test_transmute_cannot_be_activated_outside_main_phase(step):
    engine, player, obj = _setup()
    engine.state.current_step = step
    assert not engine.can_activate(player, obj, obj.activated_abilities[0])


def test_transmute_requires_mana_and_hand_zone_and_empty_stack():
    engine, player, obj = _setup()
    ability = obj.activated_abilities[0]
    player.mana_pool.empty()
    assert not engine.can_activate(player, obj, ability)
    player.mana_pool.add_many({"U": 2, "C": 1})
    engine.state.stack.append(object())
    assert not engine.can_activate(player, obj, ability)
    engine.state.stack.clear()
    player.hand.remove(obj)
    player.add_to_zone(obj, Zone.GRAVEYARD)
    assert not engine.can_activate(player, obj, ability)


def test_transmute_may_fail_to_find_and_still_shuffles():
    engine, player, obj = _setup()
    engine.activate_ability(player, obj, 0)
    engine.resolve_until_stable()
    with patch.object(engine.rules, "shuffle_library", wraps=engine.rules.shuffle_library) as shuffle:
        engine.rules.resolve_choice(None)
        shuffle.assert_called_once_with(player)
    assert player.hand == []
    assert obj in player.graveyard
