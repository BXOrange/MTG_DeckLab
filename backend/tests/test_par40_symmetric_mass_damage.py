"""PAR-40 — symmetric mass-damage board-wipe selectors.

`_SELECTOR_WORD_MAP` + the `damage_selector` handler regex gained two
global-scope union selectors `DealDamageEffect` already resolves:
``each_creature_and_player`` ("~ deals N damage to each creature and each
player" — Cave-In / Fire Tempest / Inferno / Pestilence Demon) and
``each_creature_and_planeswalker`` ("… to each creature and each
planeswalker" — Star of Extinction / Storm's Wrath / Dragonback Assault).
Both unions come first in the alternation so the bare "each creature" branch
can't consume a prefix and then fail the fullmatch. No engine change — the
selectors were already wired in `DealDamageEffect._selector_targets`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, pid, toughness=2):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=2, toughness=toughness),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_each_creature_and_each_player_parses():
    assert parse_effect_body("~ deals 2 damage to each creature and each player") == [
        EffectSpec("damage", {"amount": 2, "selector": "each_creature_and_player"})
    ]


def test_each_creature_and_each_planeswalker_parses():
    assert parse_effect_body("~ deals 20 damage to each creature and each planeswalker") == [
        EffectSpec("damage", {"amount": 20, "selector": "each_creature_and_planeswalker"})
    ]


def test_it_subject_form_parses():
    assert parse_effect_body("it deals 6 damage to each creature and each player") == [
        EffectSpec("damage", {"amount": 6, "selector": "each_creature_and_player"})
    ]


def test_bare_each_creature_still_plain():
    assert parse_effect_body("~ deals 2 damage to each creature") == [
        EffectSpec("damage", {"amount": 2, "selector": "each_creature"})
    ]


def test_unknown_union_fails_closed():
    assert parse_effect_body("~ deals 2 damage to each creature and each land") is None


def test_real_cards_modeled():
    for name, text in [
        ("Cave-In", "Cave-In deals 2 damage to each creature and each player."),
        ("Inferno", "Inferno deals 6 damage to each creature and each player."),
        ("Storm's Wrath", "Storm's Wrath deals 4 damage to each creature and each planeswalker."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Instant", is_instant=True,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_each_creature_and_player_hits_everything():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Fire Tempest", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    mine = _creature(state, "My Bear", "p1", toughness=3)
    theirs = _creature(state, "Their Bear", "p2", toughness=3)
    eng.recompute_continuous_effects()

    build_effects([EffectSpec("damage", {
        "amount": 2, "selector": "each_creature_and_player",
    })], src)[0].apply(GameContext(state, eng.rules), None)
    eng.rules.check_state_based_actions()

    assert mine.damage_marked == 2
    assert theirs.damage_marked == 2
    assert state.player_by_id("p1").life == 18
    assert state.player_by_id("p2").life == 18


def test_each_creature_and_player_is_lethal_symmetrically():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Inferno", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    mine = _creature(state, "My Bear", "p1")
    theirs = _creature(state, "Their Bear", "p2")
    eng.recompute_continuous_effects()

    build_effects([EffectSpec("damage", {
        "amount": 6, "selector": "each_creature_and_player",
    })], src)[0].apply(GameContext(state, eng.rules), None)
    eng.rules.check_state_based_actions()

    assert mine not in state.battlefield
    assert theirs not in state.battlefield
    assert state.player_by_id("p1").life == 14
