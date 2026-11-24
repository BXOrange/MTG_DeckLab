"""Quantum Reduction pays real teamwork costs and suppresses its host's abilities."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board(off_turn=True):
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    aura=card(engine,'Quantum Reduction',zone=Zone.HAND)
    host=card(engine,'Serra Angel',player='p2')
    helper=filler(engine,'Helper',power=2,toughness=2)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    if off_turn:
        engine.state.active_player_index=1
        engine.state.current_step='end'
    return engine,aura,host,helper,p


def test_fresh_specs_binding_and_native_keywords():
    engine,aura,host,helper,p=_board()
    a,b=specs_for(aura.card),specs_for(aura.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert aura.parametric_keywords['teamwork']['n']==2
    assert aura.parametric_keywords['enchant']['quality']=='creature'
    assert len(aura.static_effects)==2


def test_off_turn_requires_announced_teamwork_even_if_it_is_affordable():
    engine,aura,host,helper,p=_board()
    assert not engine.can_cast(p,aura,targets=[host])
    assert engine.can_cast(p,aura,targets=[host],teamwork=True,teamwork_choices=[helper.instance_id])
    assert not helper.tapped and not aura.teamwork_paid


def test_cast_using_teamwork_taps_helper_and_resolves_aura():
    engine,aura,host,helper,p=_board()
    engine.cast_spell(p,aura,targets=[host],teamwork=True,teamwork_choices=[helper.instance_id])
    assert helper.tapped and aura.teamwork_paid
    engine.resolve_until_stable()
    assert aura.zone==Zone.BATTLEFIELD and aura.attached_to==host.instance_id
    assert host.power==-1 and host.toughness==4
    assert not combat.has(host,'flying') and not combat.has(host,'vigilance')


@pytest.mark.parametrize('invalid',['tapped','opponent','insufficient','duplicate'])
def test_illegal_teamwork_cannot_supply_flash(invalid):
    engine,aura,host,helper,p=_board()
    choices=[helper.instance_id]
    if invalid=='tapped':
        helper.tapped=True
    elif invalid=='opponent':
        helper.controller_id='p2'
    elif invalid=='insufficient':
        helper.card.power=1
        engine.recompute_continuous_effects()
    else:
        choices*=2
    before=p.mana_pool.to_dict()
    assert not engine.can_cast(p,aura,targets=[host],teamwork=True,teamwork_choices=choices)
    with pytest.raises(ValueError):
        engine.cast_spell(p,aura,targets=[host],teamwork=True,teamwork_choices=choices)
    assert p.mana_pool.to_dict()==before and aura.zone==Zone.HAND


def test_two_summoning_sick_one_power_helpers_can_pay():
    engine,aura,host,helper,p=_board()
    helper.tapped=True
    one=filler(engine,'One',power=1,toughness=1)
    two=filler(engine,'Two',power=1,toughness=1)
    one.summoning_sick=two.summoning_sick=True
    engine.cast_spell(p,aura,targets=[host],teamwork=True,teamwork_choices=[one.instance_id,two.instance_id])
    engine.resolve_until_stable()
    assert one.tapped and two.tapped and aura.attached_to==host.instance_id


def test_normal_cast_does_not_need_teamwork():
    engine,aura,host,helper,p=_board(False)
    engine.cast_spell(p,aura,targets=[host])
    engine.resolve_until_stable()
    assert not helper.tapped and not aura.teamwork_paid and host.power==-1


def test_stale_paid_flag_does_not_authorize_unpaid_off_turn_proposal():
    engine,aura,host,helper,p=_board()
    aura.teamwork_paid=True
    assert not engine.can_cast(p,aura,targets=[host],teamwork=False)
    assert aura.teamwork_paid is True


def test_leaving_aura_restores_printed_power_and_abilities():
    engine,aura,host,helper,p=_board(False)
    engine.cast_spell(p,aura,targets=[host])
    engine.resolve_until_stable()
    engine.rules.exile(aura)
    engine.recompute_continuous_effects()
    assert host.power==4 and host.toughness==4
    assert combat.has(host,'flying') and combat.has(host,'vigilance')


def test_countering_spell_does_not_refund_teamwork_taps():
    engine,aura,host,helper,p=_board()
    engine.cast_spell(p,aura,targets=[host],teamwork=True,teamwork_choices=[helper.instance_id])
    engine.rules.counter_spell(aura)
    engine.resolve_until_stable()
    assert helper.tapped and aura.zone==Zone.GRAVEYARD and host.power==4


def test_clone_preserves_teamwork_cast_and_attachment():
    engine,aura,host,helper,p=_board()
    engine.cast_spell(p,aura,targets=[host],teamwork=True,teamwork_choices=[helper.instance_id])
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    copied=clone.state.find_object(aura.instance_id)
    assert copied.teamwork_paid and copied.attached_to==host.instance_id
    assert clone.state.find_object(host.instance_id).power==-1
    assert host.power==4


def test_independent_flash_permission_can_allow_cast_without_teamwork():
    engine,aura,host,helper,p=_board()
    card(engine,'Vedalken Orrery')
    engine.recompute_continuous_effects()
    assert engine.can_cast(p,aura,targets=[host])
    engine.cast_spell(p,aura,targets=[host])
    engine.resolve_until_stable()
    assert not helper.tapped and aura.attached_to==host.instance_id
