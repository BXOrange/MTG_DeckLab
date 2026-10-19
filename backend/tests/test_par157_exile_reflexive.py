"""Exile success creates a fresh reflexive trigger with later target announcement."""
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached

TOKEN = 'exile target creature card from a graveyard. when you do, create a 1/1 colorless spirit creature token'
COUNTER = 'exile target noncreature card from a graveyard. when you do, put a +1/+1 counter on target creature you control'


def _back(eng):
    card = _cached('Teachings of the Kirin // Kirin-Touched Orochi')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    eng.resolve_until_stable()
    for _ in range(2):
        eng.rules.advance_sagas(eng.state.player_by_id('p1'))
        eng.resolve_until_stable()
        if eng.state.pending_choice:
            assert eng.state.pending_choice['kind'] == 'trigger_target'
            eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
            eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    return source


def _attack(eng, source, mode):
    source.summoning_sick = False
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_mode'
    eng.resolve_pending_choice(str(mode))
    assert eng.state.pending_choice['kind'] == 'trigger_target'


@pytest.mark.parametrize('text', [TOKEN, COUNTER])
def test_reflexive_payoff_does_not_announce_its_targets_with_the_initial_exile(text):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    specs = parse_effect_body(text)
    assert specs and len(specs) == 1 and specs[0].type == 'exile'
    effect = build_effects(specs, source)[0]
    assert len(effect.target_specs) == 1
    assert effect.target_specs[0].kind.startswith('any_graveyard_')


def test_no_new_exile_does_not_trigger_even_after_an_earlier_success(monkeypatch):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    old = _bf(eng, _creature('Earlier'))
    eng.rules.context.exile(old)
    target = _bf(eng, _creature('Unmoved'))
    eng.rules.put_into_graveyard(target)
    effect = build_effects(parse_effect_body(TOKEN), source)[0]
    monkeypatch.setattr(eng.rules, 'exile', lambda obj: None)
    effect.apply(eng.rules.context, [target])
    assert not eng.rules.pending_triggers
    assert target.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('dragon', [False, True])
def test_reflexive_effect_conditions_survive_spec_serialization(dragon):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    if dragon:
        _bf(eng, Card(id='Dragon', name='Dragon', type_line='Creature — Dragon', is_creature=True, power=2, toughness=2))
    target = _bf(eng, _creature('Victim'))
    eng.rules.put_into_graveyard(target)
    text = 'exile target creature card from a graveyard. when you do, draw a card if you control a dragon'
    build_effects(parse_effect_body(text), source)[0].apply(eng.rules.context, [target])
    assert len(eng.rules.pending_triggers) == 1
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').library) == (4 if dragon else 5)


@pytest.mark.parametrize('text', [
    'exile 2 target creature cards from graveyards. when you do, draw a card',
    'exile target creature card from a graveyard. when you do, if the moon is purple, draw a card',
    'exile target creature card from a graveyard. when you do, fly to the moon',
    'exile a creature card from your graveyard. when you do, draw a card',
    'exile an instant or sorcery card from your graveyard. when you do, tap target creature',
])
def test_unimplemented_batching_and_unknown_conditions_or_bodies_fail_closed(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
@pytest.mark.parametrize('mode', [0, 1])
def test_kirin_back_modes_announce_the_payoff_only_after_exile_and_survive_clone(mode):
    eng = _engine()
    source = _back(eng)
    creature = _bf(eng, _creature('Dead creature'), 'p2')
    artifact = _bf(eng, Card(id='Dead artifact', name='Dead artifact', type_line='Artifact'), 'p2')
    for target in (creature, artifact):
        eng.rules.put_into_graveyard(target)
    target = creature if mode == 0 else artifact
    old_tokens = len([o for o in eng.state.battlefield if o.is_token])
    _attack(eng, source, mode)
    offered = {o['id'] for o in eng.state.pending_choice['options']}
    assert str(target.instance_id) in offered
    assert str((artifact if mode == 0 else creature).instance_id) not in offered
    assert str(source.instance_id) not in offered
    if mode == 0:
        eng.resolve_pending_choice(str(target.instance_id))
        eng.resolve_until_stable()
        assert target.zone == Zone.EXILE
        assert len([o for o in eng.state.battlefield if o.is_token]) == old_tokens + 1
    else:
        eng.resolve_pending_choice(str(target.instance_id))
        assert target.zone == Zone.EXILE and eng.state.pending_choice['kind'] == 'trigger_target'
        assert str(source.instance_id) in {o['id'] for o in eng.state.pending_choice['options']}
        clone = GameEngine(eng.state.clone())
        clone.resolve_pending_choice(str(source.instance_id))
        assert clone.state.find_object(source.instance_id).counters.get('+1/+1') == 1
        assert not source.counters.get('+1/+1')


@pytest.mark.full_cache
def test_reflexive_controller_is_the_original_ability_controller_after_source_control_change():
    eng = _engine()
    source = _back(eng)
    recipient = next(o for o in eng.state.battlefield if o.is_token)
    old = recipient.counters.get('+1/+1', 0)
    target = _bf(eng, Card(id='Dead artifact', name='Dead artifact', type_line='Artifact'), 'p2')
    eng.rules.put_into_graveyard(target)
    _attack(eng, source, 1)
    source.controller_id = 'p2'
    eng.resolve_pending_choice(str(target.instance_id))
    choice = eng.state.pending_choice
    assert choice and choice['kind'] == 'trigger_target' and choice['player_id'] == 'p1'
    assert str(source.instance_id) not in {o['id'] for o in choice['options']}
    eng.resolve_pending_choice(str(recipient.instance_id))
    assert recipient.counters['+1/+1'] == old + 1


@pytest.mark.full_cache
def test_initial_target_revisit_fizzles_without_creating_a_spirit():
    eng = _engine()
    source = _back(eng)
    target = _bf(eng, _creature('Dead creature'), 'p2')
    eng.rules.put_into_graveyard(target)
    _attack(eng, source, 0)
    eng.rules.resolve_choice(str(target.instance_id))
    before = len([o for o in eng.state.battlefield if o.is_token])
    eng.rules.exile(target)
    eng.rules._remove_from_current_zone(eng.state.player_by_id(target.owner_id), target)
    eng.state.player_by_id('p2').add_to_zone(target, Zone.GRAVEYARD)
    eng.resolve_until_stable()
    assert target.zone == Zone.GRAVEYARD
    assert len([o for o in eng.state.battlefield if o.is_token]) == before
    assert not eng.state.pending_choice
