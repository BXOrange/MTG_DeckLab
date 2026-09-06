"""PAR-30 — the colour-list target extended to bounce / put-on-library /
graveyard-recursion.

`ReturnToHandEffect` / `ReturnToLibraryEffect` / `ReturnFromGraveyardEffect`
each gained a `colors` param threaded into their `TargetSpec`; three
dedicated `_RETURN_*_TWO_COLOR_RE` handlers (Escape Routes, Hunting Drake,
Crypt Angel). `TargetSpec.colors` + `targeting._color_ok` were already
wired into every `legal_targets` branch these kinds resolve through.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _bf_creature(state, name, colors, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors)),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def _gy_creature(state, name, colors, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors)),
                   owner_id=pid, zone=Zone.GRAVEYARD)
    state.player_by_id(pid).graveyard.append(o)
    return o


# --- parse -----------------------------------------------------------------


def test_bounce_two_color_parses():
    assert match_clause(
        "return target white or black creature you control to its owner's hand"
    ) == [EffectSpec("return_to_hand", {"target_kind": "creature_you_control",
                                        "colors": ["W", "B"]})]
    assert match_clause(
        "return target green or blue creature to its owner's hand"
    ) == [EffectSpec("return_to_hand", {"target_kind": "creature", "colors": ["G", "U"]})]


def test_library_two_color_parses():
    assert match_clause(
        "put target red or green creature on top of its owner's library"
    ) == [EffectSpec("return_to_library", {"target_kind": "creature",
                                           "position": "top", "colors": ["R", "G"]})]


def test_graveyard_two_color_parses():
    assert match_clause(
        "return target blue or red creature card from your graveyard to your hand"
    ) == [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature",
                                               "destination": "hand", "colors": ["U", "R"]})]


def test_same_colour_twice_fails_closed():
    assert match_clause(
        "return target red or red creature to its owner's hand"
    ) is None
    assert match_clause(
        "put target blue or blue creature on top of its owner's library"
    ) is None


def test_real_cards_modeled():
    for name, text, tline in [
        ("Escape Routes",
         "{2}{U}: Return target white or black creature you control to its owner's hand.",
         "Creature — Human Wizard"),
        ("Hunting Drake",
         "When Hunting Drake enters, put target red or green creature on top of its owner's library.",
         "Creature — Drake"),
        ("Crypt Angel",
         "When Crypt Angel enters, return target blue or red creature card from your graveyard to your hand.",
         "Creature — Angel"),
    ]:
        c = Card(id=name[:3], name=name, type_line=tline, is_creature=True,
                 power=2, toughness=2, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_bounce_only_offers_a_matching_colour():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    white = _bf_creature(state, "White Bear", {"W"})
    black = _bf_creature(state, "Black Bear", {"B"})
    green = _bf_creature(state, "Green Bear", {"G"})
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("return_to_hand", {
        "target_kind": "creature_you_control", "colors": ["W", "B"],
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert {white.instance_id, black.instance_id} <= offered
    assert green.instance_id not in offered


def test_graveyard_return_two_color_moves_the_card_to_hand():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    blue = _gy_creature(state, "Blue Ghoul", {"U"})

    build_effects([EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand", "colors": ["U", "R"],
    })], src)[0].apply(GameContext(state, eng.rules), [blue])

    assert blue in p1.hand and blue not in p1.graveyard


def test_library_return_two_color_moves_the_creature():
    eng, state = _engine()
    p2 = state.player_by_id("p2")
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    red = _bf_creature(state, "Red Bear", {"R"}, pid="p2")

    build_effects([EffectSpec("return_to_library", {
        "target_kind": "creature", "position": "top", "colors": ["R", "G"],
    })], src)[0].apply(GameContext(state, eng.rules), [red])

    assert red not in state.battlefield
    assert p2.library and p2.library[-1] is red
