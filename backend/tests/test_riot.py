"""RULE 702.136 / 614.12: Riot is a pre-entry choice, including static grants."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.battlefield_batches import start_battlefield_batch
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone


def engine():
    return GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)


def creature(name='Riot Bear', text='Riot', **kwargs):
    return Card(id=name, name=name, type_line='Creature — Bear', is_creature=True,
                power=2, toughness=2, oracle_text=text, keywords=['Riot'] if 'Riot' in text else [], **kwargs)


def object_in(eng, card, zone=Zone.HAND, owner='p1'):
    obj = GameObject(card, owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def rhythm(eng, owner='p1'):
    return object_in(eng, Card(id='rhythm', name='Rhythm of the Wild', type_line='Enchantment',
        oracle_text="Creature spells you control can't be countered.\nNontoken creatures you control have riot."),
        Zone.BATTLEFIELD, owner)


def cast(eng, obj):
    eng.state.current_phase = 'precombat_main'
    eng.state.current_step = 'main1'
    eng.cast_spell(eng.state.player_by_id(obj.owner_id), obj)
    eng.resolve_until_stable()


@pytest.mark.parametrize('answer', ['counter', 'haste', None])
def test_native_riot_asks_before_entry_and_applies_the_answer(answer):
    eng = engine()
    obj = object_in(eng, creature())
    entered = []
    eng.state.subscribe(lambda e: entered.append(e) if e.type == EventType.ENTERS_BATTLEFIELD else None)
    cast(eng, obj)
    assert eng.state.pending_choice['kind'] == 'riot'
    assert obj not in eng.state.battlefield and entered == []
    eng.resolve_pending_choice(answer)
    eng.recompute_continuous_effects()
    assert obj in eng.state.battlefield and len(entered) == 1
    assert obj.counters.get('+1/+1', 0) == int(answer == 'counter')
    assert combat.has_haste(obj) == (answer != 'counter')


@pytest.mark.parametrize('name', ['Devoted Druid', 'Naga Vitalist'])
def test_bugreport_rhythm_grants_the_entry_choice_to_a_nontoken(name):
    eng = engine()
    rhythm(eng)
    obj = object_in(eng, creature(name, '{T}: Add {G}.'))
    cast(eng, obj)
    assert eng.state.pending_choice['kind'] == 'riot'
    eng.resolve_pending_choice('counter')
    assert obj.counters['+1/+1'] == 1


def test_multiple_riot_instances_offer_independent_choices_and_clone_safely():
    eng = engine()
    rhythm(eng)
    obj = object_in(eng, creature())
    cast(eng, obj)
    eng.resolve_pending_choice('counter')
    assert eng.state.pending_choice['kind'] == 'riot'
    assert obj not in eng.state.battlefield
    cloned = GameEngine(eng.state.clone())
    copied = cloned.state.pending_permanent_entry['obj']
    cloned.resolve_pending_choice('haste')
    cloned.recompute_continuous_effects()
    assert copied.counters['+1/+1'] == 1 and combat.has_haste(copied)
    assert obj not in eng.state.battlefield and eng.state.pending_choice
    eng.resolve_pending_choice('counter')
    assert obj.counters['+1/+1'] == 2


def test_haste_survives_cleanup_source_loss_and_control_change_but_not_reentry():
    eng = engine()
    source = rhythm(eng)
    obj = object_in(eng, creature(text=''))
    cast(eng, obj)
    eng.resolve_pending_choice('haste')
    eng.rules.put_into_graveyard(source)
    eng._step_cleanup()
    obj.controller_id = 'p2'
    eng.recompute_continuous_effects()
    assert combat.has_haste(obj)
    eng.rules.put_into_graveyard(obj)
    eng.rules.return_from_graveyard(obj, 'battlefield')
    eng.recompute_continuous_effects()
    assert not combat.has_haste(obj)


def test_rhythm_does_not_grant_riot_to_opponents_or_tokens():
    eng = engine()
    rhythm(eng, 'p2')
    obj = object_in(eng, creature(text=''))
    cast(eng, obj)
    assert not eng.state.pending_choice and not obj.counters
    rhythm(eng)
    tokens = eng.rules.create_token('p1', creature('Token', ''))
    assert len(tokens) == 1 and not eng.state.pending_choice and not tokens[0].counters


def test_native_riot_token_chooses_before_entry():
    eng = engine()
    tokens = eng.rules.create_token('p1', creature())
    assert not tokens and eng.state.pending_choice['kind'] == 'riot'
    eng.resolve_pending_choice('haste')
    eng.recompute_continuous_effects()
    assert len(tokens) == 1 and combat.has_haste(tokens[0])


def test_batch_return_asks_each_entrant_and_survives_clone():
    eng = engine()
    rhythm(eng)
    a = object_in(eng, creature('A', ''), Zone.GRAVEYARD)
    b = object_in(eng, creature('B', ''), Zone.GRAVEYARD)
    start_battlefield_batch(eng.rules, [a, b], 'p1')
    assert eng.state.pending_choice['kind'] == 'riot'
    eng.resolve_pending_choice('counter')
    assert a not in eng.state.battlefield
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('haste')
    clone.recompute_continuous_effects()
    a2, b2 = clone.state.find_object(a.instance_id), clone.state.find_object(b.instance_id)
    assert a2.counters['+1/+1'] == 1 and combat.has_haste(b2)
    assert a not in eng.state.battlefield and b not in eng.state.battlefield


def test_riot_choice_has_a_json_serializable_public_view():
    import json
    from mtg_analyzer.services.game_session import GameSession
    eng = engine()
    obj = object_in(eng, creature())
    cast(eng, obj)
    session = GameSession(eng, require_setup=False)
    assert json.loads(json.dumps(session.view()))['pending_choice']['kind'] == 'riot'


def test_direct_reanimation_and_blink_offer_riot_again():
    eng = engine()
    rhythm(eng)
    obj = object_in(eng, creature(text=''), Zone.GRAVEYARD)
    eng.rules.return_from_graveyard(obj)
    assert eng.state.pending_choice['kind'] == 'riot' and obj.zone == Zone.GRAVEYARD
    eng.resolve_pending_choice('counter')
    assert obj.counters['+1/+1'] == 1
    eng.rules.blink(obj)
    assert eng.state.pending_choice['kind'] == 'riot' and obj.zone == Zone.EXILE
    eng.resolve_pending_choice('haste')
    eng.recompute_continuous_effects()
    assert not obj.counters and combat.has_haste(obj)


def test_rhythm_entering_in_same_batch_does_not_grant_riot_yet():
    eng = engine()
    source = rhythm(eng)
    eng.rules.put_into_graveyard(source)
    obj = object_in(eng, creature(text=''), Zone.GRAVEYARD)
    start_battlefield_batch(eng.rules, [source, obj], 'p1')
    assert not eng.state.pending_choice and not obj.counters
