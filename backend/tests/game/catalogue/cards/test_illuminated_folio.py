"""Illuminated Folio reveals a same-color pair as a cost and draws only on resolution."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game


def board(*names):
    engine = game(players=3, library=30)
    source = card(engine, 'Illuminated Folio')
    cards = [card(engine, name, zone=Zone.HAND) for name in names]
    engine.state.players[0].mana_pool.add('C', 1)
    return engine, source, cards


def activate(engine, source, chosen=None):
    engine.activate_ability(engine.state.players[0], source, 0,
                           hand_card_choices=None if chosen is None else [obj.instance_id for obj in chosen])


def reveal_events(engine):
    return [event for event in engine.state.events_this_turn() if event.type == 'REVEAL']


def test_fresh_specs_bind_actual_activation_cost():
    engine, source, cards = board('Llanowar Elves', 'Birds of Paradise')
    a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert source.activated_abilities[0].cost.reveal_shared_color == 2


def test_actual_cast_then_reveal_cost_and_draw_on_resolution():
    engine=game(library=30); source=card(engine,'Illuminated Folio',zone=Zone.HAND); cast(engine,source)
    a=card(engine,'Llanowar Elves',zone=Zone.HAND); b=card(engine,'Birds of Paradise',zone=Zone.HAND)
    before=len(engine.state.players[0].hand)
    activate(engine,source,[a,b])
    assert source.tapped and len(engine.state.players[0].hand)==before
    assert len(reveal_events(engine))==2 and a.zone==b.zone==Zone.HAND
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==before+1


@pytest.mark.parametrize('names', [('Sol Ring','Mind Stone'),('Forest','Forest'),('Noble Hierarch','Counterspell'),('Wasteland Strangler','Dark Ritual'),('Llanowar Elves','Counterspell')])
def test_invalid_color_pair_pays_nothing(names):
    engine,source,cards=board(*names)
    with pytest.raises(ValueError):activate(engine,source,cards)
    assert not source.tapped and engine.state.players[0].mana_pool.total()==1
    assert not reveal_events(engine) and not engine.state.stack


def test_multicolored_cards_may_share_one_of_several_colors():
    engine,source,cards=board('Izzet Charm','Lightning Bolt')
    activate(engine,source,cards);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==3 and len(reveal_events(engine))==2


def test_color_indicator_counts():
    engine,source,cards=board('Dryad Arbor','Llanowar Elves')
    activate(engine,source,cards);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==3


@pytest.mark.parametrize('indices',[(0,),(0,0),(0,1,2)])
def test_exactly_two_distinct_cards_are_required(indices):
    engine,source,cards=board('Llanowar Elves','Birds of Paradise','Giant Growth')
    with pytest.raises(ValueError):activate(engine,source,[cards[i] for i in indices])
    assert not source.tapped and not reveal_events(engine)


def test_automatic_choice_finds_valid_pair_after_incompatible_first_card():
    engine,source,cards=board('Counterspell','Llanowar Elves','Birds of Paradise')
    activate(engine,source)
    assert {e.get('instance_id') for e in reveal_events(engine)}=={cards[1].instance_id,cards[2].instance_id}


def test_legal_action_offers_only_cards_with_a_partner_and_fixed_count():
    engine,source,cards=board('Counterspell','Llanowar Elves','Birds of Paradise','Sol Ring')
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert not action.get('has_x')
    assert action['reveal_cost']['count']==2 and action['reveal_cost']['shared_color']
    assert {o['instance_id'] for o in action['reveal_cost']['options']}=={cards[1].instance_id,cards[2].instance_id}
    assert all(o['colors']==['G'] for o in action['reveal_cost']['options'])


def test_card_removed_from_hand_invalidates_payment_without_side_effects():
    engine,source,cards=board('Llanowar Elves','Birds of Paradise')
    engine.rules.exile(cards[1])
    with pytest.raises(ValueError):activate(engine,source,cards)
    assert not source.tapped and not reveal_events(engine)


def test_card_in_an_opponents_hand_cannot_pay():
    engine,source,cards=board('Llanowar Elves')
    other=card(engine,'Birds of Paradise',player='p2',zone=Zone.HAND)
    with pytest.raises(ValueError):activate(engine,source,[cards[0],other])
    assert not source.tapped and not reveal_events(engine)


def test_countering_does_not_unpay_the_reveal_or_draw():
    engine,source,cards=board('Llanowar Elves','Birds of Paradise')
    activate(engine,source,cards);engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert len(reveal_events(engine))==2 and len(engine.state.players[0].hand)==2 and source.tapped


def test_pending_activation_survives_clone_without_revealing_again():
    engine,source,cards=board('Llanowar Elves','Birds of Paradise');activate(engine,source,cards)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert len(restored.state.players[0].hand)==3 and len(reveal_events(restored))==2
    assert len(engine.state.players[0].hand)==2


def test_no_mana_or_tapped_source_cannot_reveal():
    engine,source,cards=board('Llanowar Elves','Birds of Paradise')
    engine.state.players[0].mana_pool.empty()
    with pytest.raises(ValueError):activate(engine,source,cards)
    engine.state.players[0].mana_pool.add('C',1);source.tapped=True
    with pytest.raises(ValueError):activate(engine,source,cards)
    assert not reveal_events(engine)


def test_no_valid_pair_removes_the_activation_offer():
    engine,source,cards=board('Counterspell','Llanowar Elves')
    assert not any(a['type']=='activate_ability' and a['instance_id']==source.instance_id
                   for a in engine.legal_actions(engine.state.players[0]))


def test_revealed_cards_are_publicly_known_but_stay_in_hand():
    import json
    from mtg_analyzer.services.game_session import GameSession

    engine,source,cards=board('Llanowar Elves','Birds of Paradise')
    session=GameSession(engine)
    assert 'Birds of Paradise' not in json.dumps(session.view('p2'))
    activate(engine,source,cards)
    assert 'Birds of Paradise' in json.dumps(session.view('p2'))
    assert all(obj in engine.state.players[0].hand for obj in cards)


def test_same_pair_can_pay_another_activation_after_untapping():
    engine,source,cards=board('Llanowar Elves','Birds of Paradise')
    activate(engine,source,cards);engine.resolve_until_stable()
    source.tapped=False;engine.state.players[0].mana_pool.add('C',1)
    activate(engine,source,cards);engine.resolve_until_stable()
    assert len(reveal_events(engine))==4 and len(engine.state.players[0].hand)==4
