"""Draw LKI, current return characteristics and permanent, visit-scoped haste."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell

VANISH = "Exile target creature. You draw cards equal to that creature's power. At the beginning of your next upkeep, return that card to the battlefield under its owner's control. If you do, discard cards equal to that creature's toughness."
OBZEDAT = "When Obzedat enters, target opponent loses 2 life and you gain 2 life.\nAt the beginning of your end step, you may exile Obzedat. If you do, return it to the battlefield under its owner's control at the beginning of your next upkeep. It gains haste."


def _vanish(eng, target):
    spell = _hand(eng, _spell('Vanish into Memory', VANISH))
    eng.state.player_by_id('p1').mana_pool.add('C', 1)
    eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=[target]); eng.resolve_until_stable()
    return spell


def _upkeep(eng, player='p1'):
    eng.state.active_player_index = next(i for i, p in enumerate(eng.state.players) if p.id == player)
    eng._fire_delayed_triggers('upkeep'); eng.resolve_until_stable()


def _discard_all_choices(eng):
    while eng.state.pending_choice:
        pending = eng.state.pending_choice
        assert pending['kind'] == 'choose_objects' and pending['action'] == 'discard'
        eng.resolve_pending_choice(pending['options'][0]['id'])


def test_vanish_draws_departing_power_then_discards_new_toughness_with_clone():
    eng = _engine(library=20); target = _bf(eng, _creature('Visitor', 2, 4), 'p2')
    target.temp_power = 3; target.counters['+1/+1'] = 1
    _vanish(eng, target)
    player = eng.state.player_by_id('p1')
    assert len(player.hand) == 6 and target.zone == Zone.EXILE
    _upkeep(eng, 'p2'); assert target.zone == Zone.EXILE
    _upkeep(eng)
    assert target.zone == Zone.BATTLEFIELD and target.controller_id == 'p2'
    assert eng.state.pending_choice['player_id'] == 'p1'
    cloned = GameEngine(eng.state.clone())
    _discard_all_choices(cloned)
    assert len(cloned.state.player_by_id('p1').hand) == 2
    assert len(player.hand) == 6


@pytest.mark.parametrize('missing', ['token', 'revisit', 'hand'])
def test_failed_return_never_discards(missing):
    eng = _engine(); target = _bf(eng, _creature('Visitor', 2, 4))
    target.is_token = missing == 'token'
    _vanish(eng, target)
    if missing != 'token':
        eng.rules.return_to_hand(target)
        if missing == 'revisit': eng.rules.exile(target)
    player = eng.state.player_by_id('p1'); before = len(player.hand)
    _upkeep(eng)
    assert eng.state.pending_choice is None and len(player.hand) == before
    assert target.zone != Zone.BATTLEFIELD


def test_return_copy_choice_finishes_before_current_toughness_discard():
    eng = _engine(library=20)
    model = _bf(eng, _creature('Copy Model', 2, 3), 'p2')
    target = _bf(eng, _creature('Clone', 0, 0, oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    eng.rules.become_copy(target, model)
    target.temp_power = 3
    _vanish(eng, target)
    assert len(eng.state.player_by_id('p1').hand) == 5
    _upkeep(eng)
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    assert target.zone == Zone.EXILE
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(model.instance_id))
    assert clone.state.pending_choice['action'] == 'discard'
    _discard_all_choices(clone)
    assert len(clone.state.player_by_id('p1').hand) == 2


def test_returned_animated_land_has_no_toughness_and_discards_nothing():
    eng = _engine()
    target = _bf(eng, Card(id='land', name='Animated Land', type_line='Land', is_land=True))
    from mtg_analyzer.game.effects.counters_tokens import GrantUntilEffect
    GrantUntilEffect(static={'type': 'type_change', 'params': {
        'add_types': ['creature'], 'power': 2, 'toughness': 5}}, source=target,
        target_kind=None, self_subject=True).apply(eng.rules.context)
    _vanish(eng, target)
    assert len(eng.state.player_by_id('p1').hand) == 2
    _upkeep(eng)
    assert target.zone == Zone.BATTLEFIELD and not target.is_creature
    assert len(eng.state.player_by_id('p1').hand) == 2 and eng.state.pending_choice is None


def test_vanish_draw_replacement_pause_keeps_spell_and_delayed_tail_through_clone():
    eng = _engine(library=20); target = _bf(eng, _creature('Visitor', 2, 4))
    dredger = _bf(eng, _creature('Dredger', oracle_text='Dredge 1', keywords=['Dredge']))
    eng.rules.put_into_graveyard(dredger)
    spell = _vanish(eng, target)
    assert eng.state.pending_choice['kind'] == 'dredge'
    assert spell.zone == Zone.STACK and not eng.state.delayed_triggers
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('draw')
    assert clone.state.pending_choice['kind'] == 'dredge' and not clone.state.delayed_triggers
    clone.resolve_pending_choice(str(dredger.instance_id))
    assert clone.state.pending_choice is None and len(clone.state.delayed_triggers) == 1
    assert clone.state.find_object(spell.instance_id).zone == Zone.GRAVEYARD
    assert len(clone.state.player_by_id('p1').hand) == 2
    assert spell.zone == Zone.STACK and not eng.state.delayed_triggers


def test_instruction_replacement_order_survives_clone_before_individual_draws():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType
    eng = _engine(library=20); target = _bf(eng, _creature('Visitor', 2, 4))
    player = eng.state.player_by_id('p1')
    player.player_effects.extend([
        ReplacementEffect(EventType.DRAW_INSTRUCTION, lambda event, context: event.copy_with(count=event.get('count') * 2), description='Double'),
        ReplacementEffect(EventType.DRAW_INSTRUCTION, lambda event, context: event.copy_with(count=event.get('count') + 1), description='Plus one'),
    ])
    spell = _vanish(eng, target)
    assert eng.state.pending_choice['kind'] == 'replacement_order' and not player.hand
    clone = GameEngine(eng.state.clone()); clone.resolve_pending_choice('0')
    assert len(clone.state.player_by_id('p1').hand) == 5
    assert len(clone.state.delayed_triggers) == 1
    assert clone.state.find_object(spell.instance_id).zone == Zone.GRAVEYARD
    assert not player.hand and spell.zone == Zone.STACK


def test_dredge_mill_order_finishes_card_return_before_remaining_instruction():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType
    eng = _engine(library=20); target = _bf(eng, _creature('Visitor', 2, 4))
    dredger = _bf(eng, _creature('Dredger', oracle_text='Dredge 1', keywords=['Dredge']))
    eng.rules.put_into_graveyard(dredger)
    player = eng.state.player_by_id('p1')
    player.player_effects.extend([ReplacementEffect(EventType.WOULD_MILL, lambda event, context: event,
        description=str(i)) for i in range(2)])
    _vanish(eng, target)
    eng.resolve_pending_choice(str(dredger.instance_id))
    assert eng.state.pending_choice['kind'] == 'replacement_order'
    clone = GameEngine(eng.state.clone()); clone.resolve_pending_choice('0')
    assert clone.state.pending_choice is None
    assert clone.state.find_object(dredger.instance_id) in clone.state.player_by_id('p1').hand
    assert len(clone.state.player_by_id('p1').hand) == 2 and len(clone.state.delayed_triggers) == 1
    assert not clone.state.pending_dredge_return


def _obzedat_end(eng, source):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', phase='ending'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('do')
    assert source.zone == Zone.EXILE


@pytest.mark.parametrize('owner', ['p1', 'p2'])
def test_obzedat_original_controller_upkeep_return_has_persistent_haste_and_etb(owner):
    eng = _engine()
    source = _bf(eng, _creature('Obzedat, Ghost Council', 5, 5, oracle_text=OBZEDAT), owner)
    source.controller_id = 'p1'
    _obzedat_end(eng, source)
    cloned = GameEngine(eng.state.clone())
    _upkeep(cloned, 'p2'); assert cloned.state.find_object(source.instance_id).zone == Zone.EXILE
    _upkeep(cloned)
    returned = cloned.state.find_object(source.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and 'haste' in returned.granted_keywords
    assert returned.controller_id == owner
    opponent = 'p2' if owner == 'p1' else 'p1'
    cloned.resolve_pending_choice(opponent)
    assert cloned.state.player_by_id(owner).life == 22 and cloned.state.player_by_id(opponent).life == 18
    cloned._step_cleanup(); cloned.recompute_continuous_effects()
    assert 'haste' in returned.granted_keywords
    cloned.rules.blink(returned); cloned.recompute_continuous_effects()
    assert 'haste' not in returned.granted_keywords


def test_obzedat_end_trigger_does_not_follow_a_blinked_source():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = _engine(); source = _bf(eng, _creature('Obzedat, Ghost Council', 5, 5, oracle_text=OBZEDAT))
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', phase='ending'))
    eng.rules.put_triggers_on_stack(); eng.rules.resolve_choice('do')
    eng.rules.blink(source); eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and not eng.state.delayed_triggers


def test_rider_cards_return_fresh_specs():
    for name in ('Vanish into Memory', 'Obzedat, Ghost Council'):
        a, b = specs_for(_creature(name)), specs_for(_creature(name))
        assert a and a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
