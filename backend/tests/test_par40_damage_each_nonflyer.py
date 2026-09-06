"""PAR-40 — "~ deals N damage to each creature without flying [and each
player]." (RULE 601.2c — the Earthquake / Fault Line / Tremor / Rolling
Temblor ground-sweeper family).

New `damage_each_nonflyer` handler + `DealDamageEffect.selector_filter` (a
`combat.matches_object_filter`-shaped dict applied to the `each_creature`
/ `each_creature_and_player` iteration only — players in a union selector
are never filtered).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, name, pid, toughness=2, keywords=None):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bird",
             is_creature=True, power=2, toughness=toughness,
             keywords=list(keywords or [])),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_bare_nonflyer_form_parses():
    assert parse_effect_body("~ deals 2 damage to each creature without flying") == [
        EffectSpec("damage", {
            "amount": 2, "selector": "each_creature",
            "selector_filter": {"without_keyword": "flying"},
        })
    ]


def test_x_and_player_form_parses():
    assert parse_effect_body(
        "~ deals x damage to each creature without flying and each player"
    ) == [
        EffectSpec("damage", {
            "amount": "x", "selector": "each_creature_and_player",
            "selector_filter": {"without_keyword": "flying"},
        })
    ]


def test_plain_each_creature_still_unfiltered():
    assert parse_effect_body("~ deals 2 damage to each creature") == [
        EffectSpec("damage", {"amount": 2, "selector": "each_creature"})
    ]


def test_real_cards_modeled():
    for name, text in [
        ("Tremor", "Tremor deals 1 damage to each creature without flying."),
        ("Earthquake",
         "Earthquake deals X damage to each creature without flying and each player."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Sorcery", is_sorcery=True,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_nonflyers_take_damage_flyers_do_not():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="q", name="Earthquake", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    ground = _creature(state, "Grizzly Bear", "p1", toughness=3)
    flyer = _creature(state, "Wind Drake", "p2", toughness=3, keywords=["flying"])
    eng.recompute_continuous_effects()

    build_effects([EffectSpec("damage", {
        "amount": 2, "selector": "each_creature",
        "selector_filter": {"without_keyword": "flying"},
    })], src)[0].apply(GameContext(state, eng.rules), None)
    eng.rules.check_state_based_actions()

    assert ground.damage_marked == 2
    assert flyer.damage_marked == 0


def test_and_each_player_hits_players_too_but_never_filters_them():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="q", name="Earthquake", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    ground = _creature(state, "Bear", "p1", toughness=5)
    flyer = _creature(state, "Drake", "p2", toughness=5, keywords=["flying"])
    eng.recompute_continuous_effects()

    build_effects([EffectSpec("damage", {
        "amount": 3, "selector": "each_creature_and_player",
        "selector_filter": {"without_keyword": "flying"},
    })], src)[0].apply(GameContext(state, eng.rules), None)

    assert ground.damage_marked == 3
    assert flyer.damage_marked == 0
    assert state.player_by_id("p1").life == 17
    assert state.player_by_id("p2").life == 17
