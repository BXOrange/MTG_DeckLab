"""Conditional returns execute through actual activation/casting and choices."""
import pytest
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell


def _end(eng):
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()


@pytest.mark.parametrize('answer', ['now', 'later'])
def test_gilraen_return_timing_choice_survives_clone(answer):
    eng = _engine()
    source = _bf(eng, _creature('Gilraen, Dúnedain Protector'))
    target = _bf(eng, _creature('Bear'))
    spec = source.activated_abilities[0].effects[0].target_spec
    assert source.instance_id not in {o['instance_id'] for o in legal_targets(eng.state, 'p1', spec, source)}
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 2)
    eng.activate_ability(player, source, targets=[target]); eng.resolve_until_stable()
    assert target.zone == Zone.EXILE
    clone = GameEngine(eng.state.clone())
    clone.rules.resolve_choice(answer); clone.resolve_until_stable()
    actual = clone.state.find_object(target.instance_id)
    assert actual.zone == (Zone.BATTLEFIELD if answer == 'now' else Zone.EXILE)
    _end(clone)
    assert actual.zone == Zone.BATTLEFIELD
    assert actual.counters == ({} if answer == 'now' else {'vigilance': 1, 'lifelink': 1})
    assert target.zone == Zone.EXILE


@pytest.mark.parametrize('pay', [True, False, None])
def test_koya_pay_or_return_at_end_uses_original_ability_controller(pay):
    eng = _engine()
    target = _bf(eng, _creature('Bear'), 'p2')
    source = _hand(eng, _creature('Koya, Death from Above', oracle_text=
        "Flying\nWhen Koya enters, exile up to one other target creature. At the beginning of the next end step, you may pay {3}{B}. If you don't, return that card to the battlefield under its owner's control."))
    eng.cast_spell(eng.state.player_by_id('p1'), source)
    eng.resolve_until_stable()
    eng.rules.resolve_choice(str(target.instance_id)); eng.resolve_until_stable()
    assert target.zone == Zone.EXILE
    source.controller_id = 'p2'
    player = eng.state.player_by_id('p1')
    if pay is not None:
        player.mana_pool.add('B', 1); player.mana_pool.add('C', 3)
    _end(eng)
    if pay is not None:
        assert eng.state.pending_choice['player_id'] == 'p1'
        clone = GameEngine(eng.state.clone())
        clone.rules.resolve_choice('pay' if pay else 'decline'); clone.resolve_until_stable()
        actual = clone.state.find_object(target.instance_id)
        assert actual.zone == (Zone.EXILE if pay else Zone.BATTLEFIELD)
        assert clone.state.player_by_id('p1').mana_pool.total() == (0 if pay else 4)
    else:
        assert target.zone == Zone.BATTLEFIELD and target.controller_id == 'p2'


def test_gilraen_decline_never_returns_a_later_exile_visit():
    eng = _engine(); source = _bf(eng, _creature('Gilraen, Dúnedain Protector'))
    target = _bf(eng, _creature('Bear'))
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 2)
    eng.activate_ability(player, source, targets=[target]); eng.resolve_until_stable()
    eng.rules.resolve_choice('later')
    eng.rules.return_to_hand(target); eng.rules.exile(target)
    _end(eng)
    assert target.zone == Zone.EXILE


def test_koya_zero_targets_creates_no_delayed_return():
    eng = _engine()
    target = _bf(eng, _creature('Bear'), 'p2')
    source = _hand(eng, _creature('Koya, Death from Above'))
    eng.cast_spell(eng.state.player_by_id('p1'), source); eng.resolve_until_stable()
    assert str(source.instance_id) not in {o['id'] for o in eng.state.pending_choice['options']}
    eng.resolve_pending_choice('decline')
    assert target.zone == Zone.BATTLEFIELD and not eng.state.delayed_triggers


@pytest.mark.parametrize('gift', [True, False])
def test_parting_gust_actual_gift_cast_and_conditional_return(gift):
    eng = _engine(); target = _bf(eng, _creature('Bear'), 'p2')
    text = ('Gift a tapped Fish\nExile target nontoken creature. If the gift wasn\'t promised, '
            'return that card to the battlefield under its owner\'s control with a +1/+1 '
            'counter on it at the beginning of the next end step.')
    spell = _hand(eng, _spell('Parting Gust', text))
    player = eng.state.player_by_id('p1'); player.mana_pool.add('W', 2)
    eng.cast_spell(player, spell, targets=[target], gift_opponent_id='p2' if gift else None)
    eng.resolve_until_stable()
    assert target.zone == Zone.EXILE
    assert bool([o for o in eng.state.permanents() if o.is_token and o.name == 'Fish']) == gift
    _end(eng)
    assert target.zone == (Zone.EXILE if gift else Zone.BATTLEFIELD)
    if not gift:
        assert target.counters == {'+1/+1': 1}


def test_parting_gust_cannot_target_token_and_all_entries_are_fresh():
    eng = _engine()
    spell = _hand(eng, _spell('Parting Gust', 'Gift a tapped Fish'))
    token = _bf(eng, _creature('Token')); token.is_token = True
    spec = spell.spell_effects[0].target_spec
    assert token.instance_id not in {o['instance_id'] for o in legal_targets(eng.state, 'p1', spec, spell)}
    for name in ('Parting Gust', 'Gilraen, Dúnedain Protector', 'Koya, Death from Above'):
        card = _creature(name)
        a, b = specs_for(card), specs_for(card)
        assert a and b and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
