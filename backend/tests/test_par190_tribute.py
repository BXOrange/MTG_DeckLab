"""PAR-190: Tribute N (RULE 702.104) -- the opponent's as-enters choice and the "if tribute wasn't paid" gate."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.test_mec118_opponent_choice import _db_card, _engine, _put

CARDS = [
    'Fanatic of Xenagos', 'Nessian Demolok', 'Nessian Wilds Ravager', 'Oracle of Bones', 'Ornitharch',
    'Pharagax Giant', 'Shrike Harpy', 'Siren of the Fanged Coast', 'Snake of the Golden Grove', 'Thunder Brute',
]


def cast(eng, name):
    spell = _put(eng, _db_card(name), 'p1', Zone.HAND)
    eng.state.players[0].mana_pool.add_many({c: 10 for c in 'WUBRGC'})
    eng.cast_spell(eng.state.players[0], spell)
    eng.resolve_until_stable()
    return spell


@pytest.mark.parametrize('name', CARDS)
def test_real_tribute_cards_modeled(name):
    assert parse_oracle(_db_card(name)).modeled


def test_paid_tribute_puts_counters_and_skips_the_rider():
    eng = _engine()
    spell = cast(eng, 'Ornitharch')
    choice = eng.state.pending_choice
    assert choice['kind'] == 'tribute' and choice['player_id'] == 'p2'
    eng.resolve_pending_choice('pay'); eng.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and spell.tribute_paid
    assert spell.counters.get('+1/+1') == 2
    assert not [o for o in eng.state.battlefield if o.is_token]


def test_declined_tribute_fires_the_rider():
    eng = _engine()
    spell = cast(eng, 'Ornitharch')
    eng.resolve_pending_choice('decline'); eng.resolve_until_stable()
    assert not spell.tribute_paid and not spell.counters.get('+1/+1')
    assert len([o for o in eng.state.battlefield if o.is_token]) == 2


def test_snake_gains_life_only_when_declined():
    eng = _engine()
    cast(eng, 'Snake of the Golden Grove')
    eng.resolve_pending_choice('decline'); eng.resolve_until_stable()
    assert eng.state.players[0].life == 24


def test_multiplayer_controller_picks_the_opponent_then_that_player_answers():
    eng = _engine(3)
    spell = cast(eng, 'Thunder Brute')
    assert eng.state.pending_choice['kind'] == 'tribute_opponent'
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('p3')
    assert eng.state.pending_choice['kind'] == 'tribute' and eng.state.pending_choice['player_id'] == 'p3'
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('pay'); clone.resolve_until_stable()
    assert clone.state.find_object(spell.instance_id).counters.get('+1/+1') == 3


def test_blinked_creature_is_a_new_object_without_the_old_payment():
    eng = _engine()
    spell = cast(eng, 'Thunder Brute')
    eng.resolve_pending_choice('pay'); eng.resolve_until_stable()
    assert spell.tribute_paid
    spell.reset_as_new_object()
    assert not spell.tribute_paid
