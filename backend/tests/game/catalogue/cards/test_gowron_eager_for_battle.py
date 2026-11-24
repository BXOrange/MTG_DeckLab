"""Gowron remembers the sacrificed creature's current subtypes per activation."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    gowron=card(engine,'Gowron, Eager for Battle')
    return engine,gowron,engine.state.player_by_id('p1')


def victim(engine,kind='Klingon',player='p1'):
    return filler(engine,'Victim '+kind,type_line='Creature — '+kind,player=player,power=2,toughness=2)


def activate(engine,gowron,player,obj):
    engine.activate_ability(player,gowron,0,sacrifice_choice=obj.instance_id)


def test_fresh_specs_and_binding():
    engine,gowron,player=board()
    a,b=specs_for(gowron.card),specs_for(gowron.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(gowron.triggered_abilities)==1 and len(gowron.activated_abilities)==1


@pytest.mark.parametrize('kind,reward',[('Klingon',True),('Human',False)])
def test_sacrifice_trample_counter_and_conditional_reward(kind,reward):
    engine,gowron,player=board()
    obj=victim(engine,kind)
    hand,life=len(player.hand),player.life
    activate(engine,gowron,player,obj)
    assert obj.zone==Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert combat.has(gowron,'trample') and gowron.counters.get('+1/+1')==1
    assert len(player.hand)==hand+reward and player.life==life-reward


def test_two_pending_activations_keep_separate_subtypes():
    engine,gowron,player=board()
    klingon,human=victim(engine),victim(engine,'Human')
    hand,life=len(player.hand),player.life
    activate(engine,gowron,player,klingon)
    activate(engine,gowron,player,human)
    engine.resolve_until_stable()
    assert len(player.hand)==hand+1 and player.life==life-1
    assert gowron.counters.get('+1/+1')==2


def test_graveyard_type_change_does_not_change_payment():
    engine,gowron,player=board()
    obj=victim(engine)
    hand=len(player.hand)
    activate(engine,gowron,player,obj)
    obj.card.type_line='Creature — Human'
    engine.resolve_until_stable()
    assert len(player.hand)==hand+1


def test_current_granted_klingon_type_counts():
    engine,gowron,player=board()
    obj=victim(engine,'Human')
    from mtg_analyzer.game.effects.core import EffectRegistry
    effect=EffectRegistry.create('grant_until',{'target_kind':'creature','duration':'end_of_turn',
        'static':{'type':'type_change','params':{'add_subtypes':['Klingon']}}})
    effect.apply(engine.rules.context,[obj])
    engine.recompute_continuous_effects()
    assert obj.has_subtype('Klingon')
    hand=len(player.hand)
    activate(engine,gowron,player,obj); engine.resolve_until_stable()
    assert len(player.hand)==hand+1


def test_cannot_sacrifice_gowron_or_opponents_creature():
    engine,gowron,player=board()
    enemy=victim(engine,player='p2')
    for obj in [gowron,enemy]:
        with pytest.raises(ValueError):
            activate(engine,gowron,player,obj)
        assert obj.zone==Zone.BATTLEFIELD


def test_opponents_creature_dying_adds_counter():
    engine,gowron,player=board()
    enemy=victim(engine,player='p2')
    engine.rules.destroy(enemy); engine.resolve_until_stable()
    assert gowron.counters.get('+1/+1')==1


def test_countered_activation_does_not_draw_or_gain_trample():
    engine,gowron,player=board()
    obj=victim(engine); hand,life=len(player.hand),player.life
    activate(engine,gowron,player,obj)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert obj.zone==Zone.GRAVEYARD and not combat.has(gowron,'trample')
    assert len(player.hand)==hand and player.life==life
    assert gowron.counters.get('+1/+1')==1


def test_clone_preserves_paid_klingon_and_reward_after_source_leaves():
    engine,gowron,player=board()
    obj=victim(engine); hand=len(player.hand)
    activate(engine,gowron,player,obj)
    engine.rules.put_triggers_on_stack()
    clone=GameEngine(engine.state.clone())
    clone.rules.exile(clone.state.find_object(gowron.instance_id))
    clone.resolve_until_stable()
    assert len(clone.state.player_by_id('p1').hand)==hand+1
    assert len(player.hand)==hand


def test_changeling_satisfies_klingon_condition():
    engine,gowron,player=board()
    obj=filler(engine,'Changeling',type_line='Creature — Shapeshifter',power=2,toughness=2,
               keywords=['Changeling'],oracle_text='Changeling')
    hand=len(player.hand)
    activate(engine,gowron,player,obj); engine.resolve_until_stable()
    assert len(player.hand)==hand+1


def test_returned_gowron_does_not_gain_old_activations_trample():
    engine,gowron,player=board()
    obj=victim(engine); hand=len(player.hand)
    activate(engine,gowron,player,obj)
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(gowron)
    engine.rules.return_from_graveyard(gowron,'battlefield')
    engine.resolve_until_stable()
    assert not combat.has(gowron,'trample') and not gowron.counters
    assert len(player.hand)==hand+1


def test_trample_ends_at_cleanup_but_counter_remains():
    engine,gowron,player=board()
    obj=victim(engine)
    activate(engine,gowron,player,obj); engine.resolve_until_stable()
    advance_to(engine,'cleanup')
    engine.recompute_continuous_effects()
    assert not combat.has(gowron,'trample') and gowron.counters.get('+1/+1')==1
