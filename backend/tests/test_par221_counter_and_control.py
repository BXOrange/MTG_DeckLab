"""PAR-221: counter movement / targeted counter removal / counted temporary steals, parsed and executed."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_player_references import game, board
from tests.test_par210_object_phrases import cast  # noqa: F401  (shared fixtures import side effects)


def run(eng, source, text, targets):
    specs = parse_effect_body(text)
    assert specs is not None
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context, targets)


def test_move_counter_between_two_targets_moves_only_the_named_kind():
    eng = game()
    source = board(eng, creature('Source'))
    src, dst = board(eng, creature('A')), board(eng, creature('B'))
    src.counters.update({'+1/+1': 2, 'charge': 1})
    run(eng, source, 'move a +1/+1 counter from target creature onto a second target creature', [src, dst])
    assert src.counters.get('+1/+1') == 1 and src.counters.get('charge') == 1
    assert dst.counters.get('+1/+1') == 1


def test_move_all_of_one_kind_leaves_other_kinds():
    eng = game()
    source = board(eng, creature('Source'))
    src, dst = board(eng, creature('A')), board(eng, creature('B'))
    src.counters.update({'+1/+1': 3, 'charge': 2})
    run(eng, source, 'move all +1/+1 counters from target creature onto target creature', [src, dst])
    assert not src.counters.get('+1/+1') and src.counters.get('charge') == 2
    assert dst.counters.get('+1/+1') == 3


def test_move_counter_from_self_and_onto_self_announce_one_target():
    eng = game()
    source = board(eng, creature('Source'))
    other = board(eng, creature('Other'))
    source.counters['+1/+1'] = 2
    run(eng, source, 'move a +1/+1 counter from ~ onto target creature', [other])
    assert source.counters.get('+1/+1') == 1 and other.counters.get('+1/+1') == 1
    run(eng, source, 'move a +1/+1 counter from target creature onto ~', [other])
    assert source.counters.get('+1/+1') == 2 and not other.counters.get('+1/+1')


def test_move_with_nothing_of_that_kind_is_a_no_op():
    eng = game()
    source = board(eng, creature('Source'))
    src, dst = board(eng, creature('A')), board(eng, creature('B'))
    src.counters['charge'] = 1
    run(eng, source, 'move a +1/+1 counter from target creature onto another target creature', [src, dst])
    assert src.counters.get('charge') == 1 and not dst.counters.get('+1/+1')


def test_remove_named_counter_from_target():
    eng = game()
    source = board(eng, creature('Source'))
    tgt = board(eng, creature('A'))
    tgt.counters['-1/-1'] = 2
    run(eng, source, 'remove a -1/-1 counter from target creature', [tgt])
    assert tgt.counters.get('-1/-1') == 1
    run(eng, source, 'remove all -1/-1 counters from target creature', [tgt])
    assert not tgt.counters.get('-1/-1')


@pytest.mark.parametrize('text', [
    'move a +1/+1 counter from target creature onto up to one other target creature',
    'move a +2/+2 counter from target creature onto another target creature',
    'move a +1/+1 counter from target player onto target creature',
    'remove up to one -1/-1 counter from target creature',
])
def test_adversarial_variants_stay_unclaimed(text):
    assert match_clause(text) is None


def test_counted_temporary_steal_parses_with_its_untap_haste_tail():
    specs = parse_effect_body(
        'gain control of any number of target creatures until end of turn. untap those creatures. '
        'they gain haste until end of turn.')
    assert [s.type for s in specs] == ['gain_control_until_eot']
    assert specs[0].params['target_count'] > 1 and specs[0].params['optional']


@pytest.mark.parametrize('name', ['Afiya Grove', 'Daghatar the Adamant', 'Chainbreaker', 'Harness by Force'])
def test_real_cards_are_modeled(name):
    from tests.test_par210_player_references import DB
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled
