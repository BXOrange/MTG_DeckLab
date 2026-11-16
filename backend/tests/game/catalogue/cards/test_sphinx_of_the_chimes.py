"""Sphinx of the Chimes discards a same-name nonland pair as a cost, then draws four."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card,cast,filler,game


def board(*names):
    engine=game(players=3,library=40);source=card(engine,'Sphinx of the Chimes')
    cards=[card(engine,name,zone=Zone.HAND) for name in names]
    return engine,source,cards


def activate(engine,source,cards=None):
    engine.activate_ability(engine.state.players[0],source,0,
                           discard_choices=None if cards is None else [obj.instance_id for obj in cards])


def test_fresh_specs_bind_flying_and_discard_ability():
    engine,source,cards=board('Counterspell','Counterspell');a,b=specs_for(source.card),specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source,'flying') and len(source.activated_abilities)==1


def test_actual_cast_then_pays_discard_before_drawing_four():
    engine=game(library=40);source=card(engine,'Sphinx of the Chimes',zone=Zone.HAND);cast(engine,source)
    cards=[card(engine,'Counterspell',zone=Zone.HAND) for _ in range(2)]
    activate(engine,source,cards)
    assert all(obj.zone==Zone.GRAVEYARD for obj in cards) and not engine.state.players[0].hand
    engine.resolve_until_stable();assert len(engine.state.players[0].hand)==4


@pytest.mark.parametrize('names',[('Forest','Forest'),('Counterspell','Negate'),('Sol Ring','Mind Stone')])
def test_invalid_pair_does_not_discard_or_start_activation(names):
    engine,source,cards=board(*names)
    with pytest.raises(ValueError):activate(engine,source,cards)
    assert all(obj.zone==Zone.HAND for obj in cards) and not engine.state.stack


@pytest.mark.parametrize('indices',[(0,),(0,0),(0,1,2)])
def test_exactly_two_distinct_cards_are_required(indices):
    engine,source,cards=board('Counterspell','Counterspell','Counterspell')
    with pytest.raises(ValueError):activate(engine,source,[cards[i] for i in indices])
    assert len(engine.state.players[0].hand)==3


def test_automatic_choice_skips_an_unmatched_first_card():
    engine,source,cards=board('Negate','Counterspell','Counterspell')
    activate(engine,source)
    assert cards[0].zone==Zone.HAND and cards[1].zone==cards[2].zone==Zone.GRAVEYARD


def test_both_pairs_are_offered_but_orphan_and_land_cards_are_not():
    engine,source,cards=board('Counterspell','Counterspell','Negate','Negate','Sol Ring','Forest','Forest')
    action=next(a for a in engine.legal_actions(engine.state.players[0]) if a['type']=='activate_ability' and a['instance_id']==source.instance_id)
    assert action['discard_cost']['matching_names'] and action['discard_cost']['count']==2
    assert {o['instance_id'] for o in action['discard_cost']['options']}=={obj.instance_id for obj in cards[:4]}
    assert all(o['names']==[o['name']] for o in action['discard_cost']['options'])


def test_no_valid_pair_hides_activation_offer():
    engine,source,cards=board('Counterspell','Negate')
    assert not any(a['type']=='activate_ability' and a['instance_id']==source.instance_id
                   for a in engine.legal_actions(engine.state.players[0]))


def test_opponents_hand_card_cannot_pay():
    engine,source,cards=board('Counterspell')
    other=card(engine,'Counterspell',player='p2',zone=Zone.HAND)
    with pytest.raises(ValueError):activate(engine,source,[cards[0],other])
    assert cards[0].zone==other.zone==Zone.HAND


def test_card_that_left_hand_cannot_pay_stale_choice():
    engine,source,cards=board('Counterspell','Counterspell');engine.rules.exile(cards[1])
    with pytest.raises(ValueError):activate(engine,source,cards)
    assert cards[0].zone==Zone.HAND and not engine.state.stack


def test_countered_ability_does_not_refund_cost_or_draw_cards():
    engine,source,cards=board('Counterspell','Counterspell');activate(engine,source,cards)
    engine.rules.counter_ability(engine.state.stack[-1]);engine.resolve_until_stable()
    assert all(obj.zone==Zone.GRAVEYARD for obj in cards) and not engine.state.players[0].hand


def test_source_can_activate_while_tapped_and_summoning_sick():
    engine,source,cards=board('Counterspell','Counterspell');source.tapped=True;source.summoning_sick=True
    activate(engine,source,cards);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==4


def test_pending_draw_survives_source_departure():
    engine,source,cards=board('Counterspell','Counterspell');activate(engine,source,cards)
    engine.rules.exile(source);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==4 and source.zone==Zone.EXILE


def test_pending_draw_survives_clone_without_discarding_again():
    engine,source,cards=board('Counterspell','Counterspell');activate(engine,source,cards)
    restored=GameEngine(engine.state.clone());restored.resolve_until_stable()
    assert len(restored.state.players[0].hand)==4 and len(restored.state.players[0].graveyard)==2
    assert not engine.state.players[0].hand


def test_split_cards_need_only_one_name_in_common():
    engine,source,cards=board()
    a=filler(engine,'Fire // Ice',type_line='Instant',layout='split',back_name='Ice',zone=Zone.HAND)
    b=filler(engine,'Fire // Water',type_line='Instant',layout='split',back_name='Water',zone=Zone.HAND)
    assert a.names==('Fire','Ice')
    activate(engine,source,[a,b]);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==4


def test_dfc_back_name_does_not_match_a_hand_card():
    engine,source,cards=board()
    a=filler(engine,'Front // Back',type_line='Creature',power=2,toughness=2,layout='transform',back_name='Back',zone=Zone.HAND)
    b=filler(engine,'Back',type_line='Instant',zone=Zone.HAND)
    assert a.names==('Front',)
    with pytest.raises(ValueError):activate(engine,source,[a,b])
    assert a.zone==b.zone==Zone.HAND


def test_adventure_name_is_not_a_name_of_the_card_in_hand():
    engine,source,cards=board()
    a=filler(engine,'Creature // Adventure',type_line='Creature',power=2,toughness=2,layout='adventure',back_name='Adventure',zone=Zone.HAND)
    b=filler(engine,'Adventure',type_line='Instant',zone=Zone.HAND)
    with pytest.raises(ValueError):activate(engine,source,[a,b])


def test_a_second_pair_can_pay_another_activation_without_tapping():
    engine,source,cards=board('Counterspell','Counterspell','Negate','Negate')
    activate(engine,source,cards[:2]);activate(engine,source,cards[2:]);engine.resolve_until_stable()
    assert len(engine.state.players[0].hand)==8 and not source.tapped


@pytest.mark.parametrize('names', [
    ('Cecily, Haunted Mage', 'Eleven, the Mage'),
    ('Aisha of Sparks and Smoke', 'Ken, Burning Brawler'),
    ("Gisa's Favorite Shovel", 'Lucille'),
    ('Mathise, Surge Channeler', 'Simon, Wild Magic Sorcerer'),
])
def test_interchangeable_english_names_can_pay_and_share_picker_keys(names):
    engine, source, _ = board()
    cards = [filler(engine, name, type_line='Artifact', zone=Zone.HAND) for name in names]
    action = next(a for a in engine.legal_actions(engine.state.players[0])
                  if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id)
    options = action['discard_cost']['options']
    assert len(options) == 2 and options[0]['names'] == options[1]['names']
    assert tuple(obj.name for obj in cards) == names
    activate(engine, source, cards)
    engine.resolve_until_stable()
    assert len(engine.state.players[0].hand) == 4


def test_automatic_payment_finds_interchangeable_name_pair():
    engine, source, _ = board('Negate')
    cards = [filler(engine, name, type_line='Artifact', zone=Zone.HAND)
             for name in ('Cecily, Haunted Mage', 'Eleven, the Mage')]
    activate(engine, source)
    assert all(obj.zone == Zone.GRAVEYARD for obj in cards)


def test_same_mechanics_or_flavor_name_do_not_make_names_interchangeable():
    engine, source, _ = board()
    a = filler(engine, 'Counterspell', type_line='Instant', zone=Zone.HAND)
    b = filler(engine, 'Other Name', type_line='Instant', flavor_name='Counterspell', zone=Zone.HAND)
    with pytest.raises(ValueError):
        activate(engine, source, [a, b])


def test_changed_name_replaces_interchangeable_identity():
    engine, source, _ = board()
    a = filler(engine, 'Cecily, Haunted Mage', type_line='Artifact', zone=Zone.HAND)
    b = filler(engine, 'Eleven, the Mage', type_line='Artifact', zone=Zone.HAND)
    a._derived_name = 'Other Name'
    with pytest.raises(ValueError):
        activate(engine, source, [a, b])
    a._derived_name = 'Eleven, the Mage'
    activate(engine, source, [a, b])


def test_nameless_hand_cards_cannot_pay_a_same_name_cost():
    engine, source, cards = board('Counterspell', 'Counterspell')
    for obj in cards:
        obj._derived_name = ''
    with pytest.raises(ValueError):
        activate(engine, source, cards)
    assert all(obj.zone == Zone.HAND for obj in cards)
