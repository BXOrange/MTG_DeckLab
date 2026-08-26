"""RULE 603.1 trigger-condition recognition beyond enters/dies/attacks/blocks,
and RULE 500.7's phase/step trigger family beyond upkeep/draw/end/cleanup.

The parser's trigger vocabulary used to name exactly four object verbs and
four steps; everything else fell out of the coverage gate as `UNMODELED` no
matter how well the engine could already fire it. This covers the widened
table (`parser/oracle/segmenter.py`'s `_TRIGGER_VERBS`/`_PHASE_STEP_WORDS`)
and the fail-closed rule that keeps a verb with no matching engine event out.

Reference: CR 603.1, 500.7, 507, 505, 708.8, 509.5, 701.21b, 702.140c.
"""

import pytest

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle import segmenter


def creature(name="Tester", text=""):
    return Card(
        id=name, name=name, type_line="Creature — Human", is_creature=True,
        power=2, toughness=2, mana_cost_string="{1}{G}", converted_mana_cost=2,
        oracle_text=text,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _spec_trigger(text):
    result = parse_oracle(creature(text=text))
    assert result.coverage == "MODELED", result.unclaimed
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert len(triggered) == 1
    return triggered[0].trigger


# -- Object-subject verbs (RULE 603.1) --------------------------------------


@pytest.mark.parametrize(
    "condition,event",
    [
        ("this creature is turned face up", "TURNED_FACE_UP"),
        ("this creature leaves the battlefield", "LEAVES_BATTLEFIELD"),
        ("this creature becomes blocked", "BECOMES_BLOCKED"),
        ("this creature becomes tapped", "TAPPED"),
        ("this creature becomes untapped", "UNTAPPED"),
        ("this creature mutates", "MUTATES"),
    ],
)
def test_new_self_subject_verbs_bind_to_their_event(condition, event):
    trigger = _spec_trigger(f"Whenever {condition}, draw a card.")
    assert trigger["event"] == event
    assert trigger["condition"] == {"subject": "self"}


def test_new_verbs_work_for_a_group_subject_too():
    trigger = _spec_trigger("Whenever another creature you control leaves the battlefield, draw a card.")
    assert trigger["event"] == "LEAVES_BATTLEFIELD"
    assert trigger["condition"] == {
        "subject": "group", "type": "creature", "controller": "you", "other": True,
    }


def test_new_verbs_compose_in_the_compound_shape():
    """"~ <verb> or <verb>" builds one ability per event."""
    result = parse_oracle(creature(text="Whenever this creature enters or is turned face up, draw a card."))
    assert result.coverage == "MODELED"
    triggered = [s for s in result.specs if s.ability_kind == "triggered"]
    assert triggered[0].trigger["event"] == ["ENTERS_BATTLEFIELD", "TURNED_FACE_UP"]


def test_a_verb_with_no_engine_event_stays_unclaimed():
    """Fail-closed: "specializes" names no engine event at all (RULE
    701's specialize mechanic has no primitive built — see BACKLOG.md's
    `MEC` tickets), so it can't earn a `_TRIGGER_VERBS` row and the whole
    clause stays unrecognized. ("Becomes untapped" used to be this test's
    own example — MEC-43 round 4E gave it a real per-permanent
    `EventType.UNTAPPED`, see `test_new_self_subject_verbs_bind_to_their_
    event` above instead.)"""
    result = parse_oracle(creature(text="Whenever this creature specializes, draw a card."))
    assert result.coverage == "UNMODELED"


def test_the_verb_table_only_names_real_event_types():
    """The front-end is import-pure, so its `EventType` strings are literals —
    this is what keeps them honest."""
    for _verb, event in segmenter._TRIGGER_VERBS:
        assert getattr(EventType, event) == event


# -- Those triggers actually fire ------------------------------------------


def _on_battlefield(eng, text, controller="p1"):
    obj = GameObject(creature(text=text), owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_a_turned_face_up_trigger_fires_when_the_morph_is_revealed():
    """The whole point of the morph trigger family (RULE 708.8), end to end."""
    eng = make_engine()
    card = creature(text="When this creature is turned face up, draw a card.")
    card.oracle_text = (
        "Morph {1}{G}\nWhen this creature is turned face up, draw a card."
    )
    card.keywords = ["Morph"]
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.rules.turn_face_down(obj, "morph")
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    player = eng.state.player_by_id("p1")
    for _ in range(3):
        player.add_to_zone(
            GameObject(creature("Filler"), owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY
        )
    player.mana_pool.add("C", 1)
    player.mana_pool.add("G", 1)
    eng.turn_face_up(player, obj, 0)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert len(player.hand) == 1


def test_a_becomes_tapped_trigger_fires_on_a_real_tap():
    eng = make_engine()
    obj = _on_battlefield(eng, "Whenever this creature becomes tapped, you gain 2 life.")
    eng.rules.set_tapped(obj, True)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == 22


def test_a_leaves_the_battlefield_trigger_fires_on_a_real_departure():
    eng = make_engine()
    obj = _on_battlefield(eng, "When this creature leaves the battlefield, you gain 3 life.")
    eng.rules.put_into_graveyard(obj)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == 23


# -- Phase/step triggers (RULE 500.7) ---------------------------------------


@pytest.mark.parametrize(
    "condition,step,relation",
    [
        ("combat on your turn", "begin_combat", "you"),
        ("each combat", "begin_combat", None),
        ("your first main phase", "main1", "you"),
        ("your second main phase", "main2", "you"),
        ("your postcombat main phase", "main2", "you"),
        ("each of your postcombat main phases", "main2", "you"),
        ("each player's upkeep", "upkeep", None),
        ("each opponent's end step", "end", "not_you"),
    ],
)
def test_phase_trigger_vocabulary(condition, step, relation):
    trigger = _spec_trigger(f"At the beginning of {condition}, you gain 1 life.")
    assert trigger["event"] == "STEP_BEGIN"
    assert trigger["filter"] == {"step": step}
    assert trigger.get("phase_relation") == relation


def test_a_begin_combat_trigger_fires_in_the_right_step():
    eng = make_engine()
    _on_battlefield(eng, "At the beginning of combat on your turn, you gain 1 life.")
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat"))
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == 21


def test_a_your_turn_phase_trigger_does_not_fire_on_an_opponents_turn():
    eng = make_engine()
    _on_battlefield(eng, "At the beginning of combat on your turn, you gain 1 life.")
    eng.state.active_player_index = 1  # Bob's turn
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat"))
    assert eng.rules.put_triggers_on_stack() == 0
    assert eng.state.player_by_id("p1").life == 20


def test_every_recognized_step_word_is_a_real_step_name():
    from mtg_analyzer.game.phases import describe_turn_structure

    real_steps = {step for steps in describe_turn_structure().values() for step in steps}
    assert set(segmenter._PHASE_STEP_WORDS.values()) <= real_steps
