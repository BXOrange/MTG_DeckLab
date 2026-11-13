"""Polukranos replaces its entry count and pays for prevention with counters."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, cast, activate
from tests.support.star_trek import advance_to


def _board(zone=Zone.HAND):
    engine=game(players=2,library=20)
    advance_to(engine,'main1')
    source=card(engine,'Polukranos, Unchained',zone=zone)
    return engine,source


def _normal():
    engine,source=_board()
    cast(engine,source,pool={'B':1,'G':1,'C':2})
    return engine,source


def _escape(engine,source):
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(6)]
    cast(engine,source,pool={'B':1,'G':1,'C':4},graveyard_exile_choices=[o.instance_id for o in fuel])
    assert all(o.zone==Zone.EXILE for o in fuel)


def test_specs_fresh_and_bound():
    engine,source=_normal()
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.replacement_effects)==1 and len(source.activated_abilities)==1


def test_normal_cast_enters_with_six_and_pays_four_mana():
    engine,source=_normal()
    assert source.zone==Zone.BATTLEFIELD and source.counters.get('+1/+1')==6
    assert source.power==6 and source.toughness==6
    assert engine.state.players[0].mana_pool.total()==0


def test_escape_enters_with_twelve_instead_of_six_or_eighteen():
    engine,source=_board(Zone.GRAVEYARD)
    _escape(engine,source)
    assert source.zone==Zone.BATTLEFIELD and source.counters.get('+1/+1')==12
    assert source.power==12 and engine.state.players[0].mana_pool.total()==0


def test_later_noncast_entry_uses_six_again():
    engine,source=_board(Zone.GRAVEYARD)
    _escape(engine,source)
    engine.rules.exile(source)
    engine.rules.return_from_graveyard(source,'battlefield')
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==6


@pytest.mark.parametrize('damage,remaining',[(0,6),(1,5),(3,3),(6,0),(20,0)])
def test_prevents_all_damage_and_removes_only_available_counters(damage,remaining):
    engine,source=_normal()
    engine.rules.deal_damage(source,damage)
    engine.resolve_until_stable()
    if remaining:
        assert source.zone==Zone.BATTLEFIELD and source.counters.get('+1/+1')==remaining
        assert source.damage_marked==0
    else:
        assert source.zone==Zone.GRAVEYARD


def test_fight_uses_pre_damage_power_and_prevents_return_damage():
    engine,source=_normal()
    target=filler(engine,'Opponent',player='p2',power=2,toughness=6)
    engine.state.players[0].mana_pool.add_many({'B':1,'G':1,'C':1})
    activate(engine,source,targets=[target])
    assert target.zone==Zone.GRAVEYARD
    assert source.counters.get('+1/+1')==4 and source.damage_marked==0
    assert engine.state.players[0].mana_pool.total()==0


def test_cannot_fight_itself():
    engine,source=_normal()
    engine.state.players[0].mana_pool.add_many({'B':1,'G':1,'C':1})
    with pytest.raises(ValueError):
        activate(engine,source,targets=[source])
    assert source.counters.get('+1/+1')==6


@pytest.mark.parametrize('damage',[2,3])
def test_unpreventable_damage_still_removes_counters(damage):
    engine,source=_normal()
    engine.rules.disable_damage_prevention_this_turn()
    engine.rules.deal_damage(source,damage)
    engine.resolve_until_stable()
    if damage==2:
        assert source.zone==Zone.BATTLEFIELD and source.counters.get('+1/+1')==4
        assert source.damage_marked==2
    else:
        assert source.zone==Zone.GRAVEYARD


def test_no_counters_means_no_prevention():
    engine,source=_normal()
    card(engine,'Glorious Anthem')
    source.counters.clear()
    engine.recompute_continuous_effects()
    engine.rules.deal_damage(source,1)
    engine.resolve_until_stable()
    assert source.zone==Zone.GRAVEYARD


def test_clone_keeps_counters_and_prevention():
    engine,source=_board(Zone.GRAVEYARD)
    _escape(engine,source)
    engine=GameEngine(engine.state.clone())
    source=engine.state.find_object(source.instance_id)
    engine.rules.deal_damage(source,3)
    engine.resolve_until_stable()
    assert source.counters.get('+1/+1')==9 and source.damage_marked==0


@pytest.mark.parametrize('invalid',['too_few','self','duplicate'])
def test_escape_requires_six_other_distinct_cards(invalid):
    engine,source=_board(Zone.GRAVEYARD)
    fuel=[filler(engine,f'Fuel {i}',type_line='Instant',zone=Zone.GRAVEYARD) for i in range(6)]
    picks=fuel[:5] if invalid=='too_few' else [source]+fuel[:5] if invalid=='self' else [fuel[0]]*6
    player=engine.state.players[0]
    player.mana_pool.add_many({'B':1,'G':1,'C':4})
    with pytest.raises(ValueError):
        engine.cast_spell(player,source,graveyard_exile_choices=[o.instance_id for o in picks])
    assert player.mana_pool.total()==6 and source.zone==Zone.GRAVEYARD
    assert all(o.zone==Zone.GRAVEYARD for o in fuel)


def test_damage_to_clone_does_not_remove_original_states_counters():
    engine,source=_normal()
    clone=GameEngine(engine.state.clone())
    copied=clone.state.find_object(source.instance_id)
    clone.rules.deal_damage(copied,2)
    clone.resolve_until_stable()
    assert copied.counters.get('+1/+1')==4
    assert source.counters.get('+1/+1')==6
