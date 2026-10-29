"""PAR-224: player turns, counted activation caps and shared library operands."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


def engine():
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    eng.begin_turn()
    return eng


def source(eng, text, name='Test', zone=Zone.BATTLEFIELD, owner='p1', type_line=None):
    card = Card(id=name, name=name, type_line=type_line or ('Sorcery' if zone == Zone.STACK else 'Artifact'), is_sorcery=zone == Zone.STACK, oracle_text=text)
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    return obj


def apply(eng, text, targets=None):
    src = source(eng, '', zone=Zone.STACK)
    specs = match_clause(text)
    assert specs is not None
    for effect in build_effects(specs, src):
        effect.apply(GameContext(eng.state, eng.rules), targets)


def test_time_warp_targets_the_chosen_player():
    eng = engine()
    obj = source(eng, 'Target player takes an extra turn after this one.', 'Time Warp', Zone.STACK)
    result = parse_oracle(obj.card)
    assert result.modeled
    effect = build_effects(result.specs[0].effects, obj)[0]
    assert effect.target_spec.kind == 'player'
    effect.apply(GameContext(eng.state, eng.rules), [eng.state.players[1]])
    assert eng.state.extra_turns == ['p2']
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'


@pytest.mark.parametrize('extra', [False, True])
def test_skip_next_turn_consumes_one_replacement_per_turn(extra):
    eng = engine()
    apply(eng, 'you skip your next turn')
    apply(eng, 'you skip your next turn')
    # The replacement survives its source leaving and is retained by clone.
    eng = GameEngine(eng.state.clone())
    if extra:
        eng.state.extra_turns.extend(['p1', 'p1'])
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'
    if not extra:
        eng.begin_turn()
        assert eng.state.active_player.id == 'p2'
        eng.begin_turn()
        assert eng.state.active_player.id == 'p2'
    assert not eng.state.players[0].player_effects
    eng.begin_turn()
    assert eng.state.active_player.id == 'p1'


def test_twice_cap_is_per_ability_and_resets_each_turn():
    eng = engine()
    obj = source(eng, '{0}: You gain 1 life. Activate no more than twice each turn.')
    assert parse_oracle(obj.card).modeled
    [ability] = obj.activated_abilities
    player = eng.state.players[0]
    assert ability.per_turn_limit == 2
    for _ in range(2):
        assert eng.can_activate(player, obj, ability)
        eng.activate_ability(player, obj, 0)
        eng.resolve_until_stable()
    assert not eng.can_activate(player, obj, ability)
    eng.begin_turn()
    assert eng.can_activate(player, obj, ability)


@pytest.mark.parametrize('position', ['top', 'bottom', 'the bottom'])
def test_shared_library_object_phrase_executes(position):
    eng = engine()
    target = source(eng, '', 'Target', owner='p2')
    # Use the existing permanent operand first; no source controller ownership assumption.
    apply(eng, f"put target permanent on {position} of its owner's library", [target])
    assert target.zone == Zone.LIBRARY
    assert target in eng.state.players[1].library


@pytest.mark.parametrize('text', [
    'target player takes an extra turn after this 1 if you win a coin flip',
    'you skip your next turn unless you pay {3}',
    'activate no more than twice each turn for each opponent',
    "put target creature on top of its owner's library at random",
    "put target imaginary creature on top of its owner's library",
])
def test_unknown_riders_fail_closed(text):
    assert match_clause(text) is None


def test_aethertow_uses_combat_target_filter_and_moves_card():
    from mtg_analyzer.game.targeting import legal_targets
    eng = engine()
    card = Card(id='aethertow', name='Aethertow', type_line='Instant', is_instant=True,
                oracle_text="Put target attacking or blocking creature on top of its owner's library.\nConspire")
    assert parse_oracle(card).modeled
    src = GameObject(card, owner_id='p1', zone=Zone.STACK)
    src.controller_id = 'p1'
    effect = build_effects(parse_oracle(card).specs[0].effects, src)[0]
    assert effect.target_spec.kind == 'attacking_or_blocking_creature'
    creature = GameObject(Card(id='bear', name='Bear', type_line='Creature', is_creature=True,
                               power=2, toughness=2), owner_id='p2', zone=Zone.BATTLEFIELD)
    creature.controller_id = 'p2'
    eng.state.add_to_battlefield(creature)
    assert legal_targets(eng.state, 'p1', effect.target_spec, src) == []
    creature.attacking = True
    assert any(t.get('instance_id') == creature.instance_id
               for t in legal_targets(eng.state, 'p1', effect.target_spec, src))
    effect.apply(GameContext(eng.state, eng.rules), [creature])
    assert creature.zone == Zone.LIBRARY
    assert creature in eng.state.players[1].library


def test_group_library_operation_uses_shared_operand_grammar():
    specs = match_clause("put all artifacts on top of their owners' libraries")
    assert specs is not None
    eng = engine()
    first = source(eng, '', 'First')
    second = source(eng, '', 'Second', owner='p2')
    apply(eng, "put all artifacts on top of their owners' libraries")
    assert first in eng.state.players[0].library
    assert second in eng.state.players[1].library


def test_granted_twice_cap_survives_recompute():
    eng = engine()
    target = source(eng, '', 'Host')
    aura = source(eng, 'Enchant artifact.\nEnchanted artifact has "{0}: You gain 1 life. Activate no more than twice each turn."', 'Grant', type_line='Enchantment — Aura')
    aura.attached_to = target.instance_id
    eng.recompute_continuous_effects()
    [ability] = target.granted_activated_abilities
    assert ability.per_turn_limit == 2
    for _ in range(2):
        eng.activate_ability(eng.state.players[0], target, 0)
        eng.resolve_until_stable()
        eng.recompute_continuous_effects()
    assert not eng.can_activate(eng.state.players[0], target, target.granted_activated_abilities[0])


def test_skip_targeted_extra_turn_preserves_regular_next_player():
    eng = engine()
    # p2 skips their first upcoming turn, which happens to be extra.
    src = source(eng, '', 'Skip source', zone=Zone.STACK, owner='p2')
    effect = build_effects(match_clause('you skip your next turn'), src)[0]
    effect.apply(GameContext(eng.state, eng.rules))
    eng.state.extra_turns.append('p2')
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'
    assert eng.state.players[1].turns_taken == 1
    assert not eng.state.players[1].player_effects


def test_targeted_extra_turn_resumes_regular_order_after_clone():
    eng = engine()
    apply(eng, 'target player takes an extra turn after this 1', [eng.state.players[1]])
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'
    eng = GameEngine(eng.state.clone())
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'  # p2's regular turn still follows
    eng.begin_turn()
    assert eng.state.active_player.id == 'p1'


def test_latest_extra_turn_is_taken_first():
    eng = engine()
    apply(eng, 'target player takes an extra turn after this 1', [eng.state.players[0]])
    apply(eng, 'target player takes an extra turn after this 1', [eng.state.players[1]])
    assert eng.state.extra_turns == ['p2', 'p1']
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'
    eng.begin_turn()
    assert eng.state.active_player.id == 'p1'
    eng.begin_turn()
    assert eng.state.active_player.id == 'p2'


def test_lethal_vapors_skip_belongs_to_activating_player():
    eng = engine()
    obj = source(eng, '{0}: Destroy Lethal Vapors. You skip your next turn. Any player may activate this ability.',
                 'Lethal Vapors')
    assert parse_oracle(obj.card).modeled
    eng.activate_ability(eng.state.players[1], obj, 0)
    eng.resolve_until_stable()
    assert not eng.state.players[0].player_effects
    assert eng.state.players[1].player_effects
    eng.begin_turn()
    assert eng.state.active_player.id == 'p1'
