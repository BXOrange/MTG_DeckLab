"""Those Old Scientists executes all Saga chapters with real graveyard targets."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, RICH
from tests.support.star_trek import advance_to


def board():
    engine=game(players=3,library=30); advance_to(engine,'main1')
    saga=card(engine,'Those Old Scientists',zone=Zone.HAND)
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,saga,player


def start(engine,saga,player):
    engine.cast_spell(player,saga); engine.resolve_until_stable()
    for _ in range(8):
        if engine.state.pending_choice is None:
            return
        choice=engine.state.pending_choice
        engine.resolve_pending_choice(str(choice['options'][0]['id']))
    raise AssertionError('discard choices did not finish')


def next_chapter(engine,saga):
    engine.rules.add_counters(saga,1,'lore'); engine.resolve_until_stable()


def pick(engine,obj):
    option=next(o for o in engine.state.pending_choice['options'] if o.get('instance_id')==obj.instance_id)
    engine.resolve_pending_choice(str(option['id']))


def third(engine,saga,player):
    start(engine,saga,player); next_chapter(engine,saga)
    if engine.state.pending_choice:
        engine.resolve_pending_choice('decline')
    next_chapter(engine,saga)


def test_fresh_specs_and_binding():
    engine,saga,player=board()
    a,b=specs_for(saga.card),specs_for(saga.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(saga.triggered_abilities)==3


def test_first_chapter_draws_two_then_discards_two():
    engine,saga,player=board()
    before_hand,before_library=len(player.hand),len(player.library)
    start(engine,saga,player)
    assert len(player.hand)==before_hand-1
    assert len(player.library)==before_library-2 and len(player.graveyard)==2
    assert saga.counters.get('lore')==1


@pytest.mark.parametrize('name',['Sol Ring','Lightning Bolt','Divination'])
def test_second_chapter_returns_artifact_instant_or_sorcery(name):
    engine,saga,player=board(); start(engine,saga,player)
    obj=card(engine,name,zone=Zone.GRAVEYARD)
    next_chapter(engine,saga); pick(engine,obj)
    assert obj.zone==Zone.HAND


def test_second_chapter_excludes_creatures_lands_and_other_graveyards():
    engine,saga,player=board(); start(engine,saga,player)
    bad=[card(engine,'Serra Angel',zone=Zone.GRAVEYARD),card(engine,'Forest',zone=Zone.GRAVEYARD),
         card(engine,'Sol Ring',player='p2',zone=Zone.GRAVEYARD)]
    good=card(engine,'Sol Ring',zone=Zone.GRAVEYARD)
    next_chapter(engine,saga)
    offered={o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert good.instance_id in offered and not any(o.instance_id in offered for o in bad)
    engine.resolve_pending_choice('decline')
    assert good.zone==Zone.GRAVEYARD


@pytest.mark.parametrize('owners',[('p1','p1'),('p1','p2'),('p2','p3')])
def test_third_chapter_moves_two_cards_to_owners_libraries(owners):
    engine,saga,player=board()
    objs=[card(engine,'Serra Angel',player=owner,zone=Zone.GRAVEYARD) for owner in owners]
    third(engine,saga,player)
    pick(engine,objs[0]); pick(engine,objs[1])
    assert saga.zone==Zone.GRAVEYARD
    for obj in objs:
        assert obj.zone==Zone.LIBRARY and obj in engine.state.player_by_id(obj.owner_id).library


def test_third_chapter_can_choose_no_cards():
    engine,saga,player=board()
    third(engine,saga,player)
    engine.resolve_pending_choice('stop')
    assert saga.zone==Zone.GRAVEYARD


def test_third_chapter_can_choose_only_one_card():
    engine,saga,player=board()
    obj=card(engine,'Serra Angel',player='p2',zone=Zone.GRAVEYARD)
    third(engine,saga,player); pick(engine,obj)
    if engine.state.pending_choice:
        engine.resolve_pending_choice('stop')
    assert obj.zone==Zone.LIBRARY and saga.zone==Zone.GRAVEYARD



def test_third_chapter_shuffles_each_owner_only_once(monkeypatch):
    engine,saga,player=board()
    objs=[card(engine,'Serra Angel',player='p2',zone=Zone.GRAVEYARD) for _ in range(2)]
    third(engine,saga,player)
    shuffled=[]
    original=engine.rules.shuffle_library
    def record(owner):
        shuffled.append(owner.id)
        return original(owner)
    monkeypatch.setattr(engine.rules,'shuffle_library',record)
    pick(engine,objs[0]); pick(engine,objs[1])
    assert shuffled==['p2']



def test_clone_preserves_first_of_two_graveyard_targets():
    from mtg_analyzer.game.game_engine import GameEngine
    engine,saga,player=board()
    objs=[card(engine,'Serra Angel',player=owner,zone=Zone.GRAVEYARD) for owner in ['p2','p3']]
    third(engine,saga,player); pick(engine,objs[0])
    clone=GameEngine(engine.state.clone())
    pick(clone,clone.state.find_object(objs[1].instance_id))
    assert all(clone.state.find_object(o.instance_id).zone==Zone.LIBRARY for o in objs)
    assert all(o.zone==Zone.GRAVEYARD for o in objs)


def test_illegal_one_of_two_targets_is_skipped_on_resolution():
    engine,saga,player=board()
    objs=[card(engine,'Serra Angel',player=owner,zone=Zone.GRAVEYARD) for owner in ['p2','p3']]
    third(engine,saga,player); pick(engine,objs[0])
    choice=engine.state.pending_choice
    option=next(o for o in choice['options'] if o.get('instance_id')==objs[1].instance_id)
    engine.rules.resolve_choice(str(option['id']))
    engine.rules.exile(objs[0]); engine.resolve_until_stable()
    assert objs[0].zone==Zone.EXILE and objs[1].zone==Zone.LIBRARY
