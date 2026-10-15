"""Dying enchanted hosts return independently of the Aura's later SBA."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.choices_actions import ReturnDyingSubjectToBattlefieldEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.events import GameEvent, EventType
from mtg_analyzer.parser.oracle.catalogue.dying_hosts import dying_host_return_specs
from mtg_analyzer.parser.oracle import parse_oracle


def setup(text,host_type='Creature — Bear'):
    eng=GameEngine.new_game([('p1','P1',[]),('p2','P2',[])],starting_hand=0)
    host=GameObject(Card(id='host',name='Host',type_line=host_type,is_creature='Creature' in host_type,
                         is_land='Land' in host_type,power=2,toughness=2),owner_id='p2',zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(host)
    aura=GameObject(Card(id='aura',name='Test Aura',type_line='Enchantment — Aura',oracle_text='Enchant creature\n'+text),owner_id='p1',zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura);eng.state.add_to_battlefield(aura);aura.attached_to=host.instance_id
    return eng,host,aura


@pytest.mark.parametrize('text,destination,controller,tapped,count',[
    ("When enchanted creature dies, return that card to the battlefield under its owner's control.",Zone.BATTLEFIELD,'p2',False,0),
    ('When enchanted creature dies, return that card to the battlefield under your control.',Zone.BATTLEFIELD,'p1',False,0),
    ("When enchanted creature dies, return that card to its owner's hand.",Zone.HAND,'p2',False,0),
    ("When enchanted creature dies, return that card to the battlefield tapped under its owner's control.",Zone.BATTLEFIELD,'p2',True,0),
    ('When enchanted creature dies, return that card to the battlefield under your control with a +1/+1 counter on it.',Zone.BATTLEFIELD,'p1',False,1),
])
def test_real_host_return_clause(text,destination,controller,tapped,count):
    eng,host,aura=setup(text)
    assert parse_oracle(aura.card).modeled
    eng.rules.destroy(host)
    eng.rules.check_state_based_actions();eng.rules.put_triggers_on_stack()
    assert aura.zone==Zone.GRAVEYARD
    assert eng.state.stack
    eng.resolve_until_stable()
    assert host.zone==destination and host.controller_id==controller
    assert host.tapped==tapped
    assert host.counters.get('+1/+1',0)==count
    assert aura.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('text',[
    "return this card to its owner's hand",
    'return this card to the battlefield transformed under your control',
    "return that card to the battlefield under your control, then draw a card",
    "return that card to its owner's hand. you draw a card",
])
def test_aura_source_and_unknown_riders_fail_closed(text):
    assert dying_host_return_specs(text) is None


def test_dying_land_uses_same_host_reference():
    eng,host,aura=setup("When enchanted land dies, return that card to its owner's hand.",host_type='Land Creature — Forest')
    eng.rules.destroy(host);eng.resolve_until_stable()
    assert host.zone==Zone.HAND and aura.zone==Zone.GRAVEYARD


def test_graveyard_leave_and_return_is_new_incarnation():
    eng,host,aura=setup('When enchanted creature dies, return that card to the battlefield under your control.')
    eng.rules.destroy(host);eng.rules.check_state_based_actions()
    eng.state.players[1].graveyard.remove(host);host.zone=Zone.EXILE;eng.state.players[1].exile.append(host)
    eng.state.players[1].exile.remove(host);host.zone=Zone.GRAVEYARD;eng.state.players[1].graveyard.append(host)
    eng.resolve_until_stable()
    assert host.zone==Zone.GRAVEYARD


def test_unholy_counter_is_present_to_etb_listener_and_replacements():
    eng,host,aura=setup('When enchanted creature dies, return that card to the battlefield under your control with a +1/+1 counter on it.')
    doubler=GameObject(Card(id='double',name='Doubling Season',type_line='Enchantment'),owner_id='p1',zone=Zone.BATTLEFIELD)
    bind_from_catalogue(doubler);eng.state.add_to_battlefield(doubler)
    observed=[]
    eng.state.subscribe(lambda event: observed.append(host.counters.get('+1/+1',0))
                        if event.type==EventType.ENTERS_BATTLEFIELD and event.get('instance_id')==host.instance_id else None)
    eng.rules.destroy(host);eng.resolve_until_stable()
    assert observed==[2] and host.counters['+1/+1']==2


def test_unrelated_creature_death_does_not_return_host():
    eng,host,aura=setup('When enchanted creature dies, return that card to the battlefield under your control.')
    other=GameObject(host.card,owner_id='p2',zone=Zone.BATTLEFIELD);eng.state.add_to_battlefield(other)
    eng.rules.destroy(other);eng.resolve_until_stable()
    assert other.zone==Zone.GRAVEYARD and host.zone==Zone.BATTLEFIELD


def journey_setup():
    text='When enchanted creature dies, return it to the battlefield under your control, then return this card to the battlefield transformed under your control.'
    eng,host,aura=setup(text)
    aura.card.layout='transform';aura.card.back_name='Atzal, Cave of Eternity'
    aura.card.back_type_line='Legendary Land';aura.card.back_oracle_text='{T}: Add {G}.'
    return eng,host,aura


def test_journey_returns_host_and_transformed_aura():
    eng,host,aura=journey_setup()
    eng.rules.destroy(host);eng.resolve_until_stable()
    assert host.zone==Zone.BATTLEFIELD and host.controller_id=='p1'
    assert aura.zone==Zone.BATTLEFIELD and aura.transformed
    assert aura.name=='Atzal, Cave of Eternity' and aura.attached_to is None


def test_journey_source_still_returns_when_host_exiled_in_response():
    eng,host,aura=journey_setup()
    eng.rules.destroy(host);eng.rules.check_state_based_actions();eng.rules.put_triggers_on_stack()
    eng.state.players[1].graveyard.remove(host);host.zone=Zone.EXILE;eng.state.players[1].exile.append(host)
    eng.resolve_until_stable()
    assert host.zone==Zone.EXILE
    assert aura.zone==Zone.BATTLEFIELD and aura.transformed


def test_journey_does_not_return_new_graveyard_incarnation_of_aura():
    eng,host,aura=journey_setup()
    eng.rules.destroy(host);eng.rules.check_state_based_actions();eng.rules.put_triggers_on_stack()
    eng.state.players[0].graveyard.remove(aura);aura.zone=Zone.EXILE;eng.state.players[0].exile.append(aura)
    eng.state.players[0].exile.remove(aura);aura.zone=Zone.GRAVEYARD;eng.state.players[0].graveyard.append(aura)
    eng.resolve_until_stable()
    assert host.zone==Zone.BATTLEFIELD and aura.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('pay', [False,True])
def test_puppet_master_returns_host_then_optional_aura(pay):
    text="When enchanted creature dies, return that card to its owner's hand. If that card is returned to its owner's hand this way, you may pay {U}{U}{U}. If you do, return this card to its owner's hand."
    eng,host,aura=setup(text)
    eng.state.players[0].mana_pool.add('U',3)
    eng.rules.destroy(host);eng.resolve_until_stable()
    assert host.zone==Zone.HAND and host.owner_id=='p2'
    assert eng.state.pending_choice and eng.state.pending_choice['kind']=='pay_cost_then'
    choice=eng.state.pending_choice
    answer=next(o['id'] for o in choice['options'] if (o['id']!='decline')==pay)
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()
    assert aura.zone==(Zone.HAND if pay else Zone.GRAVEYARD)


def test_puppet_master_missing_host_does_not_offer_aura_return():
    text="When enchanted creature dies, return that card to its owner's hand. If that card is returned to its owner's hand this way, you may pay {U}{U}{U}. If you do, return this card to its owner's hand."
    eng,host,aura=setup(text)
    eng.rules.destroy(host);eng.rules.check_state_based_actions();eng.rules.put_triggers_on_stack()
    eng.state.players[1].graveyard.remove(host);host.zone=Zone.EXILE;eng.state.players[1].exile.append(host)
    eng.resolve_until_stable()
    assert aura.zone==Zone.GRAVEYARD and not eng.state.pending_choice


def test_puppet_may_pay_even_when_aura_return_is_impossible():
    text="When enchanted creature dies, return that card to its owner's hand. If that card is returned to its owner's hand this way, you may pay {U}{U}{U}. If you do, return this card to its owner's hand."
    eng,host,aura=setup(text);eng.state.players[0].mana_pool.add('U',3)
    eng.rules.destroy(host);eng.rules.check_state_based_actions();eng.rules.put_triggers_on_stack()
    eng.state.players[0].graveyard.remove(aura);aura.zone=Zone.EXILE;eng.state.players[0].exile.append(aura)
    eng.resolve_until_stable()
    assert host.zone==Zone.HAND and eng.state.pending_choice['kind']=='pay_cost_then'
    answer=next(o['id'] for o in eng.state.pending_choice['options'] if o['id']!='decline')
    eng.resolve_pending_choice(answer);eng.resolve_until_stable()
    assert aura.zone==Zone.EXILE and eng.state.players[0].mana_pool.total()==0
