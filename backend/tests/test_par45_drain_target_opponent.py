"""PAR-45 — "target opponent loses N life [and you gain N life]" (the Blood
Artist / Zulaport Cutthroat drain family).

The `lose_life` handler's `who` alternation gained `target opponent` →
`EffectSpec("lose_life", {"target_kind": "opponent"})` (the RULE 115
opponent-restricted player target, already a valid `ALLOWED_TARGET_KINDS`
entry). The paired "and you gain N life" clause is claimed by the existing
`gain_life` row via the ordinary connector split — no new "drain" effect
type needed.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine(players=2):
    seats = [("p1", "Alice", []), ("p2", "Bob", [])]
    if players == 3:
        seats.append(("p3", "Carol", []))
    eng = GameEngine.new_game(seats, starting_life=20, starting_hand=0)
    return eng, eng.state


# --- parse -----------------------------------------------------------------


def test_target_opponent_loses_life_parses():
    assert parse_effect_body("target opponent loses 3 life") == [
        EffectSpec("lose_life", {"amount": 3, "target_kind": "opponent"})
    ]


def test_drain_pair_splits_into_lose_and_gain():
    assert parse_effect_body("target opponent loses 1 life and you gain 1 life") == [
        EffectSpec("lose_life", {"amount": 1, "target_kind": "opponent"}),
        EffectSpec("gain_life", {"amount": 1}),
    ]


def test_target_player_still_maps_to_the_plain_player_kind():
    assert parse_effect_body("target player loses 2 life") == [
        EffectSpec("lose_life", {"amount": 2, "target_kind": "player"})
    ]


def test_real_cards_modeled():
    creatures = [
        ("Blood Artist",
         "Whenever Blood Artist or another creature dies, target opponent "
         "loses 1 life and you gain 1 life."),
        ("Pierce Strider",
         "When Pierce Strider enters, target opponent loses 3 life."),
    ]
    for name, text in creatures:
        c = Card(id=name[:3], name=name, type_line="Creature", is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)

    bump = Card(id="btn", name="Bump in the Night", type_line="Sorcery", is_sorcery=True,
                oracle_text="Target opponent loses 3 life.")
    assert parse_oracle(bump).coverage != UNMODELED, parse_oracle(bump).unclaimed


# --- execute -------------------------------------------------------------------


def test_opponent_target_offers_only_opponents():
    eng, state = _engine(players=3)
    src = GameObject(Card(id="src", name="Blood Artist", type_line="Creature — Vampire",
                          is_creature=True, power=0, toughness=1),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)

    eff = build_effects([EffectSpec("lose_life", {"amount": 1, "target_kind": "opponent"})], src)[0]
    offered = {t["player_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}
    assert offered == {"p2", "p3"}  # never p1 itself


def test_drain_moves_life_both_ways():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Zulaport Cutthroat", type_line="Creature — Ally",
                          is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)

    ctx = GameContext(state, eng.rules)
    lose, gain = build_effects([
        EffectSpec("lose_life", {"amount": 1, "target_kind": "opponent"}),
        EffectSpec("gain_life", {"amount": 1}),
    ], src)
    lose.apply(ctx, [state.player_by_id("p2")])
    gain.apply(ctx, None)

    assert state.player_by_id("p2").life == 19
    assert state.player_by_id("p1").life == 21
