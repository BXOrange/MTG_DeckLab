"""Giant Shark: damaged opposing creatures, per-blocker triggers and Island state."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=2,library=20)
    advance_to(engine,'main1')
    island=card(engine,'Island')
    card(engine,'Island',player='p2')
    shark=card(engine,'Giant Shark')
    return engine,shark,island


def _opposing(engine,name='Opponent',damaged=True):
    obj=filler(engine,name,player='p2',power=1,toughness=8)
    if damaged:
        engine.rules.deal_damage(obj,1)
    return obj


def _attack_and_block(engine,shark,blockers,resolve=True):
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[0],[{'attacker':shark,'defender':engine.state.players[1]}])
    advance_to(engine,'declare_blockers')
    engine.declare_blockers(engine.state.players[1],[(b,shark) for b in blockers])
    if resolve:
        engine.resolve_until_stable()
        engine.recompute_continuous_effects()


def test_fresh_specs_and_bound_abilities():
    engine,shark,island=_board()
    a,b=specs_for(shark.card),specs_for(shark.card)
    assert len(a)==4 and a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(shark.triggered_abilities)==3


@pytest.mark.parametrize('damaged',[False,True])
def test_blocked_by_damaged_creature(damaged):
    engine,shark,island=_board()
    blocker=_opposing(engine,damaged=damaged)
    _attack_and_block(engine,shark,[blocker])
    assert shark.power==(6 if damaged else 4)
    assert combat.has(shark,'trample')==damaged


@pytest.mark.parametrize('damage_flags',[(True,True),(True,False),(False,False)])
def test_one_trigger_per_damaged_blocker(damage_flags):
    engine,shark,island=_board()
    blockers=[_opposing(engine,f'Blocker {i}',d) for i,d in enumerate(damage_flags)]
    _attack_and_block(engine,shark,blockers)
    assert shark.power==4+2*sum(damage_flags)


@pytest.mark.parametrize('damaged',[False,True])
def test_shark_blocking_a_damaged_attacker(damaged):
    engine,shark,island=_board()
    attacker=_opposing(engine,damaged=damaged)
    engine.state.active_player_index=1
    advance_to(engine,'declare_attackers')
    engine.declare_attackers(engine.state.players[1],[{'attacker':attacker,'defender':engine.state.players[0]}])
    advance_to(engine,'declare_blockers')
    engine.declare_blockers(engine.state.players[0],[(shark,attacker)])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert shark.power==(6 if damaged else 4)


@pytest.mark.parametrize('change',['removed_damage','new_visit','clone','source_leaves'])
def test_damage_history_and_pending_trigger_visits(change):
    engine,shark,island=_board()
    blocker=_opposing(engine)
    if change=='removed_damage':
        blocker.damage_marked=0
    if change=='new_visit':
        engine.rules.exile(blocker)
        engine.rules.return_from_graveyard(blocker,'battlefield')
    _attack_and_block(engine,shark,[blocker],resolve=False)
    engine.rules.put_triggers_on_stack()
    if change=='clone':
        engine=GameEngine(engine.state.clone())
        shark=engine.state.find_object(shark.instance_id)
    elif change=='source_leaves':
        engine.rules.exile(shark)
        engine.rules.return_from_graveyard(shark,'battlefield')
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert shark.power==(4 if change in ('new_visit','source_leaves') else 6)


@pytest.mark.parametrize('change',['island_leaves','island_stolen','shark_stolen','no_island_on_entry'])
def test_state_trigger_when_controller_has_no_islands(change):
    engine,shark,island=_board()
    if change=='island_leaves':
        engine.rules.exile(island)
    elif change=='island_stolen':
        island.controller_id='p2'
    elif change=='shark_stolen':
        # Remove the new controller's Island before the transfer.
        for obj in list(engine.state.battlefield):
            if obj.name=='Island' and obj.controller_id=='p2':
                engine.rules.exile(obj)
        shark.controller_id='p2'
    else:
        engine.rules.exile(island)
        shark=card(engine,'Giant Shark')
    engine.resolve_until_stable()
    assert shark.zone==Zone.GRAVEYARD


def test_no_island_defender_cannot_be_attacked():
    engine,shark,island=_board()
    for obj in list(engine.state.battlefield):
        if obj.name=='Island' and obj.controller_id=='p2':
            engine.rules.exile(obj)
    advance_to(engine,'declare_attackers')
    with pytest.raises(ValueError):
        engine.declare_attackers(engine.state.players[0],[{'attacker':shark,'defender':engine.state.players[1]}])


def test_pump_and_trample_change_real_combat_damage_then_expire():
    engine,shark,island=_board()
    blocker=filler(engine,'Small blocker',player='p2',power=1,toughness=2)
    engine.rules.deal_damage(blocker,1)
    _attack_and_block(engine,shark,[blocker])
    advance_to(engine,'main2')
    assert engine.state.players[1].life==15
    assert blocker.zone==Zone.GRAVEYARD
    advance_to(engine,'cleanup')
    engine.advance_step()
    engine.recompute_continuous_effects()
    assert shark.power==4 and not combat.has(shark,'trample')


def test_prior_turn_damage_does_not_qualify():
    engine,shark,island=_board()
    blocker=_opposing(engine)
    engine.begin_turn()
    engine.begin_turn()
    advance_to(engine,'main1')
    _attack_and_block(engine,shark,[blocker])
    assert shark.power==4 and not combat.has(shark,'trample')


def test_state_trigger_already_on_stack_still_sacrifices_after_island_returns():
    engine,shark,island=_board()
    engine.rules.exile(island)
    engine.rules.check_state_based_actions()
    engine.rules.put_triggers_on_stack()
    card(engine,'Island')
    engine.resolve_until_stable()
    assert shark.zone==Zone.GRAVEYARD
