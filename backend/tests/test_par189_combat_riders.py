"""Shared resolving defender permission and combat-assignment riders."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, text, power=3, toughness=4):
    return Card(id=name, name=name, type_line='Creature — Beast', is_creature=True,
                oracle_text=text, power=power, toughness=toughness)


def _game():
    return GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)


def _put(engine, card, controller='p1'):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


@pytest.mark.parametrize('name,text', [
    ('Mirror Wall', 'Defender\n{W}: Mirror Wall can attack this turn as though it didn\'t have defender.'),
    ('Nivix Cyclops', 'Defender\nWhenever you cast an instant or sorcery spell, Nivix Cyclops gets +3/+0 until end of turn and can attack this turn as though it didn\'t have defender.'),
    ('Ophidian', 'Whenever Ophidian attacks and isn\'t blocked, you may draw a card. If you do, Ophidian assigns no combat damage this turn.'),
    ('Laccolith Grunt', 'Whenever Laccolith Grunt becomes blocked, you may have it deal damage equal to its power to target creature. If you do, Laccolith Grunt assigns no combat damage this turn.'),
])
def test_real_cards_are_modeled(name, text):
    result = parse_oracle(_card(name, text))
    assert result.modeled, result.unclaimed


def test_permission_retains_defender_and_expires_in_cleanup():
    engine = _game()
    wall = _put(engine, _card('Mirror Wall', 'Defender\n{W}: Mirror Wall can attack this turn as though it didn\'t have defender.'))
    wall.summoning_sick = False
    engine.recompute_continuous_effects()
    p1, p2 = engine.state.players
    assert not engine._can_attack(p1, wall, p2)
    wall.activated_abilities[0].effects[0].apply(GameContext(engine.state, engine.rules))
    assert combat.has_defender(wall)
    assert engine._can_attack(p1, wall, p2)
    engine._step_cleanup()
    assert not engine._can_attack(p1, wall, p2)


@pytest.mark.parametrize('answer,suppressed', [('yes', True), ('decline', False)])
def test_laccolith_optional_damage_and_assignment_are_one_choice(answer, suppressed):
    engine = _game()
    source = _put(engine, _card('Laccolith Grunt', 'Whenever Laccolith Grunt becomes blocked, you may have it deal damage equal to its power to target creature. If you do, Laccolith Grunt assigns no combat damage this turn.'))
    victim = _put(engine, _card('Victim', '', toughness=9), 'p2')
    source.attacking = True
    source.combat_defender = {'kind': 'player', 'id': 'p2'}
    optional = source.triggered_abilities[0].effects[0]
    optional.apply(GameContext(engine.state, engine.rules), [victim])
    assert engine.state.pending_choice is not None
    engine.rules.resolve_choice(answer)
    assert victim.damage_marked == (3 if suppressed else 0)
    assert getattr(source, 'temp_assign_no_combat_damage', False) == suppressed
    engine.state.damage_prevention_disabled = True
    life = engine.state.players[1].life
    engine._deal_combat_damage_step(False)
    assert engine.state.players[1].life == life - (0 if suppressed else 3)
    engine._step_cleanup()
    assert not source.temp_assign_no_combat_damage


def test_assignment_restriction_applies_to_blockers_and_leaves_noncombat_damage():
    engine = _game()
    attacker = _put(engine, _card('Attacker', '', power=1, toughness=9))
    blocker = _put(engine, _card('Blocker', '', power=4), 'p2')
    attacker.attacking = True
    attacker.blocked_by = [blocker.instance_id]
    blocker.blocking = attacker.instance_id
    specs = match_clause('~ assigns no combat damage this turn')
    effect = build_effects(specs, source=blocker)[0]
    effect.apply(GameContext(engine.state, engine.rules))
    engine._deal_combat_damage_step(False)
    assert attacker.damage_marked == 0
    engine.rules.deal_damage(attacker, 2, source=blocker, combat=False)
    assert attacker.damage_marked == 2


def test_unbound_pronoun_and_unsupported_riders_fail_closed():
    assert match_clause('it assigns no combat damage this turn') is None
    assert match_clause('~ assigns no combat damage next turn') is None
    assert match_clause("~ can attack this turn as though it didn't have defender and flying") is None
    assert parse_effect_body('you may quibble. if you do, ~ assigns no combat damage this turn', reading=ClauseReading(self_subject=True)) is None
    assert parse_effect_body('you may draw a card. when you do, ~ assigns no combat damage this turn', reading=ClauseReading(self_subject=True)) is None


def test_pending_optional_and_assignment_flag_survive_clone_but_not_new_zone_visit():
    engine = _game()
    source = _put(engine, _card('Ophidian', 'Whenever Ophidian attacks and isn\'t blocked, you may draw a card. If you do, Ophidian assigns no combat damage this turn.'))
    source.triggered_abilities[0].effects[0].apply(GameContext(engine.state, engine.rules))
    cloned = GameEngine(engine.state.clone())
    cloned.rules.resolve_choice('yes')
    copied = cloned.state.find_object(source.instance_id)
    assert copied.temp_assign_no_combat_damage
    assert not source.temp_assign_no_combat_damage
    again = cloned.state.clone().find_object(source.instance_id)
    assert again.temp_assign_no_combat_damage
    again.reset_as_new_object()
    assert not again.temp_assign_no_combat_damage


@pytest.mark.parametrize('keyword', ['first strike', 'double strike'])
def test_assignment_prohibition_covers_both_damage_steps(keyword):
    engine = _game()
    source = _put(engine, _card('Striker', keyword))
    source.attacking = True
    source.combat_defender = {'kind': 'player', 'id': 'p2'}
    source.temp_assign_no_combat_damage = True
    engine.recompute_continuous_effects()
    life = engine.state.players[1].life
    engine._deal_combat_damage_step(True)
    engine._deal_combat_damage_step(False)
    assert engine.state.players[1].life == life


def test_laccolith_rig_flags_firing_host_and_announces_damage_target():
    engine = _game()
    host = _put(engine, _card('Host', '', power=5))
    victim = _put(engine, _card('Victim', '', toughness=9), 'p2')
    aura_card = Card(id='Laccolith Rig', name='Laccolith Rig', type_line='Enchantment — Aura',
                     oracle_text='Enchant creature\nWhenever enchanted creature becomes blocked, you may have it deal damage equal to its power to target creature. If you do, the first creature assigns no combat damage this turn.')
    aura = _put(engine, aura_card)
    aura.attached_to = host.instance_id
    effect = aura.triggered_abilities[0].effects[0]
    assert len(effect.target_specs) == 1
    context = GameContext(engine.state, engine.rules)
    context.trigger_event = {'instance_id': host.instance_id}
    effect.apply(context, [victim])
    engine.rules.resolve_choice('yes')
    assert victim.damage_marked == 5
    assert host.temp_assign_no_combat_damage
    assert not aura.temp_assign_no_combat_damage


@pytest.mark.parametrize('antecedent', [
    "put the top creature card of defending player's graveyard onto the battlefield under your control",
    'destroy target artifact defending player controls',
    'gain control of target artifact defending player controls',
    'gain control of target land defending player controls for as long as you control ~',
])
def test_independent_defending_player_antecedent_gaps_remain_fail_closed(antecedent):
    reading = ClauseReading(self_subject=True)
    assert parse_effect_body(antecedent, reading=reading) is None
    assert parse_effect_body(f'you may {antecedent}. if you do, ~ assigns no combat damage this turn', reading=reading) is None


@pytest.mark.parametrize('reading,subject', [
    (ClauseReading(self_subject=True), None),
    (ClauseReading(previous_subject=True), 'previous_target'),
    (ClauseReading(group_subject=True), 'trigger_subject'),
    (ClauseReading(attached_subject=True), 'trigger_subject'),
])
def test_assignment_pronouns_preserve_their_explicit_reading(reading, subject):
    [spec] = match_clause('it assigns no combat damage this turn', reading=reading)
    assert spec.type == 'assign_no_combat_damage'
    assert spec.params.get('subject') == subject
