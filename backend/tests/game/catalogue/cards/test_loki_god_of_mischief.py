"""Loki draws only for own targeted abilities, once each turn."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, activate, filler, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    loki=card(engine,'Loki, God of Mischief')
    pinger=card(engine,'Prodigal Pyromancer')
    return engine,loki,pinger


def _ping(engine,pinger,target,resolve=True):
    player=engine.state.player_by_id(pinger.controller_id)
    engine.activate_ability(player,pinger,0,targets=[target])
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()


def test_specs_fresh_and_bound():
    engine,loki,pinger=_board()
    a,b=specs_for(loki.card),specs_for(loki.card)
    assert len(a)==1 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(loki.triggered_abilities)==1 and loki.triggered_abilities[0].once_per_turn


@pytest.mark.parametrize('kind',['self','own_creature','opponent_creature','own_player','opponent_player'])
def test_own_activated_ability_targeting_any_player_or_permanent_draws(kind):
    engine,loki,pinger=_board()
    targets={'self':loki,'own_creature':pinger,'own_player':engine.state.players[0],
        'opponent_player':engine.state.players[1]}
    targets['opponent_creature']=filler(engine,player='p2',power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    _ping(engine,pinger,targets[kind])
    assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('kind',['spell','opponent_ability','graveyard_card','untargeted'])
def test_nonqualifying_event_does_not_consume_limit(kind):
    engine,loki,pinger=_board()
    before=len(engine.state.players[0].hand)
    if kind=='spell':
        cast(engine,card(engine,'Lightning Bolt',zone=Zone.HAND),targets=[engine.state.players[1]])
    elif kind=='opponent_ability':
        other=card(engine,'Prodigal Pyromancer',player='p2')
        _ping(engine,other,engine.state.players[0])
    elif kind=='graveyard_card':
        ooze=card(engine,'Scavenging Ooze')
        target=card(engine,'Grizzly Bears',zone=Zone.GRAVEYARD)
        engine.state.players[0].mana_pool.add_many({'G':1})
        activate(engine,ooze,targets=[target])
    else:
        stone=card(engine,'Spear Spewer')
        activate(engine,stone)
    assert len(engine.state.players[0].hand)==before
    _ping(engine,pinger,engine.state.players[1])
    assert len(engine.state.players[0].hand)==before+1


def test_several_abilities_share_one_trigger_per_turn():
    engine,loki,pinger=_board()
    other=card(engine,'Prodigal Pyromancer')
    before=len(engine.state.players[0].hand)
    _ping(engine,pinger,engine.state.players[1])
    _ping(engine,other,engine.state.players[2])
    assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('change',['source_leaves','source_stolen','target_leaves','counter_ability','clone'])
def test_trigger_survives_changes_after_target_announcement(change):
    engine,loki,pinger=_board()
    target=filler(engine,player='p2',power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    _ping(engine,pinger,target,resolve=False)
    if change=='source_leaves':
        engine.rules.exile(loki)
    elif change=='source_stolen':
        loki.controller_id='p2'
    elif change=='target_leaves':
        engine.rules.exile(target)
    elif change=='counter_ability':
        original=next(i for i in engine.state.stack if i.source is pinger)
        engine.rules.counter_ability(original)
    else:
        engine=GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==before+1


def test_each_turn_limit_resets_and_clone_keeps_spent_state():
    engine,loki,pinger=_board()
    _ping(engine,pinger,engine.state.players[1])
    engine=GameEngine(engine.state.clone())
    other=card(engine,'Prodigal Pyromancer')
    before=len(engine.state.players[0].hand)
    _ping(engine,other,engine.state.players[1])
    assert len(engine.state.players[0].hand)==before
    engine.begin_turn()
    advance_to(engine,'main1')
    third=card(engine,'Prodigal Pyromancer')
    _ping(engine,third,engine.state.players[1])
    assert len(engine.state.players[0].hand)==before+1


def test_own_targeted_triggered_ability_draws():
    engine,loki,pinger=_board()
    target=filler(engine,'Victim',player='p2',power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    creature=card(engine,'Ravenous Chupacabra',zone=Zone.HAND)
    cast(engine,creature)
    choice=engine.state.pending_choice
    assert choice is not None
    option=next(o for o in choice['options'] if o.get('instance_id')==target.instance_id)
    engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()
    assert target.zone==Zone.GRAVEYARD
    assert len(engine.state.players[0].hand)==before+1


def test_ability_copy_controlled_by_you_can_trigger():
    engine,loki,pinger=_board()
    opponent_pinger=card(engine,'Prodigal Pyromancer',player='p2')
    before=len(engine.state.players[0].hand)
    _ping(engine,opponent_pinger,engine.state.players[2],resolve=False)
    original=next(i for i in engine.state.stack if i.source is opponent_pinger)
    engine.rules.copy_ability(original,'p1')
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==before+1
    assert engine.state.players[2].life==18


def test_ability_targeting_spell_does_not_trigger():
    engine,loki,pinger=_board()
    apprentice=card(engine,'Daring Apprentice')
    spell=card(engine,'Lightning Bolt',player='p2',zone=Zone.HAND)
    engine.state.players[1].mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.players[1],spell,targets=[engine.state.players[2]])
    before=len(engine.state.players[0].hand)
    activate(engine,apprentice,targets=[spell])
    assert len(engine.state.players[0].hand)==before
    _ping(engine,pinger,engine.state.players[1])
    assert len(engine.state.players[0].hand)==before+1
