"""Tests for `game/mana_potential.py` — the non-mutating "what if I tapped
everything for mana" simulator behind "Mana-Potenzial" (open vs. used).

Reference: docs/implementation-state/Done_Backend.md "Mana-Potenzial".
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game import mana_potential


def _make_engine(cards=(), hand=0, players=1):
    seats = [("p1", "Alice", list(cards))]
    if players > 1:
        seats.append(("p2", "Bob", []))
    return GameEngine.new_game(seats, starting_life=20, starting_hand=hand)


def _land(name, color, tapped=False):
    card = Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    return obj


def _dork(name, oracle, power=1, toughness=1):
    card = Card(
        id=name, name=name, type_line="Creature — Elf Druid", is_creature=True,
        oracle_text=oracle, power=power, toughness=toughness,
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _artifact(name, oracle):
    card = Card(id=name, name=name, type_line="Artifact", oracle_text=oracle)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _spirit_guide(name="Simian Spirit Guide", color="R"):
    return Card(
        id=name, name=name, type_line="Creature — Ape Spirit", is_creature=True,
        oracle_text=f"Exile this card from your hand: Add {{{color}}}.",
    )


# ---------------------------------------------------------------------------
# open_potential_summary
# ---------------------------------------------------------------------------


def test_open_potential_counts_plain_untapped_lands():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for forest in (_land("Forest", "G"), _land("Forest", "G")):
        eng.state.add_to_battlefield(forest)

    potential = mana_potential.open_potential_summary(eng, p1)
    assert potential["G"] == 2
    assert potential["W"] == 0


def test_open_potential_ignores_already_tapped_lands():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))
    eng.state.add_to_battlefield(_land("Forest", "G", tapped=True))

    assert mana_potential.open_potential_summary(eng, p1)["G"] == 1


def test_open_potential_includes_hand_exile_sources():
    guide = _spirit_guide(color="R")
    eng = _make_engine([guide], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player

    assert mana_potential.open_potential_summary(eng, p1)["R"] == 1


def test_open_potential_prefers_net_positive_converter_over_plain_tap():
    # Selvala, Heart of the Wilds stub: {G}, {T}: Add X mana in any
    # combination of colours, X = greatest power among creatures you
    # control. With one Forest and Selvala herself (power 3) on board,
    # maximizing G should route the Forest's G into paying Selvala's own
    # {G} cost and get X=3 back — net 3, not just 1 from the Forest alone.
    selvala = _dork(
        "Selvala Stub",
        "{G}, {T}: Add X mana in any combination of colors, "
        "where X is the greatest power among creatures you control.",
        power=3, toughness=3,
    )
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))
    eng.state.add_to_battlefield(selvala)

    assert mana_potential.open_potential_summary(eng, p1)["G"] == 3


def test_open_potential_handles_shared_sacrifice_contention():
    # Two independent sac-outlets both wanting "a creature" but only one
    # creature actually available on board — only one outlet can fire.
    rock_a = _artifact("Sac Rock A", "Sacrifice a creature: Add {C}{C}.")
    rock_b = _artifact("Sac Rock B", "Sacrifice a creature: Add {C}{C}.")
    bear = _dork("Bear", "")
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for obj in (rock_a, rock_b, bear):
        eng.state.add_to_battlefield(obj)

    assert mana_potential.open_potential_summary(eng, p1)["C"] == 2


# ---------------------------------------------------------------------------
# used_potential_summary / record_mana_produced (per-turn tracking)
# ---------------------------------------------------------------------------


def test_used_potential_starts_at_zero():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    assert mana_potential.used_potential_summary(eng, p1)["G"] == 0


def test_used_potential_increments_on_real_tap_for_mana():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))

    forest = eng.state.battlefield[-1]
    eng.tap_for_mana(p1, forest)
    assert mana_potential.used_potential_summary(eng, p1)["G"] == 1


def test_used_potential_increments_on_real_hand_mana_ability():
    guide = _spirit_guide(color="R")
    eng = _make_engine([guide], hand=1)
    eng.begin_turn()
    p1 = eng.state.active_player
    obj = p1.hand[0]

    eng.activate_hand_mana_ability(p1, obj)
    assert mana_potential.used_potential_summary(eng, p1)["R"] == 1


def test_used_potential_resets_for_every_player_on_begin_turn():
    eng = _make_engine(players=2)
    eng.begin_turn()
    p1, p2 = eng.state.players
    eng.state.add_to_battlefield(_land("Forest", "G"))
    forest = eng.state.battlefield[-1]
    forest.owner_id = "p1"
    forest.controller_id = "p1"
    eng.tap_for_mana(p1, forest)
    assert eng.state.mana_produced_this_turn["p1"] == {"G": 1}

    eng.begin_turn()
    assert eng.state.mana_produced_this_turn["p1"] == {}
    assert eng.state.mana_produced_this_turn["p2"] == {}


def test_open_plus_used_equals_baseline_total_capacity():
    # The invariant the feature promises: what's still open, plus what's
    # already been produced this turn, equals the max you could have
    # gotten from these sources in one pass.
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for _ in range(3):
        eng.state.add_to_battlefield(_land("Forest", "G"))

    baseline = mana_potential.open_potential_summary(eng, p1)["G"]
    assert baseline == 3

    forest = eng.state.battlefield[0]
    eng.tap_for_mana(p1, forest)

    open_now = mana_potential.open_potential_summary(eng, p1)["G"]
    used_now = mana_potential.used_potential_summary(eng, p1)["G"]
    assert open_now == 2
    assert used_now == 1
    assert open_now + used_now == baseline


# ---------------------------------------------------------------------------
# find_tap_plan / is_castable_via_potential
# ---------------------------------------------------------------------------


def test_find_tap_plan_returns_empty_steps_when_pool_already_covers_cost():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    p1.mana_pool.add("G", 2)

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{G}{G}"))
    assert plan is not None
    assert plan.steps == []


def test_find_tap_plan_finds_a_multi_source_plan():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for _ in range(2):
        eng.state.add_to_battlefield(_land("Forest", "G"))
    eng.state.add_to_battlefield(_land("Mountain", "R"))

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{2}{G}"))
    assert plan is not None
    assert len(plan.steps) == 3
    assert plan.total_produced() == {"G": 2, "R": 1}


def test_find_tap_plan_returns_none_when_unaffordable():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))

    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{5}{G}")) is None


def test_find_tap_plan_chains_through_a_converter():
    selvala = _dork(
        "Selvala Stub",
        "{G}, {T}: Add X mana in any combination of colors, "
        "where X is the greatest power among creatures you control.",
        power=3, toughness=3,
    )
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))
    eng.state.add_to_battlefield(selvala)

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{G}{G}{G}"))
    assert plan is not None
    for step in plan.steps:
        assert step.instance_id in {
            o.instance_id for o in eng.state.battlefield
        }


def test_is_castable_via_potential_reflects_find_tap_plan():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_land("Forest", "G"))

    assert mana_potential.is_castable_via_potential(eng, p1, ManaCost.parse("{G}")) is True
    assert mana_potential.is_castable_via_potential(eng, p1, ManaCost.parse("{G}{G}{G}{G}")) is False


# ---------------------------------------------------------------------------
# Filter lands — "{B/G}, {T}: Add {B}{B}, {B}{G}, or {G}{G}." (Twilight Mire)
# ---------------------------------------------------------------------------


def _filter_land(name="Twilight Mire"):
    card = Card(
        id=name, name=name, type_line="Land", is_land=True,
        oracle_text="{T}: Add {C}.\n{B/G}, {T}: Add {B}{B}, {B}{G}, or {G}{G}.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


def _run_plan(eng, p1, plan):
    """Actually activate a plan's steps and hand back the resulting pool."""
    for step in plan.steps:
        src = next(o for o in eng.state.battlefield if o.instance_id == step.instance_id)
        eng.tap_for_mana(
            p1, src, option_index=step.option_index,
            ability_index=step.ability_index, color_split=step.color_split,
        )
    return p1.mana_pool


@pytest.mark.parametrize(
    "lands, cost",
    [
        (["Swamp", "Swamp"], "{G}{G}"),       # filter one Swamp's {B} into {G}{G}
        (["Forest"], "{G}{G}"),               # Forest -> G, filter it into GG (net +1)
        (["Swamp"], "{B}{G}"),                # keep a B, filter for the missing G
        (["Swamp", "Swamp"], "{B}{B}{G}"),    # BB + filter one into BG
        (["Swamp", "Swamp"], "{1}{G}{G}"),
    ],
)
def test_filter_land_tap_plan_covers_a_cost_only_the_filter_can_reach(lands, cost):
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    for i, basic in enumerate(lands):
        land = _land(basic, basic[0])
        land.card.id = f"{basic}-{i}"  # keep instance ids distinct
        eng.state.add_to_battlefield(land)
    eng.state.add_to_battlefield(_filter_land())

    plan = mana_potential.find_tap_plan(eng, p1, ManaCost.parse(cost))
    assert plan is not None, f"{lands} + filter should reach {cost}"
    # the plan must genuinely execute to a payable pool, not merely be "found"
    assert _run_plan(eng, p1, plan).can_pay(ManaCost.parse(cost))


def test_filter_land_does_not_invent_mana_it_cannot_make():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    s1 = _land("Swamp", "B")
    s2 = _land("Swamp", "B")
    s2.card.id = "Swamp-2"
    eng.state.add_to_battlefield(s1)
    eng.state.add_to_battlefield(s2)
    eng.state.add_to_battlefield(_filter_land())

    # 2 Swamps + one filter is at most 3 mana, and at most 2 of {G}.
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{G}{G}{G}")) is None
    assert mana_potential.find_tap_plan(eng, p1, ManaCost.parse("{4}")) is None


def test_filter_land_alone_only_makes_colorless():
    eng = _make_engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    eng.state.add_to_battlefield(_filter_land())

    # No {B}/{G} anywhere to feed the {B/G} activation cost.
    assert mana_potential.is_castable_via_potential(eng, p1, ManaCost.parse("{G}")) is False
    assert mana_potential.is_castable_via_potential(eng, p1, ManaCost.parse("{C}")) is True
