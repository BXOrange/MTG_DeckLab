"""PAR-29 — RULE 701.44 Explore: a new engine primitive + oracle handlers.

`RulesEngine.explore` reveals the top card of the exploring permanent's
controller's library; a land goes to hand, otherwise a +1/+1 counter goes on
the permanent and its controller may put the revealed card into their
graveyard (the one interactive pause, `explore_bin`). `EventType.EXPLORED`
fires once the whole process is done (RULE 701.44b).

Parser: `it/he/she explores` (self-subject trigger), `~ explores`, `that
creature explores` (previous clause's pick), `target creature [you control]
explores`. "explores, then it explores again" (Defossilize) and mass "each
Merfolk you control explores" stay unclaimed.

Reference: game/rules/search_mixin.py (`explore`), game/effects.py
(`ExploreEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_self_and_pronoun_explores_parse():
    assert match_clause("~ explores") == [EffectSpec("explore", {})]
    assert match_clause("it explores") is None
    assert match_clause("it explores", self_subject=True) == [EffectSpec("explore", {})]
    assert match_clause("she explores", self_subject=True) == [EffectSpec("explore", {})]


def test_previous_subject_explores_parses():
    assert match_clause("that creature explores") is None
    assert match_clause("that creature explores", previous_subject=True) == [
        EffectSpec("explore", {"previous_subject": True})
    ]


def test_target_creature_explores_parses():
    assert match_clause("target creature you control explores") == [
        EffectSpec("explore", {"target_kind": "creature_you_control"})
    ]


def test_double_explore_and_mass_explore_stay_unclaimed():
    assert match_clause("it explores, then it explores again", self_subject=True) is None
    assert match_clause("each merfolk creature you control explores") is None


def test_real_explore_card_is_modeled_end_to_end():
    card = Card(
        id="Scout", name="Scout", type_line="Creature — Merfolk Scout",
        is_creature=True, power=1, toughness=1,
        oracle_text="When this creature enters, it explores.",
    )
    result = parse_oracle(card)
    assert result.modeled
    assert [e.type for e in result.effect_specs[0].effects] == ["explore"]


# --- execute -----------------------------------------------------------------


def _engine_with_explorer(top_cards):
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")
    for c in top_cards:  # last element ends up on top of the library
        p1.library.append(GameObject(c, owner_id="p1", zone=Zone.LIBRARY))
    card = Card(id="X", name="X", type_line="Creature — Scout",
               is_creature=True, power=1, toughness=1)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return eng, state, p1, obj


def _land():
    return Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True)


def _bear():
    return Card(id="B", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def test_explore_reveals_a_land_puts_it_in_hand_no_counter():
    eng, state, p1, obj = _engine_with_explorer([_land()])
    fired = []
    state.subscribe(lambda e: fired.append(e.get("found_land"))
                    if e.type == EventType.EXPLORED else None)

    eng.rules.explore(obj)

    assert [c.name for c in p1.hand] == ["Forest"]
    assert obj.plus_one_counters == 0
    assert state.pending_choice is None
    assert fired == [True]


def test_explore_reveals_a_nonland_counter_and_optional_bin():
    eng, state, p1, obj = _engine_with_explorer([_bear()])
    fired = []
    state.subscribe(lambda e: fired.append(e.get("found_land"))
                    if e.type == EventType.EXPLORED else None)

    eng.rules.explore(obj)
    assert obj.plus_one_counters == 1
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "explore_bin"
    assert fired == []  # not yet — the process isn't complete

    eng.resolve_pending_choice("graveyard")
    assert [c.name for c in p1.graveyard] == ["Bear"]
    assert not p1.library
    assert fired == [False]


def test_explore_decline_bin_leaves_card_on_top():
    eng, state, p1, obj = _engine_with_explorer([_bear()])
    eng.rules.explore(obj)
    eng.resolve_pending_choice("top")
    assert [c.name for c in p1.library] == ["Bear"]
    assert not p1.graveyard
    assert obj.plus_one_counters == 1


def test_explore_with_empty_library_still_fires_and_does_not_crash():
    eng, state, p1, obj = _engine_with_explorer([])
    fired = []
    state.subscribe(lambda e: fired.append(e.get("found_land"))
                    if e.type == EventType.EXPLORED else None)
    eng.rules.explore(obj)
    assert fired == [False]
    assert state.pending_choice is None


def test_real_card_explores_on_etb_via_binder():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(_bear(), owner_id="p1", zone=Zone.LIBRARY))

    card = Card(id="Cen", name="Cen", type_line="Creature — Merfolk Scout",
               is_creature=True, power=1, toughness=1,
               oracle_text="When this creature enters, it explores.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    assert state.pending_choice["kind"] == "explore_bin"
    assert obj.plus_one_counters == 1
