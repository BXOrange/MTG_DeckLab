"""Reported Solo interactions: Ral's reduction, modal casts and public tax outcomes."""
import pytest

from tests.test_taxed_draw_family import (
    two_player_engine, battlefield, to_hand, advance_to_main,
)
from mtg_analyzer.services.table_feed import TableFeed


@pytest.mark.parametrize('name,cost', [('Opera Love Song', '{R}'), ('Strike It Rich', '{R}'), ('The One Ring', '{4}')])
def test_ral_reduction_is_in_cost_preview_and_only_affects_instants_and_sorceries(name, cost):
    eng, p1, _ = two_player_engine()
    battlefield(eng, 'Ral, Monsoon Mage')
    spell = to_hand(eng, name)
    advance_to_main(eng)
    assert eng.effective_cast_cost(p1, spell).render() == cost


def test_ral_discount_is_used_for_modal_spell_payment():
    eng, p1, _ = two_player_engine()
    battlefield(eng, 'Ral, Monsoon Mage')
    spell = to_hand(eng, 'Opera Love Song')
    advance_to_main(eng)
    p1.mana_pool.add('R', 1)
    actions = [a for a in eng.legal_actions(p1) if a.get('instance_id') == spell.instance_id and a['type'] == 'cast_spell']
    assert {a['mode'] for a in actions} == {0, 1}
    assert all(a['effective_cost'] == '{R}' for a in actions)
    eng.cast_spell(p1, spell, mode=0)
    assert p1.mana_pool.total() == 0
    assert spell not in p1.hand


@pytest.mark.parametrize('answer,can_pay,action', [('pay', True, 'pay_cost'), ('decline', True, 'decline_cost'), (None, False, 'decline_cost')])
def test_rhystic_study_payment_outcome_is_announced(answer, can_pay, action):
    eng, p1, p2 = two_player_engine()
    battlefield(eng, 'Rhystic Study')
    spell = to_hand(eng, 'Lightning Bolt', 'p2')
    advance_to_main(eng)
    p2.mana_pool.add('R', 1)
    if can_pay:
        p2.mana_pool.add('C', 1)
    start = len(eng.state.event_log)
    before = len(p1.hand)
    eng.cast_spell(p2, spell, targets=[p1])
    eng.resolve_until_stable()
    if answer:
        eng.resolve_pending_choice(answer)
    feed = TableFeed()
    feed.announce_events(eng.state, eng.state.event_log[start:], 1)
    entries = [m for m in feed.view() if m['action'] in ('pay_cost', 'decline_cost')]
    assert len(entries) == 1
    assert entries[0]['action'] == action
    assert entries[0]['actor_id'] == 'p2'
    assert entries[0]['card_name'] == 'Rhystic Study'
    assert entries[0]['cost_label'] == '{1}'
    assert len(p1.hand) == before + (answer != 'pay')
    feed.trim_moves(0)
    assert feed.view() == []


def test_bot_tax_answer_reaches_both_players_feed_through_session_actions():
    from mtg_analyzer.services.bots import _one_bot_action, create_bot
    from mtg_analyzer.services.game_session import GameSession

    eng, _, p2 = two_player_engine()
    battlefield(eng, 'Rhystic Study')
    spell = to_hand(eng, 'Lightning Bolt', 'p2')
    advance_to_main(eng)
    p2.mana_pool.add_many({'R': 1, 'C': 1})
    session = GameSession(eng, require_setup=False)
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id,
                          'targets': [{'player_id': 'p1'}]}, actor_id='p2')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id'] == 'p2'
    assert _one_bot_action(session, {'p2': create_bot('goldfish', 'p2')})
    for perspective in ('p1', 'p2'):
        entries = [m for m in session.view(perspective=perspective)['table_messages']
                   if m['action'] == 'decline_cost']
        assert len(entries) == 1
        assert entries[0]['actor_id'] == 'p2'
        assert entries[0]['card_name'] == 'Rhystic Study'
        assert entries[0]['cost_label'] == '{1}'


def test_ral_reduction_applies_to_flashback_but_not_opponents_spells():
    from mtg_analyzer.models.game.game_object import Zone

    eng, p1, p2 = two_player_engine()
    battlefield(eng, 'Ral, Monsoon Mage')
    spell = to_hand(eng, 'Strike It Rich')
    p1.hand.remove(spell)
    p1.add_to_zone(spell, Zone.GRAVEYARD)
    opponents_spell = to_hand(eng, 'Opera Love Song', 'p2')
    advance_to_main(eng)
    assert eng.effective_cast_cost(p1, spell).render() == '{1}{R}'
    assert eng.effective_cast_cost(p2, opponents_spell).render() == '{1}{R}'
    p1.mana_pool.add_many({'R': 1, 'C': 1})
    actions = [a for a in eng.legal_actions(p1) if a['type'] == 'cast_spell'
               and a.get('instance_id') == spell.instance_id]
    assert actions and actions[0]['effective_cost'] == '{1}{R}'
    eng.cast_spell(p1, spell)
    assert p1.mana_pool.total() == 0
    assert spell not in p1.graveyard


def test_payment_announcement_waits_until_a_sacrifice_cost_is_finished():
    from mtg_analyzer.game.costs import ActivationCost
    from mtg_analyzer.models.game.events import EventType

    eng, p1, _ = two_player_engine()
    source = battlefield(eng, 'Rhystic Study')
    chosen = battlefield(eng, 'Grizzly Bears')
    battlefield(eng, 'Grizzly Bears')
    advance_to_main(eng)
    eng.rules._request_pay_cost_then(p1, ActivationCost(sacrifice='creature'), [], source)
    eng.resolve_pending_choice('pay')
    assert eng.state.pending_choice is not None
    assert not any(e.type == EventType.OPTIONAL_COST_DECIDED for e in eng.state.event_log)
    eng.resolve_pending_choice(str(chosen.instance_id))
    assert chosen in p1.graveyard
    decisions = [e for e in eng.state.event_log if e.type == EventType.OPTIONAL_COST_DECIDED]
    assert len(decisions) == 1
    assert decisions[0].get('paid') is True
