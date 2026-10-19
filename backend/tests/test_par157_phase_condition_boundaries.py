"""Phase intervening conditions gate triggering and the whole resolving body."""
import pytest
from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


def _upkeep(eng):
    eng.state.current_step = 'upkeep'
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', player_id='p1'))


def _thopter(eng, name='Other Thopter'):
    return _bf(eng, Card(id=name, name=name, type_line='Artifact Creature — Thopter',
        is_creature=True, power=1, toughness=1))


@pytest.mark.full_cache
def test_thopter_assembly_does_not_trigger_when_another_thopter_exists():
    eng = _engine()
    source = _bf(eng, _cached('Thopter Assembly'))
    _thopter(eng)
    _upkeep(eng)
    assert not eng.rules.pending_triggers
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert not any(obj.is_token for obj in eng.state.battlefield)


@pytest.mark.full_cache
def test_thopter_assembly_rechecks_the_condition_after_another_thopter_enters():
    eng = _engine()
    source = _bf(eng, _cached('Thopter Assembly'))
    _upkeep(eng)
    assert eng.rules.pending_triggers
    _thopter(eng)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert not any(obj.is_token for obj in eng.state.battlefield)


@pytest.mark.full_cache
def test_thopter_assembly_returns_and_creates_the_five_tokens_when_both_checks_pass():
    eng = _engine()
    source = _bf(eng, _cached('Thopter Assembly'))
    _upkeep(eng)
    eng.resolve_until_stable()
    assert source.zone == Zone.HAND
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 5
    assert all(obj.is_creature and obj.card.is_artifact and obj.power == obj.toughness == 1 for obj in tokens)
    assert all(combat.has_flying(obj) for obj in tokens)


@pytest.mark.full_cache
def test_thopter_assemblys_later_visit_counts_as_another_thopter_for_its_old_trigger():
    eng = _engine()
    source = _bf(eng, _cached('Thopter Assembly'))
    _upkeep(eng)
    queue, eng.rules.pending_triggers = eng.rules.pending_triggers, []
    eng.rules._place_triggers(queue)
    assert eng.state.stack
    old = source.zone_incarnation
    eng.rules.blink(source)
    assert source.zone_incarnation != old
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert not any(obj.is_token for obj in eng.state.battlefield)


def test_phase_condition_checks_the_complete_body_once_before_its_first_effect():
    eng = _engine()
    card = Card(id='Conditional Clock', name='Conditional Clock', type_line='Artifact', oracle_text=(
        'At the beginning of your upkeep, if you control a creature, destroy target creature you control. Draw a card.'))
    assert parse_oracle(card).modeled
    _bf(eng, card)
    victim = _bf(eng, _creature('Only creature'))
    _upkeep(eng)
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice(str(victim.instance_id))
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD
    assert len(eng.state.player_by_id('p1').library) == 4


def test_one_sentence_phase_condition_does_not_arm_a_trigger_while_false():
    eng = _engine()
    _bf(eng, Card(id='Conditional Clock', name='Conditional Clock', type_line='Artifact', oracle_text=(
        'At the beginning of your upkeep, if you control a creature, draw a card.')))
    _upkeep(eng)
    assert not eng.rules.pending_triggers
    _bf(eng, _creature('Late creature'))
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').library) == 5
