"""Leyline batches all matching targets of each spell/ability announcement."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.card_registry import opening_hand_battlefield_permission
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, cast, activate, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Leyline of Combustion')
    creatures=[filler(engine,f'Target {i}',power=2,toughness=5) for i in range(2)]
    return engine,source,creatures


def _bond(engine,targets,player='p2',resolve=True):
    spell=card(engine,'Common Bond',player=player,zone=Zone.HAND)
    p=engine.state.player_by_id(player)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,spell,targets=targets,target_groups=[[targets[0]],[targets[1]]])
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()
    return spell


def test_specs_fresh_bound_and_opening_hand_permission():
    engine,source,_=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert len(a)==1 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1
    assert opening_hand_battlefield_permission(source.card)


@pytest.mark.parametrize('same',[False,True])
def test_multiple_permanent_targets_or_repeated_target_trigger_once(same):
    engine,source,creatures=_board()
    _bond(engine,[creatures[0],creatures[0] if same else creatures[1]])
    assert [p.life for p in engine.state.players]==[20,18,20]


@pytest.mark.parametrize('target_kind',['player','creature','source'])
def test_opponent_spell_targeting_you_or_own_permanent(target_kind):
    engine,source,creatures=_board()
    target=engine.state.players[0] if target_kind=='player' else source if target_kind=='source' else creatures[0]
    name='Disenchant' if target_kind=='source' else 'Lightning Bolt'
    cast(engine,card(engine,name,player='p2',zone=Zone.HAND),targets=[target])
    assert engine.state.players[1].life==18


@pytest.mark.parametrize('own_spell',[False,True])
def test_nonqualifying_targets_or_caster_do_not_trigger(own_spell):
    engine,source,creatures=_board()
    target=creatures[0] if own_spell else filler(engine,player='p3',power=2,toughness=2)
    _bond(engine,[target,target],player='p1' if own_spell else 'p2')
    assert [p.life for p in engine.state.players]==[20]*3


def test_separate_spells_each_trigger_without_turn_limit():
    engine,source,creatures=_board()
    _bond(engine,creatures)
    _bond(engine,creatures)
    assert engine.state.players[1].life==16


def test_activated_ability_targeting_player_triggers():
    engine,source,creatures=_board()
    pinger=card(engine,'Prodigal Pyromancer',player='p2')
    activate(engine,pinger,targets=[engine.state.players[0]],player='p2')
    assert [p.life for p in engine.state.players]==[19,18,20]


@pytest.mark.parametrize('change',['counter','source_leaves','source_stolen','target_leaves','clone'])
def test_trigger_survives_changes_after_target_announcement(change):
    engine,source,creatures=_board()
    spell=_bond(engine,creatures,resolve=False)
    if change=='counter':
        engine.rules.counter_spell(spell)
    elif change=='source_leaves':
        engine.rules.exile(source)
    elif change=='source_stolen':
        source.controller_id='p3'
    elif change=='target_leaves':
        engine.rules.exile(creatures[0])
        engine.rules.exile(creatures[1])
    else:
        engine=GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    assert [p.life for p in engine.state.players]==[20,18,20]


def test_spell_copy_has_its_own_target_announcement():
    engine,source,creatures=_board()
    _bond(engine,creatures,resolve=False)
    original=next(i for i in engine.state.stack if i.kind=='spell')
    engine.rules.copy_spell(original,'p2')
    engine.resolve_until_stable()
    assert engine.state.players[1].life==16


def test_each_leyline_triggers_independently():
    engine,source,creatures=_board()
    card(engine,'Leyline of Combustion')
    _bond(engine,creatures)
    assert engine.state.players[1].life==16


def test_player_and_permanent_targeted_together_trigger_once():
    engine,source,creatures=_board()
    spell=card(engine,'Electrolyze',player='p2',zone=Zone.HAND)
    cast(engine,spell,targets=[engine.state.players[0],creatures[0]],damage_divisions={'0':[1,1]})
    assert [p.life for p in engine.state.players]==[19,18,20]


def test_targeting_own_graveyard_card_is_not_targeting_a_permanent():
    engine,source,creatures=_board()
    target=card(engine,'Grizzly Bears',zone=Zone.GRAVEYARD)
    ooze=card(engine,'Scavenging Ooze',player='p2')
    engine.state.players[1].mana_pool.add_many({'G':1})
    activate(engine,ooze,targets=[target],player='p2')
    assert engine.state.players[1].life==21
    assert target.zone==Zone.EXILE


@pytest.mark.parametrize('accept',[True,False])
def test_opening_hand_permission_places_leyline_without_mana(accept):
    engine=game()
    source=card(engine,'Leyline of Combustion',zone=Zone.HAND)
    player=engine.state.players[0]
    engine.rules.offer_opening_hand_battlefield_choice(player,source)
    assert engine.state.pending_choice['kind']=='opening_hand_battlefield'
    engine=GameEngine(engine.state.clone())
    source=engine.state.find_object(source.instance_id)
    engine.resolve_pending_choice('battlefield' if accept else 'decline')
    assert source.zone==(Zone.BATTLEFIELD if accept else Zone.HAND)
    assert engine.state.players[0].mana_pool.total()==0
