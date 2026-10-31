"""PAR-181: real targeted copy clauses and stable announcements/payment."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec

TEXTS = {
    'Force of Rowan': ('You may pay 1 life and exile a red card from your hand rather than pay this spell\'s mana cost.\n'
        'Copy target instant or sorcery spell. You may choose new targets for the copy.'),
    'Adric, Mathematical Genius': ('{2}{U}, {T}: Copy target activated or triggered ability you control. '
        'You may choose new targets for the copy.\nUltimate Sacrifice — {1}{U}, Sacrifice Adric: '
        'Counter target activated or triggered ability.\nDoctor\'s companion '
        '(You can have two commanders if the other is the Doctor.)'),
    'League Guildmage': ('{3}{U}, {T}: Draw a card.\n{X}{R}, {T}: Copy target instant or sorcery spell you '
        'control with mana value X. You may choose new targets for the copy.'),
    'Resonance Technician': ('Flying\nWhen this creature enters, you may discard a card. If you do, investigate twice.\n'
        '{T}, Tap X untapped artifacts you control: Copy target instant or sorcery spell you control with mana value X. '
        'You may choose new targets for the copy.'),
}


def card(name, type_line='Creature', text=None, mana_value=2, cost=''):
    return Card(id=name, name=name, type_line=type_line, oracle_text=TEXTS.get(name, '') if text is None else text,
        converted_mana_cost=mana_value, mana_cost_string=cost, is_creature='Creature' in type_line,
        is_instant='Instant' in type_line, is_sorcery='Sorcery' in type_line,
        power=2 if 'Creature' in type_line else None, toughness=2 if 'Creature' in type_line else None)


def engine():
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', []), ('p3', 'Chris', [])],
                              starting_life=20, starting_hand=0)
    return eng


def put(eng, c, owner='p1', zone=Zone.BATTLEFIELD):
    obj = GameObject(c, owner_id=owner, controller_id=owner, zone=zone)
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone != Zone.STACK:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def original(eng, owner='p1', mana_value=2, kind='spell', category='activated_ability', x=0, cost=''):
    obj = put(eng, card('Original', 'Instant' if kind == 'spell' else 'Creature',
                      'Deal 2 damage to target player.' if kind == 'spell' else '', mana_value, cost), owner,
              Zone.STACK if kind == 'spell' else Zone.BATTLEFIELD)
    obj.x_paid = x
    effects = obj.spell_effects if kind == 'spell' else build_effects([
        EffectSpec('damage', {'amount': 2, 'target_kind': 'player'})], obj)
    item = StackItem(kind=kind, controller_id=owner, obj=obj if kind == 'spell' else None,
                     source=obj if kind == 'ability' else None, effects=effects,
                     targets=[eng.state.player_by_id('p2')], category=category, x=x)
    eng.state.stack.append(item)
    return item


def fund(eng, colors=None):
    eng.state.player_by_id('p1').mana_pool.add_many(colors or {'U': 10, 'R': 10, 'C': 10})


def copy_effect(source):
    return next(e for a in source.activated_abilities for e in a.effects
                if e.__class__.__name__ in ('CopySpellEffect', 'CopyTargetAbilityEffect'))


def activate(eng, name, item, x=0, tap_choices=None):
    source = put(eng, card(name))
    fund(eng)
    index = 1 if name == 'League Guildmage' else 0
    eng.activate_ability(eng.state.player_by_id('p1'), source, index,
                         targets=[item if item.kind == 'ability' else item.obj], x=x, tap_choices=tap_choices)
    return source


def finish_retarget(eng, retain):
    choice = eng.state.pending_choice
    assert choice['kind'] == 'copy_targets'
    if retain:
        eng.rules.resolve_choice('decline')
    else:
        option = next(o for o in choice['options'] if o.get('player_id') == 'p3')
        eng.rules.resolve_choice(option['id'])


@pytest.mark.parametrize('name', TEXTS)
def test_four_real_cards_modeled_and_bound(name):
    c = card(name, 'Instant' if name == 'Force of Rowan' else 'Creature')
    assert parse_oracle(c).modeled
    eng = engine()
    obj = put(eng, c)
    if name == 'Force of Rowan':
        assert obj.spell_effects[0].target_spec.spell_filter['card_types'] == ['instant', 'sorcery']
    else:
        assert copy_effect(obj).choose_new_targets


@pytest.mark.parametrize('retain', [True, False])
def test_force_of_rowan_copies_opponents_spell_and_retargets(retain):
    eng = engine()
    item = original(eng, owner='p2')
    rowan = put(eng, card('Force of Rowan', 'Instant', mana_value=5, cost='{3}{R}{R}'), zone=Zone.HAND)
    fund(eng)
    eng.cast_spell(eng.state.player_by_id('p1'), rowan, targets=[item.obj])
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, retain)
    copy = eng.state.stack[-1]
    assert copy.stack_id != item.stack_id and copy.controller_id == 'p1'
    assert copy.targets == [eng.state.player_by_id('p2' if retain else 'p3')]
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == (16 if retain else 18)
    assert eng.state.player_by_id('p3').life == (20 if retain else 18)


@pytest.mark.parametrize('category', ['activated_ability', 'triggered_ability'])
@pytest.mark.parametrize('retain', [True, False])
def test_adric_makes_one_copy_without_x(category, retain):
    eng = engine()
    item = original(eng, kind='ability', category=category)
    source = activate(eng, 'Adric, Mathematical Genius', item)
    assert source.tapped
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, retain)
    copied = eng.state.stack[-1]
    assert copied.kind == 'ability' and copied.source is item.source
    assert copied.stack_id != item.stack_id
    assert copied.category == category
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == (16 if retain else 18)
    assert eng.state.player_by_id('p3').life == (20 if retain else 18)


@pytest.mark.parametrize('wrong', ['opponent', 'spell'])
def test_adric_rejects_wrong_original_without_paying(wrong):
    eng = engine()
    item = original(eng, owner='p2' if wrong == 'opponent' else 'p1',
                    kind='spell' if wrong == 'spell' else 'ability')
    source = put(eng, card('Adric, Mathematical Genius'))
    fund(eng)
    before = eng.state.player_by_id('p1').mana_pool.total()
    with pytest.raises(ValueError):
        eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[item])
    assert not source.tapped and eng.state.player_by_id('p1').mana_pool.total() == before


@pytest.mark.parametrize('retain', [True, False])
def test_league_guildmage_exact_paid_x_and_target_choice(retain):
    eng = engine()
    item = original(eng, mana_value=2)
    fund(eng, {'R': 1, 'C': 2})
    source = put(eng, card('League Guildmage'))
    eng.activate_ability(eng.state.player_by_id('p1'), source, 1, targets=[item.obj], x=2)
    assert eng.state.player_by_id('p1').mana_pool.total() == 0
    source.x_paid = 7  # A later activation cannot rewrite the resolving X.
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, retain)
    assert len(eng.state.stack) == 2


@pytest.mark.parametrize('wrong', ['value', 'controller', 'kind'])
def test_league_guildmage_rejects_illegal_original_before_costs(wrong):
    eng = engine()
    item = original(eng, owner='p2' if wrong == 'controller' else 'p1',
                    mana_value=3 if wrong == 'value' else 2, kind='ability' if wrong == 'kind' else 'spell')
    source = put(eng, card('League Guildmage'))
    fund(eng)
    before = eng.state.player_by_id('p1').mana_pool.total()
    with pytest.raises(ValueError):
        eng.activate_ability(eng.state.player_by_id('p1'), source, 1,
                             targets=[item if wrong == 'kind' else item.obj], x=2)
    assert not source.tapped and eng.state.player_by_id('p1').mana_pool.total() == before


@pytest.mark.parametrize('x', [0, 2])
def test_resonance_technician_taps_exactly_announced_artifacts(x):
    eng = engine()
    item = original(eng, mana_value=x)
    artifacts = [put(eng, card(f'Rock{i}', 'Artifact')) for i in range(3)]
    source = activate(eng, 'Resonance Technician', item, x=x,
                      tap_choices=[o.instance_id for o in artifacts[:x]])
    assert source.tapped
    assert [o.tapped for o in artifacts] == [i < x for i in range(3)]
    source.x_paid = 9
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, True)
    assert len(eng.state.stack) == 2


@pytest.mark.parametrize('chosen', [1, 3])
def test_resonance_rejects_wrong_count_without_partial_payment(chosen):
    eng = engine()
    item = original(eng, mana_value=2)
    artifacts = [put(eng, card(f'Rock{i}', 'Artifact')) for i in range(3)]
    source = put(eng, card('Resonance Technician'))
    with pytest.raises(ValueError):
        eng.activate_ability(eng.state.player_by_id('p1'), source, 0, targets=[item.obj], x=2,
                             tap_choices=[o.instance_id for o in artifacts[:chosen]])
    assert not source.tapped and not any(o.tapped for o in artifacts)


def test_copy_target_choice_survives_clone_and_has_new_stack_identity():
    eng = engine()
    item = original(eng)
    activate(eng, 'League Guildmage', item, x=2)
    eng.rules.resolve_top_of_stack()
    restored = GameEngine(eng.state.clone())
    finish_retarget(restored, False)
    assert restored.state.stack[-1].stack_id != item.stack_id
    assert restored.state.stack[-1].targets == [restored.state.player_by_id('p3')]
    assert eng.state.pending_choice['kind'] == 'copy_targets'


@pytest.mark.parametrize('text', [
    'copy target instant or sorcery spell you control with mana value x or less. you may choose new targets for the copy',
    'copy target activated or triggered ability you control from a creature source. you may choose new targets for the copy',
    'copy target instant or sorcery spell, except the copy is red. you may choose new targets for the copy',
])
def test_unknown_copy_qualifiers_remain_unclaimed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('change', ['controller', 'left', 'recast'])
def test_league_original_must_remain_legal_and_same_stack_visit(change):
    eng = engine()
    item = original(eng)
    activate(eng, 'League Guildmage', item, x=2)
    if change == 'controller':
        item.controller_id = 'p2'
    else:
        eng.state.stack.remove(item)
        item.obj.zone = Zone.GRAVEYARD
        if change == 'recast':
            item.obj.zone = Zone.STACK
            replacement = StackItem(kind='spell', obj=item.obj, controller_id='p1',
                                    effects=item.effects, targets=item.targets)
            eng.state.stack.insert(0, replacement)
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice is None
    assert len(eng.state.stack) == (0 if change == 'left' else 1)


def test_adric_original_ability_must_still_be_controlled_by_you():
    eng = engine()
    item = original(eng, kind='ability')
    activate(eng, 'Adric, Mathematical Genius', item)
    item.controller_id = 'p2'
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice is None and eng.state.stack == [item]


def test_shared_counter_scope_is_preserved_after_binding():
    from mtg_analyzer.game.targeting import legal_targets
    eng = engine()
    mine = original(eng)
    theirs = original(eng, owner='p2')
    source = put(eng, card('Counter Test', 'Instant', 'Counter target spell you control.'))
    effect, = source.spell_effects
    assert effect.target_spec.kind == 'spell_you_control'
    options = legal_targets(eng.state, 'p1', effect.target_spec, source=source)
    assert [o['instance_id'] for o in options] == [mine.obj.instance_id]
    assert theirs.obj.instance_id not in [o['instance_id'] for o in options]


def test_target_x_spell_mana_value_includes_its_own_x():
    eng = engine()
    item = original(eng, mana_value=1, x=2, cost='{X}{R}')
    assert item.obj.mana_value == 3
    source = activate(eng, 'League Guildmage', item, x=3)
    source.x_paid = 8
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, True)
    assert eng.state.stack[-1].x == 2


def test_copy_without_target_change_permission_keeps_original_targets():
    eng = engine()
    item = original(eng)
    source = put(eng, card('Simple Copy', 'Creature', '{T}: Copy target instant or sorcery spell you control.'))
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[item.obj])
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice is None
    assert eng.state.stack[-1].targets == item.targets


def test_shared_tap_x_cost_grammar_recombines_with_creatures():
    eng = engine()
    item = original(eng)
    source = put(eng, card('Creature tap copy', text=(
        '{T}, Tap X untapped creatures you control: Copy target instant or sorcery spell '
        'you control with mana value X. You may choose new targets for the copy.')))
    helpers = [put(eng, card(f'Helper{i}')) for i in range(3)]
    assert parse_oracle(source.card).modeled
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[item.obj], x=2,
                         tap_choices=[helper.instance_id for helper in helpers[:2]])
    assert source.tapped and [o.tapped for o in helpers] == [True, True, False]
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, True)
    assert len(eng.state.stack) == 2


def test_unknown_tap_x_cost_filter_stays_unmodeled():
    assert not parse_oracle(card('Uncharged cost', text=(
        '{T}, Tap X untapped artifacts you control that have never attacked: Copy target '
        'instant or sorcery spell you control with mana value X. You may choose new targets for the copy.'))).modeled


def test_gogo_keeps_announced_x_copy_count():
    eng = engine()
    item = original(eng, kind='ability')
    source = put(eng, card('Gogo, Master of Mimicry', text=(
        '{X}{X}, {T}: Copy target activated or triggered ability you control X times. '
        'You may choose new targets for the copies. This ability cannot be copied and X cannot be 0.')))
    fund(eng)
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[item], x=2)
    source.x_paid = 7
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, True)
    finish_retarget(eng, True)
    assert len(eng.state.stack) == 3


def test_gained_glacian_looks_at_announced_x_after_source_x_changes():
    eng = engine()
    source = put(eng, card('Glacian, Powerstone Engineer', text=(
        '{T}, Tap X untapped artifacts you control: Look at the top X cards of your library. '
        'Put one of those cards into your hand and the rest into your graveyard.\n'
        'Partner (You can have two commanders if both have partner.)')))
    assert parse_oracle(source.card).modeled
    artifacts = [put(eng, card(f'Glacian Rock{i}', 'Artifact')) for i in range(3)]
    library = [put(eng, card(f'Library{i}', 'Sorcery'), zone=Zone.LIBRARY) for i in range(4)]
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, x=2,
                         tap_choices=[o.instance_id for o in artifacts[:2]])
    source.x_paid = 8
    eng.rules.resolve_top_of_stack()
    choice = eng.state.pending_choice
    assert choice['kind'] == 'look_top_select'
    choices = [o for o in choice['options'] if o.get('instance_id') is not None]
    assert len(choices) == 2
    eng.resolve_pending_choice(choices[0]['id'])
    player = eng.state.player_by_id('p1')
    assert len(player.hand) == 1 and len(player.graveyard) == 1 and len(player.library) == 2
    assert {o.instance_id for o in player.hand + player.graveyard} == {o.instance_id for o in library[-2:]}


@pytest.mark.parametrize('changed', [False, True])
def test_shared_counter_own_spell_scope_still_holds_at_resolution(changed):
    eng = engine()
    item = original(eng)
    counter = put(eng, card('Scoped Counter', 'Instant', 'Counter target spell you control.', cost='{U}'), zone=Zone.HAND)
    fund(eng)
    eng.cast_spell(eng.state.player_by_id('p1'), counter, targets=[item.obj])
    if changed:
        item.controller_id = 'p2'
    eng.rules.resolve_top_of_stack()
    assert (item in eng.state.stack) == changed
    assert item.obj.zone == (Zone.STACK if changed else Zone.GRAVEYARD)
    assert counter.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('name', ['League Guildmage', 'Resonance Technician'])
def test_normal_action_offers_originals_for_all_affordable_x_before_announcement(name):
    eng = engine()
    item = original(eng, mana_value=2)
    other_value = original(eng, mana_value=3)
    source = put(eng, card(name))
    fund(eng)
    artifacts = [put(eng, card(f'Offer Rock{i}', 'Artifact')) for i in range(4)]
    index = 1 if name == 'League Guildmage' else 0
    action = next(a for a in eng.legal_actions(eng.state.player_by_id('p1'))
                  if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id
                  and a['ability_index'] == index)
    assert action['has_x'] and action['min_x'] == 0 and action['max_x'] > 2
    assert not action.get('locked')
    requirement, = action['targets']
    assert requirement['mana_value_from_x'] is True
    assert {o['instance_id']: o['mana_value'] for o in requirement['options']} == {
        item.obj.instance_id: 2, other_value.obj.instance_id: 3,
    }
    assert source.x_paid == 0  # Offer generation never announces X.
    # Follow the normal action protocol, choosing the MV2 option at X2.
    eng.activate_ability(eng.state.player_by_id('p1'), source, index, targets=[item.obj], x=2,
                         tap_choices=[o.instance_id for o in artifacts[:2]] if name == 'Resonance Technician' else None)
    eng.rules.resolve_top_of_stack()
    finish_retarget(eng, True)
    assert eng.state.stack[-1].targets == item.targets


@pytest.mark.parametrize('name', ['League Guildmage', 'Resonance Technician'])
@pytest.mark.parametrize('wrong', ['missing', 'opponent', 'unaffordable', 'ability'])
def test_normal_action_locks_when_no_payable_x_has_a_legal_original(name, wrong):
    eng = engine()
    if wrong != 'missing':
        original(eng, owner='p2' if wrong == 'opponent' else 'p1',
                 mana_value=8 if wrong == 'unaffordable' else 2,
                 kind='ability' if wrong == 'ability' else 'spell')
    source = put(eng, card(name))
    fund(eng, {'R': 1, 'C': 3})
    for i in range(3):
        put(eng, card(f'Unavailable Rock{i}', 'Artifact'))
    index = 1 if name == 'League Guildmage' else 0
    action = next(a for a in eng.legal_actions(eng.state.player_by_id('p1'))
                  if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id
                  and a['ability_index'] == index)
    assert action['has_x'] and action['max_x'] == 3
    assert action['locked'] and action['targets'][0]['options'] == []
