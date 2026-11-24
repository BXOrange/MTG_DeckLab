"""Danitha's two qualifying cast forms share a single per-turn limit."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, cast, game, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    source=card(engine,'Danitha, Sword of Hope')
    return engine,source


def _equipment(engine):
    spell=card(engine,'Swiftfoot Boots',zone=Zone.HAND)
    cast(engine,spell)
    return spell


def _targeted(engine,target,player='p1',resolve=True):
    spell=card(engine,'Defiant Strike',player=player,zone=Zone.HAND)
    if resolve:
        cast(engine,spell,targets=[target])
    else:
        owner=engine.state.player_by_id(player)
        owner.mana_pool.add_many(RICH)
        engine.cast_spell(owner,spell,targets=[target])
        engine.rules.put_triggers_on_stack()
    return spell


def test_specs_are_fresh_and_first_strike_binds():
    engine,source=_board()
    a,b=specs_for(source.card),specs_for(source.card)
    assert len(a)==2 and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.triggered_abilities)==1 and source.triggered_abilities[0].once_per_turn
    assert combat.has(source,'first_strike')


def test_equipment_without_targets_draws():
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    _equipment(engine)
    assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('self_target',[False,True])
def test_spell_targeting_owned_creature_draws_once(self_target):
    engine,source=_board()
    target=source if self_target else filler(engine,power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    _targeted(engine,target)
    # One from Danitha and one from Defiant Strike itself.
    assert len(engine.state.players[0].hand)==before+2


@pytest.mark.parametrize('order',['equipment_first','target_first'])
def test_both_forms_share_once_each_turn_limit(order):
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    if order=='equipment_first':
        _equipment(engine)
        _targeted(engine,source)
    else:
        _targeted(engine,source)
        _equipment(engine)
    assert len(engine.state.players[0].hand)==before+2


@pytest.mark.parametrize('kind',['Artifact','Enchantment','Creature'])
def test_nonqualifying_spell_does_not_spend_limit(kind):
    engine,source=_board()
    spell=filler(engine,'Other',type_line=kind,zone=Zone.HAND,
        power=2 if kind=='Creature' else None,toughness=2 if kind=='Creature' else None)
    before=len(engine.state.players[0].hand)-1
    cast(engine,spell)
    assert len(engine.state.players[0].hand)==before
    _equipment(engine)
    assert len(engine.state.players[0].hand)==before+1


def test_targeting_opponents_creature_does_not_spend_limit():
    engine,source=_board()
    target=filler(engine,player='p2',power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    _targeted(engine,target)
    assert len(engine.state.players[0].hand)==before+1
    _equipment(engine)
    assert len(engine.state.players[0].hand)==before+2


def test_opponents_spell_targeting_own_creature_does_not_trigger():
    engine,source=_board()
    before=len(engine.state.players[0].hand)
    _targeted(engine,source,player='p2')
    assert len(engine.state.players[0].hand)==before


@pytest.mark.parametrize('change',['counter_spell','source_leaves','target_leaves','source_stolen','clone'])
def test_qualifying_cast_trigger_survives_later_changes(change):
    engine,source=_board()
    target=filler(engine,power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    spell=_targeted(engine,target,resolve=False)
    if change=='counter_spell':
        engine.rules.counter_spell(spell)
    elif change=='source_leaves':
        engine.rules.exile(source)
    elif change=='target_leaves':
        engine.rules.exile(target)
    elif change=='source_stolen':
        source.controller_id='p3'
    else:
        engine=GameEngine(engine.state.clone())
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==before+(1 if change in ('counter_spell','target_leaves') else 2)


def test_limit_resets_on_next_players_turn_and_clone_keeps_spent_limit():
    engine,source=_board()
    _equipment(engine)
    engine=GameEngine(engine.state.clone())
    source=engine.state.find_object(source.instance_id)
    before=len(engine.state.players[0].hand)
    _targeted(engine,source)
    assert len(engine.state.players[0].hand)==before+1
    engine.begin_turn()
    advance_to(engine,'main1')
    before=len(engine.state.players[0].hand)
    _targeted(engine,source)
    assert len(engine.state.players[0].hand)==before+2


def test_multiple_own_creature_targets_still_draw_once():
    engine,source=_board()
    other=filler(engine,power=2,toughness=2)
    before=len(engine.state.players[0].hand)
    spell=card(engine,'Common Bond',zone=Zone.HAND)
    cast(engine,spell,targets=[source,other],groups=[[source],[other]])
    assert len(engine.state.players[0].hand)==before+1
    assert source.counters.get('+1/+1')==1 and other.counters.get('+1/+1')==1


def test_separate_danithas_each_trigger_once():
    engine,source=_board()
    engine.rules.copy_permanent('p1',source,not_legendary=True)
    before=len(engine.state.players[0].hand)
    _equipment(engine)
    assert len(engine.state.players[0].hand)==before+2
    _targeted(engine,source)
    assert len(engine.state.players[0].hand)==before+3
