"""PAR-30 "copy of a named card" body singletons (v195) — The Joiner of Cats.

Two new pieces:

1. `CreateNamedCardTokenEffect` / the `create_token_copy_of_named` spec —
   "create a token that's a [tapped and attacking] copy of `<a specific
   named real card>`" (Lurrus of the Dream-Den). The copiable values come
   from the card cache (`services.card_lookup.card_by_name`), so the token
   has that card's real abilities.

2. `impulsive_look` gains `miss_effect_specs` — "If you don't put a card
   onto the battlefield this way, `<body>`." runs when the look places
   nothing (declined, or nothing eligible).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_lookup import card_by_name


# --- parse -----------------------------------------------------------


def test_named_card_token_handler_emits_spec():
    (spec,) = parse_effect_body(
        "create a token that's a tapped and attacking copy of lurrus of the dream-den"
    )
    assert spec.type == "create_token_copy_of_named"
    assert spec.params == {
        "card_name": "lurrus of the dream-den", "tapped": True, "attacking": True,
    }


def test_named_card_token_rejects_non_names():
    # "enchanted creature" / "chosen permanent" / "that creature" are not
    # proper card names — the handler must not claim them.
    for phrase in (
        "create a token that's a copy of enchanted creature",
        "create a token that's a copy of enchanted artifact",
        "create a token that's a copy of chosen permanent",
        "create a token that's a copy of that creature",
    ):
        got = parse_effect_body(phrase)
        assert got is None or got[0].type != "create_token_copy_of_named", phrase


def test_look_top_else_branch_threads_miss_effect_specs():
    (spec,) = parse_effect_body(
        "look at the top 6 cards of your library. you may put a cat creature "
        "card from among them onto the battlefield tapped and attacking. put "
        "the rest of the cards on the bottom of your library in a random "
        "order. if you don't put a card onto the battlefield this way, create "
        "a token that's a tapped and attacking copy of lurrus of the dream-den."
    )
    assert spec.type == "impulsive_look"
    assert spec.params["miss_effect_specs"] == [
        {"type": "create_token_copy_of_named",
         "params": {"card_name": "lurrus of the dream-den",
                    "tapped": True, "attacking": True}}
    ]


def test_joiner_of_cats_modeled():
    c = card_by_name("The Joiner of Cats")
    if c is None:
        pytest.skip("The Joiner of Cats not in the local card cache")
    assert parse_oracle(c).coverage != UNMODELED


# --- execute --------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    src = GameObject(
        Card(id="j", name="The Joiner of Cats",
             type_line="Legendary Creature — Cat", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    return eng, src


def _run_look(eng, src):
    specs = [EffectSpec("impulsive_look", {
        "count": 6, "criteria": {"type": "cat"},
        "hit_destination": "battlefield_attacking",
        "miss_destination": "library_bottom_random", "optional": True,
        "miss_effect_specs": [{
            "type": "create_token_copy_of_named",
            "params": {"card_name": "lurrus of the dream-den",
                       "tapped": True, "attacking": True},
        }],
    })]
    build_effects(specs, src)[0].apply(eng.rules.context, None)


def test_miss_branch_runs_when_nothing_eligible():
    if card_by_name("Lurrus of the Dream-Den") is None:
        pytest.skip("Lurrus not in the local card cache")
    eng, src = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(3):  # no Cats — nothing eligible
        o = GameObject(Card(id=f"b{i}", name=f"Bear{i}",
                            type_line="Creature — Bear", is_creature=True,
                            power=1, toughness=1),
                       owner_id="p1", zone=Zone.LIBRARY)
        o.controller_id = "p1"
        p1.library.append(o)
    _run_look(eng, src)
    assert eng.state.pending_choice is None
    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert [t.name for t in toks] == ["Lurrus of the Dream-Den"]
    assert toks[0].tapped and toks[0].attacking
    # the token is built from Lurrus's real card — 3/2, legendary, and its
    # hand-authored "cast from graveyard" permission bound as a static
    assert (toks[0].power, toks[0].toughness) == (3, 2)
    assert "legendary" in toks[0].type_words
    assert toks[0].static_effects


def test_miss_branch_runs_when_player_declines():
    if card_by_name("Lurrus of the Dream-Den") is None:
        pytest.skip("Lurrus not in the local card cache")
    eng, src = _engine()
    p1 = eng.state.player_by_id("p1")
    cat = GameObject(Card(id="cat", name="Housecat",
                          type_line="Creature — Cat", is_creature=True,
                          power=1, toughness=1),
                     owner_id="p1", zone=Zone.LIBRARY)
    cat.controller_id = "p1"
    p1.library.append(cat)
    _run_look(eng, src)
    assert eng.state.pending_choice is not None  # a real choice opened
    eng.rules.resolve_impulsive_look_choice(None)  # decline
    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert [t.name for t in toks] == ["Lurrus of the Dream-Den"]


def test_miss_branch_does_not_run_when_a_card_is_placed():
    if card_by_name("Lurrus of the Dream-Den") is None:
        pytest.skip("Lurrus not in the local card cache")
    eng, src = _engine()
    p1 = eng.state.player_by_id("p1")
    cat = GameObject(Card(id="cat", name="Housecat",
                          type_line="Creature — Cat", is_creature=True,
                          power=1, toughness=1),
                     owner_id="p1", zone=Zone.LIBRARY)
    cat.controller_id = "p1"
    p1.library.append(cat)
    _run_look(eng, src)
    eng.rules.resolve_impulsive_look_choice(cat.instance_id)  # take the Cat
    names = sorted(o.name for o in eng.state.battlefield if getattr(o, "is_token", False))
    assert "Lurrus of the Dream-Den" not in names
    assert cat in eng.state.battlefield and cat.attacking
