"""PAR-124 — a spell's "whenever … this turn" is a triggered ability that lasts the turn.

RULE 603.7a: "Whenever a creature enters this turn, draw a card" does not put an ability
on the spell (an instant in a graveyard has none that functions); it creates one when the
spell resolves. Parse tests pin the wrapping (and that a permanent's ordinary trigger is
untouched); execute tests cast real spells, resolve them, and then make the events happen
— the assertions are on what the trigger *does*, on its own turn and no later.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter, _named
from tests.test_par120_count_phrase import _creature, _put

DRAW_ON_ENTER = "Whenever a creature you control enters this turn, draw a card."


def _spell(state, oracle, *, types="Sorcery", owner="p1", name="Spell"):
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle,
                is_instant=types == "Instant", is_sorcery=types == "Sorcery",
                converted_mana_cost=0)
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.player_by_id(owner).hand.append(obj)
    return obj


def _cast(engine, state, spell, caster="p1"):
    engine.rules.cast_spell(state.player_by_id(caster), spell)
    engine.resolve_until_stable()


def _library(state, player_id="p1", count=3):
    p = state.player_by_id(player_id)
    for i in range(count):
        p.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                    owner_id=player_id, zone=Zone.LIBRARY))
    return p


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _effect(oracle, types="Sorcery"):
    result = _parse(Card(id="S", name="S", type_line=types, oracle_text=oracle,
                         is_instant=types == "Instant", is_sorcery=types == "Sorcery"))
    assert result.modeled, oracle
    [spec] = [s for s in result.specs if s.ability_kind in ("spell_effect", "triggered")]
    return spec


@pytest.mark.parametrize(
    "oracle",
    [
        DRAW_ON_ENTER,
        "Until end of turn, whenever a creature you control enters, draw a card.",
        "Whenever a creature attacks this turn, it gains lifelink until end of turn.",
    ],
)
def test_a_spell_wraps_its_trigger_in_a_turn_scoped_effect(oracle):
    spec = _effect(oracle)
    assert spec.ability_kind == "spell_effect"
    [effect] = spec.effects
    assert effect.type == "create_turn_trigger"
    assert effect.params["trigger"]["event"] in ("ENTERS_BATTLEFIELD", "ATTACKS")
    assert effect.params["effects"]


def test_a_permanents_trigger_is_not_wrapped():
    spec = _effect("Whenever a creature you control enters, draw a card.", types="Enchantment")
    assert spec.ability_kind == "triggered"


def test_a_trailing_duration_on_a_permanents_trigger_is_still_a_duration():
    spec = _effect("Whenever a creature you control attacks, it gains lifelink until end of turn.",
                   types="Enchantment")
    assert spec.ability_kind == "triggered"


@pytest.mark.parametrize(
    "name",
    ["Beck // Call", "Bonus Round", "First Day of Class", "Indulge // Excess",
     "Mage Hunters' Onslaught", "Ondu Rising", "Rite of Harmony"],
)
def test_the_previously_inert_claims_are_now_turn_triggers(name):
    result = parse_oracle(_named(name))
    assert result.modeled is True
    assert not any(s.ability_kind == "triggered" for s in result.specs)
    assert any(e.type == "create_turn_trigger" for s in result.specs for e in s.effects)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_the_trigger_does_nothing_until_the_spell_resolves_then_fires_this_turn():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    source = _put(state, "Nothing.", name="Bystander", types="Creature — Bear")
    spell = _spell(state, DRAW_ON_ENTER)
    before = len(p1.hand)
    _fire_enter(engine, state, source)
    assert len(p1.hand) == before  # not yet cast
    _cast(engine, state, spell)
    hand = len(p1.hand)
    assert state.turn_scoped_triggers
    _fire_enter(engine, state, source)
    assert len(p1.hand) == hand + 1
    _fire_enter(engine, state, source)
    assert len(p1.hand) == hand + 2  # a trigger lasts the turn, it is not one-shot


def test_it_respects_its_subject_filter():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    mine = _put(state, "Nothing.", name="Mine", types="Creature — Bear")
    theirs = _put(state, "Nothing.", name="Theirs", types="Creature — Bear", owner="p2")
    _cast(engine, state, _spell(state, DRAW_ON_ENTER))
    hand = len(p1.hand)
    _fire_enter(engine, state, theirs)
    assert len(p1.hand) == hand  # "you control"
    _fire_enter(engine, state, mine)
    assert len(p1.hand) == hand + 1


def test_it_expires_when_the_turn_ends():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    source = _put(state, "Nothing.", name="Bystander", types="Creature — Bear")
    _cast(engine, state, _spell(state, DRAW_ON_ENTER))
    state.internal_turn.number += 1
    hand = len(p1.hand)
    _fire_enter(engine, state, source)
    assert len(p1.hand) == hand
    assert state.turn_scoped_triggers == []


def test_it_survives_the_snapshot_an_undo_restores():
    from mtg_analyzer.game.game_engine import GameEngine

    engine, state = _engine()
    state.current_step = "main1"
    _library(state)
    _cast(engine, state, _spell(state, DRAW_ON_ENTER))
    restored = GameEngine(state.clone())
    restored_state = restored.state
    creature = _put(restored_state, "Nothing.", name="Late", types="Creature — Bear")
    hand = len(restored_state.player_by_id("p1").hand)
    _fire_enter(restored, restored_state, creature)
    assert len(restored_state.player_by_id("p1").hand) == hand + 1


def test_it_belongs_to_the_caster_not_to_whoever_the_event_names():
    engine, state = _engine()
    state.current_step = "main1"
    p1, p2 = _library(state, "p1"), _library(state, "p2")
    mine = _put(state, "Nothing.", name="Mine", types="Creature — Bear")
    _cast(engine, state, _spell(state, "Whenever a creature enters this turn, draw a card."))
    theirs = _put(state, "Nothing.", name="Theirs", types="Creature — Bear", owner="p2")
    hand1, hand2 = len(p1.hand), len(p2.hand)
    _fire_enter(engine, state, theirs)
    assert len(p1.hand) == hand1 + 1  # the caster draws, for any creature
    assert len(p2.hand) == hand2
    _fire_enter(engine, state, mine)
    assert len(p1.hand) == hand1 + 2


def test_an_opponent_casting_it_gets_their_own_you_control():
    engine, state = _engine()
    state.current_step = "main1"
    p1, p2 = _library(state, "p1"), _library(state, "p2")
    mine = _put(state, "Nothing.", name="Mine", types="Creature — Bear")
    theirs = _put(state, "Nothing.", name="Theirs", types="Creature — Bear", owner="p2")
    _cast(engine, state, _spell(state, DRAW_ON_ENTER, owner="p2"), caster="p2")
    hand1, hand2 = len(p1.hand), len(p2.hand)
    _fire_enter(engine, state, mine)
    assert (len(p1.hand), len(p2.hand)) == (hand1, hand2)  # not the caster's creature
    _fire_enter(engine, state, theirs)
    assert (len(p1.hand), len(p2.hand)) == (hand1, hand2 + 1)


def test_a_bare_it_names_the_creature_that_fired_the_trigger():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "Nothing.", name="Mine", types="Creature — Bear")
    other = _put(state, "Nothing.", name="Other", types="Creature — Bear")
    _cast(engine, state, _spell(
        state, "Whenever a creature you control enters this turn, put a +1/+1 counter on it."
    ))
    _fire_enter(engine, state, other)
    assert other.counters.get("+1/+1") == 1
    assert not source.counters.get("+1/+1")


def test_a_spells_own_other_effects_still_resolve():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    _cast(engine, state, _spell(state, "You gain 3 life.\n" + DRAW_ON_ENTER))
    assert p1.life == 23
    assert state.turn_scoped_triggers


def test_the_once_variant_fires_a_single_time():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    source = _put(state, "Nothing.", name="Bystander", types="Creature — Bear")
    _cast(engine, state, _spell(state, "When you next cast a creature spell this turn, draw a card."))
    hand = len(p1.hand)
    for _ in range(2):
        creature = GameObject(Card(id="C", name="C", type_line="Creature — Bear", is_creature=True),
                              owner_id="p1", zone=Zone.HAND)
        state.player_by_id("p1").hand.append(creature)
        state.fire_event(GameEvent(
            EventType.SPELL_CAST, player_id="p1", card_id="C", spell="C",
            instance_id=creature.instance_id, object_types=sorted(creature.type_words),
            mana_value=0, from_hand=True, from_zone="hand",
        ))
        engine.resolve_until_stable()
    assert len(p1.hand) == hand + 2 + 1  # two creatures came into the hand, one card was drawn
    assert state.turn_scoped_triggers == []


def test_doublecast_copies_the_next_instant_or_sorcery_once():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    _cast(engine, state, _spell(
        state, "When you next cast an instant or sorcery spell this turn, copy that spell. "
               "You may choose new targets for the copy.", name="Doublecast"))
    life = p1.life
    _cast(engine, state, _spell(state, "You gain 3 life.", types="Instant", name="Heal"))
    assert p1.life == life + 6            # the spell and its copy
    _cast(engine, state, _spell(state, "You gain 3 life.", types="Instant", name="Heal2"))
    assert p1.life == life + 9            # "next" — the second one is not copied


def test_a_creature_spell_is_not_the_next_instant_or_sorcery():
    engine, state = _engine()
    state.current_step = "main1"
    p1 = _library(state)
    _cast(engine, state, _spell(
        state, "When you next cast an instant or sorcery spell this turn, copy that spell. "
               "You may choose new targets for the copy.", name="Doublecast"))
    creature = _spell(state, "Nothing.", types="Creature — Bear", name="Bear")
    _cast(engine, state, creature)
    life = p1.life
    _cast(engine, state, _spell(state, "You gain 3 life.", types="Instant", name="Heal"))
    assert p1.life == life + 6            # the creature did not use up "next"
