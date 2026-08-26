"""RULE 202.2f/700.6 "devotion to hybrid" (Blended Twistling) — a
`continuous.count_selector` reading distinct from ordinary "devotion to
<colour>": any hybrid mana symbol counts once toward it, regardless of
which two colours it's between (unlike ordinary devotion, where a hybrid
pip counts toward *both* of its colours). A mono-hybrid pip ({2/W}) isn't a
mix of colours at all, so it doesn't count.

Also covers the *permanent* self-anthem shape ("~ gets +X/+X, where X is
your devotion to <colour/hybrid>.") this card needed alongside the
selector — the existing devotion-scaled `pump` handlers only covered the
"until end of turn" resolve-time shape.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def permanent(name, mana_cost_string, is_creature=True, power=2, toughness=2, **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        is_creature=is_creature, power=power, toughness=toughness,
        mana_cost_string=mana_cost_string, converted_mana_cost=3, **kw,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_blended_twistling_is_modeled():
    card = permanent(
        "Blended Twistling", "{2}{G/W}",
        oracle_text="Changeling\nThis creature gets +X/+X, where X is your "
                    "devotion to hybrid.",
        keywords=["Changeling"], type_line="Creature — Shapeshifter",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_hybrid_pip_counts_once_regardless_of_color_pair():
    eng = make_engine("p1", "p2")
    put(eng.state, permanent("Twin Hybrid", "{G/W}{U/B}"))
    assert continuous.count_selector(eng.state, "p1", "devotion_to_hybrid") == 2


def test_mono_hybrid_pip_does_not_count():
    eng = make_engine("p1", "p2")
    put(eng.state, permanent("Mono Hybrid Thing", "{2/W}{2/U}"))
    assert continuous.count_selector(eng.state, "p1", "devotion_to_hybrid") == 0


def test_only_the_controllers_own_hybrid_permanents_count():
    eng = make_engine("p1", "p2")
    put(eng.state, permanent("Mine", "{G/W}"), controller="p1")
    put(eng.state, permanent("Theirs", "{G/W}"), controller="p2")
    assert continuous.count_selector(eng.state, "p1", "devotion_to_hybrid") == 1


def test_blended_twistling_gets_plus_x_x_from_its_own_devotion():
    eng = make_engine("p1", "p2")
    twistling = put(eng.state, permanent(
        "Blended Twistling", "{2}{G/W}",
        oracle_text="Changeling\nThis creature gets +X/+X, where X is your "
                    "devotion to hybrid.",
        keywords=["Changeling"], type_line="Creature — Shapeshifter",
    ))
    eng.recompute_continuous_effects()
    assert (twistling.power, twistling.toughness) == (3, 3)

    put(eng.state, permanent("Another Hybrid", "{U/B}"))
    eng.recompute_continuous_effects()
    assert (twistling.power, twistling.toughness) == (4, 4)
