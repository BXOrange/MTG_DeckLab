"""Exile/copy captures the departing battlefield face, not the exiled front."""
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine, _bf, _creature
from test_par136_delayed_blink import _card


def _attack(eng, source, target):
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.rules.resolve_choice(str(target.instance_id))
    eng.resolve_until_stable()


def test_attacking_thief_copies_last_copy_values_and_returns_physical_card():
    eng = _engine()
    source = _bf(eng, _creature('Identity Thief'))
    target = _bf(eng, _creature('Physical Card'), 'p2')
    model = _bf(eng, _creature('Flying Bear', 4, 5, oracle_text='Flying'))
    eng.rules.become_copy(target, model)
    target.counters['+1/+1'] = 3
    _attack(eng, source, target)
    eng.recompute_continuous_effects()
    assert source.name == 'Flying Bear' and source.power == 4
    assert target.zone == Zone.EXILE
    clone = GameEngine(eng.state.clone())
    clone._fire_delayed_triggers('end'); clone.resolve_until_stable()
    returned = clone.state.find_object(target.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.name == 'Physical Card'
    clone._step_cleanup()
    assert clone.state.find_object(source.instance_id).name == 'Identity Thief'
    assert target.zone == Zone.EXILE


def test_thief_copies_transformed_face_and_does_not_transform_returned_card():
    eng = _engine(); source = _bf(eng, _creature('Identity Thief'))
    card = _card('Front', layout='transform', back_name='Back',
        back_type_line='Creature — Dragon', back_power=6, back_toughness=7, back_oracle_text='Flying')
    target = _bf(eng, card, 'p2')
    eng.rules.transform_permanent(target)
    _attack(eng, source, target)
    assert source.name == 'Back' and target.zone == Zone.EXILE
    eng._fire_delayed_triggers('end'); eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.name == 'Front'


def test_departed_thief_still_exiles_target_but_cannot_modify_new_source_visit():
    eng = _engine(); source = _bf(eng, _creature('Identity Thief'))
    target = _bf(eng, _creature('Other'), 'p2')
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(eng.state.player_by_id('p1'), [source])
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_choice(str(target.instance_id))
    eng.rules.blink(source)
    eng.resolve_until_stable()
    assert source.name == 'Identity Thief' and target.zone == Zone.EXILE
    eng._fire_delayed_triggers('end'); eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD
