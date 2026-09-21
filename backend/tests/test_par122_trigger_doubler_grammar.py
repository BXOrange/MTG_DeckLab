"""PAR-122 — trigger doublers ("… triggers an additional time", RULE 603.2d).

One `trigger_doubler` spec built from two composed halves: a *cause* (a
trigger-shaped dict — the gerund "a creature you control attacking" is the head
"a creature you control attacks") and a *subject* (a `matches_object_filter`
dict on the doubled permanent, plus "another"/"attached"). Parse tests pin the
grammar and that it fails closed; execute tests put a real doubler on a real
board and count how many times a real trigger is placed.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter, _named

TAIL = ", that ability triggers an additional time."


def _params(text):
    specs = static_effect_specs(text)
    assert specs is not None and len(specs) == 1 and specs[0].type == "trigger_doubler", text
    return specs[0].params


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("if a triggered ability of a legendary creature you control triggers" + TAIL,
         {"subject": {"filter": {"legendary": True, "card_type": "creature"}}}),
        ("if an ability of another wolf or battle you control triggers" + TAIL,
         {"subject": {"filter": {"any_of": [{"subtype": "wolf"}, {"card_type": "battle"}]},
                      "other": True}}),
        ("if a triggered ability of a permanent you control but don't own triggers" + TAIL,
         {"subject": {"filter": {"not_owned_by_you": True}}}),
        ("if an ability of equipped creature triggers" + TAIL, {"subject": {"attached": True}}),
        ("if a triggered ability of another elemental you control triggers, it triggers an additional time.",
         {"subject": {"filter": {"subtype": "elemental"}, "other": True}}),
        ("if an artifact or creature entering causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "ENTERS_BATTLEFIELD",
                    "condition": {"subject": "group", "controller": "any", "other": False,
                                  "type": ["artifact", "creature"]}}}),
        ("if a creature you control attacking causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "ATTACKS",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "type": "creature"}}}),
        ("if a creature you control dealing combat damage to a player causes a triggered ability of a permanent you control to trigger" + TAIL,
         {"cause": {"event": "DAMAGE",
                    "condition": {"subject": "group", "controller": "you", "other": False,
                                  "filter": {"card_type": "creature"}},
                    "filter": {"combat": True, "is_player": True}}}),
    ],
)
def test_doubler_parses(text, expected):
    assert _params(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "if a triggered ability of a creature an opponent controls triggers" + TAIL,  # only your own
        "if a triggered ability of a frobnicator you control triggers" + TAIL,
        "if a frobnicator entering causes a triggered ability of a permanent you control to trigger" + TAIL,
        "if a creature exploring causes a triggered ability of a permanent you control to trigger" + TAIL,
        "if a triggered ability of a creature you control triggers, that ability triggers twice.",
    ],
)
def test_doubler_fails_closed(text):
    assert static_effect_specs(text) is None


def test_as_long_as_wrapper_gates_the_whole_doubler():
    params = _params(
        "as long as you have an enduring story, if an ability of a dwarf you control triggers" + TAIL
    )
    assert params["active_if"] == {"kind": "has_enduring_story"}
    assert params["subject"] == {"filter": {"subtype": "dwarf"}}


@pytest.mark.parametrize(
    "name",
    [
        "Panharmonicon", "Ancient Greenwarden", "Naban, Dean of Iteration", "Starfield Vocalist",
        "Teysa Karlov", "Isshin, Two Heavens as One", "Wulfgar of Icewind Dale",
        "Felix Five-Boots", "Annie Joins Up", "Chief of the Wilds", "Jabs, Mistress of Mockery",
        "Katara, the Fearless", "Splinter, Radical Rat", "Twinflame Travelers",
        "Wizard's Staff", "Bifur, Melodic Rider",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Engine: doubling a real trigger
# ---------------------------------------------------------------------------

ETB = "When ~ enters, you gain 1 life."


def _put(state, name="Doubler", oracle="", owner="p1", types="Enchantment", **kw):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle,
                is_creature="Creature" in types,
                power=1 if "Creature" in types else None,
                toughness=1 if "Creature" in types else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _doubler(state, cause_or_subject_text):
    return _put(state, "Doubler", cause_or_subject_text + TAIL)


def _etb_gain(doubler_text, entering_types, owner="p1", doubler_owner="p1", **kw):
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, doubler_text)
    entering = _put(state, "Entering", ETB, owner=owner, types=entering_types, **kw)
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    return state.player_by_id("p1").life - life


def test_cause_scopes_which_event_doubles():
    text = "if an artifact or creature entering causes a triggered ability of a permanent you control to trigger"
    assert _etb_gain(text, "Creature — Bear") == 2
    assert _etb_gain(text, "Artifact") == 2
    assert _etb_gain(text, "Enchantment") == 1


def test_cause_subject_carries_the_controller_scope():
    text = "if a wizard you control entering causes a triggered ability of a permanent you control to trigger"
    assert _etb_gain(text, "Creature — Wizard") == 2
    assert _etb_gain(text, "Creature — Bear") == 1


def test_subject_scopes_whose_ability_doubles():
    text = "if a triggered ability of a legendary creature you control triggers"
    assert _etb_gain(text, "Legendary Creature — Bear", is_legendary=True) == 2
    assert _etb_gain(text, "Creature — Bear") == 1


def test_another_excludes_the_doubler_itself():
    engine, state = _engine()
    state.current_step = "main1"
    oracle = ("If a triggered ability of another elemental you control triggers, "
              "it triggers an additional time.\n" + ETB)
    doubler = _put(state, "Elemental Twin", oracle, types="Creature — Elemental")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, doubler)          # its own ETB: not "another"
    assert state.player_by_id("p1").life - life == 1
    other = _put(state, "Other", ETB, types="Creature — Elemental")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, other)
    assert state.player_by_id("p1").life - life == 2


def test_you_control_but_dont_own():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a triggered ability of a permanent you control but don't own triggers")
    mine = _put(state, "Mine", ETB, types="Creature — Bear")
    borrowed = _put(state, "Borrowed", ETB, types="Creature — Bear")
    borrowed.owner_id = "p2"          # p1 controls it (Threaten-style) but does not own it

    def gained(obj):
        life = state.player_by_id("p1").life
        _fire_enter(engine, state, obj)
        return state.player_by_id("p1").life - life

    assert gained(mine) == 1
    assert gained(borrowed) == 2


def test_a_dies_cause_doubles_the_watching_trigger():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a creature dying causes a triggered ability of a permanent you control to trigger")
    _put(state, "Watcher", "Whenever a creature dies, you gain 1 life.")
    victim = _put(state, "Victim", types="Creature — Bear")
    life = state.player_by_id("p1").life
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life - life == 2


def test_an_active_if_gate_switches_the_whole_doubler_off():
    engine, state = _engine()
    state.current_step = "main1"
    doubler = _put(state, "Doubler", "If a triggered ability of a creature you control triggers" + TAIL,
                   types="Creature — Bear")
    effect = next(e for e in doubler.static_effects if type(e).__name__ == "TriggerDoublerEffect")
    entering = _put(state, "Entering", ETB, types="Creature — Bear")
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    assert state.player_by_id("p1").life - life == 2
    effect.active_if = {"kind": "never"}     # an unknown gate never holds (fail closed)
    life = state.player_by_id("p1").life
    _fire_enter(engine, state, entering)
    assert state.player_by_id("p1").life - life == 1


def test_a_doubler_only_doubles_its_own_controllers_permanents():
    engine, state = _engine()
    state.current_step = "main1"
    _doubler(state, "if a triggered ability of a creature you control triggers")
    theirs = _put(state, "Theirs", ETB, owner="p2", types="Creature — Bear")
    life = state.player_by_id("p2").life
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id="p2", card_id=theirs.card.id,
        object=theirs.name, instance_id=theirs.instance_id, object_types=sorted(theirs.type_words),
    ))
    engine.resolve_until_stable()
    assert state.player_by_id("p2").life - life == 1
