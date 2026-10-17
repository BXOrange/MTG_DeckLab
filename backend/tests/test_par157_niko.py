"""Niko copies depart from LKI, expire before end-step triggers and return independently."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game import copy_mechanics
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.token_database import default_token_database
from test_mec106_gift import _engine, _bf, _creature

NIKO = 'When Niko enters, create two Shard tokens. (They\'re enchantments with "{2}, Sacrifice this token: Scry 1, then draw a card.")\n{2}, {T}: Exile target nonlegendary creature you control. Shards you control become copies of it until the next end step. Return it to the battlefield under its owner\'s control at the beginning of the next end step.'


def _niko(eng):
    source = _bf(eng, Card(id='niko', name='Niko, Light of Hope', type_line='Legendary Creature — Human Wizard',
        is_creature=True, is_legendary=True, power=3, toughness=4, oracle_text=NIKO))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id))
    eng.resolve_until_stable()
    return source, [obj for obj in eng.state.battlefield if obj.name == 'Shard']


def _activate(eng, source, target):
    source.tapped = False
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 2)
    eng.activate_ability(player, source, targets=[target]); eng.resolve_until_stable()


def _end(eng):
    from mtg_analyzer.game.phases import GamePhase, GameStep
    eng._run_step(GamePhase('ending', []), GameStep('end'))


def test_niko_creates_real_shards_and_preserves_instance_state_when_copying():
    eng = _engine(); source, shards = _niko(eng)
    assert len(shards) == 2 and all(len(o.activated_abilities) == 1 for o in shards)
    assert specs_for(source.card)[0] is not specs_for(source.card)[0]
    target = _bf(eng, _creature('Visitor', 3, 4))
    target.temp_power = 5; target.counters['+1/+1'] = 2
    shards[0].counters['+1/+1'] = 1; shards[0].tapped = True
    _activate(eng, source, target)
    assert target.zone == Zone.EXILE
    assert all(o.name == 'Visitor' and o.is_token for o in shards)
    assert shards[0].power == 4 and shards[1].power == 3 and shards[0].tapped
    _end(eng)
    assert all(o.name == 'Shard' and not o.is_creature for o in shards)
    assert target.zone == Zone.BATTLEFIELD and target.power == 3


def test_copy_ends_before_end_step_trigger_checks_and_return_is_counterable():
    eng = _engine(); source, shards = _niko(eng)
    target = _bf(eng, _creature('End Visitor', oracle_text='At the beginning of your end step, draw a card.'))
    _activate(eng, source, target)
    # Hold priority so the independent delayed return remains on the stack.
    eng.interactive_priority = True
    _end(eng)
    assert all(o.name == 'Shard' for o in shards)
    assert len(eng.state.stack) == 1 and len(eng.state.player_by_id('p1').hand) == 0
    eng.rules.counter_ability(eng.state.stack[-1])
    eng.resolve_until_stable()
    assert target.zone == Zone.EXILE


def test_fixed_shard_set_survives_control_change_but_not_zone_revisit():
    eng = _engine(); source, shards = _niko(eng)
    target = _bf(eng, _creature('Visitor', 3, 4))
    _activate(eng, source, target)
    shards[0].controller_id = 'p2'
    later = eng.rules.create_token('p1', default_token_database().get_token('Shard'))[0]
    eng.rules.put_into_graveyard(source)
    assert later.name == 'Shard' and shards[0].name == 'Visitor'
    eng.rules.return_to_hand(target); eng.rules.exile(target)
    _end(eng)
    assert all(o.name == 'Shard' for o in shards) and shards[0].controller_id == 'p2'
    assert target.zone == Zone.EXILE


@pytest.mark.parametrize('duration', ['end_of_turn', None])
def test_newer_copy_outlives_niko_copy_expiration(duration):
    eng = _engine(); source, shards = _niko(eng)
    target = _bf(eng, _creature('Visitor', 3, 4)); newer = _bf(eng, _creature('New Copy', 5, 6))
    _activate(eng, source, target)
    copy_mechanics.become_copy(shards[0], newer, duration=duration)
    _end(eng)
    assert shards[0].name == 'New Copy' and shards[1].name == 'Shard'
    eng._step_cleanup(); eng.recompute_continuous_effects()
    assert shards[0].name == ('Shard' if duration else 'New Copy')


def test_niko_during_end_step_survives_cleanup_and_clone_until_following_end_step():
    eng = _engine(); source, shards = _niko(eng)
    _end(eng)
    target = _bf(eng, _creature('Visitor', 3, 4))
    _activate(eng, source, target)
    eng._step_cleanup(); eng.recompute_continuous_effects()
    assert all(o.name == 'Visitor' for o in shards)
    clone = GameEngine(eng.state.clone()); _end(clone)
    assert all(clone.state.find_object(o.instance_id).name == 'Shard' for o in shards)
    assert clone.state.find_object(target.instance_id).zone == Zone.BATTLEFIELD
    assert shards[0].name == 'Visitor' and target.zone == Zone.EXILE


def test_niko_targets_only_nonlegendary_creatures_you_control():
    eng = _engine(); source, shards = _niko(eng)
    enemy = _bf(eng, _creature('Enemy'), 'p2')
    for target in [source, enemy, shards[0]]:
        with pytest.raises(ValueError):
            _activate(eng, source, target)


def test_shard_activated_ability_sacrifices_scries_then_draws():
    eng = _engine(); _, shards = _niko(eng)
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 2)
    eng.activate_ability(player, shards[0]); eng.resolve_until_stable()
    assert shards[0] not in eng.state.battlefield
    assert eng.state.pending_choice['kind'] == 'scry'
    eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
    assert len(player.hand) == 1


def test_niko_uses_last_copied_face_and_can_exile_a_token():
    eng = _engine(); source, shards = _niko(eng)
    model = _bf(eng, _creature('Copied Model', 4, 5))
    target = _bf(eng, _creature('Original', 1, 1)); eng.rules.become_copy(target, model)
    target.is_token = True
    _activate(eng, source, target)
    assert all(o.name == 'Copied Model' and o.power == 4 for o in shards)
    _end(eng)
    assert all(o.name == 'Shard' for o in shards) and target not in eng.state.battlefield


def test_zone_revisit_ends_copy_on_a_nontoken_shard():
    eng = _engine(); source, _ = _niko(eng)
    shard = _bf(eng, Card(id='physical-shard', name='Physical Shard',
                         type_line='Enchantment — Shard'))
    target = _bf(eng, _creature('Visitor', 3, 4))
    _activate(eng, source, target)
    eng.rules.exile(shard); eng.rules.return_from_graveyard(shard, 'battlefield')
    assert shard.name == 'Physical Shard' and not shard._duration_copy_layers
    later = _bf(eng, _creature('Later Copy', 5, 5)); eng.rules.become_copy(shard, later)
    _end(eng)
    assert shard.name == 'Later Copy'


def test_cleanup_removes_older_eot_copy_beneath_niko_duration():
    eng = _engine(); source, shards = _niko(eng)
    # Retain Shard as a copiable subtype so the next activation includes it.
    first = _bf(eng, Card(id='shard-model', name='Shard Creature', type_line='Creature — Shard',
                         is_creature=True, power=3, toughness=4))
    eng.rules.become_copy_until_end_of_turn(shards[0], first)
    _end(eng)
    target = _bf(eng, _creature('Visitor', 5, 6)); _activate(eng, source, target)
    eng._step_cleanup(); eng.recompute_continuous_effects()
    assert shards[0].name == 'Visitor'
    _end(eng)
    assert shards[0].name == 'Shard'


def test_copy_expiration_precedes_return_entry_choice_and_survives_clone():
    eng = _engine(); source, shards = _niko(eng)
    model = _bf(eng, _creature('Model', 4, 5))
    target = _bf(eng, _creature('Clone', 0, 0, oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    eng.rules.become_copy(target, model); _activate(eng, source, target)
    assert all(o.name == 'Model' for o in shards)
    _end(eng)
    assert all(o.name == 'Shard' for o in shards) and target.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    clone = GameEngine(eng.state.clone()); clone.resolve_pending_choice(str(model.instance_id))
    assert clone.state.find_object(target.instance_id).name == 'Model'
    assert clone.state.find_object(target.instance_id).zone == Zone.BATTLEFIELD
    assert target.zone == Zone.EXILE


def test_copying_does_not_fire_the_copied_creatures_entry_ability():
    eng = _engine(); source, shards = _niko(eng)
    target = _bf(eng, _creature('Entry Visitor', oracle_text='When this creature enters, draw a card.'))
    _activate(eng, source, target)
    player = eng.state.player_by_id('p1')
    assert all(o.name == 'Entry Visitor' for o in shards) and not player.hand
    _end(eng)
    assert len(player.hand) == 1  # Only the returning original actually entered.
