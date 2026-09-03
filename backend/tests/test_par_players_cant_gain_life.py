"""PAR-42/45-adjacent — "Players can't gain life." as a standing static
(RULE 119.3-adjacent).

New `prevent_all_life_gain` marker `StaticAbility` (layer
`life_gain_prohibition`, `_NON_RULE_613_LAYERS`), consulted live by
`RulesEngine.gain_life` via `continuous.life_gain_prohibited_for`. Covers
the bare board-wide form (Forsaken Wastes / Everlasting Torment / Havoc
Festival / Leyline of Punishment), the opponent-scoped form (Erebos, God
of the Dead) and Sulfuric Vortex's replacement-phrased equivalent. The
turn-scoped burn-spell rider ("Players can't gain life this turn." —
Skullcrack) reuses `PreventLifeGainEffect` with a new `recipient="all"`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, name, text, controller="p1"):
    o = GameObject(Card(id=name[:8], name=name, type_line="Enchantment", oracle_text=text),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    bind_from_catalogue(o)
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_bare_form_parses_unscoped():
    assert static_effect_specs("players can't gain life") == [
        EffectSpec("prevent_all_life_gain", {})
    ]


def test_opponent_scoped_form_parses():
    assert static_effect_specs("your opponents can't gain life") == [
        EffectSpec("prevent_all_life_gain", {"scope": "opponents"})
    ]


def test_replacement_phrased_form_parses():
    assert static_effect_specs(
        "if a player would gain life, that player gains no life instead"
    ) == [EffectSpec("prevent_all_life_gain", {})]


def test_real_cards_modeled():
    for name, text in [
        ("Erebos, God of the Dead",
         "Indestructible\nAs long as your devotion to black is less than five, "
         "Erebos isn't a creature.\nYour opponents can't gain life.\n"
         "{1}{B}, Pay 2 life: Draw a card."),
        ("Rain of Gore",
         "If a player would gain life, that player gains no life instead."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Enchantment", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_bare_static_cancels_every_players_life_gain():
    eng = _engine()
    state = eng.state
    _bf(state, "Forsaken Wastes", "Players can't gain life.")
    eng.recompute_continuous_effects()

    eng.rules.gain_life(state.player_by_id("p1"), 5)
    eng.rules.gain_life(state.player_by_id("p2"), 5)
    assert state.player_by_id("p1").life == 20
    assert state.player_by_id("p2").life == 20


def test_opponent_scoped_static_spares_its_own_controller():
    eng = _engine()
    state = eng.state
    _bf(state, "Erebos", "Your opponents can't gain life.", controller="p1")
    eng.recompute_continuous_effects()

    eng.rules.gain_life(state.player_by_id("p1"), 5)   # controller — allowed
    eng.rules.gain_life(state.player_by_id("p2"), 5)   # opponent — blocked
    assert state.player_by_id("p1").life == 25
    assert state.player_by_id("p2").life == 20


def test_no_static_leaves_life_gain_working():
    eng = _engine()
    state = eng.state
    eng.rules.gain_life(state.player_by_id("p1"), 3)
    assert state.player_by_id("p1").life == 23
