"""Tests for "look at the top N cards, take one matching a filter, put the
rest into Y" (Grisly Salvage/Commune with the Gods-shaped) — distinct from
`SearchLibraryEffect` (whole-library search) and `top_library.py`'s standing
"look at/play from the top" permission (never moves a card).

Engine side: `game/effects/core.py`'s `ImpulsiveLookEffect` +
`RulesEngine._request_impulsive_look`/`_resume_impulsive_look`
(`game/rules_engine.py`).
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.effects.core import ImpulsiveLookEffect
from mtg_analyzer.game.game_engine import GameEngine


def _card(name, type_line, **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def make_engine(hand=0):
    return GameEngine.new_game(
        [("p1", "Alice", [_card("Filler", "Instant", is_instant=True)])],
        starting_life=20, starting_hand=hand,
    )


def _stock_library(eng, p1, cards):
    """Replace p1's library (bottom..top) with ``cards`` so ``cards[-1]`` is
    the top of the deck (`Player.library`'s own convention)."""
    p1.library.clear()
    for card in cards:
        p1.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))


def test_peels_exactly_n_and_offers_only_the_matching_ones():
    eng = make_engine()
    p1 = eng.state.active_player
    top4 = [
        _card("Forest", "Basic Land — Forest", is_land=True),
        _card("Bear", "Creature — Bear", is_creature=True, power=2, toughness=2),
        _card("Bolt", "Instant", is_instant=True),
        _card("Island", "Basic Land — Island", is_land=True),
    ]
    _stock_library(eng, p1, top4)  # Island is on top

    eng.rules._request_impulsive_look(p1, 4, {"type": ["Land", "Creature"]})

    choice = eng.state.pending_choice
    assert choice["kind"] == "impulsive_look"
    assert len(choice["peeled"]) == 4
    assert {e["name"] for e in choice["eligible"]} == {"Forest", "Bear", "Island"}
    assert len(p1.library) == 0
    assert len(p1.exile) == 4


def test_stops_early_if_the_library_runs_out():
    eng = make_engine()
    p1 = eng.state.active_player
    _stock_library(eng, p1, [_card("Forest", "Basic Land — Forest", is_land=True)])

    eng.rules._request_impulsive_look(p1, 4, {"type": ["Land"]})

    choice = eng.state.pending_choice
    assert len(choice["peeled"]) == 1
    assert len(p1.library) == 0


def test_no_eligible_card_skips_the_choice_and_routes_everything_to_miss():
    eng = make_engine()
    p1 = eng.state.active_player
    _stock_library(eng, p1, [
        _card("Bolt", "Instant", is_instant=True),
        _card("Shock", "Instant", is_instant=True),
    ])

    eng.rules._request_impulsive_look(p1, 2, {"type": ["Land"]}, miss_destination="graveyard")

    assert eng.state.pending_choice is None
    assert len(p1.exile) == 0
    assert {o.name for o in p1.graveyard} == {"Bolt", "Shock"}


def test_taking_the_hit_routes_pick_to_hand_and_rest_to_graveyard():
    eng = make_engine()
    p1 = eng.state.active_player
    top4 = [
        _card("Mountain", "Basic Land — Mountain", is_land=True),
        _card("Bear", "Creature — Bear", is_creature=True, power=2, toughness=2),
        _card("Bolt", "Instant", is_instant=True),
        _card("Forest", "Basic Land — Forest", is_land=True),  # top
    ]
    _stock_library(eng, p1, top4)

    eng.rules._request_impulsive_look(p1, 4, {"type": ["Land", "Creature"]})
    forest_id = next(e["instance_id"] for e in eng.state.pending_choice["eligible"] if e["name"] == "Forest")

    eng.rules.resolve_choice(forest_id)

    assert eng.state.pending_choice is None
    assert [o.name for o in p1.hand] == ["Forest"]
    assert {o.name for o in p1.graveyard} == {"Mountain", "Bear", "Bolt"}
    assert len(p1.exile) == 0


def test_declining_routes_everything_to_miss_destination():
    eng = make_engine()
    p1 = eng.state.active_player
    top4 = [
        _card("Mountain", "Basic Land — Mountain", is_land=True),
        _card("Bear", "Creature — Bear", is_creature=True, power=2, toughness=2),
        _card("Bolt", "Instant", is_instant=True),
        _card("Forest", "Basic Land — Forest", is_land=True),
    ]
    _stock_library(eng, p1, top4)

    eng.rules._request_impulsive_look(p1, 4, {"type": ["Land", "Creature"]})
    eng.rules.resolve_choice(None)

    assert eng.state.pending_choice is None
    assert len(p1.hand) == 0
    assert {o.name for o in p1.graveyard} == {"Mountain", "Bear", "Bolt", "Forest"}
    assert len(p1.exile) == 0


def test_rejects_an_instance_id_that_was_not_offered():
    eng = make_engine()
    p1 = eng.state.active_player
    _stock_library(eng, p1, [
        _card("Bolt", "Instant", is_instant=True),
        _card("Forest", "Basic Land — Forest", is_land=True),
    ])
    eng.rules._request_impulsive_look(p1, 2, {"type": ["Land"]})
    bolt_id = next(o.instance_id for o in p1.exile if o.name == "Bolt")
    try:
        eng.rules.resolve_choice(bolt_id)
        assert False, "expected a ValueError"
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Full cast pipeline via the `impulsive_look` EffectRegistry entry
# ---------------------------------------------------------------------------


def test_cast_a_grisly_salvage_like_spell():
    eng = make_engine(hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 1, "C": 1})
    top4 = [
        _card("Mountain", "Basic Land — Mountain", is_land=True),
        _card("Bear", "Creature — Bear", is_creature=True, power=2, toughness=2),
        _card("Bolt", "Instant", is_instant=True),
        _card("Forest", "Basic Land — Forest", is_land=True),
    ]
    _stock_library(eng, p1, top4)

    spell = GameObject(
        Card(id="Grisly Salvage", name="Grisly Salvage", type_line="Sorcery",
             mana_cost_string="{1}{B}", converted_mana_cost=2, is_sorcery=True),
        owner_id="p1", zone=Zone.HAND,
    )
    spell.spell_effects = [ImpulsiveLookEffect(count=4, criteria={"type": ["Land", "Creature"]})]
    p1.add_to_zone(spell, Zone.HAND)

    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice["kind"] == "impulsive_look"
    bear_id = next(e["instance_id"] for e in choice["eligible"] if e["name"] == "Bear")
    eng.rules.resolve_choice(bear_id)

    assert [o.name for o in p1.hand] == ["Bear"]
    # The spell itself joins the graveyard too, same as any resolved sorcery.
    assert {o.name for o in p1.graveyard} == {"Mountain", "Bolt", "Forest", "Grisly Salvage"}
