"""Inserted end steps use the real turn cursor, triggers and saved state."""
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.additional_steps import AdditionalEndStepEffect
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature


TEXT = ("At the beginning of your end step, exile target creature you control, then "
        "return it to the battlefield under its owner's control. Then if it's the first "
        "end step of the turn, there is an additional end step after this step.")


def _before_end(eng):
    eng.start()
    while eng.state.current_step != 'main2':
        eng.advance_step()


def test_real_y_shtola_blinks_in_both_end_steps_then_reaches_cleanup():
    eng = _engine()
    _before_end(eng)
    source = _bf(eng, _creature("Y'shtola Rhul", oracle_text=TEXT), eng.state.active_player.id)
    _bf(eng, _creature('Other Creature'), eng.state.active_player.id)
    assert parse_oracle(source.card).modeled
    before = source.zone_incarnation
    assert eng.advance_step() == ('ending', 'end')
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.rules.resolve_choice(str(source.instance_id))
    eng.resolve_until_stable()
    assert source.zone_incarnation == before + 2
    assert eng.state.pending_extra_end_steps == 1
    cloned = GameEngine(eng.state.clone())
    cloned.resume_at(eng.step_cursor)
    assert cloned.advance_step() == ('ending', 'end')
    cloned.rules.resolve_choice(str(source.instance_id))
    cloned.resolve_until_stable()
    assert cloned.state.end_steps_this_turn == 2
    assert cloned.state.pending_extra_end_steps == 0
    assert cloned.state.find_object(source.instance_id).zone_incarnation == before + 4
    assert cloned.advance_step() == ('ending', 'cleanup')


def test_multiple_unconditional_requests_each_open_a_real_end_step():
    eng = _engine()
    _before_end(eng)
    eng.advance_step()
    for _ in range(2):
        AdditionalEndStepEffect().apply(eng.rules.context)
    assert eng.advance_step() == ('ending', 'end')
    assert eng.advance_step() == ('ending', 'end')
    assert eng.state.end_steps_this_turn == 3
    assert eng.advance_step() == ('ending', 'cleanup')
    eng.advance_step()
    assert eng.state.end_steps_this_turn == 0


def test_skipped_end_step_does_not_count_as_first_and_effect_outside_end_is_noop():
    eng = _engine()
    AdditionalEndStepEffect().apply(eng.rules.context)
    assert eng.state.pending_extra_end_steps == 0
    _before_end(eng)
    original = eng.rules.should_skip_step
    eng.rules.should_skip_step = lambda player, step: step == 'end' or original(player, step)
    eng.advance_step()
    assert eng.state.end_steps_this_turn == 0


def test_run_turn_consumes_inserted_end_step_without_skipping_cleanup():
    eng = _engine()
    ends = []
    def on_event(event):
        if event.type == EventType.STEP_BEGIN and event.get('step') == 'end':
            ends.append(event)
            AdditionalEndStepEffect(only_first=True).apply(eng.rules.context)
    eng.state.subscribe(on_event)
    eng.run_turn()
    assert len(ends) == 2
    assert eng.state.current_step == 'cleanup'


def test_unknown_condition_or_step_stays_unclaimed():
    assert parse_effect_body("if it's the second end step of the turn, there is an additional end step after this step") is None
    assert parse_effect_body('there is an additional cleanup step after this step') is None
