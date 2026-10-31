"""PAR-178: optional energy branches retain referents and announced targets."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

# Exact cached Oracle bodies, without optional reminder text.
CARDS = {
    'Aetherstream Leopard': ('Trample\nWhen this creature enters, you get {E}.\n'
        'Whenever this creature attacks, you may pay {E}. If you do, it gets +2/+0 until end of turn.'),
    'Hexgold Slith': ('When this creature enters, you get {E}{E}.\n'
        'Whenever this creature attacks, you may pay {E}{E}. If you do, it gains first strike until end of turn.\n'
        'Whenever this creature deals combat damage to a player, put a +1/+1 counter on it.'),
    'Conduit Goblin': ('When this creature enters, you get {E}{E}.\n'
        'At the beginning of combat on your turn, you may pay {E}. If you do, another target creature you control '
        'gets +1/+0 and gains haste until end of turn.'),
    "Consul's Shieldguard": ('When this creature enters, you get {E}{E}.\n'
        'Whenever this creature attacks, you may pay {E}. If you do, another target attacking creature '
        'gains indestructible until end of turn.'),
    'Eddytrail Hawk': ('Flying\nWhen this creature enters, you get {E}{E}.\n'
        'Whenever this creature attacks, you may pay {E}. If you do, another target attacking creature '
        'gains flying until end of turn.'),
}
TARGETED = ['Conduit Goblin', "Consul's Shieldguard", 'Eddytrail Hawk']


def card(name):
    return Card(id=name, name=name, type_line='Creature', is_creature=True,
                power=2, toughness=2, oracle_text=CARDS.get(name, ''))


def board(eng, name, controller='p1'):
    obj = GameObject(card(name), owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    obj.attacking = True
    return obj


def setup(name, energy=3):
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    source = board(eng, name)
    target = board(eng, 'Bear')
    eng.state.player_by_id('p1').counters['energy'] = energy
    return eng, source, target


def fire(eng, source):
    if source.name == 'Conduit Goblin':
        event = GameEvent(EventType.STEP_BEGIN, step='begin_combat', phase='combat', player_id='p1')
    else:
        event = GameEvent(EventType.ATTACKS, instance_id=source.instance_id,
                          controller_id='p1', player_id='p1', object_types=['creature', 'artifact'] if source.card.is_artifact else ['creature'])
    eng.state.fire_event(event)
    eng.rules.put_triggers_on_stack()


def choose_target(eng, target):
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.rules.resolve_choice(target.instance_id)


@pytest.mark.parametrize('name', CARDS)
def test_five_real_cards_modeled(name):
    assert parse_oracle(card(name)).modeled


@pytest.mark.parametrize('name', ['Aetherstream Leopard', 'Hexgold Slith'])
@pytest.mark.parametrize('answer', ['pay', 'decline', 'insufficient'])
def test_source_payoff_and_payment_paths(name, answer):
    eng, source, target = setup(name, energy=0 if answer == 'insufficient' else 3)
    fire(eng, source)
    eng.resolve_until_stable()
    if answer == 'insufficient':
        assert eng.state.pending_choice is None
    else:
        assert eng.state.pending_choice['kind'] == 'pay_energy_then'
        eng.resolve_pending_choice(answer)
    eng.recompute_continuous_effects()
    assert source.power == (4 if name == 'Aetherstream Leopard' and answer == 'pay' else 2)
    assert ('first_strike' in source.temp_keywords) == (name == 'Hexgold Slith' and answer == 'pay')
    assert target.power == 2 and not target.temp_keywords
    expected = 3 - (2 if name == 'Hexgold Slith' else 1) if answer == 'pay' else (0 if answer == 'insufficient' else 3)
    assert eng.state.player_by_id('p1').counters['energy'] == expected


@pytest.mark.parametrize('name', TARGETED)
@pytest.mark.parametrize('answer', ['pay', 'decline', 'insufficient'])
def test_target_announced_before_payment_and_selected_only(name, answer):
    eng, source, target = setup(name, energy=0 if answer == 'insufficient' else 3)
    bystander = board(eng, 'Bystander')
    bystander.attacking = False
    fire(eng, source)
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    options = {o['id'] for o in eng.state.pending_choice['options']}
    assert source.instance_id not in options
    if name != 'Conduit Goblin':
        assert bystander.instance_id not in options
    choose_target(eng, target)
    eng.resolve_until_stable()
    if answer == 'insufficient':
        assert eng.state.pending_choice is None
    else:
        assert eng.state.pending_choice['kind'] == 'pay_energy_then'
        eng.resolve_pending_choice(answer)
    eng.recompute_continuous_effects()
    keyword = {'Conduit Goblin': 'haste', "Consul's Shieldguard": 'indestructible', 'Eddytrail Hawk': 'flying'}[name]
    assert (keyword in target.temp_keywords) == (answer == 'pay')
    assert target.power == (3 if name == 'Conduit Goblin' and answer == 'pay' else 2)
    assert not source.temp_keywords and not bystander.temp_keywords


@pytest.mark.parametrize('name', TARGETED)
def test_target_becomes_illegal_before_resolution_no_energy_offer(name):
    eng, source, target = setup(name)
    fire(eng, source)
    choose_target(eng, target)
    if name == 'Conduit Goblin':
        target.controller_id = 'p2'
    else:
        target.attacking = False
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.player_by_id('p1').counters['energy'] == 3
    assert not target.temp_keywords


@pytest.mark.parametrize('name', ['Aetherstream Leopard', 'Conduit Goblin'])
def test_payment_clone_and_undo_retain_original_objects(name):
    eng, source, target = setup(name)
    fire(eng, source)
    if name in TARGETED:
        choose_target(eng, target)
    eng.resolve_until_stable()
    checkpoint = eng.state.clone()
    restored = GameEngine(checkpoint.clone())
    restored.resolve_pending_choice('pay')
    restored.recompute_continuous_effects()
    recipient = restored.state.find_object(target.instance_id if name in TARGETED else source.instance_id)
    assert recipient.power == (3 if name in TARGETED else 4)
    assert source.power == target.power == 2
    # Undo follows GameSession._restore: a fresh engine around the snapshot.
    undone = GameEngine(checkpoint.clone())
    undone.resolve_pending_choice('decline')
    assert undone.state.player_by_id('p1').counters['energy'] == 3
    assert undone.state.find_object(recipient.instance_id).temp_power == 0


def test_ambiguous_bare_source_pronoun_stays_unclaimed():
    assert parse_effect_body('you may pay {e}. if you do, it gets +2/+0 until end of turn') is None
    # PAR-207: a *reflexive* payoff names its own target, so nothing is ambiguous and `pay_cost_then` carries it.
    (reflexive,) = parse_effect_body('you may pay {e}. when you do, target creature gains flying until end of turn')
    assert reflexive.type == 'pay_cost_then' and reflexive.params['then_trigger'][0]['params']['target_kind'] == 'creature'


def test_source_new_zone_visit_is_not_pumped_after_payment():
    eng, source, target = setup('Aetherstream Leopard')
    fire(eng, source)
    eng.resolve_until_stable()
    source.zone = Zone.EXILE
    source.zone = Zone.BATTLEFIELD
    eng.resolve_pending_choice('pay')
    assert source.temp_power == target.temp_power == 0
    assert eng.state.player_by_id('p1').counters['energy'] == 2


def test_branch_controller_survives_source_control_change():
    eng, source, _ = setup('Aetherstream Leopard')
    # The same optional-payment primitive also supports untargeted payoffs.
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    effect, = build_effects([EffectSpec('pay_energy_then', {
        'amount': 1, 'effects': [{'type': 'gain_life', 'params': {'amount': 3}}],
    })], source)
    effect.apply(eng.rules.context)
    source.controller_id = 'p2'
    before = [p.life for p in eng.state.players]
    eng.resolve_pending_choice('pay')
    assert [p.life for p in eng.state.players] == [before[0] + 3, before[1]]


def test_target_announcement_survives_clone_before_payment_offer():
    eng, source, target = setup('Eddytrail Hawk')
    fire(eng, source)
    restored = GameEngine(eng.state.clone())
    restored.rules.resolve_choice(target.instance_id)
    restored.resolve_until_stable()
    restored.resolve_pending_choice('pay')
    assert 'flying' in restored.state.find_object(target.instance_id).temp_keywords
    assert not target.temp_keywords


def test_existing_coup_target_is_not_announced_twice():
    eng, source, target = setup('Confiscation Coup')
    # Its hand-authored wrapper and branch both describe the same target.
    effect = source.spell_effects[-1]
    assert len(effect.target_specs) == 1


def test_nested_reflexive_target_is_not_announced_early():
    # PAR-207: the whole payoff (target included) is the reflexive trigger's, so its target is chosen only after the
    # payment (RULE 603.12) -- it is no longer a body the ability would have to announce up front.
    (spec,) = parse_effect_body(
        'you may pay {e}. when you do, you gain 1 life, then target creature gains flying until end of turn'
    )
    assert spec.type == 'pay_cost_then' and 'effects' not in spec.params
    assert [e['type'] for e in spec.params['then_trigger']] == ['gain_life', 'pump']


def test_independent_target_groups_fail_closed_as_atomic_payment():
    assert parse_effect_body(
        'you may pay {e}. if you do, target creature gets +1/+1 until end of turn, '
        'then target creature gains flying until end of turn'
    ) is None


def test_group_firing_object_survives_energy_then_counter_choices():
    eng, _, _ = setup('Bear')
    dominator_card = Card(id='dominator', name='Assaultron Dominator', type_line='Artifact Creature',
        is_creature=True, power=2, toughness=2, oracle_text=(
            'When this creature enters, you get {E}{E}.\n'
            'Whenever an artifact creature you control attacks, you may pay {E}. If you do, '
            'put your choice of a +1/+1, first strike, or trample counter on that creature.'))
    source = GameObject(dominator_card, owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    attacker = GameObject(Card(id='servo', name='Servo', type_line='Artifact Creature',
                          is_creature=True, power=1, toughness=1), owner_id='p1', zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(attacker)
    attacker.attacking = True
    fire(eng, attacker)
    eng.resolve_until_stable()
    eng.resolve_pending_choice('pay')
    assert eng.state.pending_choice['kind'] == 'counter_kind'
    eng.resolve_pending_choice('0')
    assert attacker.counters.get('+1/+1') == 1
    assert source.counters.get('+1/+1', 0) == 0


def test_target_returned_zone_visit_does_not_receive_paid_payoff():
    eng, source, target = setup('Eddytrail Hawk')
    fire(eng, source)
    choose_target(eng, target)
    target.zone = Zone.EXILE
    target.zone = Zone.BATTLEFIELD
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.player_by_id('p1').counters['energy'] == 3
    assert not target.temp_keywords
