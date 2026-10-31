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


def effects_for(source, text):
    specs = parse_effect_body(text)
    assert specs is not None, text
    return build_effects(specs, source)


def test_exact_mana_value_is_not_a_ceiling_and_x_is_announced():
    from mtg_analyzer.game.targeting import legal_targets
    from mtg_analyzer.models.cards.card import Card
    eng = game()
    source = board(eng, creature('Source'))
    source.x_paid = 2
    cheap = board(eng, creature('Cheap', cost='{1}'), 'p2')
    two = board(eng, creature('Two', cost='{2}'), 'p2')
    effect, = effects_for(source, 'gain control of target creature with mana value x')
    assert effect.target_spec.exact_mana_value == 'x'
    choices = legal_targets(eng.state, "p1", effect.target_spec, source=source)
    assert two.instance_id in {t["instance_id"] for t in choices}
    assert cheap.instance_id not in {t["instance_id"] for t in choices}
    effect.apply(eng.rules.context, [two])
    assert two.controller_id == 'p1' and two.tapped is False
    assert 'haste' not in two.temp_keywords


@pytest.mark.parametrize('counted', ['creatures', 'islands'])
def test_dynamic_power_bound_is_inclusive_and_rechecks_current_count(counted):
    from mtg_analyzer.game.targeting import legal_targets
    from mtg_analyzer.models.cards.card import Card
    eng = game()
    source = board(eng, creature('Source'))
    if counted == 'islands':
        board(eng, Card(id='island', name='Island', type_line='Basic Land — Island', is_land=True))
    target = board(eng, creature('Target', power=2, toughness=2), 'p2')
    effect, = effects_for(source, 'gain control of target creature with power less than or equal to '
                          f'the number of {counted} you control')
    eng.recompute_continuous_effects()
    assert target.instance_id not in {t["instance_id"] for t in legal_targets(eng.state, "p1", effect.target_spec, source=source)}
    if counted == 'creatures':
        board(eng, creature('Ally'))
    else:
        board(eng, Card(id='island2', name='Island', type_line='Basic Land — Island', is_land=True))
    assert target.instance_id in {t["instance_id"] for t in legal_targets(eng.state, "p1", effect.target_spec, source=source)}
    effect.apply(eng.rules.context, [target])
    assert target.controller_id == 'p1'


@pytest.mark.parametrize('ending', ['untap', 'lose_control', 'leave'])
def test_controlled_and_tapped_window_ends_permanently(ending):
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'), 'p2')
    source.tapped = True
    run(eng, source, 'gain control of target creature for as long as you control ~ and ~ remains tapped', [target])
    assert target.controller_id == 'p1'
    if ending == 'untap':
        source.tapped = False
    elif ending == 'lose_control':
        from mtg_analyzer.game.control import gain_control
        gain_control(eng.state, source, 'p2')
    else:
        eng.rules.destroy(source)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2'
    source.tapped = True
    source.controller_id = 'p1'
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2'


@pytest.mark.parametrize('window', ['you control ~', '~ remains on the battlefield', '~ remains tapped'])
def test_duration_that_ended_before_resolution_never_takes_control(window):
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'), 'p2')
    effect, = effects_for(source, f'gain control of target creature for as long as {window}')
    if window == 'you control ~':
        source.controller_id = 'p2'
    elif 'battlefield' in window:
        eng.rules.destroy(source)
    # Ability's controller is fixed at announcement (RULE 113.8).
    eng.rules.context.resolving_controller_id = 'p1'
    effect.apply(eng.rules.context, [target])
    assert target.controller_id == 'p2' and not target.control_effects


@pytest.mark.parametrize('name', ['Trade the Helm', 'Entrancing Melody', 'Beguiler of Wills',
                                'Rubinia Soulsinger', 'Helm of Possession', 'Vedalken Shackles'])
def test_residual_real_cards_are_modeled(name):
    from tests.test_par210_player_references import DB
    card = DB.get_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize('text', [
    'gain control of target creature with mana value x or greater',
    'gain control of target creature for as long as you control ~ or ~ remains tapped',
    'gain control of target creature with power less than or equal to the number of cards in your hand',
])
def test_unknown_bounds_and_duration_connectives_fail_closed(text):
    assert parse_effect_body(text) is None


def test_exchange_union_targets_execute_and_keep_controller_scopes():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.game.targeting import legal_targets
    eng = game()
    source = board(eng, creature('Source'))
    mine = board(eng, Card(id='artifact', name='Artifact', type_line='Artifact'))
    theirs = board(eng, creature('Theirs'), 'p2')
    effect, = effects_for(source, 'exchange control of target artifact or creature you control '
                          'and target artifact or creature an opponent controls')
    own = {t['instance_id'] for t in legal_targets(eng.state, 'p1', effect.target_spec, source=source)}
    opposing = {t['instance_id'] for t in legal_targets(eng.state, 'p1', effect.extra_target_specs[0], source=source)}
    assert mine.instance_id in own and theirs.instance_id not in own
    assert theirs.instance_id in opposing and mine.instance_id not in opposing
    effect.apply(eng.rules.context, [mine, theirs])
    assert mine.controller_id == 'p2' and theirs.controller_id == 'p1'


def test_target_enchanted_duration_survives_source_death_and_ends_when_aura_leaves():
    from mtg_analyzer.models.cards.card import Card
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'), 'p2')
    aura = board(eng, Card(id='aura', name='Aura', type_line='Enchantment — Aura'))
    aura.attached_to = target.instance_id
    run(eng, source, 'gain control of target creature for as long as that creature is enchanted', [target])
    assert target.controller_id == 'p1'
    eng.rules.destroy(source)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p1'
    eng.rules.destroy(aura)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2'


def test_power_duration_ends_even_if_source_remains_tapped():
    eng = game()
    source = board(eng, creature('Source', power=3, toughness=3))
    target = board(eng, creature('Target'), 'p2')
    source.tapped = True
    eng.recompute_continuous_effects()
    run(eng, source, "gain control of target creature with power less than or equal to ~'s power "
        "for as long as ~ remains tapped and that creature's power remains less than or equal to ~'s power", [target])
    assert target.controller_id == 'p1'
    target.counters['+1/+1'] = 2
    eng.recompute_continuous_effects()
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2' and source.tapped
    target.counters.clear()
    eng.recompute_continuous_effects()
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2'


def test_later_permanent_steal_survives_earlier_window_ending():
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'), 'p2')
    run(eng, source, 'gain control of target creature for as long as you control ~', [target])
    run(eng, source, 'gain control of target creature', [target])
    eng.rules.destroy(source)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p1'


def test_blinked_source_is_not_the_announced_source_visit():
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'), 'p2')
    effect, = effects_for(source, 'gain control of target creature for as long as you control ~')
    eng.rules.context.resolving_source_incarnation = source.zone_incarnation
    source.zone_incarnation += 1
    effect.apply(eng.rules.context, [target])
    assert target.controller_id == 'p2' and not target.control_effects


def test_independent_source_windows_survive_clone_and_expire_separately():
    from mtg_analyzer.game.control import control_window_active
    eng = game()
    first = board(eng, creature('First source'))
    second = board(eng, creature('Second source'))
    target = board(eng, creature('Target'), 'p2')
    text = 'gain control of target creature for as long as you control ~'
    run(eng, first, text, [target])
    run(eng, second, text, [target])
    clone = eng.state.clone()
    cloned_target = clone.find_object(target.instance_id)
    assert len(cloned_target.control_effects) == 2
    clone.find_object(first.instance_id).controller_id = 'p2'
    assert not control_window_active(clone, cloned_target, cloned_target.control_effects[0]['window'])
    assert control_window_active(eng.state, target, target.control_effects[0]['window'])
    eng.rules.destroy(first)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p1'
    eng.rules.destroy(second)
    eng.rules._revert_source_bound_control()
    assert target.controller_id == 'p2'


def test_dynamic_count_grammar_composes_other_known_nouns_and_rejects_unknown_ones():
    spec, = match_clause('gain control of target creature with power less than or equal to '
                         'the number of artifacts you control')
    assert spec.params['creature_filter']['power_le_count_selector']['filter'] == {'card_type': 'artifact'}
    assert match_clause('gain control of target creature with power less than or equal to '
                        'the number of blargs you control') is None


def test_union_target_blink_returns_the_target_and_leaves_source_in_place():
    eng = game()
    source = board(eng, creature('Source'))
    target = board(eng, creature('Target'))
    source_visit, target_visit = source.zone_incarnation, target.zone_incarnation
    run(eng, source, "exile target artifact or creature you control, then return it to the battlefield "
        "under its owner's control", [target])
    assert source.zone_incarnation == source_visit
    assert target.zone_incarnation > target_visit
    assert target in eng.state.battlefield
