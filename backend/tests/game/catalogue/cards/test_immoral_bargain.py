"""Variable sacrifice costs and destroy targets are fixed at casting."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_mardu_surge_deck import _game, _card, _filler


def _setup(name):
    engine = _game()
    engine.state.current_step = 'main1'
    player = engine.state.player_by_id('p1')
    spell = _card(engine, name, zone=Zone.HAND)
    player.mana_pool.add_many({'B': 4, 'G': 4, 'C': 15})
    mine = [_filler(engine, f'Mine{i}', power=1, toughness=1) for i in range(3)]
    theirs = [_filler(engine, f'Theirs{i}', power=1, toughness=1, player='p2') for i in range(3)]
    return engine, player, spell, mine, theirs


@pytest.mark.parametrize('name', ['Eliminate the Competition', 'Immoral Bargain'])
def test_cost_and_targets_are_committed_before_resolution(name):
    engine, player, spell, mine, theirs = _setup(name)
    engine.cast_spell(player, spell, x=2, targets=theirs[:2],
                      sacrifice_choices=[o.instance_id for o in mine[1:]])
    assert mine[0].zone == Zone.BATTLEFIELD and all(o.zone == Zone.GRAVEYARD for o in mine[1:])
    assert all(o.zone == Zone.BATTLEFIELD for o in theirs)
    assert engine.state.stack[-1].targets == theirs[:2]
    engine.resolve_until_stable()
    assert all(o.zone == Zone.GRAVEYARD for o in theirs[:2])
    assert theirs[2].zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('name', ['Eliminate the Competition', 'Immoral Bargain'])
def test_countering_spell_never_refunds_cost_or_destroys_targets(name):
    engine, player, spell, mine, theirs = _setup(name)
    engine.cast_spell(player, spell, x=1, targets=theirs[:1], sacrifice_choices=[mine[0].instance_id])
    engine.rules.counter_spell(spell)
    assert mine[0].zone == Zone.GRAVEYARD and all(o.zone == Zone.BATTLEFIELD for o in theirs)


@pytest.mark.parametrize('bad', ['duplicate', 'foreign', 'count'])
def test_invalid_sacrifice_selection_rejected_before_mana_payment(bad):
    engine, player, spell, mine, theirs = _setup('Eliminate the Competition')
    picks = [mine[0].instance_id, mine[1].instance_id]
    if bad == 'duplicate':
        picks[1] = picks[0]
    elif bad == 'foreign':
        picks[1] = theirs[0].instance_id
    else:
        picks.pop()
    mana = player.mana_pool.total()
    with pytest.raises(ValueError, match='distinct creatures'):
        engine.cast_spell(player, spell, x=2, targets=theirs[:2], sacrifice_choices=picks)
    assert player.mana_pool.total() == mana
    assert spell.zone == Zone.HAND and all(o.zone == Zone.BATTLEFIELD for o in mine)


def test_x_zero_needs_no_sacrifice_or_targets():
    engine, player, spell, mine, theirs = _setup('Eliminate the Competition')
    engine.cast_spell(player, spell, x=0, targets=[], sacrifice_choices=[])
    engine.resolve_until_stable()
    assert all(o.zone == Zone.BATTLEFIELD for o in mine + theirs)


def test_immoral_bargain_can_target_artifact_but_not_land():
    engine, player, spell, mine, theirs = _setup('Immoral Bargain')
    rock = _filler(engine, 'Rock', 'Artifact', player='p2')
    engine.cast_spell(player, spell, x=1, targets=[rock], sacrifice_choices=[mine[0].instance_id])
    engine.resolve_until_stable()
    assert rock.zone == Zone.GRAVEYARD


def test_hexproof_target_cannot_be_announced_before_sacrifice():
    engine, player, spell, mine, theirs = _setup('Eliminate the Competition')
    theirs[0].intrinsic_keywords.add('hexproof')
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, x=1, targets=theirs[:1], sacrifice_choices=[mine[0].instance_id])
    assert mine[0].zone == Zone.BATTLEFIELD and spell.zone == Zone.HAND


def test_sacrifice_prohibition_allows_x_zero_but_not_positive_payment():
    engine, player, spell, mine, theirs = _setup('Eliminate the Competition')
    _card(engine, 'Yasharn, Implacable Earth')
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, x=1, targets=theirs[:1], sacrifice_choices=[mine[0].instance_id])
    engine.cast_spell(player, spell, x=0, targets=[], sacrifice_choices=[])
    assert all(o.zone == Zone.BATTLEFIELD for o in mine)


def test_sacrifice_x_offer_is_not_limited_by_mana_total():
    engine, player, spell, mine, theirs = _setup('Eliminate the Competition')
    player.mana_pool.empty()
    player.mana_pool.add_many({'B': 1, 'C': 4})
    for i in range(7):
        _filler(engine, f'Extra{i}', power=1, toughness=1)
    action = next(a for a in engine.legal_actions(player) if a.get('instance_id') == spell.instance_id)
    assert action['has_x'] and action['max_x'] == 10
