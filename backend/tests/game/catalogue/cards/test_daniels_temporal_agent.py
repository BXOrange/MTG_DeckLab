"""Daniels pays the graveyard-to-library-bottom move before gaining life."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, RICH
from tests.support.star_trek import advance_to


def board(zone=Zone.GRAVEYARD):
    engine=game(players=3,library=20); advance_to(engine,'main1')
    daniels=card(engine,'Daniels, Temporal Agent',zone=zone)
    player=engine.state.player_by_id('p1'); player.mana_pool.add_many(RICH)
    return engine,daniels,player


def test_fresh_specs_binding_and_cost_serialization():
    engine,daniels,player=board()
    a,b=specs_for(daniels.card),specs_for(daniels.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    cost=daniels.activated_abilities[0].cost
    assert cost.bottom_self_from_graveyard and 'bottom' in cost.label()
    clone=parse_activation_cost(cost.to_dict())
    assert clone.bottom_self_from_graveyard and clone.activation_zones==('graveyard',)


def test_cost_moves_to_bottom_without_shuffling_then_gain_life():
    engine,daniels,player=board()
    before=list(player.library); life=player.life
    engine.activate_ability(player,daniels,0)
    assert daniels.zone==Zone.LIBRARY and player.library==[daniels,*before]
    assert player.life==life
    engine.resolve_until_stable()
    assert player.life==life+2 and player.library==[daniels,*before]


def test_countering_does_not_refund_card_or_mana():
    engine,daniels,player=board(); life=player.life
    engine.activate_ability(player,daniels,0)
    pool=player.mana_pool.to_dict()
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert player.life==life and player.library[0] is daniels
    assert player.mana_pool.to_dict()==pool


@pytest.mark.parametrize('zone',[Zone.BATTLEFIELD,Zone.HAND,Zone.EXILE])
def test_activation_only_from_graveyard(zone):
    engine,daniels,player=board(zone)
    assert not engine.can_activate(player,daniels,daniels.activated_abilities[0])
    with pytest.raises(ValueError):
        engine.activate_ability(player,daniels,0)
    assert daniels.zone==zone


def test_insufficient_mana_leaves_card_in_graveyard():
    engine,daniels,player=board()
    player.mana_pool=type(player.mana_pool)()
    with pytest.raises(ValueError):
        engine.activate_ability(player,daniels,0)
    assert daniels.zone==Zone.GRAVEYARD


def test_opponent_cannot_activate_your_graveyard_card():
    engine,daniels,player=board()
    opponent=engine.state.player_by_id('p2'); opponent.mana_pool.add_many(RICH)
    with pytest.raises(ValueError):
        engine.activate_ability(opponent,daniels,0)
    assert daniels.zone==Zone.GRAVEYARD


def test_clone_preserves_paid_cost_and_resolving_controller():
    engine,daniels,player=board(); life=player.life
    engine.activate_ability(player,daniels,0)
    clone=GameEngine(engine.state.clone()); clone.resolve_until_stable()
    assert clone.state.player_by_id('p1').life==life+2 and player.life==life
    assert clone.state.player_by_id('p1').library[0].instance_id==daniels.instance_id


def test_real_cast_returns_own_creature_card_to_hand():
    engine,daniels,player=board(Zone.HAND)
    creature=card(engine,'Serra Angel',zone=Zone.GRAVEYARD)
    opponent=card(engine,'Serra Angel',player='p2',zone=Zone.GRAVEYARD)
    engine.cast_spell(player,daniels); engine.resolve_until_stable()
    choice=engine.state.pending_choice
    assert opponent.instance_id not in {o.get('instance_id') for o in choice['options']}
    option=next(o for o in choice['options'] if o.get('instance_id')==creature.instance_id)
    engine.resolve_pending_choice(str(option['id']))
    assert creature.zone==Zone.HAND and daniels.zone==Zone.BATTLEFIELD



def test_second_activation_is_unavailable_after_paying_first():
    engine,daniels,player=board()
    engine.activate_ability(player,daniels,0)
    with pytest.raises(ValueError):
        engine.activate_ability(player,daniels,0)
    engine.resolve_until_stable()
    assert player.life==22


def test_graveyard_ability_is_listed_among_legal_actions():
    engine,daniels,player=board()
    actions=engine.legal_actions(player)
    assert any(a.get('type')=='activate_ability' and a.get('instance_id')==daniels.instance_id for a in actions)
