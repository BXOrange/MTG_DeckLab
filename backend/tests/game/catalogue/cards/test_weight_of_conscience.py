"""Weight of Conscience taps a same-type pair as a cost, then exiles its enchanted creature."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board(names=('Grizzly Bears','Runeclaw Bear'),host_player='p2'):
    engine=game(players=3,library=30)
    host=card(engine,'Colossal Dreadmaw',player=host_player)
    aura=card(engine,'Weight of Conscience')
    assert engine.rules.attach_to_target(aura,host,check_control=False)
    creatures=[card(engine,name) for name in names]
    engine.recompute_continuous_effects()
    return engine,aura,host,creatures


def activate(engine,aura,creatures=None):
    engine.activate_ability(engine.state.player_by_id(aura.controller_id),aura,0,
                           tap_choices=None if creatures is None else [obj.instance_id for obj in creatures])


def test_fresh_specs_bind_restriction_and_activation():
    engine,aura,host,creatures=board();a,b=specs_for(aura.card),specs_for(aura.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(aura.activated_abilities)==1 and combat.has(host,'cant_attack')
    assert not combat.has(host,'cant_block')


def test_real_cast_attaches_and_prevents_attacking():
    engine=game(library=30);host=card(engine,'Colossal Dreadmaw',player='p2')
    aura=card(engine,'Weight of Conscience',zone=Zone.HAND);cast(engine,aura,targets=[host])
    assert aura.attached_to==host.instance_id and combat.has(host,'cant_attack')


def test_taps_cost_creatures_immediately_and_exiles_only_at_resolution():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    assert all(obj.tapped for obj in creatures) and not aura.tapped
    assert host.zone==Zone.BATTLEFIELD and not engine.state.stack[-1].targets
    engine.resolve_until_stable()
    assert host.zone==Zone.EXILE and aura.zone==Zone.GRAVEYARD


def test_summoning_sick_creatures_can_pay_non_symbol_tap_cost():
    engine,aura,host,creatures=board()
    for obj in creatures:obj.summoning_sick=True
    activate(engine,aura,creatures);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE


def test_enchanted_creature_itself_can_pay_if_you_control_it():
    engine,aura,host,creatures=board(('Llanowar Elves',),host_player='p1')
    other=card(engine,'Snapping Sailback')
    activate(engine,aura,[host,other]);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE and other.tapped


@pytest.mark.parametrize('names',[('Grizzly Bears','Llanowar Elves'),('Ornithopter','Grizzly Bears')])
def test_no_shared_creature_type_rejects_without_tapping(names):
    engine,aura,host,creatures=board(names)
    with pytest.raises(ValueError):activate(engine,aura,creatures)
    assert not any(obj.tapped for obj in creatures) and not engine.state.stack
    assert host.zone==Zone.BATTLEFIELD


def test_empty_type_sets_do_not_share_a_type():
    engine,aura,host,creatures=board(())
    creatures=[filler(engine,'Typeless A',power=2,toughness=2),filler(engine,'Typeless B',power=2,toughness=2)]
    with pytest.raises(ValueError):activate(engine,aura,creatures)
    assert not any(obj.tapped for obj in creatures)


def test_changeling_shares_with_a_bear():
    engine,aura,host,creatures=board(('Universal Automaton','Grizzly Bears'))
    activate(engine,aura,creatures);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE


@pytest.mark.parametrize('indices',[(0,),(0,0),(0,1,2)])
def test_exactly_two_distinct_creatures_are_required(indices):
    engine,aura,host,creatures=board(('Grizzly Bears','Runeclaw Bear','Grizzly Bears'))
    with pytest.raises(ValueError):activate(engine,aura,[creatures[i] for i in indices])
    assert not any(obj.tapped for obj in creatures)


def test_opposing_creature_or_tapped_creature_cannot_pay():
    engine,aura,host,creatures=board();creatures[1].controller_id='p2'
    with pytest.raises(ValueError):activate(engine,aura,creatures)
    creatures[1].controller_id='p1';creatures[1].tapped=True
    with pytest.raises(ValueError):activate(engine,aura,creatures)
    assert not creatures[0].tapped


def test_automatic_choice_skips_incompatible_first_creature():
    engine,aura,host,creatures=board(('Llanowar Elves','Grizzly Bears','Runeclaw Bear'))
    activate(engine,aura)
    assert not creatures[0].tapped and creatures[1].tapped and creatures[2].tapped


def test_legal_cost_picker_offers_compatible_creatures_with_types():
    engine,aura,host,creatures=board(('Llanowar Elves','Grizzly Bears','Runeclaw Bear'))
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==aura.instance_id)
    assert action['tap_cost']['shared_creature_type'] and action['tap_cost']['count']==2
    assert {o['instance_id'] for o in action['tap_cost']['options']}=={creatures[1].instance_id,creatures[2].instance_id}
    assert all('bear' in o['creature_types'] for o in action['tap_cost']['options'])


def test_layer_type_changes_count_for_the_pair():
    from mtg_analyzer.game.effects.core import StaticAbility
    engine,aura,host,creatures=board(('Llanowar Elves','Grizzly Bears'))
    aura.static_effects.append(StaticAbility('type',affects='creatures_you_control',source=aura,params={'add_subtypes':['Human']}))
    engine.recompute_continuous_effects();activate(engine,aura,creatures);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE


def test_removed_aura_uses_its_last_enchanted_creature():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    engine.rules.exile(aura);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE


def test_old_ability_does_not_exile_returned_host():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    engine.rules.put_into_graveyard(host);engine.rules.return_from_graveyard(host,'battlefield')
    engine.resolve_until_stable()
    assert host.zone==Zone.BATTLEFIELD


def test_aura_returned_on_another_host_keeps_old_abilitys_last_relationship():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    engine.rules.put_into_graveyard(aura)
    other=card(engine,'Grizzly Bears',player='p3')
    engine.rules.return_from_graveyard(aura,'battlefield')
    assert engine.rules.attach_to_target(aura,other,check_control=False)
    engine.resolve_until_stable()
    assert host.zone==Zone.EXILE and other.zone==Zone.BATTLEFIELD


def test_countering_does_not_untap_paid_creatures():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert host.zone==Zone.BATTLEFIELD and all(obj.tapped for obj in creatures)


def test_pending_activation_survives_clone():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert restored.state.find_object(host.instance_id).zone==Zone.EXILE and host.zone==Zone.BATTLEFIELD


def test_copy_of_ability_after_aura_departure_keeps_attachment_lki():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    original=engine.state.stack[-1];engine.rules.exile(aura)
    engine.rules.copy_ability(original,'p1')
    engine.rules.counter_ability(original);engine.resolve_until_stable()
    assert host.zone==Zone.EXILE and all(obj.tapped for obj in creatures)


def test_no_compatible_pair_hides_activation_offer():
    engine,aura,host,creatures=board(('Grizzly Bears','Llanowar Elves'))
    assert not any(a['type']=='activate_ability' and a['instance_id']==aura.instance_id
                   for a in engine.legal_actions(engine.state.players[0]))


def test_changed_host_without_source_departure_is_the_current_enchanted_creature():
    engine,aura,host,creatures=board();activate(engine,aura,creatures)
    other=card(engine,'Grizzly Bears',player='p3')
    engine.rules.attach_to_target(aura,other,check_control=False)
    engine.resolve_until_stable()
    assert other.zone==Zone.EXILE and host.zone==Zone.BATTLEFIELD
