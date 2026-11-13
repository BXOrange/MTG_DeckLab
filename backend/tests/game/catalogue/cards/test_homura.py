"""Homura returns already flipped and grants the Essence's own-controller anthem."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, activate
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Homura, Human Ascendant')
    own=filler(engine,'Own',power=2,toughness=2)
    other=filler(engine,'Other',player='p2',power=2,toughness=2)
    return engine,source,own,other


def _die(engine,source,resolve=True):
    engine.rules.destroy(source)
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()
        engine.recompute_continuous_effects()


def test_fresh_specs_and_front_cannot_block():
    engine,source,own,other=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source,'cant_block') and not source.flipped
    assert own.power==2 and not combat.has(own,'flying')


def test_death_returns_as_legendary_enchantment_and_binds_only_back():
    engine,source,own,other=_board()
    _die(engine,source)
    assert source.zone==Zone.BATTLEFIELD and source.flipped and source.name=="Homura's Essence"
    assert source.is_enchantment and not source.is_creature and source.is_legendary
    assert not source.triggered_abilities and not combat.has(source,'cant_block')
    assert own.power==4 and own.toughness==4 and combat.has(own,'flying')
    assert other.power==2 and not combat.has(other,'flying')


def test_granted_pump_is_sourced_on_each_creature_and_expires():
    engine,source,own,other=_board()
    _die(engine,source)
    engine.state.players[0].mana_pool.add_many({'R':2})
    activate(engine,own)
    activate(engine,own)
    engine.recompute_continuous_effects()
    assert own.power==6 and own.toughness==4 and other.power==2
    advance_to(engine,'cleanup')
    engine.advance_step()
    engine.recompute_continuous_effects()
    assert own.power==4 and own.toughness==4


def test_new_creatures_receive_full_grant():
    engine,source,own,other=_board()
    _die(engine,source)
    later=filler(engine,'Later',power=1,toughness=1)
    assert later.power==3 and combat.has(later,'flying')
    assert len(later.granted_activated_abilities)==1


@pytest.mark.parametrize('change',['source_exiled','controller_changed','clone'])
def test_anthem_and_grants_follow_current_essence_controller(change):
    engine,source,own,other=_board()
    _die(engine,source)
    if change=='source_exiled':
        engine.rules.exile(source)
    elif change=='controller_changed':
        source.controller_id='p2'
    else:
        engine=GameEngine(engine.state.clone())
        own=engine.state.find_object(own.instance_id)
        other=engine.state.find_object(other.instance_id)
    engine.recompute_continuous_effects()
    assert own.power==(4 if change=='clone' else 2)
    assert other.power==(4 if change=='controller_changed' else 2)
    assert len(own.granted_activated_abilities)==(1 if change=='clone' else 0)


@pytest.mark.parametrize('change',['clone','stolen_before_death','counter','exile','new_visit'])
def test_death_return_tracks_exact_graveyard_visit_and_defaults_to_owner(change):
    engine,source,own,other=_board()
    if change=='stolen_before_death':
        source.controller_id='p2'
    _die(engine,source,resolve=False)
    if change=='counter':
        engine.rules.counter_ability(engine.state.stack[-1])
    elif change in ('exile','new_visit'):
        engine.rules.exile(source)
        if change=='new_visit':
            engine.rules.return_from_graveyard(source,'hand')
            engine.state.players[0].remove_from_zone(source,Zone.HAND)
            engine.rules.put_into_graveyard(source)
    elif change=='clone':
        engine=GameEngine(engine.state.clone())
        source=engine.state.find_object(source.instance_id)
    engine.resolve_until_stable()
    should_return=change in ('clone','stolen_before_death')
    assert source.zone==(Zone.BATTLEFIELD if should_return else Zone.EXILE if change=='exile' else Zone.GRAVEYARD)
    assert source.flipped==should_return
    if should_return:
        assert source.controller_id=='p1'


def test_destroyed_enchantment_does_not_return_again():
    engine,source,own,other=_board()
    _die(engine,source)
    engine.rules.destroy(source)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD
    assert own.power==2 and engine.state.pending_choice is None


def test_reanimated_after_essence_leaves_is_front_face_again():
    engine,source,own,other=_board()
    _die(engine,source)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.flipped and source.is_creature and combat.has(source,'cant_block')
    assert own.power==2


def test_return_event_is_enchantment_entry_not_creature_entry():
    engine,source,own,other=_board()
    _die(engine,source)
    events=[e for e in engine.state.events_this_turn()
            if e.type=='ENTERS_BATTLEFIELD' and e.get('instance_id')==source.instance_id]
    assert events and 'enchantment' in events[-1].get('object_types')
    assert 'creature' not in events[-1].get('object_types')


def test_front_cannot_be_declared_as_a_blocker():
    engine,source,own,other=_board()
    engine.state.active_player_index=1
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[1],[{'attacker':other,'defender':engine.state.players[0]}])
    advance_to(engine,'declare_blockers')
    with pytest.raises(ValueError):
        engine.declare_blockers(engine.state.players[0],[(source,other)])


def test_pending_granted_pump_survives_essence_leaving():
    engine,source,own,other=_board()
    _die(engine,source)
    player=engine.state.players[0]
    player.mana_pool.add_many({'R':1})
    engine.activate_ability(player,own,0)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert own.power==3 and own.toughness==2 and not combat.has(own,'flying')


def test_back_specs_are_fresh():
    engine,source,own,other=_board()
    _die(engine,source)
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[2] is not b[0].effects[2]
