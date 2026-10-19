"""Reflexive conditions check at creation and once over the full resolving body."""
import pytest
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _hand, _creature

TOKEN = ('Create a 2/1 white Cat Warrior creature token. When you do, if you control '
         'a red permanent other than Gated Foundry, Gated Foundry deals damage equal to the number of creatures you control to any target.')


def _setup(red=False, source_red=False, body=TOKEN):
    eng = _engine()
    source = _bf(eng, Card(id='Gated Foundry', name='Gated Foundry', type_line='Planeswalker — Example',
        loyalty=3, color_identity={'R'} if source_red else {'W'}, oracle_text='0: ' + body))
    assert parse_oracle(source.card).modeled
    other = _bf(eng, _creature('Red creature', color_identity={'R'})) if red else None
    return eng, source, other


def _activate(eng, source):
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    eng.resolve_until_stable()


@pytest.mark.parametrize('source_red', [False, True])
def test_creation_occurs_but_false_condition_never_arms_a_later_trigger(source_red):
    eng, source, _ = _setup(source_red=source_red)
    _activate(eng, source)
    assert len([o for o in eng.state.battlefield if o.is_token]) == 1
    assert not eng.state.pending_choice and not eng.state.stack
    _bf(eng, _creature('Later red creature', color_identity={'R'}))
    eng.resolve_until_stable()
    assert not eng.state.pending_choice and eng.state.player_by_id('p2').life == 20


def test_true_condition_announces_later_targets_then_rechecks_before_resolving():
    eng, source, red = _setup(red=True)
    _activate(eng, source)
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.rules.resolve_choice('p2')
    eng.rules.put_into_graveyard(red)
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 20


def test_body_measurements_are_taken_at_resolution_and_clone_keeps_the_condition():
    eng, source, red = _setup(red=True)
    _activate(eng, source)
    clone = GameEngine(eng.state.clone())
    _bf(clone, _creature('Later creature'))
    clone.resolve_pending_choice('p2')
    assert clone.state.player_by_id('p2').life == 17  # red creature, token, later creature
    assert eng.state.player_by_id('p2').life == 20


def test_condition_is_checked_once_for_the_entire_body():
    body = ('Create a 2/1 white Cat Warrior creature token. When you do, if you control a red permanent '
            'other than Gated Foundry, destroy target creature. Draw a card.')
    eng, source, red = _setup(red=True, body=body)
    _activate(eng, source)
    eng.resolve_pending_choice(str(red.instance_id))
    eng.resolve_until_stable()
    assert red.zone == Zone.GRAVEYARD
    assert len(eng.state.player_by_id('p1').library) == 4


def test_other_than_source_excludes_only_the_original_zone_visit():
    eng, source, _ = _setup(source_red=True)
    original = source.zone_incarnation
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    eng.rules.blink(source)
    assert source.zone_incarnation != original
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('p2')
    assert eng.state.player_by_id('p2').life == 19


def test_no_created_token_does_not_fire_even_with_an_earlier_created_object(monkeypatch):
    eng, source, red = _setup(red=True)
    eng.rules.context.created_objects = [red]
    monkeypatch.setattr(eng.rules, 'create_token', lambda *args, **kwargs: [])
    source.activated_abilities[0].effects[0].apply(eng.rules.context)
    assert not eng.rules.pending_triggers
    assert not any(o.is_token for o in eng.state.battlefield)


@pytest.mark.parametrize('red_exists', [False, True])
def test_targeted_exile_uses_the_same_trigger_condition_axis(red_exists):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    if red_exists:
        _bf(eng, _creature('Red creature', color_identity={'R'}))
    target = _bf(eng, _creature('Dead creature'), 'p2')
    eng.rules.put_into_graveyard(target)
    text = ('exile target creature card from a graveyard. when you do, '
            'if you control a red permanent other than ~, draw a card')
    specs = parse_effect_body(text)
    assert specs
    build_effects(specs, source)[0].apply(eng.rules.context, [target])
    assert target.zone == Zone.EXILE
    eng.resolve_until_stable()
    assert len(eng.state.player_by_id('p1').library) == (4 if red_exists else 5)


def test_token_continuous_colors_apply_before_the_trigger_condition_is_checked():
    from mtg_analyzer.game.effects.core import EffectRegistry
    eng, source, _ = _setup()
    coloring = EffectRegistry.create('color', {'affects': 'creatures_you_control', 'colors': ['R']})
    coloring.source = source
    source.static_effects.append(coloring)
    _activate(eng, source)
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('p2')
    assert eng.state.player_by_id('p2').life == 19


@pytest.mark.full_cache
@pytest.mark.parametrize('red_exists', [False, True])
def test_ajani_printed_zero_body_uses_the_shared_condition_and_excludes_its_red_source(red_exists):
    from test_par157_back_selections import _cached
    eng = _engine()
    card = _cached('Ajani, Nacatl Pariah // Ajani, Nacatl Avenger').back_face()
    source = _bf(eng, card)
    if red_exists:
        _bf(eng, _creature('Other red creature', color_identity={'R'}))
    zero = next(spec for spec in parse_oracle(card).specs if (spec.cost or {}).get('loyalty') == 0)
    build_effects(zero.effects, source)[0].apply(eng.rules.context)
    eng.resolve_until_stable()
    assert len([obj for obj in eng.state.battlefield if obj.is_token]) == 1
    if red_exists:
        assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
        eng.resolve_pending_choice('p2')
    else:
        assert not eng.state.pending_choice
    assert eng.state.player_by_id('p2').life == (18 if red_exists else 20)


@pytest.mark.full_cache
def test_a_later_otherwise_payment_is_not_captured_as_a_creation_reflexive():
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached('Rose Room Treasurer')).modeled


@pytest.mark.full_cache
def test_eastfarthing_farmer_counts_foods_when_its_separate_trigger_resolves():
    from test_par157_back_selections import _cached
    eng = _engine()
    source = _hand(eng, _cached('Eastfarthing Farmer'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 2, 'W': 1})
    eng.cast_spell(player, source)
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    assert len([obj for obj in eng.state.battlefield if 'Food' in obj.card.type_line]) == 1
    clone = GameEngine(eng.state.clone())
    _bf(clone, Card(id='Second Food', name='Second Food', type_line='Artifact — Food'))
    clone.resolve_pending_choice(str(source.instance_id))
    copied = clone.state.find_object(source.instance_id)
    assert copied.power == source.power + 2 and copied.toughness == source.toughness + 2
    assert source.power == source.card.power


@pytest.mark.full_cache
def test_raiju_counts_a_modified_later_source_visit_as_another_creature():
    from test_par157_back_selections import _cached
    eng = _engine()
    source = _bf(eng, _cached('Thundering Raiju'))
    recipient = _bf(eng, _creature('Counter recipient'))
    source.summoning_sick = False
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.rules.resolve_choice(str(recipient.instance_id))
    eng.rules.blink(source)
    source.add_counters('+1/+1', 1)
    eng.resolve_until_stable()
    assert recipient.counters.get('+1/+1') == 1
    assert eng.state.player_by_id('p2').life == 18
