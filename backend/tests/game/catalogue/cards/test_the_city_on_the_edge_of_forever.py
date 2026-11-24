"""The City phases out both boards and its Human holds them out until removed."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.token_database import synthesize_token_card
from tests.support.deck_batch import card, filler, game, cast
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    bodies=[filler(engine,'Body '+p,player=p,power=2,toughness=2) for p in ['p1','p2','p3']]
    artifacts=[filler(engine,'Artifact '+p,player=p,type_line='Artifact') for p in ['p1','p2','p3']]
    land=filler(engine,'Ordinary land',type_line='Land')
    enchantment=filler(engine,'Ordinary enchantment',type_line='Enchantment')
    saga=card(engine,'The City on the Edge of Forever',zone=Zone.HAND)
    return engine,saga,bodies,artifacts,land,enchantment


def chapter(engine,saga):
    engine.rules.add_counters(saga,1,'lore'); engine.resolve_until_stable()


def human(engine):
    return next(o for o in engine.state.permanents() if o.is_token and o.name=='Human'
                and o.card.oracle_text=="Permanents can't phase in.")


def untap(engine,player):
    engine.state.active_player_index=int(player[-1])-1
    engine._step_untap(); engine.resolve_until_stable()


def test_fresh_specs_and_binding():
    engine,saga,*_=board(); a,b=specs_for(saga.card),specs_for(saga.card)
    assert len(saga.triggered_abilities)==3
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    for spec in a: spec.validate()


def test_first_chapter_phases_all_artifacts_and_creatures_then_creates_human():
    engine,saga,bodies,artifacts,land,enchantment=board(); cast(engine,saga)
    assert all(o.phased_out for o in bodies+artifacts)
    assert not land.phased_out and not enchantment.phased_out and not saga.phased_out
    token=human(engine)
    assert token.is_token and token.power==0 and token.toughness==1
    assert token.colors=={'W'} and 'Human' in token.card.type_line
    assert not token.phased_out and len(token.static_effects)==1


@pytest.mark.parametrize('player',['p1','p2','p3'])
def test_human_prevents_every_players_permanents_from_phasing_in(player):
    engine,saga,bodies,artifacts,*_=board(); cast(engine,saga); untap(engine,player)
    assert all(o.phased_out for o in bodies+artifacts)


def test_source_departure_does_not_remove_humans_prohibition():
    engine,saga,bodies,*_=board(); cast(engine,saga); engine.rules.exile(saga)
    untap(engine,'p2'); assert bodies[1].phased_out


def test_removing_human_releases_each_players_permanents_on_their_untap():
    engine,saga,bodies,artifacts,*_=board(); cast(engine,saga)
    engine.rules.destroy(human(engine)); engine.resolve_until_stable()
    untap(engine,'p2')
    assert not bodies[1].phased_out and not artifacts[1].phased_out
    assert bodies[0].phased_out and bodies[2].phased_out
    untap(engine,'p3'); assert not bodies[2].phased_out


def test_phased_out_human_does_not_prohibit_its_own_phase_in():
    from mtg_analyzer.game.effects.attachments_transforms import PhaseOutEffect
    engine,saga,bodies,*_=board(); cast(engine,saga); token=human(engine)
    PhaseOutEffect(target=token).apply(engine.rules.context)
    untap(engine,'p1')
    assert not token.phased_out and not bodies[0].phased_out
    untap(engine,'p2'); assert bodies[1].phased_out


def test_ability_loss_disables_prohibition():
    from mtg_analyzer.game.effects.core import EffectRegistry
    engine,saga,bodies,*_=board(); cast(engine,saga); token=human(engine)
    marker=EffectRegistry.create('remove_all_abilities',{'affects':'self'}); marker.source=token
    token.static_effects.append(marker); engine.recompute_continuous_effects()
    assert token.loses_all_abilities
    untap(engine,'p2'); assert not bodies[1].phased_out


def test_same_named_plain_human_does_not_have_prohibition():
    engine,saga,bodies,*_=board(); cast(engine,saga)
    engine.rules.destroy(human(engine)); engine.resolve_until_stable()
    plain=engine.rules.create_token('p1',synthesize_token_card('Human',power=1,toughness=1,
                                       colors=['W'],subtypes=['Human']),1)[0]
    assert not plain.static_effects
    untap(engine,'p2'); assert not bodies[1].phased_out


def test_copied_human_keeps_its_intrinsic_prohibition():
    engine,saga,bodies,*_=board(); cast(engine,saga); token=human(engine)
    copy=filler(engine,'Copy body',power=1,toughness=1)
    engine.rules.become_copy(copy,token)
    engine.rules.destroy(token); engine.resolve_until_stable()
    untap(engine,'p2'); assert bodies[1].phased_out
    engine.rules.destroy(copy); engine.resolve_until_stable()
    untap(engine,'p2'); assert not bodies[1].phased_out


def test_attachment_phases_indirectly_even_if_equipment_was_created_first():
    engine,saga,bodies,*_=board()
    equipment=filler(engine,'Equipment',player='p3',type_line='Artifact — Equipment',
                     oracle_text='Equip {2}',keywords=['Equip'])
    engine.state.battlefield.remove(equipment); engine.state.battlefield.insert(0,equipment)
    equipment.attached_to=bodies[1].instance_id
    cast(engine,saga)
    assert equipment.phased_out and equipment.phased_out_with==bodies[1].instance_id
    assert equipment.attached_to==bodies[1].instance_id
    engine.rules.destroy(human(engine)); engine.resolve_until_stable()
    untap(engine,'p3'); assert equipment.phased_out
    untap(engine,'p2'); assert not equipment.phased_out and not bodies[1].phased_out


def test_second_chapter_draws_two_and_each_player_loses_two_life():
    engine,saga,*_=board(); cast(engine,saga)
    before=len(engine.state.player_by_id('p1').hand); chapter(engine,saga)
    assert len(engine.state.player_by_id('p1').hand)==before+2
    assert [p.life for p in engine.state.players]==[18,18,18]


def test_third_chapter_sacrifices_creature_token_gains_five_and_finishes_saga():
    engine,saga,*_=board(); cast(engine,saga); token=human(engine)
    chapter(engine,saga); chapter(engine,saga)
    assert engine.state.pending_choice is None  # the only legal mandatory sacrifice happens immediately
    assert token not in engine.state.battlefield
    assert engine.state.player_by_id('p1').life==23 and saga.zone==Zone.GRAVEYARD


def test_third_chapter_without_creature_token_gains_nothing():
    engine,saga,*_=board(); cast(engine,saga)
    engine.rules.destroy(human(engine)); engine.resolve_until_stable()
    chapter(engine,saga); chapter(engine,saga)
    assert engine.state.pending_choice is None
    assert engine.state.player_by_id('p1').life==18 and saga.zone==Zone.GRAVEYARD


def test_third_chapter_cannot_sacrifice_noncreatures_or_nontokens():
    engine,saga,*_=board(); cast(engine,saga); token=human(engine)
    engine.rules.create_token('p1',synthesize_token_card('Treasure',is_artifact=True),1)
    other=filler(engine,'Later creature',power=1,toughness=1)
    second=engine.rules.create_token('p1',synthesize_token_card('Soldier',power=1,toughness=1,
                                        colors=['W'],subtypes=['Soldier']),1)[0]
    chapter(engine,saga); chapter(engine,saga)
    ids={o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert token.instance_id in ids and second.instance_id in ids and other.instance_id not in ids
    engine.resolve_pending_choice(str(token.instance_id))
    assert other in engine.state.battlefield


def test_clone_preserves_human_prohibition_and_phased_out_objects():
    engine,saga,bodies,*_=board(); cast(engine,saga)
    clone=GameEngine(engine.state.clone()); untap(clone,'p2')
    assert clone.state.find_object(bodies[1].instance_id).phased_out
    clone.rules.destroy(human(clone)); clone.resolve_until_stable(); untap(clone,'p2')
    assert not clone.state.find_object(bodies[1].instance_id).phased_out
    assert bodies[1].phased_out


def test_human_with_phasing_blocks_phase_in_even_as_it_phases_out():
    engine,saga,bodies,*_=board(); cast(engine,saga); token=human(engine)
    token.intrinsic_keywords.add('phasing')
    untap(engine,'p1')
    assert token.phased_out and bodies[0].phased_out
    untap(engine,'p2'); assert not bodies[1].phased_out
    untap(engine,'p1'); assert not token.phased_out and not bodies[0].phased_out


def test_third_chapter_retains_controller_after_source_control_change():
    engine,saga,*_=board(); cast(engine,saga); token=human(engine)
    other=engine.rules.create_token('p1',synthesize_token_card('Soldier',power=1,toughness=1,
                                        colors=['W'],subtypes=['Soldier']),1)[0]
    chapter(engine,saga)
    engine.rules.add_counters(saga,1,'lore'); engine.rules.put_triggers_on_stack()
    saga.controller_id='p2'; engine.recompute_continuous_effects(); engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id']=='p1'
    engine.resolve_pending_choice(str(token.instance_id))
    assert engine.state.player_by_id('p1').life==23
    assert engine.state.player_by_id('p2').life==18 and other in engine.state.battlefield


def test_clone_preserves_pending_third_chapter_sacrifice():
    engine,saga,*_=board(); cast(engine,saga); token=human(engine)
    engine.rules.create_token('p1',synthesize_token_card('Soldier',power=1,toughness=1,
                              colors=['W'],subtypes=['Soldier']),1)
    chapter(engine,saga); chapter(engine,saga)
    clone=GameEngine(engine.state.clone()); clone.resolve_pending_choice(str(token.instance_id))
    assert clone.state.player_by_id('p1').life==23
    assert clone.state.find_object(saga.instance_id).zone==Zone.GRAVEYARD
    assert token in engine.state.battlefield and engine.state.player_by_id('p1').life==18
