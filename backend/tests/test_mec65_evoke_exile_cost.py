"""MEC-65 — RULE 702.74 Evoke paid by exiling a coloured hand card."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _incarnation(name: str, color_name: str) -> Card:
    return Card(
        id=name,
        name=name,
        type_line="Creature — Elemental Incarnation",
        mana_cost_string="{5}",
        converted_mana_cost=5,
        is_creature=True,
        power=3,
        toughness=3,
        keywords=["Evoke"],
        oracle_text=f"Evoke—Exile a {color_name} card from your hand.",
    )


def _hand_object(state, card: Card) -> GameObject:
    player = state.active_player
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


@pytest.mark.parametrize(
    ("name", "color_name", "color"),
    [
        ("Solitude", "white", "W"),
        ("Endurance", "green", "G"),
        ("Fury", "red", "R"),
        ("Subtlety", "blue", "U"),
        ("Grief", "black", "B"),
    ],
)
def test_modern_incarnations_offer_and_pay_their_exile_cost_evoke(name, color_name, color):
    engine = GameEngine.new_game([("p1", "Alice", [])], starting_hand=0)
    state = engine.state
    player = state.active_player
    engine.begin_turn()
    state.current_step = "main1"

    spell = _hand_object(state, _incarnation(name, color_name))
    payment = _hand_object(state, Card(
        id=f"{name} payment", name=f"{name} payment", type_line="Creature",
        is_creature=True, color_identity={color},
    ))

    assert spell.parametric_keywords["evoke"] == {"exile_hand_card_color": color}
    evoke_actions = [a for a in engine.legal_actions(player) if a.get("evoke")]
    assert any(a.get("instance_id") == spell.instance_id for a in evoke_actions)

    engine.cast_spell(player, spell, evoke=True)
    engine.resolve_until_stable()

    assert payment.zone == Zone.EXILE
    assert spell.zone == Zone.GRAVEYARD


def test_exile_cost_evoke_requires_a_matching_hand_card():
    engine = GameEngine.new_game([("p1", "Alice", [])], starting_hand=0)
    state = engine.state
    player = state.active_player
    engine.begin_turn()
    state.current_step = "main1"

    spell = _hand_object(state, _incarnation("Solitude", "white"))
    _hand_object(state, Card(
        id="wrong payment", name="wrong payment", type_line="Creature",
        is_creature=True, color_identity={"U"},
    ))

    assert not engine.can_cast(player, spell, evoke=True)
    assert not any(a.get("evoke") for a in engine.legal_actions(player))
