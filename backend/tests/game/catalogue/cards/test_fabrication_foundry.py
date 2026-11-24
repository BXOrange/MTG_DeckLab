"""Fabrication Foundry: nonempty other-artifact cost subsets total exactly X."""
import pytest
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase


def board(*values):
    engine=game(players=3,library=30)
    source=card(engine,'Fabrication Foundry')
    cards=[filler(engine,f'Artifact {i}',type_line='Artifact',mv=value) for i,value in enumerate(values)]
    target=filler(engine,'Return target',type_line='Artifact',mv=3,zone=Zone.GRAVEYARD)
    engine.state.players[0].mana_pool.add_many({'W':1,'C':2})
    main_phase(engine)
    return engine,source,cards,target


def activate(engine,source,cards,target,x):
    engine.activate_ability(engine.state.players[0],source,0,x=x,targets=[target],
                            tap_choices=None if cards is None else [obj.instance_id for obj in cards])


def test_exiles_multiple_artifacts_as_cost_then_returns_target():
    engine,source,cards,target=board(1,2)
    activate(engine,source,cards,target,3)
    assert all(obj.zone==Zone.EXILE for obj in cards) and source.tapped
    assert target.zone==Zone.GRAVEYARD
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


@pytest.mark.parametrize('x',[2,4])
def test_sum_must_equal_x_and_illegal_target_or_cost_pays_nothing(x):
    engine,source,cards,target=board(1,2)
    with pytest.raises(ValueError):activate(engine,source,cards,target,x)
    assert all(obj.zone==Zone.BATTLEFIELD for obj in cards) and not source.tapped
    assert engine.state.players[0].mana_pool.total()==3


def test_foundry_cannot_exile_itself_as_other_artifact():
    engine,source,cards,target=board()
    with pytest.raises(ValueError):activate(engine,source,[source],target,source.mana_value)
    assert source.zone==Zone.BATTLEFIELD and not source.tapped


def test_zero_requires_at_least_one_real_zero_value_artifact():
    engine,source,cards,target=board(0)
    target.card.converted_mana_cost=0
    with pytest.raises(ValueError):activate(engine,source,[],target,0)
    activate(engine,source,cards,target,0)
    engine.resolve_until_stable()
    assert cards[0].zone==Zone.EXILE and target.zone==Zone.BATTLEFIELD


def test_automatic_cost_finds_subset_with_exact_total():
    engine,source,cards,target=board(2,2,1)
    activate(engine,source,None,target,3)
    assert cards[0].zone==cards[2].zone==Zone.EXILE and cards[1].zone==Zone.BATTLEFIELD


def test_opponents_artifacts_cannot_pay():
    engine,source,cards,target=board(3)
    cards[0].controller_id='p2'
    with pytest.raises(ValueError):activate(engine,source,cards,target,3)
    assert not source.tapped


def test_countering_keeps_artifacts_exiled_and_does_not_return_target():
    engine,source,cards,target=board(3)
    activate(engine,source,cards,target,3)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert cards[0].zone==Zone.EXILE and target.zone==Zone.GRAVEYARD


def test_offer_uses_reachable_sums_and_target_union():
    engine,source,cards,target=board(1,2)
    action=next(a for a in engine.legal_actions(engine.state.players[0])
                if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert action['allowed_x']==[1,2,3]
    assert {o['instance_id'] for o in action['exile_value_cost']['options']}=={obj.instance_id for obj in cards}
    assert action['targets'][0]['max_mana_value_from_x']
    assert target.instance_id in {o['instance_id'] for o in action['targets'][0]['options']}


def test_instant_speed_activation_is_rejected():
    engine,source,cards,target=board(3)
    engine.state.current_phase='combat'
    engine.state.current_step='declare_attackers'
    with pytest.raises(ValueError):activate(engine,source,cards,target,3)
    assert not source.tapped


def test_target_cannot_exceed_paid_sum():
    engine,source,cards,target=board(2)
    with pytest.raises(ValueError):activate(engine,source,cards,target,2)
    assert cards[0].zone==Zone.BATTLEFIELD


def test_duplicate_cost_object_is_not_counted_twice():
    engine,source,cards,target=board(2)
    with pytest.raises(ValueError):activate(engine,source,[cards[0],cards[0]],target,4)
    assert not source.tapped


def test_zero_cost_artifact_may_be_included_with_positive_costs():
    engine,source,cards,target=board(0,3)
    activate(engine,source,cards,target,3)
    engine.resolve_until_stable()
    assert all(obj.zone==Zone.EXILE for obj in cards) and target.zone==Zone.BATTLEFIELD


def test_mana_is_restricted_to_artifacts():
    engine,source,cards,target=board()
    player=engine.state.players[0]
    player.mana_pool.empty()
    engine.tap_for_mana(player,source)
    other=filler(engine,'Nonartifact spell',type_line='Sorcery',mv=1,mana_cost_string='{W}',zone=Zone.HAND)
    with pytest.raises(ValueError):engine.cast_spell(player,other)
    artifact=filler(engine,'Artifact spell',type_line='Artifact',mv=1,mana_cost_string='{W}',zone=Zone.HAND)
    engine.cast_spell(player,artifact)
    engine.resolve_until_stable()
    assert artifact.zone==Zone.BATTLEFIELD


def test_pending_return_keeps_x_after_source_departure_and_clone():
    from mtg_analyzer.game.game_engine import GameEngine
    engine,source,cards,target=board(1,2)
    activate(engine,source,cards,target,3)
    engine.rules.exile(source)
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    assert restored.state.find_object(target.instance_id).zone==Zone.BATTLEFIELD
    assert target.zone==Zone.GRAVEYARD


def test_mana_pays_only_abilities_of_artifact_sources():
    from mtg_analyzer.game.effects.core import ActivatedAbility
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.costs import parse_activation_cost
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    engine,source,cards,target=board()
    player=engine.state.players[0]
    player.mana_pool.empty()
    engine.tap_for_mana(player,source)
    for kind in ('Creature','Artifact'):
        obj=filler(engine,kind,type_line=kind,**({'power':2,'toughness':2} if kind=='Creature' else {}))
        obj.activated_abilities.append(ActivatedAbility(
            build_effects([EffectSpec('draw',{'count':1})],obj),
            cost=parse_activation_cost({'mana':'{W}'}),source=obj))
        if kind=='Creature':
            with pytest.raises(ValueError):engine.activate_ability(player,obj,0)
        else:
            engine.activate_ability(player,obj,0)
            engine.resolve_until_stable()
    assert len(player.hand)==1


def test_target_may_be_cheaper_than_total_exiled_value():
    engine,source,cards,target=board(5)
    activate(engine,source,cards,target,5)
    engine.resolve_until_stable()
    assert target.zone==Zone.BATTLEFIELD


def test_opponents_graveyard_card_cannot_be_returned():
    engine,source,cards,target=board(3)
    foreign=filler(engine,'Foreign',type_line='Artifact',mv=3,player='p2',zone=Zone.GRAVEYARD)
    with pytest.raises(ValueError):activate(engine,source,cards,foreign,3)
    assert not source.tapped


def test_nonartifact_cannot_be_exiled_or_returned():
    engine,source,cards,target=board(3)
    nonartifact=filler(engine,'Not artifact',type_line='Creature',power=3,toughness=3,mv=3)
    with pytest.raises(ValueError):activate(engine,source,[nonartifact],target,3)
    wrong_target=filler(engine,'Wrong target',type_line='Creature',power=3,toughness=3,mv=3,zone=Zone.GRAVEYARD)
    with pytest.raises(ValueError):activate(engine,source,cards,wrong_target,3)
    assert not source.tapped and cards[0].zone==Zone.BATTLEFIELD


def test_specs_are_fresh():
    from mtg_analyzer.game.card_registry.core import specs_for
    engine,source,cards,target=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]


def test_actual_cast_then_recur_an_artifact():
    from tests.support.deck_batch import cast
    engine=game(players=3,library=30)
    source=card(engine,'Fabrication Foundry',zone=Zone.HAND)
    cast(engine,source)
    cost=filler(engine,'Cost',type_line='Artifact',mv=3)
    target=filler(engine,'Target',type_line='Artifact',mv=3,zone=Zone.GRAVEYARD)
    activate(engine,source,[cost],target,3)
    engine.resolve_until_stable()
    assert cost.zone==Zone.EXILE and target.zone==Zone.BATTLEFIELD


def test_no_mana_does_not_exile_or_tap_foundry():
    engine,source,cards,target=board(3)
    engine.state.players[0].mana_pool.empty()
    with pytest.raises(ValueError):activate(engine,source,cards,target,3)
    assert not source.tapped and cards[0].zone==Zone.BATTLEFIELD
