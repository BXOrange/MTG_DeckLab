"""Tests for `DiscardEffect`'s interactive choice — RULE 701.8: the player
who's discarding picks which cards leave their hand, rather than the engine
auto-choosing off the back of the hand list. This is what a "looting" effect
("Draw a card, then discard a card.") and a directly-targeted forced discard
(Mind Rot-shaped) both resolve through; cost payment (`RulesEngine.discard`,
e.g. a Madness-enabling "Discard a card: …" cost) is unaffected — see
`RulesEngine.discard_choice`'s docstring for why the two stay separate.
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import DiscardEffect, GameContext
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player


def _card(name):
    return Card(id=name, name=name, type_line="Instant", is_instant=True)


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _hand_card(player, name):
    obj = GameObject(_card(name), owner_id=player.id, zone=Zone.HAND)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def test_discarding_fewer_cards_than_the_hand_opens_a_choice():
    engine, state, p1, _ = _rules()
    a, b, c = (_hand_card(p1, n) for n in ("A", "B", "C"))
    ctx = GameContext(state, engine)

    DiscardEffect(count=1).apply(ctx, targets=[p1])

    choice = state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    assert choice["action"] == "discard"
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert offered == {a.instance_id, b.instance_id, c.instance_id}
    assert len(p1.hand) == 3  # nothing discarded until the choice is answered


def test_answering_the_choice_discards_exactly_the_chosen_card():
    engine, state, p1, _ = _rules()
    a, b, c = (_hand_card(p1, n) for n in ("A", "B", "C"))
    DiscardEffect(count=1).apply(GameContext(state, engine), targets=[p1])

    engine.resolve_choose_objects_choice(b.instance_id)

    assert state.pending_choice is None
    assert b in p1.graveyard
    assert a in p1.hand and c in p1.hand
    assert len(p1.hand) == 2


def test_discarding_two_cards_asks_twice():
    engine, state, p1, _ = _rules()
    a, b, c = (_hand_card(p1, n) for n in ("A", "B", "C"))
    DiscardEffect(count=2).apply(GameContext(state, engine), targets=[p1])

    engine.resolve_choose_objects_choice(a.instance_id)
    assert state.pending_choice is not None  # one more to pick
    engine.resolve_choose_objects_choice(c.instance_id)

    assert state.pending_choice is None
    assert a in p1.graveyard and c in p1.graveyard
    assert p1.hand == [b]


def test_discarding_the_whole_hand_needs_no_choice():
    """Windfall-shaped: `count` >= hand size is forced — nothing to pick
    between — so it resolves immediately with no prompt."""
    engine, state, p1, _ = _rules()
    a, b = (_hand_card(p1, n) for n in ("A", "B"))
    DiscardEffect(count=2).apply(GameContext(state, engine), targets=[p1])

    assert state.pending_choice is None
    assert a in p1.graveyard and b in p1.graveyard
    assert p1.hand == []


def test_the_discarding_player_chooses_even_when_targeted_by_an_opponent():
    """Mind Rot-shaped: the effect's controller (p2) picks *who* discards,
    but the discarding player (p1) still picks *which* cards — RULE 701.8
    never hands that choice to the caster."""
    engine, state, p1, p2 = _rules()
    a, b = (_hand_card(p1, n) for n in ("A", "B"))
    DiscardEffect(count=1).apply(GameContext(state, engine), targets=[p1])

    choice = state.pending_choice
    assert choice["player_id"] == p1.id
