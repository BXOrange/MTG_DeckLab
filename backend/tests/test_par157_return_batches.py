"""Exact exile-return batches reuse serializable as-entry choices."""
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.battlefield_batches import start_exile_return_batch
from mtg_analyzer.game.effects.core import GameEffect
from mtg_analyzer.models.game.game_object import Zone
from test_par136_delayed_blink import _engine, _bf, _card


class _NoteReturned(GameEffect):
    def apply(self, context, targets=None):
        context.state.player_by_id('p1').life += len(targets or [])


def test_return_as_copy_choice_survives_clone_and_typed_counters_use_new_copy():
    eng, player = _engine()
    target = _bf(eng, _card('Bear'))
    obj = _bf(eng, _card('Clone', oracle_text='You may have Clone enter as a copy of any creature on the battlefield.'), bind=True)
    eng.rules.exile(obj)
    start_exile_return_batch(eng.rules, [(obj.instance_id, obj.zone_incarnation)],
        entry_options={'typed_entry_counters': [{'kind': '+1/+1', 'count': 2, 'types': ['creature']}]},
        after_effects=[_NoteReturned()])
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    clone = GameEngine(eng.state.clone())
    clone.rules.resolve_choice(str(target.instance_id))
    current = clone.state.find_object(obj.instance_id)
    assert current.zone == Zone.BATTLEFIELD and current.name == 'Bear'
    assert current.counters == {'+1/+1': 2}
    assert clone.state.players[0].life == 21
    assert obj.zone == Zone.EXILE


def test_return_batch_rejects_exile_revisit_while_entry_choice_is_pending():
    eng, player = _engine()
    target = _bf(eng, _card('Bear'))
    obj = _bf(eng, _card('Clone', oracle_text='You may have Clone enter as a copy of any creature on the battlefield.'), bind=True)
    eng.rules.exile(obj)
    start_exile_return_batch(eng.rules, [(obj.instance_id, obj.zone_incarnation)], after_effects=[_NoteReturned()])
    assert eng.state.pending_choice
    eng.rules.return_to_hand(obj); eng.rules.exile(obj)
    eng.rules.resolve_choice(str(target.instance_id))
    assert obj.zone == Zone.EXILE and obj.name == 'Clone'
    assert player.life == 20


def test_return_batch_entry_triggers_observe_complete_returned_set(monkeypatch):
    eng, player = _engine()
    first = _bf(eng, _card('First')); second = _bf(eng, _card('Second'))
    eng.rules.exile(first); eng.rules.exile(second)
    observed = []
    fire = eng.state.fire_event
    def observe(event):
        if event.type == 'ENTERS_BATTLEFIELD' and getattr(eng.state, '_deferred_entry_events', None) is None:
            observed.append((first.zone, second.zone))
        return fire(event)
    monkeypatch.setattr(eng.state, 'fire_event', observe)
    start_exile_return_batch(eng.rules, [(o.instance_id, o.zone_incarnation) for o in [first, second]])
    assert observed == [(Zone.BATTLEFIELD, Zone.BATTLEFIELD)] * 2


def test_nested_return_batch_does_not_flush_or_replace_outer_entry_event_buffer():
    eng, player = _engine()
    obj = _bf(eng, _card('Bearer')); eng.rules.exile(obj)
    outer = []
    eng.state._deferred_entry_events = outer
    start_exile_return_batch(eng.rules, [(obj.instance_id, obj.zone_incarnation)])
    assert eng.state._deferred_entry_events is outer
    assert any(e.type == 'ENTERS_BATTLEFIELD' for e in outer)


def _three_player_copy_batch(controller='p1', owner='p1'):
    eng = GameEngine.new_game([('p1','A',[]),('p2','B',[]),('p3','C',[])], starting_hand=0)
    eng.begin_turn()
    target = _bf(eng, _card('Bear'), controller='p2')
    obj = _bf(eng, _card('Clone', oracle_text='You may have Clone enter as a copy of any creature on the battlefield.'), controller=owner, bind=True)
    source = _bf(eng, _card('Spell Source'), controller=controller)
    eng.rules.exile(obj)
    eng.rules.context.resolving_controller_id = controller
    start_exile_return_batch(eng.rules, [(obj.instance_id, obj.zone_incarnation)], source=source)
    eng.rules.context.resolving_controller_id = None
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    return eng, obj, source


def test_conceding_owned_return_entry_clears_choice_but_keeps_survivor_tail_once():
    from mtg_analyzer.game.effects.life_sacrifice import GainLifeEffect
    eng, obj, source = _three_player_copy_batch()
    survivor = _bf(eng, _card('Survivor'), controller='p2')
    eng.state.deferred_effects.append({'effects': [GainLifeEffect(2)], 'source': survivor,
        'targets': [], 'target_groups': None, 'group_index': 0, 'controller_id': 'p2'})
    eng.rules.concede(eng.state.player_by_id('p1'))
    assert eng.state.pending_choice is None
    eng.resolve_until_stable(); eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 42
    assert not eng.state.deferred_effects
    assert obj.zone != Zone.BATTLEFIELD


def test_conceding_return_controller_skips_own_entry_but_surviving_spell_finishes():
    eng, obj, source = _three_player_copy_batch(controller='p1', owner='p2')
    eng.rules.concede(eng.state.player_by_id('p2'))
    assert eng.state.pending_choice is None
    assert obj.zone != Zone.BATTLEFIELD
    assert not eng.state.player_by_id('p1').has_lost


def test_conceding_spell_controller_cancels_entry_even_when_other_player_was_choosing():
    eng, obj, source = _three_player_copy_batch(controller='p1', owner='p2')
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng.rules.concede(eng.state.player_by_id('p1'))
    assert eng.state.pending_choice is None and obj.zone == Zone.EXILE


def test_departed_noncontroller_chooser_is_replaced_by_surviving_spell_controller():
    eng, obj, source = _three_player_copy_batch(controller='p1', owner='p2')
    # RULE 800.4g: an effect may give another player the required choice.
    eng.state.pending_choice['player_id'] = 'p3'
    eng.rules.concede(eng.state.player_by_id('p3'))
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.rules.resolve_choice('decline')
    assert obj.zone == Zone.BATTLEFIELD
