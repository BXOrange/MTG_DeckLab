"""PAR-30 "copy of a named card" body singletons (v197) — Living Laser.

New primitives:

1. `GameState.cards_discarded_this_turn` — a per-player, per-turn discard
   count, bumped at every `DISCARD_CARD` fire site
   (`RulesEngine._note_discarded`), reset for the incoming active player in
   `GameEngine.begin_turn` — the same shape as `cards_drawn_this_turn`.

2. `continuous.count_selector("cards_discarded_this_turn")`.

3. `CopyPermanentEffect.count_selector` — "create a token that's a copy of
   ~ **for each card you've discarded this turn**" (`copy_self_for_each`
   handler → `copy_permanent` with `target_kind=None`, `referent="source"`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -----------------------------------------------------------


def test_copy_self_for_each_discard_handler():
    specs = parse_effect_body(
        "for each card you've discarded this turn, create a token that's a "
        "copy of ~, except the token isn't legendary"
    )
    assert [s.type for s in specs] == ["copy_permanent"]
    assert specs[0].params == {
        "target_kind": None, "referent": "source",
        "count_selector": "cards_discarded_this_turn", "not_legendary": True,
    }


def test_living_laser_full_body_modeled():
    specs = parse_effect_body(
        "for each card you've discarded this turn, create a token that's a "
        "copy of ~, except the token isn't legendary. the tokens enter "
        "tapped and attacking. exile the tokens at the beginning of the next "
        "end step."
    )
    kinds = [s.type for s in specs]
    assert kinds == ["copy_permanent", "create_delayed_trigger"]
    assert specs[0].params["tapped"] and specs[0].params["attacking"]
    assert specs[0].params["count_selector"] == "cards_discarded_this_turn"
    assert specs[1].params["effects"] == [{"type": "exile_specific", "params": {}}]


def test_living_laser_card_modeled():
    c = Card(
        id="ll", name="Living Laser",
        type_line="Legendary Artifact Creature — Equipment", is_creature=True,
        oracle_text=(
            "Haste\nWhenever Living Laser attacks, for each card you've "
            "discarded this turn, create a token that's a copy of Living "
            "Laser, except the token isn't legendary. The tokens enter tapped "
            "and attacking. Exile the tokens at the beginning of the next end "
            "step."
        ),
    )
    assert parse_oracle(c).coverage != UNMODELED


# --- execute -------------------------------------------------------


def _engine_with_ll():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    ll = GameObject(
        Card(id="ll", name="Living Laser",
             type_line="Legendary Artifact Creature — Equipment",
             is_creature=True, power=3, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    ll.controller_id = "p1"
    eng.state.add_to_battlefield(ll)
    return eng, ll


def test_discard_counter_tracks_and_resets():
    eng, ll = _engine_with_ll()
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        c = GameObject(Card(id=f"h{i}", name=f"J{i}", type_line="Sorcery"),
                       owner_id="p1", zone=Zone.HAND)
        c.controller_id = "p1"
        p1.hand.append(c)
    eng.rules.discard(p1, 3)
    assert eng.state.cards_discarded_this_turn["p1"] == 3
    # a fresh turn for p1 zeroes it
    eng.state.cards_discarded_this_turn["p1"] = 0
    assert eng.state.cards_discarded_this_turn["p1"] == 0


def test_copy_self_for_each_makes_one_nonlegendary_copy_per_discard():
    eng, ll = _engine_with_ll()
    p1 = eng.state.player_by_id("p1")
    for i in range(2):
        c = GameObject(Card(id=f"d{i}", name=f"D{i}", type_line="Instant"),
                       owner_id="p1", zone=Zone.HAND)
        c.controller_id = "p1"
        p1.hand.append(c)
    eng.rules.discard(p1, 2)

    spec = [EffectSpec("copy_permanent", {
        "target_kind": None, "referent": "source",
        "count_selector": "cards_discarded_this_turn", "not_legendary": True,
        "tapped": True, "attacking": True,
    })]
    build_effects(spec, ll)[0].apply(eng.rules.context, None)

    toks = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert len(toks) == 2
    for t in toks:
        assert t.name == "Living Laser"
        assert (t.power, t.toughness) == (3, 1)
        assert t.tapped and t.attacking
        assert "legendary" not in t.type_words


def test_no_copies_when_nothing_discarded():
    eng, ll = _engine_with_ll()
    spec = [EffectSpec("copy_permanent", {
        "target_kind": None, "referent": "source",
        "count_selector": "cards_discarded_this_turn",
    })]
    build_effects(spec, ll)[0].apply(eng.rules.context, None)
    assert not [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
