"""MEC-12 (cEDH staples / staples 2) — the plain "exile [up to N] [another]
target creature/permanent you control, then return that card/it to the
battlefield under your/its owner's control" blink template
(`BlinkEffect`/`parser/oracle/catalogue/handlers._blink_plain`), plus
`AddCountersEffect.amount_if_trigger_subject_subtype` (Emiel the Blessed).

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.events import EventType, GameEvent

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _catalogue_obj_on_battlefield(state, name, controller="p1"):
    obj = obj_on_battlefield(state, None, _named(name), controller=controller)
    bind_from_catalogue(obj)
    return obj


# ---------------------------------------------------------------------------
# Felidar Guardian — plain "you may" ETB blink, "permanent"/"its owner's"
# ---------------------------------------------------------------------------


def test_felidar_guardian_blinks_another_permanent_you_control():
    card = _named("Felidar Guardian")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 3})

    land = obj_on_battlefield(eng.state, eng, creature(name="Dummy Land", type_line="Land"))
    land.card.is_creature = False
    bind_from_catalogue(land)
    land.counters["charge"] = 3  # RULE 400.7: a new object keeps none of the old one's counters

    guardian = p1.hand[0]
    bind_from_catalogue(guardian)
    eng.cast_spell(p1, guardian)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None  # Felidar Guardian's own trigger opens a target choice
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    still_there = [o for o in eng.state.battlefield if o.card.name == "Dummy Land"]
    assert len(still_there) == 1
    assert still_there[0].counters == {}


def test_felidar_guardian_blink_is_declinable():
    card = _named("Felidar Guardian")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 3})

    obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    guardian = p1.hand[0]
    bind_from_catalogue(guardian)
    eng.cast_spell(p1, guardian)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    bears = [o for o in eng.state.battlefield if o.card.name == "Grizzly Bears"]
    assert len(bears) == 1


# ---------------------------------------------------------------------------
# Displacer Kitten — "up to one", nonland permanent, Avoidance ability word
# ---------------------------------------------------------------------------


def test_displacer_kitten_offers_up_to_one_nonland_permanent_on_noncreature_cast():
    eng = make_engine([_named("Shock")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 1})

    from mtg_analyzer.models.card import Card

    _catalogue_obj_on_battlefield(eng.state, "Displacer Kitten")
    sol_ring = Card(id="Sol Ring", name="Sol Ring", type_line="Artifact",
                     mana_cost_string="{1}", converted_mana_cost=1, is_creature=False)
    artifact = obj_on_battlefield(eng.state, eng, sol_ring)
    bind_from_catalogue(artifact)
    artifact.counters["charge"] = 2

    shock = p1.hand[0]
    bind_from_catalogue(shock)
    eng.cast_spell(p1, shock, targets=[eng.state.player_by_id("p1")])
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    # "up to one" — declining is a legal option alongside the real target.
    assert any(o["id"] == "decline" for o in pending["options"])
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])
    blinked = [o for o in eng.state.battlefield if o.card.name == "Sol Ring"]
    assert len(blinked) == 1
    assert blinked[0].counters == {}  # RULE 400.7: a new object, old counters gone


# ---------------------------------------------------------------------------
# Emiel the Blessed — activated blink + pay_cost_then Unicorn bonus
# ---------------------------------------------------------------------------


def _play_emiel(eng, state, p1):
    emiel = _catalogue_obj_on_battlefield(state, "Emiel the Blessed")
    return emiel


def test_emiel_activated_ability_blinks_another_creature_you_control():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 3})

    emiel = _play_emiel(eng, eng.state, p1)
    bear = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    bind_from_catalogue(bear)
    bear.counters["+1/+1"] = 2

    eng.activate_ability(p1, emiel, targets=[bear])
    eng.resolve_until_stable()

    bears = [o for o in eng.state.battlefield if o.card.name == "Grizzly Bears"]
    assert len(bears) == 1
    assert bears[0].counters == {}  # RULE 400.7: a new object, old counters gone


def test_emiel_trigger_grants_bonus_counter_for_a_unicorn():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "W": 1})

    _play_emiel(eng, eng.state, p1)
    unicorn = obj_on_battlefield(eng.state, eng, creature(
        name="Test Unicorn", type_line="Creature — Unicorn", cost="{2}{W}",
    ))
    bind_from_catalogue(unicorn)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=unicorn.instance_id,
        controller_id=unicorn.controller_id, object_types=sorted(unicorn.type_words),
    ))
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "pay_cost_then"
    yes = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(yes["id"])

    assert unicorn.counters.get("+1/+1") == 2


def test_emiel_trigger_grants_single_counter_for_a_non_unicorn():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "W": 1})

    _play_emiel(eng, eng.state, p1)
    bear = obj_on_battlefield(eng.state, eng, creature(name="Grizzly Bears", cost="{1}{G}"))
    bind_from_catalogue(bear)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=bear.instance_id,
        controller_id=bear.controller_id, object_types=sorted(bear.type_words),
    ))
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    yes = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(yes["id"])

    assert bear.counters.get("+1/+1") == 1
