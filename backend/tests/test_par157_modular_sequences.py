"""Unregistered cards recombine known subject, entry, timing and rider axes."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.catalogue.flicker_sequences import flicker_sequence_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature


@pytest.mark.parametrize('subject,reference', [('~', 'her'), ('target creature you control', 'that card')])
@pytest.mark.parametrize('timing', ['', ' at the beginning of your next upkeep'])
@pytest.mark.parametrize('counter', ['stun', 'dream', '+2/+2', 'first strike'])
def test_subject_timing_and_open_counter_kind_axes_compose(subject, reference, timing, counter):
    body = (f"exile {subject}, then return {reference} to the battlefield transformed under her owner's control"
            f" with a {counter} counter on it{timing}. if you do, draw a card.")
    spec = parse_effect_body(body)[0]
    assert spec.type == 'blink' and spec.params['transformed']
    assert spec.params['entry_counters'] == {counter: 1}
    assert spec.params['return_if_successful']
    assert spec.params['return_effects'][0]['type'] == 'draw'
    assert spec.params.get('return_step') == ('upkeep' if timing else None)


@pytest.mark.parametrize('tail', [
    'if you do, destroy target creature',
    'if you do, transform it',
    'with a counter of your choice on it',
    'with a stun counter on it, then ignore a rule of your choice',
])
def test_unknown_or_newly_targeted_return_bodies_stay_unclaimed(tail):
    assert flicker_sequence_specs("exile target creature. return it to the battlefield under its owner's control. " + tail) is None


def test_unregistered_transformed_return_finishes_entry_choices_before_successful_rider():
    eng = _engine()
    source = _bf(eng, Card(id='modular', name='Modular Example', type_line='Creature — Human',
        is_creature=True, power=2, toughness=3,
        oracle_text="{1}: Exile Modular Example, then return her to the battlefield transformed under her owner's control at the beginning of your next upkeep. If you do, create a 2/2 white Bird creature token.",
        layout='transform', back_name='Modular Back', back_type_line='Enchantment Creature — Spirit',
        back_power=4, back_toughness=5, back_oracle_text='As this permanent enters, choose a color.'))
    assert parse_oracle(source.card).modeled and parse_oracle(source.card.back_face()).modeled
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 1)
    eng.activate_ability(player, source); eng.resolve_until_stable()
    assert source.zone == Zone.EXILE
    eng._fire_delayed_triggers('upkeep'); eng.resolve_until_stable()
    assert source.zone == Zone.EXILE and eng.state.pending_choice
    assert not any(obj.name == 'Bird' for obj in eng.state.battlefield)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(clone.state.pending_choice['options'][0]['id'])
    returned = clone.state.find_object(source.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.transformed
    assert returned.power == 4 and returned.chosen_color
    assert sum(obj.name == 'Bird' for obj in clone.state.battlefield) == 1
    assert source.zone == Zone.EXILE


def test_single_faced_card_cannot_enter_transformed_or_run_successful_return_body():
    eng = _engine(); source = _bf(eng, _creature('Source')); target = _bf(eng, _creature('Single Face'))
    effects = parse_effect_body("exile target creature. return it to the battlefield transformed under its owner's control. if you do, draw a card")
    build_effects(effects, source)[0].apply(eng.rules.context, [target])
    assert target.zone == Zone.EXILE and not eng.state.player_by_id('p1').hand


def test_filtered_copy_intervening_draw_and_rider_share_one_clone_safe_sequence():
    eng = _engine(library=20); source = _bf(eng, _creature('Source'))
    recipient = _bf(eng, Card(id='recipient', name='Recipient', type_line='Enchantment — Shrine'))
    target = _bf(eng, _creature('Visitor', 4, 5))
    dredger = _bf(eng, _creature('Dredger', oracle_text='Dredge 1', keywords=['Dredge']))
    eng.rules.put_into_graveyard(dredger)
    from mtg_analyzer.parser.oracle.spec import EffectSpec
    effect = build_effects([EffectSpec('blink', {
        'target_kind': 'creature', 'return_step': 'upkeep', 'return_scope': 'controller',
        'departing_copy': {'recipients': 'you_control', 'filter': {'subtype': 'Shrine'},
                           'duration': 'end_of_turn'},
        'exile_effects': [{'type': 'draw', 'params': {'count': 1}}],
        'return_if_successful': True,
        'return_effects': [{'type': 'gain_life', 'params': {'amount': 3}}],
    })], source)[0]
    effect.apply(eng.rules.context, [target])
    assert eng.state.pending_choice['kind'] == 'dredge' and not eng.state.delayed_triggers
    assert recipient.name == 'Visitor'
    clone = GameEngine(eng.state.clone()); clone.resolve_pending_choice(str(dredger.instance_id))
    assert len(clone.state.delayed_triggers) == 1 and not eng.state.delayed_triggers
    clone._fire_delayed_triggers('upkeep'); clone.resolve_until_stable()
    assert clone.state.find_object(target.instance_id).zone == Zone.BATTLEFIELD
    assert clone.state.player_by_id('p1').life == 23
    clone._step_cleanup()
    assert clone.state.find_object(recipient.instance_id).name == 'Recipient'


def test_pending_final_chapter_survives_until_shared_transformed_return():
    eng = _engine()
    saga = _bf(eng, Card(id='modular-saga', name='Modular Saga', type_line='Enchantment — Saga',
        oracle_text="I — Exile this Saga, then return it to the battlefield transformed under your control.",
        layout='transform', back_name='Modular Saga Back', back_type_line='Creature — Spirit',
        back_power=3, back_toughness=4, back_oracle_text='Flying'))
    assert eng.rules.pending_triggers
    eng.resolve_until_stable()
    assert saga.zone == Zone.BATTLEFIELD and saga.transformed
    assert saga.name == 'Modular Saga Back' and saga.power == 3


def test_countered_final_chapter_no_longer_prevents_saga_sacrifice():
    eng = _engine()
    saga = _bf(eng, Card(id='drawing-saga', name='Drawing Saga', type_line='Enchantment — Saga',
                        oracle_text='I — Draw a card.'))
    eng.rules.put_triggers_on_stack()
    eng.rules.counter_ability(eng.state.stack[-1])
    eng.rules.check_state_based_actions()
    assert saga.zone == Zone.GRAVEYARD
