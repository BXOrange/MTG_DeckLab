"""PAR-38's remaining upkeep-drawback templates."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return engine, engine.state


def _source(state):
    source = GameObject(
        Card(id="src", name="Black Market Tycoon", type_line="Creature — Cat Rogue", is_creature=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    source.controller_id = "p1"
    state.add_to_battlefield(source)
    return source


def test_upkeep_damage_residue_cards_parse_completely():
    cards = [
        Card(id="bmt", name="Black Market Tycoon", type_line="Creature", is_creature=True,
             oracle_text="At the beginning of your upkeep, this creature deals 2 damage to you for each Treasure you control."),
        Card(id="fon", name="Force of Nature", type_line="Creature", is_creature=True,
             oracle_text="At the beginning of your upkeep, this creature deals 8 damage to you unless you pay {G}{G}{G}{G}."),
        Card(id="ets", name="Elfhame Sanctuary", type_line="Enchantment",
             oracle_text="At the beginning of your upkeep, you may search your library for a basic land card, reveal it, put it into your hand, then shuffle. If you do, you skip your draw step this turn."),
    ]
    for card in cards:
        result = parse_oracle(card)
        assert result.coverage != UNMODELED, (card.name, result.unclaimed)


def test_treasure_scaled_damage_uses_the_live_treasure_count():
    engine, state = _engine()
    source = _source(state)
    for n in range(3):
        treasure = GameObject(
            Card(id=f"t{n}", name="Treasure", type_line="Token Artifact — Treasure"),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        treasure.controller_id = "p1"
        state.add_to_battlefield(treasure)
    effect = build_effects(parse_effect_body(
        "this creature deals 2 damage to you for each Treasure you control", self_subject=True
    ), source)[0]
    effect.apply(GameContext(state, engine.rules))
    assert state.player_by_id("p1").life == 14
    assert state.player_by_id("p2").life == 20


def test_unless_pay_damage_is_only_applied_when_payment_is_declined():
    engine, state = _engine()
    source = _source(state)
    effect = build_effects(parse_effect_body(
        "this creature deals 8 damage to you unless you pay {G}{G}{G}{G}", self_subject=True
    ), source)[0]
    effect.apply(GameContext(state, engine.rules))
    # No mana means no choice prompt; the ordinary "unless" consequence is
    # resolved immediately.
    assert state.player_by_id("p1").life == 12


def test_if_you_do_draw_skip_is_one_shot():
    engine, state = _engine()
    source = _source(state)
    effect = build_effects([EffectSpec("skip_next_step", {"step": "draw"})], source)[0]
    effect.apply(GameContext(state, engine.rules))
    player = state.player_by_id("p1")
    assert engine.rules.should_skip_step(player, "draw") is True
    assert engine.rules.should_skip_step(player, "draw") is False
