"""Blight Curse batch C5 wave 7 — Tree of Perdition
(hand-authored, `ability_catalogue/entries_017.py`).

* Tree of Perdition — "{T}: Exchange target opponent's life total with this
  creature's toughness." New bespoke
  `ExchangeLifeTotalWithToughnessEffect` ("exchange_life_total_with_toughness"):
  the opponent's life becomes ~'s former (derived) toughness via life
  gain/loss; ~'s base toughness is set to the opponent's former life by a
  permanent toughness-only layer-7b `pt_set` (``power=None``). Defender folds
  in as a keyword.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


TREE_OF_PERDITION = Card(
    id="TOP", name="Tree of Perdition", type_line="Creature — Plant", is_creature=True,
    power=0, toughness=13, keywords=["Defender"],
    oracle_text="Defender\n{T}: Exchange target opponent's life total with this "
                "creature's toughness.",
)


def _tree_on_battlefield(eng):
    top = GameObject(TREE_OF_PERDITION, owner_id="p1", zone=Zone.BATTLEFIELD)
    top.controller_id = "p1"
    eng.state.add_to_battlefield(top)
    bind_from_catalogue(top)
    return top


def test_tree_of_perdition_authored_tap_ability():
    specs = specs_for(TREE_OF_PERDITION)
    act = [s for s in specs if s.ability_kind == "activated"]
    assert len(act) == 1
    assert act[0].cost["text"] == "{T}"
    assert act[0].effects[0].type == "exchange_life_total_with_toughness"


def test_exchange_sets_opponent_life_down_and_tree_toughness_up():
    eng = _engine()
    top = _tree_on_battlefield(eng)
    p2 = eng.state.players[1]
    assert p2.life == 20

    eff = build_effects([EffectSpec("exchange_life_total_with_toughness", {})], top)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])
    eng.recompute_continuous_effects()

    assert p2.life == 13          # opponent's life -> Tree's former toughness
    assert top.toughness == 20    # Tree's base toughness -> opponent's former life


def test_exchange_can_raise_a_low_opponent_via_life_gain():
    eng = _engine()
    top = _tree_on_battlefield(eng)
    p2 = eng.state.players[1]
    p2.life = 5

    eff = build_effects([EffectSpec("exchange_life_total_with_toughness", {})], top)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])
    eng.recompute_continuous_effects()

    assert p2.life == 13   # gained 8 up to Tree's former toughness
    assert top.toughness == 5


def test_later_pt_layers_still_stack_on_the_set_toughness():
    eng = _engine()
    top = _tree_on_battlefield(eng)
    p2 = eng.state.players[1]
    p2.life = 7

    eff = build_effects([EffectSpec("exchange_life_total_with_toughness", {})], top)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])
    # a +1/+1 counter is layer 7c — applies after the 7b set
    top.counters["+1/+1"] = 2
    eng.recompute_continuous_effects()

    assert top.toughness == 9    # 7 (set) + 2 (counters)
    assert top.power == 2        # printed 0 + 2 counters; power half untouched by the set


def test_exchange_noop_if_tree_left_the_battlefield():
    eng = _engine()
    top = _tree_on_battlefield(eng)
    p2 = eng.state.players[1]
    eng.state.battlefield.remove(top)

    eff = build_effects([EffectSpec("exchange_life_total_with_toughness", {})], top)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])
    assert p2.life == 20
