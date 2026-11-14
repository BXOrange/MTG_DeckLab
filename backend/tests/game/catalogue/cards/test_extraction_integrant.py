"""Extraction Integrant grants each artifact creature its own blocker trigger."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, attack
from tests.support.star_trek import advance_to


def board(copies=1):
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    sources=[card(engine,'Extraction Integrant') for _ in range(copies)]
    ally=filler(engine,'Artifact ally',type_line='Artifact Creature',power=4,toughness=4)
    vanilla=filler(engine,'Ordinary ally',power=4,toughness=4)
    blockers=[filler(engine,'Blocker '+str(i),player='p2',power=3,toughness=3) for i in range(4)]
    return engine,sources,ally,vanilla,blockers


def block(engine,assignments):
    engine.state.current_step='declare_blockers'
    engine.declare_blockers(engine.state.player_by_id('p2'),assignments)


def test_fresh_specs_and_correct_grant_recipients():
    engine,sources,ally,vanilla,blockers=board()
    a,b=specs_for(sources[0].card),specs_for(sources[0].card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    for obj in [sources[0],ally]:
        assert combat.has(obj,'menace') and len(obj.granted_triggered_abilities)==1
    assert not combat.has(vanilla,'menace') and not vanilla.granted_triggered_abilities
    assert not combat.has(blockers[0],'menace') and not blockers[0].granted_triggered_abilities


def test_each_blocker_gets_minus_one_without_a_target_choice():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert [(o.power,o.toughness) for o in blockers]==[(2,2),(2,2),(3,3),(3,3)]
    assert ally.power==4 and sources[0].power==1


def test_nonartifact_attacker_does_not_trigger_granted_ability():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[vanilla])
    block(engine,[(blockers[0],vanilla)])
    engine.resolve_until_stable()
    assert blockers[0].power==3 and blockers[0].toughness==3


def test_menace_rejects_only_one_blocker():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    with pytest.raises(ValueError):
        block(engine,[(blockers[0],ally)])
    assert blockers[0].power==3


def test_two_sources_grant_two_triggers_per_recipient():
    engine,sources,ally,vanilla,blockers=board(2)
    assert len(ally.granted_triggered_abilities)==2
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.resolve_until_stable()
    assert blockers[0].power==1 and blockers[1].toughness==1


def test_source_leaving_after_block_does_not_remove_stacked_triggers():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(sources[0])
    engine.resolve_until_stable()
    assert blockers[0].power==2 and blockers[1].power==2
    assert not combat.has(ally,'menace') and not ally.granted_triggered_abilities


def test_cloned_block_triggers_resolve_independently():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.rules.put_triggers_on_stack()
    clone=GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(blockers[0].instance_id).power==2
    assert blockers[0].power==3


def test_expiry_at_end_of_turn():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.resolve_until_stable()
    engine.rules.return_to_hand(ally)
    advance_to(engine,'cleanup')
    engine.recompute_continuous_effects()
    assert blockers[0].power==3 and blockers[1].toughness==3



def test_two_attackers_do_not_react_to_each_others_blockers():
    engine,sources,ally,vanilla,blockers=board()
    other=filler(engine,'Other artifact',type_line='Artifact Creature',power=4,toughness=4)
    attack(engine,[ally,other])
    block(engine,[(blockers[0],ally),(blockers[1],ally),(blockers[2],other),(blockers[3],other)])
    engine.resolve_until_stable()
    assert all(o.power==2 and o.toughness==2 for o in blockers)


def test_losing_artifact_type_removes_granted_abilities():
    engine,sources,ally,vanilla,blockers=board()
    ally.card.type_line='Creature'
    engine.recompute_continuous_effects()
    assert not combat.has(ally,'menace') and not ally.granted_triggered_abilities


def test_integrant_itself_has_the_granted_trigger():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[sources[0]])
    block(engine,[(blockers[0],sources[0]),(blockers[1],sources[0])])
    engine.resolve_until_stable()
    assert blockers[0].power==2 and blockers[1].power==2



def test_returned_blocker_is_a_new_object_for_the_pending_trigger():
    engine,sources,ally,vanilla,blockers=board()
    attack(engine,[ally])
    block(engine,[(blockers[0],ally),(blockers[1],ally)])
    engine.rules.put_triggers_on_stack()
    engine.rules.exile(blockers[0])
    engine.rules.return_from_graveyard(blockers[0],'battlefield')
    engine.resolve_until_stable()
    assert blockers[0].zone==Zone.BATTLEFIELD and blockers[0].power==3
    assert blockers[1].power==2
