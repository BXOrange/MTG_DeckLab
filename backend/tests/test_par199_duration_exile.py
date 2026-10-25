"""PAR-199: duration-bound exile composes with target and trigger referents."""
import pytest
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from tests.support.deck_batch import game, card, filler, enter, answer, pick_label
from tests.test_mec118_opponent_choice import _db_card

MODELED = ('Annex Sentry', 'Earth Kingdom Jailer', 'Glass Casket', 'Grasping Giant',
           'Hixus, Prison Warden', 'Seam Rip', 'Silkwrap', 'Solitary Cell',
           'Colossal Whale', 'Trapped in the Screen')

@pytest.mark.parametrize('name', MODELED)
def test_real_cards_are_fully_modeled(name):
    parsed = parse_oracle(_db_card(name))
    assert parsed.modeled, parsed.unclaimed

@pytest.mark.parametrize('noun,scope,mv,bound', [
    ('artifact or creature', ' an opponent controls', 3, 'max_mana_value'),
    ('artifact, creature, or enchantment', ' an opponent controls', 3, 'min_mana_value'),
    ('nonland permanent', ' an opponent controls', 2, 'max_mana_value'),
    ('creature', '', 3, 'max_mana_value'),
])
def test_duration_preserves_target_filters(noun, scope, mv, bound):
    comparison = 'greater' if bound == 'min_mana_value' else 'less'
    specs = match_clause(f'exile up to 1 target {noun}{scope} with mana value {mv} or {comparison} until ~ leaves the battlefield')
    assert len(specs) == 1
    params = specs[0].params
    assert params['until_source_leaves'] and params['optional']
    assert params[bound] == mv
    if scope:
        assert params['target_kind'].endswith('_you_dont_control')

def test_post_mana_value_controller_scope_and_nonooze_quality_are_retained():
    assert match_clause('exile target creature with mana value 3 or less an opponent controls until ~ leaves the battlefield')[0].params['target_kind'] == 'creature_you_dont_control'
    specs = match_clause('exile target non-ooze creature an opponent controls until ~ leaves the battlefield')
    assert specs[0].params['creature_filter'] == {'without_subtype': 'Ooze'}
    assert specs[0].params['until_source_leaves']

@pytest.mark.parametrize('text', [
    'exile target creature until ~ leaves the battlefield and draw a card',
    'exile target creature with mana value 3 or less that a goat likes until ~ leaves the battlefield',
    'exile target creature until target permanent leaves the battlefield',
    'exile target opponent until ~ leaves the battlefield',
])
def test_unsupported_duration_or_target_suffixes_fail_closed(text):
    assert match_clause(text) is None

def test_other_card_clauses_remain_fail_closed():
    for name in ('Circle of Confinement', 'Gelatinous Cube', 'Banishment', 'Deputy of Detention'):
        assert not parse_oracle(_db_card(name)).modeled

@pytest.mark.parametrize('source_name,victim_type,mv', [
    ('Annex Sentry', 'Artifact', 3), ('Glass Casket', 'Creature', 3),
    ('Seam Rip', 'Enchantment', 2), ('Solitary Cell', 'Artifact', 3),
    ('Silkwrap', 'Creature', 3), ('Earth Kingdom Jailer', 'Enchantment', 4),
])
def test_real_entry_targets_only_eligible_opponents_then_returns_immediately(source_name, victim_type, mv):
    eng = game()
    victim = filler(eng, 'Victim', type_line=victim_type, mv=mv, power=2 if victim_type == 'Creature' else None, toughness=2 if victim_type == 'Creature' else None, player='p2')
    filler(eng, 'Own ineligible', type_line=victim_type, mv=mv, power=2 if victim_type == 'Creature' else None, toughness=2 if victim_type == 'Creature' else None)
    source = card(eng, source_name)
    enter(eng, source)
    labels = [o.get('label', '') for o in eng.state.pending_choice['options']]
    assert any('Victim' in x for x in labels)
    assert not any('Own ineligible' in x for x in labels)
    answer(eng, pick_label('Victim'))
    assert victim.zone == Zone.EXILE
    eng.rules.return_to_hand(source)
    assert victim.zone == Zone.BATTLEFIELD and victim.controller_id == 'p2'
    assert not eng.state.until_source_leaves_exiles

@pytest.mark.parametrize('blink', [False, True])
def test_source_departure_before_resolution_does_not_exile(blink):
    eng = game()
    victim = filler(eng, 'Victim', player='p2', mv=2, power=2, toughness=2)
    source = card(eng, 'Glass Casket')
    enter(eng, source)
    if blink:
        eng.rules.blink(source)
    else:
        eng.rules.return_to_hand(source)
    eng.resolve_pending_choice(pick_label('Victim')(eng.state.pending_choice))
    assert victim.zone == Zone.BATTLEFIELD
    assert not eng.state.until_source_leaves_exiles

def _double_block():
    eng = game()
    source = card(eng, 'Grasping Giant')
    one = filler(eng, 'First blocker', player='p2', power=2, toughness=2)
    two = filler(eng, 'Second blocker', player='p2', power=2, toughness=2)
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.player_by_id('p2'), [
        {'blocker': one, 'attacker': source}, {'blocker': two, 'attacker': source},
    ])
    eng.rules.put_triggers_on_stack()
    return eng, source, one, two

def test_giant_triggers_separately_for_each_actual_blocker():
    eng, source, one, two = _double_block()
    assert len(eng.state.stack) == 2
    eng.rules.resolve_top_of_stack()
    assert sum(o.zone == Zone.EXILE for o in (one, two)) == 1
    assert source.zone == Zone.BATTLEFIELD
    eng.resolve_until_stable()
    assert one.zone == two.zone == Zone.EXILE
    eng.rules.exile(source)
    assert one.zone == two.zone == Zone.BATTLEFIELD

def test_old_block_trigger_does_not_exile_a_blinked_blocker():
    eng, source, one, two = _double_block()
    eng.rules.blink(one)
    eng.resolve_until_stable()
    assert one.zone == Zone.BATTLEFIELD and two.zone == Zone.EXILE
    assert source.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('changed_after_announcement', [False, True])
def test_mana_ceiling_is_enforced_on_offer_and_again_on_resolution(changed_after_announcement):
    eng = game()
    source = card(eng, 'Glass Casket')
    victim = filler(eng, 'Victim', player='p2', mv=2, power=2, toughness=2)
    filler(eng, 'Too expensive', player='p2', mv=4, power=4, toughness=4)
    enter(eng, source)
    assert not any('Too expensive' in opt.get('label', '') for opt in eng.state.pending_choice['options'])
    # Keep a response window after announcement so the target can change.
    eng.rules.resolve_choice(pick_label('Victim')(eng.state.pending_choice))
    if changed_after_announcement:
        victim.card.converted_mana_cost = 4
    eng.resolve_until_stable()
    assert victim.zone == (Zone.BATTLEFIELD if changed_after_announcement else Zone.EXILE)


@pytest.mark.parametrize('blink_damager', [False, True])
def test_hixus_exiles_only_the_original_combat_damage_source(blink_damager):
    eng = game()
    source = card(eng, 'Hixus, Prison Warden')
    attacker = filler(eng, 'Damager', player='p2', power=2, toughness=2)
    eng.rules.blink(attacker)  # Different incarnation from the ability source.
    eng.rules.deal_damage(eng.state.player_by_id('p1'), 2, source=attacker, combat=True)
    eng.rules.put_triggers_on_stack()
    assert len(eng.state.stack) == 1
    if blink_damager:
        eng.rules.blink(attacker)
    eng.resolve_until_stable()
    assert attacker.zone == (Zone.BATTLEFIELD if blink_damager else Zone.EXILE)
    assert source.zone == Zone.BATTLEFIELD
    eng.rules.return_to_hand(source)
    assert attacker.zone == Zone.BATTLEFIELD


def test_previously_modeled_wolf_gets_its_own_pump_per_artifact_blocker():
    eng = game()
    source = card(eng, 'Tel-Jilad Wolf')
    one = filler(eng, 'First artifact', player='p2', type_line='Artifact Creature', power=2, toughness=2)
    two = filler(eng, 'Second artifact', player='p2', type_line='Artifact Creature', power=2, toughness=2)
    base = source.power
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.player_by_id('p2'), [
        {'blocker': one, 'attacker': source}, {'blocker': two, 'attacker': source},
    ])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.power == base + 6
    assert one.power == two.power == 2


@pytest.mark.parametrize('name,zone', [('Sylvan Basilisk', Zone.GRAVEYARD), ('Elven Warhounds', Zone.LIBRARY), ('Gloom Sower', Zone.BATTLEFIELD)])
def test_incidental_blocker_body_families_execute_per_blocker(name, zone):
    eng = game()
    source = card(eng, name)
    one = filler(eng, 'First blocker', player='p2', power=2, toughness=2)
    two = filler(eng, 'Second blocker', player='p2', power=2, toughness=2)
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    life1, life2 = p1.life, p2.life
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(p1, [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(p2, [{'blocker': one, 'attacker': source}, {'blocker': two, 'attacker': source}])
    eng.resolve_until_stable()
    assert one.zone == two.zone == zone
    assert source.zone == Zone.BATTLEFIELD
    if name == 'Gloom Sower':
        assert p1.life == life1 + 4 and p2.life == life2 - 4
    if name == 'Elven Warhounds':
        assert {o.instance_id for o in p2.library[-2:]} == {one.instance_id, two.instance_id}


def test_whale_retains_defending_player_scope_after_duration_delegation():
    eng = game(players=3)
    source = card(eng, 'Colossal Whale')
    defender = filler(eng, 'Defending victim', player='p2', power=2, toughness=2)
    filler(eng, 'Other opponent', player='p3', power=2, toughness=2)
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [{'attacker': source, 'defender': {'kind': 'player', 'id': 'p2'}}])
    eng.resolve_until_stable()
    labels = [o.get('label', '') for o in eng.state.pending_choice['options']]
    assert any('Defending victim' in x for x in labels)
    assert not any('Other opponent' in x for x in labels)
    answer(eng, pick_label('Defending victim'))
    assert defender.zone == Zone.EXILE
    eng.rules.return_to_hand(source)
    assert defender.zone == Zone.BATTLEFIELD


def test_duration_scope_reuse_does_not_crash_on_unrelated_conditional_regeneration_rider():
    # Necrite's sacrifice antecedent is outside the immediate destruction
    # sentence; the regeneration modifier must fail closed rather than crash.
    assert not parse_oracle(_db_card('Necrite')).modeled


def test_giant_does_not_trigger_for_another_attackers_blocker():
    eng = game()
    source = card(eng, 'Grasping Giant')
    other = filler(eng, 'Other attacker', power=2, toughness=2)
    blocker = filler(eng, 'Unrelated blocker', player='p2', power=2, toughness=2)
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source, other])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.player_by_id('p2'), [{'blocker': blocker, 'attacker': other}])
    eng.resolve_until_stable()
    assert blocker.zone == Zone.BATTLEFIELD
    assert not eng.state.until_source_leaves_exiles


def test_retaliation_grants_per_blocker_pump_to_the_blocked_creature():
    eng = game()
    card(eng, 'Retaliation')
    source = filler(eng, 'Our attacker', power=2, toughness=2)
    one = filler(eng, 'First blocker', player='p2', power=2, toughness=2)
    two = filler(eng, 'Second blocker', player='p2', power=2, toughness=2)
    eng.recompute_continuous_effects()
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.state.current_step = 'declare_blockers'
    eng.declare_blockers(eng.state.player_by_id('p2'), [{'blocker': one, 'attacker': source}, {'blocker': two, 'attacker': source}])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.power == source.toughness == 4
    assert one.power == two.power == 2
