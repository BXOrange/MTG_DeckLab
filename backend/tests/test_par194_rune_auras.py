"""PAR-194: a Rune grants an Equipment a static about its equipped creature."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.control import gain_control
from mtg_analyzer.game.effects.core import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import quoted_ability_grant_effects_list, static_effect_specs
from tests.support.deck_batch import RICH, activate, card, cast, filler, game
from tests.test_mec118_opponent_choice import _db_card


RUNES = (
    ('Rune of Flight', 'flying', 0, 0),
    ('Rune of Might', 'trample', 1, 1),
    ('Rune of Mortality', 'deathtouch', 0, 0),
    ('Rune of Speed', 'haste', 1, 0),
    ('Rune of Sustenance', 'lifelink', 0, 0),
)


def _board():
    eng = game()
    eng.state.player_by_id('p1').mana_pool.add_many(RICH)
    bear = filler(eng, 'Bear', power=2, toughness=2)
    gear = filler(eng, 'Equipment', type_line='Artifact — Equipment', oracle_text='Equip {1}', keywords=['Equip'])
    return eng, bear, gear


def _rune(eng, host, name='Rune of Flight'):
    rune = card(eng, name, zone=Zone.HAND)
    before = len(eng.state.player_by_id('p1').library)
    cast(eng, rune, targets=[host])
    assert rune.attached_to == host.instance_id
    assert len(eng.state.player_by_id('p1').library) == before - 1
    return rune


def _effect(eng, target, layer, params):
    source = filler(eng, 'Continuous source', type_line='Enchantment')
    ability = StaticAbility(layer, affects='objects', params=params, source=source)
    ability.object_ids = [target.instance_id]
    source.static_effects.append(ability)
    eng.recompute_continuous_effects()
    return source


@pytest.mark.parametrize('name,keyword,power,toughness', RUNES)
def test_real_rune_cast_draw_and_equipment_activation(name, keyword, power, toughness):
    eng, bear, gear = _board()
    assert parse_oracle(_db_card(name)).modeled
    _rune(eng, gear, name)
    assert not combat.has(bear, keyword)
    assert not combat.has(gear, keyword)
    assert gear._granted_static_abilities
    assert all(ability.source is gear for ability in gear._granted_static_abilities)
    activate(eng, gear, targets=[bear])
    assert combat.has(bear, keyword)
    assert (bear.power, bear.toughness) == (2 + power, 2 + toughness)
    assert not combat.has(gear, keyword)


@pytest.mark.parametrize('name,keyword,power,toughness', RUNES)
def test_real_rune_direct_creature_clause_is_separate_from_equipment_grant(name, keyword, power, toughness):
    eng, bear, gear = _board()
    _rune(eng, bear, name)
    assert combat.has(bear, keyword)
    assert (bear.power, bear.toughness) == (2 + power, 2 + toughness)
    assert not bear._granted_static_abilities
    assert not gear._granted_static_abilities


@pytest.mark.parametrize('name,keyword,power,toughness', RUNES)
def test_plain_artifact_host_does_not_gain_a_nested_static(name, keyword, power, toughness):
    eng, bear, gear = _board()
    host = filler(eng, 'Plain artifact', type_line='Artifact')
    _rune(eng, host, name)
    assert not host._granted_static_abilities
    assert not combat.has(bear, keyword)
    assert (bear.power, bear.toughness) == (2, 2)


def test_nested_static_preserves_equipment_condition_and_attachment_scope():
    specs = static_effect_specs(
        'as long as enchanted permanent is an equipment, it has "equipped creature gets +1/+1 and has trample."'
    )
    assert len(specs) == 1 and specs[0].type == 'grant_static_ability'
    assert specs[0].params['affects'] == 'attached_permanent'
    assert specs[0].params['active_if'] == {'kind': 'is_subtype', 'subtype': 'equipment', 'of': 'attached'}
    assert {inner['type'] for inner in specs[0].params['static_specs']} == {'anthem', 'grant_keyword'}
    assert all(inner['params']['affects'] == 'attached_permanent' for inner in specs[0].params['static_specs'])


@pytest.mark.parametrize('text', (
    'as long as target permanent is an equipment, it has "equipped creature has flying."',
    'as long as enchanted permanent is an equipment, it has "equipped creature has unknownability."',
    'as long as enchanted permanent is an equipment, it has "equipped creature has flying. draw a card."',
))
def test_unsupported_nested_grants_fail_closed(text):
    assert static_effect_specs(text) is None


@pytest.mark.parametrize('inner', (
    'enchanted creature is blue',
    'enchanted creature is an artifact in addition to its other types',
    'equipped creature is blue',
    'equipped creature is an artifact in addition to its other types',
))
def test_granted_attached_statics_cannot_claim_unrepresented_earlier_layers(inner):
    assert quoted_ability_grant_effects_list(inner) is None
    assert static_effect_specs(f'enchanted permanent has "{inner}."') is None


def test_requip_and_aura_departure_move_then_remove_the_nested_grant():
    eng, bear, gear = _board()
    other = filler(eng, 'Other Bear', power=2, toughness=2)
    rune = _rune(eng, gear, 'Rune of Might')
    activate(eng, gear, targets=[bear])
    assert (bear.power, bear.toughness) == (3, 3) and combat.has(bear, 'trample')
    activate(eng, gear, targets=[other])
    assert (bear.power, bear.toughness) == (2, 2) and not combat.has(bear, 'trample')
    assert (other.power, other.toughness) == (3, 3) and combat.has(other, 'trample')
    eng.rules.exile(rune)
    eng.recompute_continuous_effects()
    assert (other.power, other.toughness) == (2, 2) and not combat.has(other, 'trample')
    assert not gear._granted_static_abilities


def test_equipment_departure_cannot_leave_the_nested_bonus_behind():
    eng, bear, gear = _board()
    rune = _rune(eng, gear, 'Rune of Might')
    activate(eng, gear, targets=[bear])
    eng.rules.exile(gear)
    eng.rules.check_state_based_actions()
    eng.resolve_until_stable()
    assert rune.zone == Zone.GRAVEYARD
    assert (bear.power, bear.toughness) == (2, 2) and not combat.has(bear, 'trample')


def test_equipment_type_condition_uses_derived_subtypes_and_disappears_with_them():
    eng, bear, gear = _board()
    host = filler(eng, 'Changing artifact', type_line='Artifact', oracle_text='Equip {1}', keywords=['Equip'])
    _rune(eng, host)
    assert not host._granted_static_abilities
    source = _effect(eng, host, 'type', {'add_subtypes': ['Equipment']})
    assert host._granted_static_abilities
    assert eng.rules.attach_to_target(host, bear)
    eng.recompute_continuous_effects()
    assert combat.has(bear, 'flying')
    eng.rules.exile(source)
    eng.recompute_continuous_effects()
    assert not host._granted_static_abilities
    assert not combat.has(bear, 'flying')


@pytest.mark.parametrize('target_kind', ('equipment', 'aura'))
def test_later_ability_removal_ends_the_source_grant(target_kind):
    eng, bear, gear = _board()
    rune = _rune(eng, gear, 'Rune of Might')
    activate(eng, gear, targets=[bear])
    _effect(eng, gear if target_kind == 'equipment' else rune, 'ability', {'lose_all_abilities': True})
    assert not combat.has(bear, 'trample')
    assert (bear.power, bear.toughness) == (2, 2)
    assert not gear._granted_static_abilities


def test_later_creature_ability_removal_respects_nested_keyword_timestamps():
    eng, bear, gear = _board()
    _rune(eng, gear, 'Rune of Might')
    activate(eng, gear, targets=[bear])
    _effect(eng, bear, 'ability', {'lose_all_abilities': True})
    assert not combat.has(bear, 'trample')
    # The Equipment's separate P/T static is not an ability of the creature.
    assert (bear.power, bear.toughness) == (3, 3)


def test_rune_granted_after_equipment_ability_removal_still_functions():
    eng, bear, gear = _board()
    activate(eng, gear, targets=[bear])
    _effect(eng, gear, 'ability', {'lose_all_abilities': True})
    _rune(eng, gear, 'Rune of Might')
    assert combat.has(bear, 'trample')
    assert (bear.power, bear.toughness) == (3, 3)


def test_equipment_reattachment_updates_the_nested_static_timestamp():
    eng, bear, gear = _board()
    other = filler(eng, 'Other Bear', power=2, toughness=2)
    _rune(eng, gear)
    activate(eng, gear, targets=[bear])
    old_timestamp = gear.timestamp
    _effect(eng, other, 'ability', {'lose_all_abilities': True})
    activate(eng, gear, targets=[other])
    assert gear.timestamp > old_timestamp
    assert combat.has(other, 'flying')
    same_host_timestamp = gear.timestamp
    assert eng.rules.attach_to_target(gear, other)
    assert gear.timestamp == same_host_timestamp
    _effect(eng, other, 'ability', {'lose_all_abilities': True})
    assert not combat.has(other, 'flying')
    activate(eng, gear, targets=[other])
    assert gear.timestamp == same_host_timestamp
    assert not combat.has(other, 'flying')


def test_colossus_hammer_and_rune_keep_the_rules_example_relative_order_after_reattach():
    eng = game()
    bear = filler(eng, 'Bear', power=2, toughness=2)
    other = filler(eng, 'Other Bear', power=2, toughness=2)
    hammer = card(eng, 'Colossus Hammer')
    _rune(eng, hammer)
    activate(eng, hammer, targets=[bear])
    assert combat.has(bear, 'flying') and bear.power == 12
    activate(eng, hammer, targets=[other])
    assert combat.has(other, 'flying') and other.power == 12
    assert not combat.has(bear, 'flying') and bear.power == 2


def test_multiple_runes_and_recomputes_stack_once_and_clone_independently():
    eng, bear, gear = _board()
    _rune(eng, gear, 'Rune of Might')
    _rune(eng, gear, 'Rune of Might')
    _rune(eng, gear, 'Rune of Speed')
    activate(eng, gear, targets=[bear])
    abilities = tuple(gear._granted_static_abilities)
    for _ in range(3):
        eng.recompute_continuous_effects()
        assert (bear.power, bear.toughness) == (5, 4)
        assert combat.has(bear, 'trample') and combat.has(bear, 'haste')
        assert tuple(gear._granted_static_abilities) == abilities
    clone = GameEngine(eng.state.clone())
    clone_gear = clone.state.find_object(gear.instance_id)
    clone_gear.attached_to = None
    clone.recompute_continuous_effects()
    clone_bear = clone.state.find_object(bear.instance_id)
    assert (clone_bear.power, clone_bear.toughness) == (2, 2)
    assert (bear.power, bear.toughness) == (5, 4)


def test_equipment_control_change_keeps_the_rune_on_its_equipped_creature():
    eng, bear, gear = _board()
    rune = _rune(eng, gear, 'Rune of Might')
    activate(eng, gear, targets=[bear])
    gain_control(eng.state, gear, 'p2')
    eng.recompute_continuous_effects()
    assert rune.controller_id == bear.controller_id == 'p1'
    assert gear.controller_id == 'p2' and gear.attached_to == bear.instance_id
    assert combat.has(bear, 'trample') and (bear.power, bear.toughness) == (3, 3)
    other = filler(eng, 'Other controller bear', player='p2', power=2, toughness=2)
    eng.state.active_player_index = 1
    eng.state.player_by_id('p2').mana_pool.add_many(RICH)
    activate(eng, gear, targets=[other], player='p2')
    assert not combat.has(bear, 'trample') and (bear.power, bear.toughness) == (2, 2)
    assert combat.has(other, 'trample') and (other.power, other.toughness) == (3, 3)


def test_later_keyword_grant_does_not_restore_removed_printed_or_earlier_instances():
    eng = game()
    creature = filler(eng, 'Exalted creature', power=2, toughness=2, keywords=['Exalted'])
    _effect(eng, creature, 'ability', {'keywords': ['exalted']})
    assert combat.keyword_instances(creature, 'exalted') == 2
    _effect(eng, creature, 'ability', {'remove_keywords': ['exalted']})
    assert combat.keyword_instances(creature, 'exalted') == 0
    _effect(eng, creature, 'ability', {'keywords': ['exalted']})
    assert combat.keyword_instances(creature, 'exalted') == 1


def test_later_prowess_grant_fires_once_without_removed_printed_or_earlier_triggers():
    eng = game()
    creature = filler(eng, 'Prowess creature', power=2, toughness=2, keywords=['Prowess'])
    _effect(eng, creature, 'ability', {'keywords': ['prowess']})
    _effect(eng, creature, 'ability', {'remove_keywords': ['prowess']})
    _effect(eng, creature, 'ability', {'keywords': ['prowess']})
    spell = filler(eng, 'Test spell', type_line='Sorcery', zone=Zone.HAND, oracle_text='You gain 1 life.')
    cast(eng, spell)
    assert combat.keyword_instances(creature, 'prowess') == 1
    assert (creature.power, creature.toughness) == (3, 3)
