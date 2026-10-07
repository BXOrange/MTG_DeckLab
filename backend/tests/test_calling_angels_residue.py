"""Explicit blocking-cost decisions and own-turn replay history."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameActionError, GameSession
from mtg_analyzer.services.replay import blank_replay, build_replay_engine, serialize_replay
from tests.test_replay import _FakeLoader
from tests.game.catalogue.cards.test_calling_all_angels_deck import _game, _card, _filler, _attack


def _block_position():
    engine = _game()
    p1, p2 = engine.state.players
    angel = _card(engine, 'Archangel of Tithes')
    blocker = _filler(engine, 'Blocker', 'Creature — Bird', power=1, toughness=3,
                      player='p2', keywords=['Flying'])
    _attack(engine, [angel])
    engine.state.current_step = 'declare_blockers'
    p2.mana_pool.add('C', 2)
    return engine, p2, angel, blocker


def test_block_tax_decline_leaves_mana_and_combat_untouched():
    engine, player, angel, blocker = _block_position()
    with pytest.raises(ValueError, match='block tax declined'):
        engine.declare_blockers(player, [{'blocker': blocker, 'attacker': angel}], pay_block_tax=False)
    assert player.mana_pool.total() == 2
    assert blocker.blocking is None and not angel.blocked_by
    engine.declare_blockers(player, [], pay_block_tax=False)
    assert player.mana_pool.total() == 2
    assert player.id in engine.state.declared_blockers_this_combat


def test_block_tax_api_exposes_cost_and_pays_only_after_confirmation():
    engine, player, angel, blocker = _block_position()
    offer = next(a for a in engine.legal_actions(player) if a.get('instance_id') == blocker.instance_id)
    assert offer['block_tax_amount'] == 1
    session = GameSession(engine)
    action = {'type': 'declare_blockers', 'player_id': player.id,
              'assignments': [{'blocker': blocker.instance_id, 'attacker': angel.instance_id}]}
    with pytest.raises(GameActionError, match='block tax declined'):
        session.apply_action({**action, 'pay_block_tax': False})
    assert session.engine.state.player_by_id(player.id).mana_pool.total() == 2
    assert session.engine.state.find_object(blocker.instance_id).blocking is None
    session.apply_action({**action, 'pay_block_tax': True})
    assert session.engine.state.player_by_id(player.id).mana_pool.total() == 1
    assert session.engine.state.find_object(blocker.instance_id).blocking == angel.instance_id


@pytest.mark.parametrize('counts', [(2, 5), (4, 0)])
def test_replay_preserves_own_turn_counts_independently_of_round(counts):
    engine = _game()
    avenger = _card(engine, 'Serra Avenger', zone=Zone.HAND)
    engine.state.current_step = 'main1'
    engine.state.turn_nr = 20
    engine.state.internal_turn.number = 40
    for p, count in zip(engine.state.players, counts):
        p.turns_taken = count
    restored = build_replay_engine(serialize_replay(engine.state), _FakeLoader({avenger.name: avenger.card}))
    assert tuple(p.turns_taken for p in restored.state.players) == counts
    player = restored.state.players[0]
    player.mana_pool.add('W', 2)
    assert restored.can_cast(player, player.hand[0]) is (counts[0] > 3)


@pytest.mark.parametrize('active,expected', [(0, (4, 3)), (1, (4, 4))])
def test_legacy_replay_infers_turns_for_seats_before_and_after_active(active, expected):
    desc = blank_replay(2)
    desc['internal_turn']['number'] = 7 + active
    desc['active_player_index'] = active
    desc['turn_nr'] = 4
    engine = build_replay_engine(desc, _FakeLoader({}))
    assert tuple(p.turns_taken for p in engine.state.players) == expected


def test_replay_turn_edit_can_move_back_and_applies_new_active_seat_first():
    engine = build_replay_engine(blank_replay(2), _FakeLoader({}))
    session = GameSession(engine, mode='replay', require_setup=False)
    session.apply_action({'type': 'edit_set_turn', 'internal_turn': 8, 'active_player_id': 'p2'})
    assert tuple(p.turns_taken for p in engine.state.players) == (4, 4)
    session.apply_action({'type': 'edit_set_turn', 'internal_turn': 1, 'active_player_id': 'p1'})
    assert tuple(p.turns_taken for p in engine.state.players) == (1, 0)


def test_one_creature_blocking_two_attackers_pays_only_one_tax():
    engine, player, angel, _ = _block_position()
    wall = _filler(engine, 'Wall', 'Creature — Wall', power=1, toughness=6, player='p2',
                   oracle_text='Wall can block any number of creatures.', keywords=['Flying'])
    other = _filler(engine, 'Other attacker', power=1, toughness=1)
    other.attacking = True
    other.combat_defender = angel.combat_defender
    engine.declare_blockers(player, [{'blocker': wall, 'attacker': angel}, {'blocker': wall, 'attacker': other}])
    assert player.mana_pool.total() == 1
    assert wall.instance_id in angel.blocked_by and wall.instance_id in other.blocked_by
