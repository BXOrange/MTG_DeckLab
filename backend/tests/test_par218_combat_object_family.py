"""PAR-218: shared combat operands, durations, and derived P/T comparisons."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_player_references import DB, board, game
from tests.test_par210_object_phrases import cast


@pytest.mark.parametrize('text', [
    'target creature blocks this turn if able',
    'up to 2 target creatures you control block this turn if able',
    'each creature your opponents control blocks this turn if able',
    'target creature can block an additional creature this turn',
    '~ can block an additional 3 creatures this turn',
    'until end of turn, target creature you control assigns combat damage equal to its toughness rather than its power',
    'target creature assigns combat damage equal to its toughness rather than its power this turn',
    'each creature attacks or blocks this turn if able',
])
def test_temporary_instructions_compose_over_object_operands(text):
    assert parse_effect_body(text)


@pytest.mark.parametrize('text', [
    'target creature blocks during its next combat if able',
    'target creature blocks this combat if able',
    'target creature can block an additional creature this turn for each land you control',
    'target creature assigns combat damage equal to its toughness rather than its power this turn and eats a banana',
    'target creature blocks this turn this turn if able',
    'it blocks this turn if able',
])
def test_unknown_durations_qualifiers_and_unbound_pronouns_fail_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('text', [
    "creatures can't block if a banana is ripe",
    'each creature you control with glitter assigns combat damage equal to its toughness rather than its power',
    'equipped creature gets +0/+3 and can block an additional creature each combat and wins the game',
    '~ attacks each combat if able unless you win the lottery',
])
def test_statics_do_not_drop_unknown_conjuncts(text):
    assert static_effect_specs(text) is None


@pytest.mark.parametrize('name', [
    'Academic Dispute', 'Culling Mark', 'Anurid Swarmsnapper', 'Coastline Chimera',
    'Mounted Archers', 'Luminous Guardian', 'Grand Melee', 'Brave the Sands',
    'High Ground', "Cenn's Tactician", 'Angler Turtle', 'Goblin Assault',
    'Bedlam', 'Razorjaw Oni', 'Streetwise Negotiator', 'Ancient Lumberknot',
    'Arcades, the Strategist', 'Gauntlets of Light', 'Treefolk Umbra',
    "Vanguard's Shield", 'Hobble', 'Solid Footing', 'Bark of Doran',
    'Iron Golem', 'Razorgrass Screen', 'Act of Heroism',
])
def test_real_cards_are_fully_modeled(name):
    card = DB.get_card(name)
    assert card is not None
    result = parse_oracle(card)
    assert result.modeled, (name, result.unclaimed)


def source(eng, text):
    card = Card(id='combat-static', name='Combat Source', type_line='Enchantment', oracle_text=text)
    assert parse_oracle(card).modeled
    return board(eng, card)


def attack(obj, defender='p2'):
    obj.attacking = True
    obj.combat_defender = {'kind': 'player', 'id': defender}


def test_targeted_block_requirement_executes_respects_restrictions_and_expires():
    eng = game()
    attacker = board(eng, creature('Attacker'))
    blocker = board(eng, creature('Blocker'), 'p2')
    cast(eng, 'Target creature blocks this turn if able.', [blocker])
    attack(attacker)
    with pytest.raises(ValueError, match='must block'):
        eng._enforce_block_requirements()
    blocker.tapped = True
    eng._enforce_block_requirements()
    blocker.tapped = False
    eng._step_cleanup()
    attack(attacker)
    eng._enforce_block_requirements()
    assert not combat.combat_restrictions(blocker, 'must_block_if_able')


def test_plural_references_apply_to_exactly_the_previous_target_group():
    eng = game()
    first = board(eng, creature('First'), 'p2')
    second = board(eng, creature('Second'), 'p2')
    other = board(eng, creature('Other'), 'p2')
    cast(eng, 'Untap two target creatures. They block this turn if able.', [first, second])
    assert combat.combat_restrictions(first, 'must_block_if_able')
    assert combat.combat_restrictions(second, 'must_block_if_able')
    assert not combat.combat_restrictions(other, 'must_block_if_able')


def test_extra_blocks_are_additive_and_expire():
    eng = game()
    bear = board(eng, creature('Bear'))
    cast(eng, 'Target creature can block an additional creature this turn.', [bear])
    cast(eng, 'Target creature can block an additional creature this turn.', [bear])
    assert combat.max_blocks_for(bear) == 3
    eng._step_cleanup()
    assert combat.max_blocks_for(bear) == 1


def test_standing_group_block_capacity_keeps_counter_filter_and_controller():
    eng = game()
    source(eng, 'Each creature you control with a +1/+1 counter on it can block an additional creature each combat.')
    own = board(eng, creature('Own'))
    other = board(eng, creature('Other'), 'p2')
    own.counters['+1/+1'] = other.counters['+1/+1'] = 1
    eng.recompute_continuous_effects()
    assert combat.max_blocks_for(own) == 2
    assert combat.max_blocks_for(other) == 1
    own.counters.clear()
    eng.recompute_continuous_effects()
    assert combat.max_blocks_for(own) == 1


def test_group_attack_requirement_uses_controller_scope():
    eng = game()
    source(eng, 'Creatures your opponents control attack each combat if able.')
    own = board(eng, creature('Own'))
    other = board(eng, creature('Other'), 'p2')
    eng.recompute_continuous_effects()
    assert not combat.has(own, 'attacks_if_able')
    assert combat.has(other, 'attacks_if_able')


def test_toughness_assignment_uses_live_comparison_and_damage():
    eng = game()
    source(eng, 'Each creature you control with toughness greater than its power assigns combat damage equal to its toughness rather than its power.')
    wall = board(eng, creature('Wall', power=1, toughness=4))
    strong = board(eng, creature('Strong', power=5, toughness=2))
    enemy = board(eng, creature('Enemy', power=1, toughness=4), 'p2')
    eng.recompute_continuous_effects()
    assert combat.combat_restrictions(wall, 'damage_uses_toughness')
    assert not combat.combat_restrictions(strong, 'damage_uses_toughness')
    assert not combat.combat_restrictions(enemy, 'damage_uses_toughness')
    attack(wall)
    before = eng.state.player_by_id('p2').life
    eng._deal_combat_damage_step(first_strike_step=False)
    assert eng.state.player_by_id('p2').life == before - 4
    source(eng, 'Creatures you control get +5/+0.')
    eng.recompute_continuous_effects()
    assert not combat.combat_restrictions(wall, 'damage_uses_toughness')


def test_attached_compound_pump_and_permission_follow_host():
    eng = game()
    host = board(eng, creature('Host', power=1, toughness=4))
    equipment = source(eng, 'Equipped creature gets +0/+3 and can block an additional creature each combat.')
    equipment.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert host.toughness == 7 and combat.max_blocks_for(host) == 2
    equipment.attached_to = None
    eng.recompute_continuous_effects()
    assert host.toughness == 4 and combat.max_blocks_for(host) == 1


def test_host_stat_condition_uses_host_rather_than_source():
    eng = game()
    host = board(eng, creature('Host', power=1, toughness=4))
    equipment = source(eng, "As long as equipped creature's toughness is greater than its power, it assigns combat damage equal to its toughness rather than its power.")
    equipment.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert combat.combat_restrictions(host, 'damage_uses_toughness')
    source(eng, 'Creatures you control get +5/+0.')
    eng.recompute_continuous_effects()
    assert not combat.combat_restrictions(host, 'damage_uses_toughness')


def test_temporary_toughness_damage_cleans_up():
    eng = game()
    wall = board(eng, creature('Wall', power=1, toughness=4))
    cast(eng, 'Until end of turn, target creature assigns combat damage equal to its toughness rather than its power.', [wall])
    assert combat.combat_restrictions(wall, 'damage_uses_toughness')
    eng._step_cleanup()
    assert not combat.combat_restrictions(wall, 'damage_uses_toughness')


def test_conditional_block_restriction_tracks_an_untapped_land():
    eng = game()
    attacker = board(eng, creature('Attacker'))
    brawler = board(eng, DB.get_card('Branded Brawlers'), 'p2')
    assert parse_oracle(brawler.card).modeled
    land = board(eng, Card(id='forest', name='Forest', type_line='Basic Land — Forest', oracle_text=''), 'p2')
    attack(attacker)
    eng.recompute_continuous_effects()
    assert not eng.can_block(eng.state.player_by_id('p2'), brawler, attacker)
    land.tapped = True
    eng.recompute_continuous_effects()
    assert eng.can_block(eng.state.player_by_id('p2'), brawler, attacker)


def test_conditional_attack_restriction_reads_the_defending_player():
    eng = game()
    brawler = board(eng, DB.get_card('Branded Brawlers'))
    brawler.summoning_sick = False
    land = board(eng, Card(id='forest', name='Forest', type_line='Basic Land — Forest', oracle_text=''), 'p2')
    eng.recompute_continuous_effects()
    assert not eng._combat_restrictions_allow(brawler, 'cant_attack_unless', eng.state.player_by_id('p2'))
    land.tapped = True
    assert eng._combat_restrictions_allow(brawler, 'cant_attack_unless', eng.state.player_by_id('p2'))


def test_real_activated_extra_block_permission_stacks_and_expires():
    eng = game()
    swarmsnapper = board(eng, DB.get_card('Anurid Swarmsnapper'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('G', 4)
    for _ in range(2):
        eng.activate_ability(player, swarmsnapper)
        eng.resolve_until_stable()
    assert combat.max_blocks_for(swarmsnapper) == 3
    eng._step_cleanup()
    assert combat.max_blocks_for(swarmsnapper) == 1


def test_real_combined_attack_block_requirement_enforces_attacking():
    eng = game()
    golem = board(eng, DB.get_card('Iron Golem'))
    golem.summoning_sick = False
    eng.recompute_continuous_effects()
    assert combat.combat_restrictions(golem, 'must_block_if_able')
    with pytest.raises(ValueError, match='attacks each combat'):
        eng._enforce_attacks_if_able()
    golem.tapped = True
    eng._enforce_attacks_if_able()


def test_compound_pump_keeps_the_previous_target_and_extra_blocks():
    eng = game()
    target = board(eng, creature('Target'))
    other = board(eng, creature('Other'))
    cast(eng, DB.get_card('Act of Heroism').oracle_text, [target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness, combat.max_blocks_for(target)) == (4, 4, 2)
    assert (other.power, other.toughness, combat.max_blocks_for(other)) == (2, 2, 1)
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness, combat.max_blocks_for(target)) == (2, 2, 1)


def test_unknown_stat_relations_and_negated_combat_conditions_fail_closed():
    eng = game()
    bear = board(eng, creature('Bear'))
    assert not combat.matches_object_filter(bear, {'stat_relation': 'mana_value>power'})
    assert not eng._combat_condition_met(bear, {'kind': 'not', 'condition': {'kind': 'invented'}}, None, None)


def test_temporary_combined_requirements_bind_for_each_group_member():
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'Each creature attacks or blocks this turn if able.')
    eng.recompute_continuous_effects()
    for obj in (own, enemy):
        assert combat.has(obj, 'attacks_if_able')
        assert combat.combat_restrictions(obj, 'must_block_if_able')
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    for obj in (own, enemy):
        assert not combat.has(obj, 'attacks_if_able')
        assert not combat.combat_restrictions(obj, 'must_block_if_able')
