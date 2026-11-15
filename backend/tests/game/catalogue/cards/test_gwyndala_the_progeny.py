"""Gwyndala creates a real Equipment and copies a resolution-time token group."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.token_database import synthesize_token_card
from tests.support.deck_batch import card, filler, game, cast, activate
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Gwyndala, the Progeny',zone=Zone.HAND); cast(engine,source)
    heirloom=next(o for o in engine.state.permanents() if o.name=='Neuroflux Heirloom')
    target=card(engine,'Bonesplitter')
    return engine,source,heirloom,target


def equipment_token(engine,name='Extra Equipment',player='p1'):
    return engine.rules.create_token(player,synthesize_token_card(name,is_artifact=True,
        subtypes=['Equipment'],keywords=['Equip'],oracle_text='Equip {2}'),1)[0]


def copy_group(engine,source,target):
    engine.state.player_by_id('p1').mana_pool.add('C',2)
    activate(engine,source,targets=[target])


def test_fresh_specs_and_bound_abilities():
    engine,source,heirloom,target=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==len(source.activated_abilities)==1
    assert len(source.activated_abilities[0].effects[0].target_specs)==1


def test_entry_creates_colorless_equipment_with_anthem_and_equip_attached_to_source():
    engine,source,heirloom,target=board()
    assert heirloom.is_token and not heirloom.is_creature and 'artifact' in heirloom.type_words
    assert 'Equipment' in heirloom.card.type_line and not heirloom.colors
    assert heirloom.attached_to==source.instance_id
    assert (source.power,source.toughness)==(2,2)
    assert len(heirloom.activated_abilities)==1


def test_heirlooms_equip_cost_is_two_and_it_can_move_to_another_creature():
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    recipient=filler(engine,'Recipient',power=2,toughness=2)
    player.mana_pool=type(player.mana_pool)(); player.mana_pool.add('C',1)
    assert not engine.can_activate(player,heirloom,heirloom.activated_abilities[0])
    player.mana_pool.add('C',1); activate(engine,heirloom,targets=[recipient])
    assert heirloom.attached_to==recipient.instance_id
    assert (source.power,source.toughness)==(1,1) and (recipient.power,recipient.toughness)==(3,3)


def test_equipment_tokens_copy_target_keep_attachments_then_revert_at_cleanup():
    engine,source,heirloom,target=board(); extra=equipment_token(engine)
    original_id,visit=heirloom.instance_id,heirloom.zone_incarnation
    copy_group(engine,source,target)
    assert heirloom.name==extra.name=='Bonesplitter'
    assert heirloom.is_token and heirloom.instance_id==original_id and heirloom.zone_incarnation==visit
    assert heirloom.attached_to==source.instance_id and (source.power,source.toughness)==(3,1)
    advance_to(engine,'cleanup')
    assert heirloom.name=='Neuroflux Heirloom' and extra.name=='Extra Equipment'
    assert heirloom.attached_to==source.instance_id and (source.power,source.toughness)==(2,2)


def test_group_excludes_opponents_tokens_non_equipment_tokens_and_nontokens():
    engine,source,heirloom,target=board()
    foreign=equipment_token(engine,player='p2')
    treasure=engine.rules.create_token('p1',synthesize_token_card('Treasure',is_artifact=True),1)[0]
    ordinary=card(engine,'Short Sword')
    copy_group(engine,source,target)
    assert heirloom.name=='Bonesplitter'
    assert foreign.name=='Extra Equipment' and treasure.name=='Treasure' and ordinary.name=='Short Sword'


def test_only_own_equipment_is_a_legal_copy_target():
    from mtg_analyzer.game.targeting import legal_targets
    engine,source,heirloom,target=board(); foreign=card(engine,'Short Sword',player='p2')
    artifact=filler(engine,'Ordinary artifact',type_line='Artifact')
    effect=source.activated_abilities[0].effects[0]
    offered=legal_targets(engine.state,'p1',effect.target_spec,source)
    ids={o.get('instance_id') for o in offered}
    assert target.instance_id in ids and heirloom.instance_id in ids
    assert foreign.instance_id not in ids and artifact.instance_id not in ids


def test_target_can_be_one_of_the_affected_tokens():
    engine,source,heirloom,target=board(); extra=equipment_token(engine)
    copy_group(engine,source,extra)
    assert heirloom.name==extra.name=='Extra Equipment'
    assert heirloom.is_token and heirloom.attached_to==source.instance_id
    assert (source.power,source.toughness)==(1,1)


def test_late_tokens_join_only_if_they_exist_at_resolution():
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    player.mana_pool.add('C',2); engine.activate_ability(player,source,0,targets=[target])
    before=equipment_token(engine,'Before resolution'); engine.resolve_until_stable()
    after=equipment_token(engine,'After resolution')
    assert before.name=='Bonesplitter' and after.name=='After resolution'


def test_affected_tokens_are_not_targets_even_if_they_have_shroud():
    engine,source,heirloom,target=board()
    heirloom.intrinsic_keywords.add('shroud'); engine.recompute_continuous_effects()
    copy_group(engine,source,target)
    assert heirloom.name=='Bonesplitter'


@pytest.mark.parametrize('change',['exile','control'])
def test_illegal_target_prevents_entire_group_copy(change):
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    player.mana_pool.add('C',2); engine.activate_ability(player,source,0,targets=[target])
    if change=='exile': engine.rules.exile(target)
    else: target.controller_id='p2'; engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert heirloom.name=='Neuroflux Heirloom' and (source.power,source.toughness)==(2,2)


def test_copy_group_uses_original_ability_controller_after_source_control_change():
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    foreign=equipment_token(engine,player='p2')
    player.mana_pool.add('C',2); engine.activate_ability(player,source,0,targets=[target])
    source.controller_id='p2'; engine.recompute_continuous_effects(); engine.resolve_until_stable()
    assert heirloom.name=='Bonesplitter' and foreign.name=='Extra Equipment'


def test_copy_activation_resolves_after_source_leaves():
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    player.mana_pool.add('C',2); engine.activate_ability(player,source,0,targets=[target])
    engine.rules.exile(source); engine.resolve_until_stable()
    assert heirloom.name=='Bonesplitter' and heirloom.attached_to is None


def test_entry_trigger_after_source_leaves_still_creates_unattached_token():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Gwyndala, the Progeny')
    from mtg_analyzer.models.game.events import EventType,GameEvent
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
        controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(source); engine.resolve_until_stable()
    token=next(o for o in engine.state.permanents() if o.name=='Neuroflux Heirloom')
    assert token.attached_to is None


def test_old_entry_trigger_cannot_attach_to_a_new_source_visit():
    from mtg_analyzer.models.game.events import EventType,GameEvent
    engine=game(players=3,library=30); advance_to(engine,'main1')
    source=card(engine,'Gwyndala, the Progeny')
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,instance_id=source.instance_id,
        controller_id='p1',object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield'); engine.resolve_until_stable()
    tokens=[o for o in engine.state.permanents() if o.name=='Neuroflux Heirloom']
    assert len(tokens)==2
    assert sum(o.attached_to==source.instance_id for o in tokens)==1
    assert (source.power,source.toughness)==(2,2)


def test_later_copy_replaces_earlier_copy_and_both_expire():
    engine,source,heirloom,target=board(); second=card(engine,'Short Sword')
    copy_group(engine,source,target); copy_group(engine,source,second)
    assert heirloom.name=='Short Sword' and (source.power,source.toughness)==(2,2)
    advance_to(engine,'cleanup')
    assert heirloom.name=='Neuroflux Heirloom' and (source.power,source.toughness)==(2,2)


def test_copy_does_not_follow_later_changes_to_the_target():
    engine,source,heirloom,target=board(); second=card(engine,'Short Sword')
    copy_group(engine,source,target); engine.rules.become_copy(target,second)
    engine.recompute_continuous_effects()
    assert heirloom.name=='Bonesplitter' and target.name=='Short Sword'


def test_cloned_pending_activation_and_cleanup_keep_original_token_definition():
    engine,source,heirloom,target=board(); player=engine.state.players[0]
    player.mana_pool.add('C',2); engine.activate_ability(player,source,0,targets=[target])
    clone=GameEngine(engine.state.clone()); clone.resolve_until_stable()
    copied=clone.state.find_object(heirloom.instance_id)
    assert copied.name=='Bonesplitter' and heirloom.name=='Neuroflux Heirloom'
    clone=GameEngine(clone.state.clone()); advance_to(clone,'cleanup')
    restored=clone.state.find_object(heirloom.instance_id)
    assert restored.name=='Neuroflux Heirloom' and restored.attached_to==source.instance_id
