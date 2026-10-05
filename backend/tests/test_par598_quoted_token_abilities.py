"""Quoted token abilities are validated, bound per token, and controller scoped."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase


@pytest.mark.parametrize("name", ["Dance with Devils", "Devils' Playground", "Mitotic Slime"])
def test_quoted_dies_abilities_fully_model_real_cards(name):
    card = CardDatabase(DB_PATH).get_card(name)
    assert parse_oracle(card).modeled


@pytest.mark.parametrize("ability", ["when ~ dies, seek a card", "draw 1 card",
                                    "when ~ dies, you gain 1 life. then seek a card"])
def test_unknown_or_incomplete_quoted_abilities_fail_closed(ability):
    assert parse_effect_body(f'create 2 1/1 red devil creature tokens. they have "{ability}"') is None


def test_devil_token_death_damage_is_the_tokens_own_trigger_and_follows_its_controller():
    db = CardDatabase(DB_PATH)
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1, p2 = engine.state.players
    spell = GameObject(db.get_card("Dance with Devils"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"C": 3, "R": 1})
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    devils = [o for o in engine.state.battlefield if o.name == "Devil"]
    assert len(devils) == 2
    assert all(len(o.triggered_abilities) == 1 for o in devils)
    devils[0].controller_id = "p2"
    engine.rules.destroy(devils[0])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("p1")
    engine.resolve_until_stable()
    assert p1.life == 19 and p2.life == 20
    assert devils[1] in engine.state.battlefield


def test_queued_token_trigger_keeps_its_controller_after_control_changes():
    from mtg_analyzer.game.effects.core import GameContext, CreateTokenEffect

    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    create = CreateTokenEffect(count=1, power=1, toughness=1, colors=["R"], subtypes=["Devil"],
                               oracle_text="When this token becomes tapped, it deals 1 damage to any target.")
    create.apply(GameContext(engine.state, engine.rules))
    token = next(o for o in engine.state.battlefield if o.is_token)
    token.controller_id = "p2"
    engine.rules.set_tapped(token, True)  # fire under p2's control
    token.controller_id = "p1"  # control changes before placement
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("p1")
    engine.resolve_until_stable()
    assert engine.state.players[0].life == 19
