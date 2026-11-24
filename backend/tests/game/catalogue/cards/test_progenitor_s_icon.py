"""Icon freezes its entry choice into a type-filtered next-spell grant."""
import pytest
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, game, cast, RICH
from tests.support.star_trek import advance_to


def _board():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    card(engine,'Llanowar Elves',zone=Zone.HAND)
    icon=card(engine,"Progenitor's Icon",zone=Zone.HAND)
    cast(engine,icon)
    choice=engine.state.pending_choice
    assert choice is not None
    option=next(o for o in choice['options'] if str(o.get('label','')).lower()=='elf' or str(o['id']).lower()=='elf')
    engine.resolve_pending_choice(option['id'])
    engine.resolve_until_stable()
    assert icon.chosen_type.lower()=='elf'
    return engine,icon


def _activate(engine,icon,resolve=True):
    engine.activate_ability(engine.state.player_by_id(icon.controller_id),icon,0)
    engine.rules.put_triggers_on_stack()
    if resolve:
        engine.resolve_until_stable()


def _off_turn(engine):
    engine.state.active_player_index=1
    engine.state.current_step='end'
    engine.state.player_by_id('p1').mana_pool.add_many(RICH)


def test_fresh_specs_real_entry_choice_and_binding():
    engine,icon=_board()
    a,b=specs_for(icon.card),specs_for(icon.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert len(icon.activated_abilities)==1


def test_only_next_matching_spell_receives_flash_timing():
    engine,icon=_board()
    _activate(engine,icon)
    _off_turn(engine)
    elf=card(engine,'Llanowar Elves',zone=Zone.HAND)
    bear=card(engine,'Grizzly Bears',zone=Zone.HAND)
    p=engine.state.player_by_id('p1')
    assert engine.can_cast(p,elf) and not engine.can_cast(p,bear)
    engine.cast_spell(p,elf)
    engine.resolve_until_stable()
    another=card(engine,'Llanowar Elves',zone=Zone.HAND)
    assert not engine.can_cast(p,another)
    assert not engine.state.next_spell_flash_grants


def test_nonmatching_cast_does_not_consume_grant():
    engine,icon=_board()
    _activate(engine,icon)
    cast(engine,card(engine,'Grizzly Bears',zone=Zone.HAND))
    assert len(engine.state.next_spell_flash_grants)==1
    _off_turn(engine)
    elf=card(engine,'Llanowar Elves',zone=Zone.HAND)
    assert engine.can_cast(engine.state.player_by_id('p1'),elf)


@pytest.mark.parametrize('change',['leaves','new_visit','clone','control'])
def test_pending_activation_keeps_original_type_and_controller(change):
    engine,icon=_board()
    _activate(engine,icon,False)
    if change=='leaves':
        engine.rules.exile(icon)
    elif change=='new_visit':
        engine.rules.exile(icon)
        engine.rules.return_from_graveyard(icon,'battlefield')
        # The old ability must not pick up a new battlefield visit's choice.
        choice=engine.state.pending_choice
        if choice is not None:
            engine.resolve_pending_choice('Bear')
        else:
            icon.chosen_type='Bear'
    elif change=='clone':
        engine=GameEngine(engine.state.clone())
    else:
        icon.controller_id='p2'
    engine.resolve_until_stable()
    _off_turn(engine)
    p=engine.state.player_by_id('p1')
    elf=card(engine,'Llanowar Elves',zone=Zone.HAND)
    bear=card(engine,'Grizzly Bears',zone=Zone.HAND)
    assert engine.can_cast(p,elf) and not engine.can_cast(p,bear)


def test_resolved_grant_survives_source_leaving():
    engine,icon=_board()
    _activate(engine,icon)
    engine.rules.exile(icon)
    _off_turn(engine)
    elf=card(engine,'Llanowar Elves',zone=Zone.HAND)
    assert engine.can_cast(engine.state.player_by_id('p1'),elf)


def test_native_mana_ability_does_not_grant_flash():
    engine,icon=_board()
    p=engine.state.player_by_id('p1')
    before=p.mana_pool.total()
    engine.tap_for_mana(p,icon,option_index=4)
    assert p.mana_pool.total()==before+1 and icon.tapped
    assert not engine.state.next_spell_flash_grants


def test_grant_expires_at_cleanup():
    engine,icon=_board()
    _activate(engine,icon)
    advance_to(engine,'untap')
    assert not engine.state.next_spell_flash_grants


def test_changeling_spell_matches_chosen_type():
    engine,icon=_board()
    _activate(engine,icon)
    _off_turn(engine)
    changeling=card(engine,'Universal Automaton',zone=Zone.HAND)
    assert engine.can_cast(engine.state.player_by_id('p1'),changeling)


def test_entry_choice_is_required_even_without_creature_cards_in_game():
    engine=game(players=3,library=30)
    advance_to(engine,'main1')
    icon=card(engine,"Progenitor's Icon",zone=Zone.HAND)
    cast(engine,icon)
    choice=engine.state.pending_choice
    assert choice is not None and choice['kind']=='choose_creature_type'
    option=next(o for o in choice['options'] if str(o['id']).lower()=='elf')
    engine.resolve_pending_choice(option['id'])
    assert icon.zone==Zone.BATTLEFIELD and icon.chosen_type.lower()=='elf'


def test_opponents_matching_spell_does_not_consume_own_grant():
    engine,icon=_board()
    _activate(engine,icon)
    engine.state.active_player_index=1
    other=card(engine,'Llanowar Elves',player='p2',zone=Zone.HAND)
    p2=engine.state.player_by_id('p2')
    p2.mana_pool.add_many(RICH)
    engine.cast_spell(p2,other)
    engine.resolve_until_stable()
    assert len(engine.state.next_spell_flash_grants)==1


def test_countering_activation_does_not_create_flash_grant():
    engine,icon=_board()
    _activate(engine,icon,False)
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert not engine.state.next_spell_flash_grants and icon.tapped
