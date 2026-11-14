"""Hatchling's death grants turn-long timing and per-cast ETB fight abilities."""
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def _board(die=True,controller='p1'):
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    hatch=card(engine,'Cherished Hatchling')
    hatch.controller_id=controller
    target=filler(engine,'Opponent',player='p2',power=1,toughness=10)
    if die:
        engine.rules.destroy(hatch)
        engine.resolve_until_stable()
    return engine,hatch,target


def _cast(engine,player='p1',name='Colossal Dreadmaw',resolve=True):
    obj=card(engine,name,player=player,zone=Zone.HAND)
    p=engine.state.player_by_id(player)
    p.mana_pool.add_many(RICH)
    engine.cast_spell(p,obj)
    if resolve:
        engine.resolve_until_stable()
    return obj


def _fight(engine,target,accept=True):
    for _ in range(12):
        choice=engine.state.pending_choice
        if choice is None:
            return
        options=choice['options']
        if not accept and any(o['id'] in ('no','decline','skip') for o in options):
            pick=next(o['id'] for o in options if o['id'] in ('no','decline','skip'))
        else:
            selected=next((o for o in options if o.get('instance_id')==target.instance_id),None)
            pick=selected['id'] if selected else options[0]['id']
        engine.resolve_pending_choice(pick)
        engine.resolve_until_stable()
    raise AssertionError('Unfinished fight')


def test_fresh_specs_binding_and_no_permission_before_death():
    engine,hatch,target=_board(False)
    a,b=specs_for(hatch.card),specs_for(hatch.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(hatch.triggered_abilities)==1
    engine.state.active_player_index=1
    obj=card(engine,'Colossal Dreadmaw',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,obj)


def test_all_own_dinosaurs_have_flash_for_the_turn_and_each_gets_fight():
    engine,hatch,target=_board()
    engine.state.active_player_index=1
    for _ in range(2):
        dino=_cast(engine)
        assert dino.zone==Zone.BATTLEFIELD and engine.state.pending_choice is not None
        _fight(engine,target)
        assert dino.damage_marked==1
    assert target.zone==Zone.GRAVEYARD  # Two six-power fights.


def test_flash_grant_does_not_extend_to_other_creatures_or_opponents():
    engine,hatch,target=_board()
    engine.state.active_player_index=2
    for player,name in [('p1','Grizzly Bears'),('p2','Colossal Dreadmaw')]:
        obj=card(engine,name,player=player,zone=Zone.HAND)
        p=engine.state.player_by_id(player)
        p.mana_pool.add_many(RICH)
        assert not engine.can_cast(p,obj)


def test_declining_fight_leaves_both_creatures_undamaged():
    engine,hatch,target=_board()
    dino=_cast(engine)
    _fight(engine,target,False)
    assert dino.damage_marked==target.damage_marked==0


def test_noncast_dinosaur_does_not_receive_etb_fight():
    engine,hatch,target=_board()
    dino=card(engine,'Colossal Dreadmaw',zone=Zone.GRAVEYARD)
    engine.rules.return_from_graveyard(dino,'battlefield')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and target.damage_marked==0


def test_reentered_dinosaur_does_not_keep_cast_granted_ability():
    engine,hatch,target=_board()
    dino=_cast(engine)
    _fight(engine,target,False)
    engine.rules.exile(dino)
    engine.rules.return_from_graveyard(dino,'battlefield')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_countering_cast_grant_prevents_fight_but_not_creature_resolution():
    engine,hatch,target=_board()
    dino=_cast(engine,resolve=False)
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack)==2
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert dino.zone==Zone.BATTLEFIELD and engine.state.pending_choice is None


def test_countering_creature_before_cast_trigger_does_not_grant_to_later_visit():
    engine,hatch,target=_board()
    dino=_cast(engine,resolve=False)
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(dino)
    engine.resolve_until_stable()
    engine.rules.return_from_graveyard(dino,'battlefield')
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_grants_belong_to_controller_of_dead_hatchling():
    engine,hatch,target=_board(controller='p2')
    engine.state.active_player_index=2
    dino=_cast(engine,player='p2')
    _fight(engine,target,False)
    assert dino.zone==Zone.BATTLEFIELD
    own=card(engine,'Colossal Dreadmaw',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,own)


def test_clone_preserves_pending_cast_grant():
    engine,hatch,target=_board()
    dino=_cast(engine,resolve=False)
    engine.rules.put_triggers_on_stack()
    engine=GameEngine(engine.state.clone())
    dino=engine.state.find_object(dino.instance_id)
    target=engine.state.find_object(target.instance_id)
    engine.resolve_until_stable()
    _fight(engine,target)
    assert target.damage_marked==6 and dino.damage_marked==1


def test_permissions_expire_at_cleanup():
    engine,hatch,target=_board()
    advance_to(engine,'untap')
    advance_to(engine,'main1')
    obj=card(engine,'Colossal Dreadmaw',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    assert not engine.can_cast(p,obj)


def test_multiple_hatchling_deaths_grant_separate_fight_triggers():
    engine,hatch,target=_board()
    other=card(engine,'Cherished Hatchling')
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    target.card.toughness=30
    dino=_cast(engine)
    _fight(engine,target)
    assert target.damage_marked==12 and dino.damage_marked==2


def test_cast_granted_ability_uses_creatures_controller_on_entry():
    engine,hatch,target=_board()
    dino=_cast(engine,resolve=False)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()  # The cast trigger grants the ETB.
    item=next(i for i in engine.state.stack if i.obj is dino)
    item.controller_id=dino.controller_id='p2'
    engine.resolve_until_stable()
    choice=engine.state.pending_choice
    assert choice is not None and choice['player_id']=='p2'
    _fight(engine,target,False)
    assert dino.zone==Zone.BATTLEFIELD


def test_countering_death_trigger_grants_neither_timing_nor_cast_trigger():
    engine,hatch,target=_board(False)
    engine.rules.destroy(hatch)
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert not engine.state.next_spell_flash_grants
    assert not engine.state.turn_scoped_triggers


def test_fight_can_choose_another_own_creature():
    engine,hatch,target=_board()
    own=filler(engine,'Own fighter',power=1,toughness=10)
    dino=_cast(engine)
    _fight(engine,own)
    assert own.damage_marked==6 and dino.damage_marked==1 and target.damage_marked==0
