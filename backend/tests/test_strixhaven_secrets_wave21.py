"""Secrets of Strixhaven — playability batch, wave 21.

Wave 21 (PARSER_VERSION 297 -> 298): "you and target opponent each draw N
cards." A `handlers.py` row emitting two `draw` EffectSpecs — one
untargeted (the source's controller) and one ``target_kind="opponent"`` —
resolved in that order. Secret Rendezvous (Silverquill + Lorehold decks),
Sky Crier, Loran of the Third Path, Farsight Adept, Flumph, Love Song of
Night and Day.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_clause_emits_two_draws():
    assert match_clause("you and target opponent each draw 3 cards") == [
        EffectSpec("draw", {"count": 3}),
        EffectSpec("draw", {"count": 3, "target_kind": "opponent"}),
    ]


def test_clause_singular_a_card():
    assert match_clause("you and target opponent each draw a card") == [
        EffectSpec("draw", {"count": 1}),
        EffectSpec("draw", {"count": 1, "target_kind": "opponent"}),
    ]


def test_adversarial_plain_draw_unaffected():
    assert match_clause("you draw a card") == [EffectSpec("draw", {"count": 1})]
    assert match_clause("target opponent draws a card") == [
        EffectSpec("draw", {"count": 1, "target_kind": "player"}),
    ]


@pytest.mark.parametrize("name", [
    "Secret Rendezvous", "Sky Crier", "Loran of the Third Path",
    "Farsight Adept", "Flumph", "Love Song of Night and Day",
])
def test_real_cards_modeled(name):
    r = parse_oracle(_db().get_card(name))
    assert r.coverage != UNMODELED, r.unclaimed


def test_runtime_only_you_and_chosen_opponent_draw():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_hand=0, starting_life=20,
    )
    p1 = eng.state.active_player
    p2, p3 = [p for p in eng.state.players if p.id != p1.id]
    for pl in eng.state.players:
        for i in range(10):
            pl.library.append(GameObject(
                card=Card(id=f"{pl.id}-l{i}", name="Island",
                          type_line="Basic Land — Island", is_land=True),
                owner_id=pl.id, zone=Zone.LIBRARY,
            ))

    src = GameObject(card=Card(id="sr", name="Secret Rendezvous", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    effs = build_effects([
        EffectSpec("draw", {"count": 3}),
        EffectSpec("draw", {"count": 3, "target_kind": "opponent"}),
    ], src)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [p2])

    assert len(p1.hand) == 3   # "you"
    assert len(p2.hand) == 3   # the chosen opponent
    assert len(p3.hand) == 0   # untouched
