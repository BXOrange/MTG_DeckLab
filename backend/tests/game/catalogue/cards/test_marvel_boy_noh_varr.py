"""Marvel Boy distinguishes entries, power-up activations, and ability copies."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.cards.card import Card
from tests.support.deck_batch import card, filler, game, enter, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Marvel Boy, Noh-Varr')
    return engine,source


def _ability(engine,keyword='Power-up',player='p1'):
    text=(f'{keyword} — {{1}}: Draw a card. (Activate each {keyword.lower()} ability only once.)'
          if keyword else '{1}: Draw a card.')
    obj=filler(engine,'Ability source',type_line='Artifact',player=player,oracle_text=text)
    assert len(obj.activated_abilities)==1
    if keyword:
        assert obj.activated_abilities[0].keyword_label==keyword.lower()
    return obj


def _activate(engine,obj,resolve=True):
    player=engine.state.player_by_id(obj.controller_id)
    player.mana_pool.add_many(RICH)
    engine.activate_ability(player,obj,0)
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()


def test_fresh_specs_and_binding():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(source.triggered_abilities)==2


@pytest.mark.parametrize('kind',['own_creature','opponent_creature','artifact','self','token'])
def test_only_another_own_creature_entering_gives_counter(kind):
    engine,source=_board()
    if kind=='self':
        entrant=source
    elif kind=='token':
        engine.rules.create_token('p1',Card(id='soldier-token',name='Soldier',type_line='Creature — Soldier',is_creature=True,power=1,toughness=1))
        engine.resolve_until_stable()
        assert source.counters.get('+1/+1')==1
        return
    else:
        entrant=filler(engine,'Entrant',type_line='Artifact' if kind=='artifact' else 'Creature',
                       player='p2' if kind=='opponent_creature' else 'p1',
                       **({} if kind=='artifact' else {'power':2,'toughness':2}))
    enter(engine,entrant)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1',0)==int(kind=='own_creature')


@pytest.mark.parametrize('keyword',['Power-up','Exhaust',None])
@pytest.mark.parametrize('player',['p1','p2'])
def test_only_own_powerup_activation_triggers(keyword,player):
    engine,source=_board()
    obj=_ability(engine,keyword,player)
    _activate(engine,obj)
    assert source.counters.get('+1/+1',0)==int(keyword=='Power-up' and player=='p1')


def test_countering_powerup_ability_does_not_undo_activation_trigger():
    engine,source=_board()
    obj=_ability(engine)
    _activate(engine,obj,resolve=False)
    original=next(i for i in engine.state.stack if i.source is obj)
    engine.rules.counter_ability(original)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==1


@pytest.mark.parametrize('change',['clone','new_visit','source_leaves','control'])
def test_waiting_trigger_tracks_marvel_boys_exact_visit(change):
    engine,source=_board()
    obj=_ability(engine)
    _activate(engine,obj,resolve=False)
    if change=='clone':
        engine=GameEngine(engine.state.clone())
        source=engine.state.find_object(source.instance_id)
    elif change=='new_visit':
        engine.rules.exile(source)
        engine.rules.return_from_graveyard(source,'battlefield')
    elif change=='source_leaves':
        engine.rules.exile(source)
    else:
        source.controller_id='p2'
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1',0)==int(change in {'clone','control'})


def test_both_triggers_follow_current_controller():
    engine,source=_board()
    source.controller_id='p2'
    enter(engine,filler(engine,'Entrant',player='p2',power=1,toughness=1))
    engine.resolve_until_stable()
    _activate(engine,_ability(engine,player='p2'))
    assert source.counters.get('+1/+1')==2


def test_copying_powerup_ability_does_not_count_as_another_activation():
    engine,source=_board()
    obj=_ability(engine)
    _activate(engine,obj,resolve=False)
    original=next(i for i in engine.state.stack if i.source is obj)
    copied=engine.rules.copy_ability(original,'p1')
    assert copied is not None
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==1


def test_each_powerup_activation_has_its_own_trigger():
    engine,source=_board()
    _activate(engine,_ability(engine))
    _activate(engine,_ability(engine))
    assert source.counters.get('+1/+1')==2
