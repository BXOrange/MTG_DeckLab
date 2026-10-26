"""Bots announce branch-specific targets and damage through their public offers."""
import pytest

from mtg_analyzer.services.bot_policies.base import Bot
from mtg_analyzer.services.bot_policies.greedy import GreedyBot
from mtg_analyzer.services.bot_policies.smart2 import SmartBot2
from tests.services.test_smart_bot import view, spell
from tests.services.test_bots import make_game, keep


def test_damage_allocation_preserves_requirement_and_target_order():
    offer = {'damage_divisions': [{'requirement_index': 1, 'total': 10, 'min_each': 1}]}
    built = {'target_groups': [[{'instance_id': 1}], [{'player_id': 'bob'}, {'instance_id': 2}, {'instance_id': 3}]]}
    assert Bot.fill_damage_divisions(offer, built)
    assert built['damage_divisions'] == {'1': [4, 3, 3]}
    built['target_groups'][1] = []
    assert Bot.fill_damage_divisions(offer, built)
    assert built['damage_divisions'] == {'1': []}


def test_damage_allocation_refuses_more_targets_than_positive_shares():
    offer = {'damage_divisions': [{'requirement_index': 0, 'total': 1, 'min_each': 1}]}
    assert not Bot.fill_damage_divisions(offer, {'targets': [{'instance_id': 1}, {'instance_id': 2}]})


def test_ai_damage_allocation_follows_its_selected_targets():
    from mtg_analyzer.services.bot_policies.ai import BotDecision
    from tests.services.test_ai_bot import bot

    offer = {'type': 'cast_spell', 'instance_id': 1, 'requires_target': True,
             'targets': [{'count': 3, 'optional': True,
                          'options': [{'player_id': 'bob'}, {'instance_id': 2}, {'instance_id': 3}]}],
             'damage_divisions': [{'requirement_index': 0, 'total': 10, 'min_each': 1}]}
    chosen = bot().complete_decision(view(), [offer], BotDecision(offer_index=0, target_indices=[[2, 0]]))
    assert chosen['targets'] == [{'instance_id': 3}, {'player_id': 'bob'}]
    assert chosen['damage_divisions'] == {'0': [5, 5]}


@pytest.mark.parametrize('policy', [GreedyBot, SmartBot2])
def test_kicked_cast_uses_variant_targets_and_announces_damage(policy):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    session = make_game()
    keep(session, 'ann', 'bob')
    engine = session.engine
    while engine.state.current_step != 'main1':
        engine.advance_step()
    player = engine.state.player_by_id('ann')
    player.hand.clear()
    player.mana_pool.add('R', 10)
    card = spell('Fight with Fire', 'Kicker {5}{R}.\nFight with Fire deals 5 damage to target creature. '
                 'If this spell was kicked, it deals 10 damage divided as you choose among any number of targets instead.',
                 '{2}{R}', 3, 'Sorcery', {'R'})
    card.keywords = ['Kicker']
    source = GameObject(card, owner_id='ann', zone=Zone.HAND)
    bind_from_catalogue(source)
    player.add_to_zone(source, Zone.HAND)
    session._bot_decklists['ann'] = {'cards': [card], 'commanders': []}
    engine.state.player_by_id('bob').life = 10
    public = session.view(perspective='ann')
    offer = next(a for a in public['legal_actions'] if a['type'] == 'cast_spell' and a['instance_id'] == source.instance_id)
    assert offer['locked']  # No creatures exist for the ordinary branch.
    assert not offer['kicker_variant'].get('locked')
    bot = policy('ann')
    bot.prepare(session)
    if policy is SmartBot2:
        variants = bot._variants(bot._context(public), offer, [offer])
        chosen = next(a for a in variants if a.get('kicked'))
        assert chosen['targets'] == offer['kicker_variant']['targets']
        bot.play(public, [offer])
        assert any(candidate['action'] and candidate['action'].get('kicked')
                   for candidate in bot.memory['trace']['candidates'])
    else:
        chosen = {**offer, 'kicked': 1}
    built = bot._fill_in(public, chosen)
    assert built and built['kicked'] == 1
    assert [o.get('player_id') for o in built['targets']] == ['bob']
    assert built['damage_divisions'] == {'0': [10]}
    before = engine.state.player_by_id('bob').life
    session.apply_action(built, actor_id='ann')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('bob').life == before - 10
