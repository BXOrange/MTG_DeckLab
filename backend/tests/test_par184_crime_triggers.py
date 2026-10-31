"""PAR-184: crime heads compose with existing bodies, player scopes and trigger limits."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par124_turn_scoped_triggers import _spell


REAL_TEXT = {
    'Blood Hustler': 'Whenever you commit a crime, put a +1/+1 counter on this creature. '
                    'This ability triggers only once each turn.\n'
                    '{3}{B}: Target opponent loses 1 life and you gain 1 life.',
    'Overzealous Muscle': 'Whenever you commit a crime during your turn, this creature gains '
                         'indestructible until end of turn.',
    'Forsaken Miner': "This creature can't block.\nWhenever you commit a crime, you may pay {B}. "
                      'If you do, return this card from your graveyard to the battlefield.',
}


def _put(state, name, text=None, zone=Zone.BATTLEFIELD):
    card = Card(id=name, name=name, type_line='Creature', is_creature=True,
                power=2, toughness=3, oracle_text=REAL_TEXT[name] if text is None else text)
    obj = GameObject(card, owner_id='p1', zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    else:
        state.player_by_id('p1').add_to_zone(obj, zone)
    return obj


def _ping(engine, state, caster='p1', target='p2'):
    spell = _spell(state, 'Deal 1 damage to target player.', types='Instant', owner=caster)
    engine.rules.cast_spell(state.player_by_id(caster), spell, targets=[state.player_by_id(target)])
    engine.resolve_until_stable()


@pytest.mark.full_cache
@pytest.mark.parametrize('name', [
    'At Knifepoint', "Bandit's Haul", 'Blood Hustler', 'Deepmuck Desperado',
    'Forsaken Miner', 'Freestrider Lookout', 'Hardbristle Bandit',
    'Marauding Sphinx', 'Overzealous Muscle',
    'Rattleback Apothecary', 'Raven of Fell Omens', 'Vadmir, New Blood',
])
def test_real_sole_blockers_are_modeled(name):
    card = CardDatabase(DB_PATH).get_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    crime = next(s for s in result.specs if (s.trigger or {}).get('event') == 'CRIME_COMMITTED')
    assert crime.trigger['condition'] == {'subject': 'you'}
    if 'This ability triggers only once each turn.' in card.oracle_text:
        assert crime.trigger['limit'] is True


@pytest.mark.full_cache
@pytest.mark.parametrize('name', ['Kaervek, the Punisher', 'Lazav, Familiar Stranger'])
def test_unimplemented_copy_bodies_still_fail_closed(name):
    result = parse_oracle(CardDatabase(DB_PATH).get_card(name))
    assert not result.modeled
    assert any('whenever you commit a crime' in line for line in result.unclaimed)


@pytest.mark.parametrize('head', [
    'you commit a crime and draw a card', 'you commit two crimes',
    'a creature commits a crime', 'you commit a crime against a creature',
    'you commit a crime for the second time each turn',
])
def test_unknown_crime_heads_fail_closed(head):
    result = parse_oracle(Card(id=head, name='Test', type_line='Enchantment',
                               oracle_text=f'Whenever {head}, you gain 1 life.'))
    assert not result.modeled


def test_real_crimes_trigger_once_before_resolution_and_reset_on_next_players_turn():
    engine, state = _engine()
    state.current_step = 'main1'
    hustler = _put(state, 'Blood Hustler')
    _ping(engine, state, target='p1')  # targeting yourself is not a crime
    _ping(engine, state, caster='p2', target='p1')  # another player's crime
    assert hustler.counters.get('+1/+1', 0) == 0
    spell = _spell(state, 'Deal 1 damage to target player.', types='Instant')
    engine.rules.cast_spell(state.player_by_id('p1'), spell, targets=[state.player_by_id('p2')])
    assert len(engine.rules.pending_triggers) == 1  # crime happens on announcement
    engine.resolve_until_stable()
    assert hustler.counters['+1/+1'] == 1
    _ping(engine, state)
    assert hustler.counters['+1/+1'] == 1
    state.internal_turn.number += 1
    state.active_player_index = 1
    _ping(engine, state)
    assert hustler.counters['+1/+1'] == 2


def test_actor_scope_tracks_current_controller_and_opponent_conjugation():
    engine, state = _engine()
    mine = _put(state, 'Watcher', 'Whenever you commit a crime, you gain 1 life.')
    _put(state, 'Opponent watcher', 'Whenever an opponent commits a crime, you gain 1 life.')
    state.fire_event(GameEvent(EventType.CRIME_COMMITTED, player_id='p2'))
    engine.resolve_until_stable()
    assert state.player_by_id('p1').life == 21
    mine.controller_id = 'p2'
    state.fire_event(GameEvent(EventType.CRIME_COMMITTED, player_id='p2'))
    engine.resolve_until_stable()
    assert state.player_by_id('p1').life == 22
    assert state.player_by_id('p2').life == 21


def test_overzealous_muscle_only_gains_indestructible_during_its_controllers_turn():
    engine, state = _engine()
    muscle = _put(state, 'Overzealous Muscle')
    state.current_step = 'main1'
    state.active_player_index = 1
    _ping(engine, state)
    engine.recompute_continuous_effects()
    assert 'indestructible' not in muscle.granted_keywords
    state.active_player_index = 0
    _ping(engine, state)
    engine.recompute_continuous_effects()
    assert 'indestructible' in muscle.granted_keywords


@pytest.mark.parametrize('pay', [False, True])
def test_forsaken_miner_functions_from_graveyard_and_returns_only_if_paid(pay):
    engine, state = _engine()
    state.current_step = 'main1'
    miner = _put(state, 'Forsaken Miner', zone=Zone.GRAVEYARD)
    state.player_by_id('p1').mana_pool.add_many({'B': 1})
    _ping(engine, state)
    choice = state.pending_choice
    assert choice and choice['kind'] == 'pay_cost_then'
    selected = next(o for o in choice['options'] if (o['id'] != 'decline') == pay)
    engine.resolve_pending_choice(selected['id'])
    assert miner.zone == (Zone.BATTLEFIELD if pay else Zone.GRAVEYARD)
