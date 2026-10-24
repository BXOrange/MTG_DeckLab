"""PAR-187: hand choices preserve card filters, visibility and exact visits."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.game_session import GameSession
from tests.test_mec118_opponent_choice import _db_card, _engine, _put


def hand(eng, name, kind='Instant', mv=2, zone=Zone.HAND):
    return _put(eng, Card(id=name, name=name, type_line=kind, converted_mana_cost=mv,
                         is_land=kind == 'Land', is_creature=kind == 'Creature',
                         is_instant=kind == 'Instant', is_sorcery=kind == 'Sorcery'), 'p2', zone)


def cast(eng, name, **kwargs):
    spell = _put(eng, _db_card(name), 'p1', Zone.HAND)
    eng.state.players[0].mana_pool.add_many({c: 10 for c in 'WUBRGC'})
    eng.cast_spell(eng.state.players[0], spell, targets=[eng.state.players[1]], **kwargs)
    eng.resolve_until_stable()
    return spell


def names(view, owner='p2'):
    return {o['name'] for p in view['state']['players'] if p['id'] == owner for o in p['hand']}


@pytest.mark.parametrize('name', ['Castigate', 'Agonizing Remorse', 'Collective Brutality', 'Appetite for Brains'])
def test_real_named_cards_modeled(name):
    assert parse_oracle(_db_card(name)).modeled


@pytest.mark.parametrize('name,eligible,kind,mv', [
    ('Castigate', True, 'Creature', 2),
    ('Appetite for Brains', True, 'Land', 5),
    ('Appetite for Brains', False, 'Instant', 3),
])
def test_real_exile_filters_and_revealed_hand(name, eligible, kind, mv):
    eng = _engine(3)
    pick = hand(eng, 'Pick', kind, mv)
    other = hand(eng, 'Other', 'Land', 0)
    cast(eng, name)
    session = GameSession(eng)
    for view in [session.view(perspective='p1'), session.view(perspective='p3'), session.observer_view()]:
        assert names(view) == {'Pick', 'Other'}
    if eligible:
        assert {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o} == {pick.instance_id}
        eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
        assert pick.zone == Zone.EXILE and other in eng.state.players[1].hand
    else:
        assert eng.state.pending_choice['kind'] == 'look_hand'
        eng.resolve_pending_choice('decline'); eng.resolve_until_stable()
        assert pick in eng.state.players[1].hand
    assert not names(session.view(perspective='p3')) and not names(session.observer_view())


@pytest.mark.parametrize('from_graveyard', [False, True])
def test_agonizing_remorse_pool_life_and_clone(from_graveyard):
    eng = _engine()
    chosen = hand(eng, 'Chosen', 'Land' if from_graveyard else 'Instant',
                  zone=Zone.GRAVEYARD if from_graveyard else Zone.HAND)
    land = hand(eng, 'Land', 'Land')
    cast(eng, 'Agonizing Remorse')
    assert eng.state.players[0].life == 20
    assert {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o} == {chosen.instance_id}
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(chosen.instance_id)); clone.resolve_until_stable()
    assert clone.state.find_object(chosen.instance_id).zone == Zone.EXILE
    assert clone.state.players[0].life == 19 and eng.state.players[0].life == 20
    assert land in eng.state.players[1].hand


def test_collective_brutality_real_mode_filters_card_types():
    eng = _engine()
    instant = hand(eng, 'Instant'); creature = hand(eng, 'Creature', 'Creature')
    cast(eng, 'Collective Brutality', mode=[0])
    assert {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o} == {instant.instance_id}
    eng.resolve_pending_choice(str(instant.instance_id)); eng.resolve_until_stable()
    assert instant in eng.state.players[1].graveyard and creature in eng.state.players[1].hand


def test_private_look_and_new_cards_visibility():
    eng = _engine(3)
    pick = hand(eng, 'Old')
    card = Card(id='Probe', name='Probe', type_line='Sorcery', is_sorcery=True,
                oracle_text="Look at target opponent's hand. You may choose a nonland card from it. That player discards that card.")
    spell = _put(eng, card, 'p1', Zone.HAND)
    eng.cast_spell(eng.state.players[0], spell, targets=[eng.state.players[1]]); eng.resolve_until_stable()
    new = hand(eng, 'New'); session = GameSession(eng)
    assert names(session.view(perspective='p1')) == {'Old'}
    assert names(session.view(perspective='p2')) == {'Old', 'New'}
    assert not names(session.view(perspective='p3')) and not names(session.observer_view())
    eng.resolve_pending_choice('decline'); eng.resolve_until_stable()
    assert pick in eng.state.players[1].hand and new in eng.state.players[1].hand


def test_returned_card_is_not_original_hand_visit():
    eng = _engine(); pick = hand(eng, 'Chosen')
    cast(eng, 'Castigate')
    eng.rules.exile(pick); eng.state.players[1].exile.remove(pick)
    pick.reset_as_new_object(); pick.zone = Zone.HAND; eng.state.players[1].hand.append(pick)
    with pytest.raises(ValueError):
        eng.resolve_pending_choice(str(pick.instance_id))
    assert pick in eng.state.players[1].hand
    assert not names(GameSession(eng).observer_view())


@pytest.mark.parametrize('text', [
    "target opponent reveals their hand. you choose a nonland card from it. exile that card until ~ leaves the battlefield",
    "target player reveals their hand. you choose a frobnicated card from it. that player discards that card",
    "target player reveals their hand. you choose a card from it with mana value 4 or greater. put it onto the battlefield",
    "you choose a nonland card from it. exile that card",
])
def test_unsupported_hand_instructions_fail_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('kind', ['Artifact', 'Creature', 'Enchantment', 'Instant', 'Sorcery', 'Planeswalker', 'Land', 'Battle'])
def test_shared_type_vocabulary_has_executable_members(kind):
    eng = _engine()
    pick = hand(eng, 'Pick', kind)
    spell = _put(eng, Card(id='Probe', name='Probe', type_line='Sorcery', is_sorcery=True,
                          oracle_text=f'Target opponent reveals their hand. You choose a {kind.lower()} card from it. That player discards that card.'), 'p1', Zone.HAND)
    eng.cast_spell(eng.state.players[0], spell, targets=[eng.state.players[1]]); eng.resolve_until_stable()
    assert {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o} == {pick.instance_id}
    eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
    assert pick in eng.state.players[1].graveyard


def enter_hand_exiler(eng, name):
    source = _put(eng, _db_card(name), 'p1', Zone.HAND)
    eng.state.players[0].mana_pool.add_many({c: 10 for c in 'WUBRGC'})
    eng.cast_spell(eng.state.players[0], source)
    eng.rules.resolve_top_of_stack(); eng.rules.put_triggers_on_stack()
    if eng.state.pending_choice:
        eng.rules.resolve_choice('p2')
    return source


@pytest.mark.parametrize('name', ['Mesmeric Fiend', 'Tidehollow Sculler'])
@pytest.mark.parametrize('leave_before', [False, True])
def test_separate_linked_exile_triggers_keep_source_visit(name, leave_before):
    eng = _engine(); pick = hand(eng, 'Pick')
    source = enter_hand_exiler(eng, name)
    if leave_before:
        eng.rules.put_into_graveyard(source)
        eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'choose_objects'
    eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE
    if not leave_before:
        eng.rules.put_into_graveyard(source); eng.resolve_until_stable()
        assert pick in eng.state.players[1].hand
    else:
        assert source.zone == Zone.GRAVEYARD and pick.zone == Zone.EXILE


def test_linked_return_does_not_return_a_new_exile_visit():
    eng = _engine(); pick = hand(eng, 'Pick')
    source = enter_hand_exiler(eng, 'Mesmeric Fiend')
    eng.resolve_until_stable(); eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
    eng.rules.return_to_hand(pick); eng.rules.exile(pick)
    eng.rules.put_into_graveyard(source); eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE


def test_aggressive_negotiations_followup_retains_announced_creature():
    eng = _engine(); pick = hand(eng, 'Discarded')
    creature = _put(eng, Card(id='Our creature', name='Our creature', type_line='Creature',
                              is_creature=True, power=2, toughness=2), 'p1')
    spell = _put(eng, _db_card('Aggressive Negotiations'), 'p1', Zone.HAND)
    eng.state.players[0].mana_pool.add_many({c: 10 for c in 'WUBRGC'})
    eng.cast_spell(eng.state.players[0], spell, targets=[eng.state.players[1], creature],
                   target_groups=[[eng.state.players[1]], [creature]])
    eng.resolve_until_stable()
    assert not creature.counters
    eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
    assert pick.zone == Zone.EXILE and creature.counters['+1/+1'] == 1


@pytest.mark.parametrize('quality,accepted,rejected', [
    ('noncreature', 'Instant', 'Creature'),
    ('nonartifact, nonland', 'Creature', 'Artifact'),
    ('instant or sorcery', 'Sorcery', 'Creature'),
])
def test_shared_filter_composition_executes_both_sides(quality, accepted, rejected):
    eng = _engine(); pick = hand(eng, 'Eligible', accepted); other = hand(eng, 'Not eligible', rejected)
    spell = _put(eng, Card(id='Probe', name='Probe', type_line='Sorcery', is_sorcery=True,
                          oracle_text=f'Target opponent reveals their hand. You choose a {quality} card from it. That player discards that card.'), 'p1', Zone.HAND)
    eng.cast_spell(eng.state.players[0], spell, targets=[eng.state.players[1]]); eng.resolve_until_stable()
    assert {o['instance_id'] for o in eng.state.pending_choice['options'] if 'instance_id' in o} == {pick.instance_id}
    eng.resolve_pending_choice(str(pick.instance_id)); eng.resolve_until_stable()
    assert pick in eng.state.players[1].graveyard and other in eng.state.players[1].hand
