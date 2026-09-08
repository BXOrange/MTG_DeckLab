"""MEC-12 (cEDH staples 2) — `enter_as_copy` extensions: `only_types`,
`add_keywords`/`add_keywords_if_target_lacks`, `keep_own_abilities`, and
`max_mana_value_from_mana_spent`. One card each: Sakashima of a Thousand
Faces, Mockingbird, Flesh Duplicate, Imposter Mech.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _prepare(name, mana=None):
    """Board (but don't yet cast) ``name``, returning ``(eng, p1, hand_obj)``
    so the caller can put target creatures on the battlefield *before*
    casting — `_offer_enter_as_copy` gathers legal targets only once, at
    resolution, so a target added afterwards is never seen."""
    card = _named(name)
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many(mana or {"U": 2, "C": 6})
    obj = p1.hand[0]
    bind_from_catalogue(obj)
    return eng, p1, obj


def _cast(eng, p1, obj, x=None):
    if x is not None:
        eng.cast_spell(p1, obj, x=x)
    else:
        eng.cast_spell(p1, obj)
    eng.resolve_until_stable()


# ---------------------------------------------------------------------------
# Sakashima of a Thousand Faces — keep_own_abilities + ignore_legend_rule
# ---------------------------------------------------------------------------


def test_sakashima_copy_keeps_its_own_abilities_too():
    eng, p1, sakashima = _prepare("Sakashima of a Thousand Faces")
    target = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
        keywords=["Deathtouch"], oracle_text="Deathtouch",
    ))
    bind_from_catalogue(target)
    _cast(eng, p1, sakashima)

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert sakashima.card.name == "Grave Titan"
    assert (sakashima.power, sakashima.toughness) == (6, 6)
    # ~'s own static (the legend-rule exemption below) survived the copy.
    assert any(a.layer == "ignore_legend_rule" for a in sakashima.static_effects)


def test_sakashima_legend_rule_exemption_lets_two_same_named_legendaries_coexist():
    eng, p1, sakashima = _prepare("Sakashima of a Thousand Faces")
    original = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
        is_legendary=True, type_line="Legendary Creature — Giant Zombie",
    ))
    bind_from_catalogue(original)
    _cast(eng, p1, sakashima)

    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert sakashima.card.name == "Grave Titan"
    eng.rules.check_state_based_actions()
    # Both survive: Sakashima's own exemption (restored via keep_own_abilities)
    # keeps applying to its controller even after it becomes "Grave Titan".
    assert sakashima in eng.state.battlefield
    assert original in eng.state.battlefield


def test_sakashima_without_a_valid_target_enters_as_itself():
    eng, p1, sakashima = _prepare("Sakashima of a Thousand Faces")
    _cast(eng, p1, sakashima)
    # No creature ~ controls to copy — RULE 603.3c-style, nothing to offer.
    assert eng.state.pending_choice is None
    assert sakashima in eng.state.battlefield
    assert sakashima.card.name == "Sakashima of a Thousand Faces"


# ---------------------------------------------------------------------------
# Mockingbird — max_mana_value_from_mana_spent + add_subtypes/add_keywords
# ---------------------------------------------------------------------------


def test_mockingbird_only_offers_creatures_at_or_under_mana_spent():
    eng, p1, bird = _prepare("Mockingbird", mana={"U": 1, "C": 3})
    cheap = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    pricey = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6,
    ))
    bind_from_catalogue(cheap)
    bind_from_catalogue(pricey)
    _cast(eng, p1, bird, x=3)

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    offered_names = {o["label"] for o in pending["options"] if o["id"] != "decline"}
    assert "Grizzly Bears" in offered_names
    assert "Grave Titan" not in offered_names  # mana value 6 > 3 spent


def test_mockingbird_copy_stays_a_bird_with_flying():
    eng, p1, bird = _prepare("Mockingbird", mana={"U": 1, "C": 3})
    bear = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    bind_from_catalogue(bear)
    _cast(eng, p1, bird, x=3)

    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert bird.card.name == "Grizzly Bears"
    assert "Bird" in bird.card.type_line
    assert "flying" in bird.intrinsic_keywords


# ---------------------------------------------------------------------------
# Flesh Duplicate — add_keywords_if_target_lacks
# ---------------------------------------------------------------------------


def test_flesh_duplicate_grants_vanishing_when_target_has_none():
    eng, p1, dupe = _prepare("Flesh Duplicate")
    bear = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    bind_from_catalogue(bear)
    _cast(eng, p1, dupe)

    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert dupe.card.name == "Grizzly Bears"
    assert "Vanishing 3" in dupe.card.oracle_text
    # `_apply_entry_counters` already ran once, automatically, as part of
    # resolving the copy choice above (RULE 614.1a/707) — the entry counter
    # is already in place, not something the test places itself.
    assert dupe.counters.get("time") == 3
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    eng.resolve_until_stable()
    assert dupe.counters.get("time") == 2


def test_flesh_duplicate_does_not_double_up_on_an_already_vanishing_target():
    eng, p1, dupe = _prepare("Flesh Duplicate")
    fading_bird = creature(
        name="Aven Riftwatcher", cost="{2}{W}", power=2, toughness=3,
        type_line="Creature — Bird Rebel Soldier",
        keywords=["Flying", "Vanishing"],
        oracle_text="Flying\nVanishing 3",
    )
    target = obj_on_battlefield(eng.state, eng, fading_bird)
    bind_from_catalogue(target)
    _cast(eng, p1, dupe)

    opt = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    # Vanishing came from the copied card's own text, not a second grant —
    # its entry counters place normally (one "Vanishing 3" clause, not two).
    assert dupe.counters.get("time") == 3


# ---------------------------------------------------------------------------
# Imposter Mech — only_types + add_keywords ("Crew 3")
# ---------------------------------------------------------------------------


def test_imposter_mech_copy_loses_creature_type_and_gains_vehicle_artifact():
    eng, p1, mech = _prepare("Imposter Mech", mana={"U": 1, "C": 1})
    enemy_bear = obj_on_battlefield(
        eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}", power=4, toughness=4),
        controller="p2",
    )
    bind_from_catalogue(enemy_bear)
    _cast(eng, p1, mech)

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert mech.card.name == "Grizzly Bears"
    assert mech.card.type_line == "Artifact — Vehicle"
    assert mech.is_creature is False
    assert mech.card.power is None and mech.card.toughness is None
    assert (mech.card.vehicle_power, mech.card.vehicle_toughness) == (4, 4)
    assert any(a.cost.crew_power for a in mech.activated_abilities)
