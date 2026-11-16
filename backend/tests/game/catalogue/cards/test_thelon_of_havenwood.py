"""Thelon's affected-object spore anthem and any-graveyard Fungus cost."""
import pytest
from mtg_analyzer.game import continuous
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board():
    engine=game(players=3,library=30)
    source=card(engine,'Thelon of Havenwood')
    engine.state.players[0].mana_pool.add_many({'B':1,'G':1})
    return engine,source


def fungus(engine,name='Fungus',player='p1',zone=Zone.BATTLEFIELD,creature=True):
    return filler(engine,name,player=player,zone=zone,
        type_line='Creature — Fungus' if creature else 'Kindred Artifact — Fungus',
        **({'power':2,'toughness':3} if creature else {}))


def activate(engine,source,cost):
    engine.activate_ability(engine.state.players[0],source,0,hand_card_choices=[cost.instance_id])


def test_fresh_specs_and_binding():
    engine,source=board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.static_effects)==len(source.activated_abilities)==1


def test_each_creature_reads_its_own_spore_count_across_controllers():
    engine,source=board()
    a=fungus(engine,'First');b=fungus(engine,'Second',player='p2')
    a.add_counters('spore',2);b.add_counters('spore',4)
    a.add_counters('charge',9)
    engine.recompute_continuous_effects()
    assert (a.power,a.toughness)==(4,5) and (b.power,b.toughness)==(6,7)
    assert (source.power,source.toughness)==(2,2)


def test_other_subtype_with_spores_does_not_get_bonus():
    engine,source=board()
    obj=filler(engine,'Other',type_line='Creature — Elf',power=2,toughness=3)
    obj.add_counters('spore',5)
    engine.recompute_continuous_effects()
    assert (obj.power,obj.toughness)==(2,3)


def test_any_graveyard_card_is_paid_before_all_fungi_get_counters():
    engine,source=board()
    cost=fungus(engine,'Cost',player='p2',zone=Zone.GRAVEYARD)
    a=fungus(engine,'Ours');b=fungus(engine,'Theirs',player='p2')
    noncreature=fungus(engine,'Kindred',player='p3',creature=False)
    activate(engine,source,cost)
    assert cost.zone==Zone.EXILE and cost in engine.state.players[1].exile
    assert not a.counters.get('spore')
    engine.resolve_until_stable()
    assert all(obj.counters.get('spore')==1 for obj in (a,b,noncreature))
    assert (a.power,a.toughness)==(3,4)
    assert not noncreature.is_creature


def test_noncreature_fungus_card_can_pay_cost():
    engine,source=board()
    cost=fungus(engine,'Kindred cost',zone=Zone.GRAVEYARD,creature=False)
    activate(engine,source,cost)
    assert cost.zone==Zone.EXILE


def test_wrong_graveyard_type_pays_nothing():
    engine,source=board()
    cost=filler(engine,'Wrong',type_line='Creature — Elf',power=2,toughness=2,zone=Zone.GRAVEYARD)
    with pytest.raises(ValueError):activate(engine,source,cost)
    assert engine.state.players[0].mana_pool.total()==2 and cost.zone==Zone.GRAVEYARD


def test_countering_does_not_refund_cost_or_add_spores():
    engine,source=board()
    cost=fungus(engine,'Cost',zone=Zone.GRAVEYARD);obj=fungus(engine)
    activate(engine,source,cost)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert cost.zone==Zone.EXILE and not obj.counters.get('spore')


def test_source_departure_ends_anthem_but_not_pending_counter_placement():
    engine,source=board()
    cost=fungus(engine,'Cost',zone=Zone.GRAVEYARD);obj=fungus(engine)
    activate(engine,source,cost)
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert obj.counters.get('spore')==1 and (obj.power,obj.toughness)==(2,3)


def test_pending_activation_and_anthem_survive_clone():
    engine,source=board()
    cost=fungus(engine,'Cost',zone=Zone.GRAVEYARD);obj=fungus(engine)
    activate(engine,source,cost)
    restored=GameEngine(engine.state.clone())
    restored.resolve_until_stable()
    copied=restored.state.find_object(obj.instance_id)
    assert copied.counters.get('spore')==1 and (copied.power,copied.toughness)==(3,4)
    assert not obj.counters.get('spore')


def test_changeling_is_a_fungus_for_cost_and_battlefield_effects():
    engine,source=board()
    cost=filler(engine,'Changeling cost',type_line='Creature — Shapeshifter',power=1,toughness=1,
                keywords=['Changeling'],zone=Zone.GRAVEYARD)
    obj=filler(engine,'Changeling permanent',type_line='Creature — Shapeshifter',power=1,toughness=1,keywords=['Changeling'])
    assert continuous.has_subtype(obj,'Fungus')
    activate(engine,source,cost)
    engine.resolve_until_stable()
    assert obj.counters.get('spore')==1 and (obj.power,obj.toughness)==(2,2)


def test_tapped_summoning_sick_source_can_activate():
    engine,source=board()
    source.tapped=source.summoning_sick=True
    cost=fungus(engine,'Cost',zone=Zone.GRAVEYARD)
    activate(engine,source,cost)
    engine.resolve_until_stable()
    assert cost.zone==Zone.EXILE


def test_no_fungus_in_any_graveyard_means_no_offer():
    engine,source=board()
    assert not any(a['type']=='activate_ability' and a['instance_id']==source.instance_id for a in engine.legal_actions(engine.state.players[0]))


def test_opponents_graveyard_cost_is_an_untargeted_pick():
    engine,source=board()
    cost=fungus(engine,'Cost',player='p2',zone=Zone.GRAVEYARD)
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert not action.get('requires_target')
    assert action['graveyard_exile_cost']['options'][0]['owner_id']=='p2'


def test_actual_cast_then_activate():
    engine=game(library=30)
    source=card(engine,'Thelon of Havenwood',zone=Zone.HAND)
    cast(engine,source)
    cost=fungus(engine,'Cost',zone=Zone.GRAVEYARD)
    obj=fungus(engine)
    activate(engine,source,cost)
    engine.resolve_until_stable()
    assert obj.counters.get('spore')==1


def test_multiple_thelons_each_contribute_a_per_counter_bonus():
    engine,source=board()
    second=card(engine,'Thelon of Havenwood',player='p2')
    obj=fungus(engine)
    obj.add_counters('spore',3)
    engine.recompute_continuous_effects()
    assert (obj.power,obj.toughness)==(8,9)
    engine.rules.exile(second)
    engine.recompute_continuous_effects()
    assert (obj.power,obj.toughness)==(5,6)


def test_insufficient_mana_does_not_exile_card():
    engine,source=board()
    cost=fungus(engine,'Cost',player='p2',zone=Zone.GRAVEYARD)
    engine.state.players[0].mana_pool.empty()
    with pytest.raises(ValueError):activate(engine,source,cost)
    assert cost.zone==Zone.GRAVEYARD


def test_removing_spore_counters_updates_bonus():
    engine,source=board()
    obj=fungus(engine)
    obj.add_counters('spore',3)
    engine.recompute_continuous_effects()
    assert obj.power==5
    engine.rules.add_counters(obj,-2,'spore')
    engine.recompute_continuous_effects()
    assert obj.power==3
