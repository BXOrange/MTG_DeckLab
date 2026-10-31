"""PAR-187: Collective Brutality pays its real discard Escalate cost."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from tests.test_mec118_opponent_choice import _db_card, _engine, _put, _vanilla


def setup(cards=2):
    eng = _engine()
    p, q = eng.state.players
    spell = _put(eng, _db_card('Collective Brutality'), 'p1', Zone.HAND)
    payments = [_put(eng, Card(id=f'Pay{i}', name=f'Pay{i}', type_line='Sorcery', is_sorcery=True),
                     'p1', Zone.HAND) for i in range(cards)]
    victim = _put(eng, _vanilla('Victim', toughness=5), 'p2')
    p.mana_pool.add_many({'B': 1, 'C': 1})
    return eng, p, q, spell, payments, victim


@pytest.mark.parametrize('mode,required', [([2], 0), ([1, 2], 1), ([0, 1, 2], 2)])
def test_real_escalate_legal_actions_offer_exact_distinct_discard_count(mode, required):
    eng, p, q, spell, cards, victim = setup()
    assert spell.parametric_keywords['escalate']['cost'].lower().rstrip('.') == 'discard a card'
    action = next(a for a in eng.legal_actions(p) if a['type'] == 'cast_spell'
                  and a['instance_id'] == spell.instance_id and a.get('mode') == mode)
    assert not action.get('locked')
    if required:
        assert action['discard_cost']['count'] == required
        assert {o['instance_id'] for o in action['discard_cost']['options']} == {o.instance_id for o in cards}
    else:
        assert 'discard_cost' not in action


@pytest.mark.parametrize('mode,available', [([1, 2], 0), ([0, 1, 2], 1)])
def test_insufficient_other_hand_cards_lock_extra_modes_without_payment(mode, available):
    eng, p, q, spell, cards, victim = setup(available)
    assert not eng.can_cast(p, spell, mode=mode)
    action = next(a for a in eng.legal_actions(p) if a['type'] == 'cast_spell'
                  and a['instance_id'] == spell.instance_id and a.get('mode') == mode)
    assert action['locked']
    with pytest.raises(ValueError):
        eng.cast_spell(p, spell, mode=mode, targets=[victim, q])
    assert spell in p.hand and p.mana_pool.total() == 2 and all(card in p.hand for card in cards)


def test_actual_two_modes_discard_chosen_card_before_resolution_and_clone_retains_payment():
    eng, p, q, spell, cards, victim = setup()
    eng.cast_spell(p, spell, mode=[1, 2], targets=[victim, q],
                   target_groups=[[victim], [q]], discard_choices=[cards[1].instance_id])
    assert cards[1] in p.graveyard and cards[0] in p.hand
    assert spell.zone == Zone.STACK and p.mana_pool.total() == 0
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert clone.state.players[0].life == 22 and clone.state.players[1].life == 18
    assert clone.state.find_object(cards[1].instance_id).zone == Zone.GRAVEYARD
    assert cards[0] in p.hand and q.life == 20


@pytest.mark.parametrize('which', ['spell', 'duplicate', 'opponent'])
def test_illegal_escalate_discard_choices_never_spend_mana_or_move_cards(which):
    eng, p, q, spell, cards, victim = setup()
    opposing = _put(eng, Card(id='Their', name='Their', type_line='Instant', is_instant=True), 'p2', Zone.HAND)
    picks = [spell.instance_id] if which == 'spell' else [cards[0].instance_id, cards[0].instance_id] if which == 'duplicate' else [opposing.instance_id]
    mode = [0, 1, 2] if which == 'duplicate' else [1, 2]
    with pytest.raises(ValueError):
        eng.cast_spell(p, spell, mode=mode, targets=[victim, q], discard_choices=picks)
    assert p.mana_pool.total() == 2 and spell in p.hand and all(card in p.hand for card in cards)
    assert opposing in q.hand


def test_duplicate_modes_rejected_before_discard_or_mana_payment():
    eng, p, q, spell, cards, victim = setup()
    with pytest.raises(ValueError):
        eng.cast_spell(p, spell, mode=[2, 2], targets=[q, q], discard_choices=[cards[0].instance_id])
    assert p.mana_pool.total() == 2 and all(card in p.hand for card in cards)


def test_all_three_modes_pay_two_discards_even_when_countered():
    eng, p, q, spell, cards, victim = setup()
    opposing = _put(eng, Card(id='Their', name='Their', type_line='Instant', is_instant=True), 'p2', Zone.HAND)
    eng.cast_spell(p, spell, mode=[0, 1, 2], targets=[q, victim, q],
                   target_groups=[[q], [victim], [q]], discard_choices=[c.instance_id for c in cards])
    assert all(card in p.graveyard for card in cards)
    assert opposing in q.hand and p.mana_pool.total() == 0
    eng.rules.counter_spell(spell)
    eng.resolve_until_stable()
    assert all(card in p.graveyard for card in cards) and spell in p.graveyard
    assert q.life == 20 and victim.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('optional,pay_extra,count', [(False, False, 2), (True, False, 1), (True, True, 2)])
def test_escalate_combines_with_existing_additional_discard_without_double_payment(optional, pay_extra, count):
    from mtg_analyzer.game.costs import parse_activation_cost
    eng, p, q, spell, cards, victim = setup(3)
    spell.additional_cast_cost = parse_activation_cost('Discard a card')
    spell.additional_cast_cost_optional = optional
    picks = [card.instance_id for card in cards[:count]]
    assert eng.can_cast(p, spell, mode=[1, 2], discard_choices=picks, pay_additional=pay_extra)
    eng.cast_spell(p, spell, mode=[1, 2], targets=[victim, q], target_groups=[[victim], [q]],
                   discard_choices=picks, pay_additional=pay_extra)
    assert all(card in p.graveyard for card in cards[:count])
    assert all(card in p.hand for card in cards[count:])
    assert spell.additional_cost_paid is (not optional or pay_extra)


def test_escalate_can_be_paid_before_a_separate_discard_hand_cost():
    from mtg_analyzer.game.costs import parse_activation_cost
    eng, p, q, spell, cards, victim = setup(3)
    spell.additional_cast_cost = parse_activation_cost('Discard your hand')
    eng.cast_spell(p, spell, mode=[1, 2], targets=[victim, q], target_groups=[[victim], [q]],
                   discard_choices=[cards[0].instance_id])
    assert all(card in p.graveyard for card in cards) and not p.hand


def test_actual_three_modes_resume_after_opponent_hand_choice():
    eng, p, q, spell, cards, victim = setup()
    opposing = _put(eng, Card(id='Their', name='Their', type_line='Instant', is_instant=True), 'p2', Zone.HAND)
    eng.cast_spell(p, spell, mode=[0, 1, 2], targets=[q, victim, q],
                   target_groups=[[q], [victim], [q]], discard_choices=[c.instance_id for c in cards])
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None and q.life == 20
    assert all(card in p.graveyard for card in cards)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(opposing.instance_id)); clone.resolve_until_stable()
    assert clone.state.players[0].life == 22 and clone.state.players[1].life == 18
    assert clone.state.find_object(opposing.instance_id).zone == Zone.GRAVEYARD
    assert clone.state.find_object(victim.instance_id).toughness == 3
