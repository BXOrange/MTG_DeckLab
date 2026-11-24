"""Skyway Robber follows exact escape-cost exile links through combat and choices."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.linked_exile import linked_cards
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def _board(escape=True):
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Skyway Robber',zone=Zone.GRAVEYARD if escape else Zone.HAND)
    names=['Divination','Lightning Bolt','Swiftfoot Boots','Grizzly Bears','Forest']
    fuel=[card(engine,name,zone=Zone.GRAVEYARD) for name in names]
    if escape:
        cast(engine,source,pool={'U':1,'C':3},graveyard_exile_choices=[o.instance_id for o in fuel])
    else:
        cast(engine,source,pool={'U':1,'C':3})
    return engine,source,fuel


def _hit(engine,source,combat_damage=True,player='p2'):
    engine.rules.deal_damage(engine.state.player_by_id(player),1,source=source,combat=combat_damage)
    engine.resolve_until_stable()


def _play(engine,obj,**kwargs):
    player=engine.state.player_by_id(engine.state.pending_choice['player_id'])
    engine.play_resolution_card(player,obj,**kwargs)
    engine.resolve_until_stable()


def test_fresh_specs_flying_and_escape_granted_ability():
    engine,source,fuel=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source,'flying') and len(source.granted_triggered_abilities)==1
    assert {o.instance_id for o in linked_cards(engine.state,source)}=={o.instance_id for o in fuel}
    assert engine.state.players[0].mana_pool.total()==0


def test_normal_cast_does_not_gain_the_ability():
    engine,source,fuel=_board(False)
    _hit(engine,source)
    assert not source.granted_triggered_abilities and engine.state.pending_choice is None


def test_only_artifacts_instants_and_sorceries_are_offered():
    engine,source,fuel=_board()
    _hit(engine,source)
    choice=engine.state.pending_choice
    assert choice['kind']=='play_during_resolution'
    assert set(choice['instance_ids'])=={o.instance_id for o in fuel[:3]}
    assert choice['free'] and choice['only_spells'] and not choice['repeat']


@pytest.mark.parametrize('kind',['instant','sorcery','artifact'])
def test_cast_one_linked_spell_for_free(kind):
    engine,source,fuel=_board()
    _hit(engine,source)
    obj=fuel[{'sorcery':0,'instant':1,'artifact':2}[kind]]
    before=len(engine.state.players[0].hand)
    _play(engine,obj,**({'targets':[engine.state.players[2]]} if kind=='instant' else {}))
    assert obj.zone==(Zone.BATTLEFIELD if kind=='artifact' else Zone.GRAVEYARD)
    assert engine.state.players[0].mana_pool.total()==0
    if kind=='sorcery':
        assert len(engine.state.players[0].hand)==before+2
    assert engine.state.pending_choice is None
    assert all(o.zone==Zone.EXILE for o in fuel if o is not obj)


def test_decline_and_later_hit_can_use_remaining_cards():
    engine,source,fuel=_board()
    _hit(engine,source)
    engine.resolve_pending_choice('decline')
    assert all(o.zone==Zone.EXILE for o in fuel)
    _hit(engine,source)
    _play(engine,fuel[0])
    _hit(engine,source)
    assert fuel[0].instance_id not in engine.state.pending_choice['instance_ids']
    _play(engine,fuel[2])


@pytest.mark.parametrize('kind',['noncombat','creature','other_source'])
def test_wrong_damage_does_not_trigger(kind):
    engine,source,fuel=_board()
    if kind=='creature':
        target=filler(engine,player='p2',power=1,toughness=4)
        engine.rules.deal_damage(target,1,source=source,combat=True)
        engine.resolve_until_stable()
    else:
        dealer=filler(engine,power=1,toughness=1) if kind=='other_source' else source
        _hit(engine,dealer,combat_damage=kind!='noncombat')
    assert engine.state.pending_choice is None


@pytest.mark.parametrize('change',['leave','steal','clone'])
def test_pending_trigger_keeps_source_links_and_controller(change):
    engine,source,fuel=_board()
    engine.rules.deal_damage(engine.state.players[1],1,source=source,combat=True)
    engine.rules.put_triggers_on_stack()
    if change=='leave':
        engine.rules.exile(source)
    elif change=='steal':
        source.controller_id='p2'
    else:
        engine=GameEngine(engine.state.clone())
        fuel=[engine.state.find_object(o.instance_id) for o in fuel]
    engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id']=='p1'
    _play(engine,fuel[0])
    assert len(engine.state.players[0].hand)==3


def test_later_noncast_entry_has_no_escape_ability_or_old_links():
    engine,source,fuel=_board()
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert not source.granted_triggered_abilities and not linked_cards(engine.state,source)
    _hit(engine,source)
    assert engine.state.pending_choice is None


def test_exile_card_returning_to_exile_is_not_the_linked_visit():
    engine,source,fuel=_board()
    obj=fuel[0]
    engine.rules.return_from_graveyard(obj,'hand')
    engine.rules.exile(obj)
    _hit(engine,source)
    assert obj.instance_id not in engine.state.pending_choice['instance_ids']


def test_modal_card_only_allows_its_artifact_spell_face():
    engine=game(players=2,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Skyway Robber',zone=Zone.GRAVEYARD)
    modal=card(engine,'Halvar, God of Battle',zone=Zone.GRAVEYARD)
    fuel=[filler(engine,f'Fuel {i}',type_line='Land',zone=Zone.GRAVEYARD) for i in range(4)]
    cast(engine,source,pool={'U':1,'C':3},graveyard_exile_choices=[modal.instance_id]+[o.instance_id for o in fuel])
    _hit(engine,source)
    assert modal.instance_id in engine.state.pending_choice['instance_ids']
    player=engine.state.players[0]
    assert not engine.can_cast(player,modal,face='front')
    assert engine.can_cast(player,modal,face='back')
    with pytest.raises(ValueError,match='spell type'):
        engine.play_resolution_card(player,modal,face='front')
    _play(engine,modal,face='back')
    assert modal.zone==Zone.BATTLEFIELD and modal.name=='Sword of the Realms'


def test_robber_control_change_uses_new_controllers_damage_trigger():
    engine,source,fuel=_board()
    source.controller_id='p2'
    engine.recompute_continuous_effects()
    _hit(engine,source,player='p3')
    assert engine.state.pending_choice['player_id']=='p2'
    before=len(engine.state.players[1].hand)
    _play(engine,fuel[0])
    assert len(engine.state.players[1].hand)==before+2


def test_real_combat_damage_opens_cast_window():
    engine,source,fuel=_board()
    source.summoning_sick=False
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[0],[{'attacker':source,'defender':engine.state.players[1]}])
    advance_to(engine,'combat_damage')
    engine.advance_step()
    engine.resolve_until_stable()
    assert engine.state.pending_choice['kind']=='play_during_resolution'
    _play(engine,fuel[2])
    assert fuel[2].zone==Zone.BATTLEFIELD


def test_second_escape_uses_only_new_escape_cost_links():
    engine,source,old_fuel=_board()
    engine.rules.put_into_graveyard(source)
    fuel=[card(engine,'Divination',zone=Zone.GRAVEYARD)]+[
        filler(engine,f'New fuel {i}',type_line='Land',zone=Zone.GRAVEYARD) for i in range(4)]
    cast(engine,source,pool={'U':1,'C':3},graveyard_exile_choices=[o.instance_id for o in fuel])
    _hit(engine,source)
    assert engine.state.pending_choice['instance_ids']==[fuel[0].instance_id]
    assert all(o.zone==Zone.EXILE for o in old_fuel)


def test_pending_free_cast_choice_survives_clone_and_robber_departure():
    engine,source,fuel=_board()
    _hit(engine,source)
    engine.rules.exile(source)
    engine=GameEngine(engine.state.clone())
    obj=engine.state.find_object(fuel[2].instance_id)
    _play(engine,obj)
    assert obj.zone==Zone.BATTLEFIELD
