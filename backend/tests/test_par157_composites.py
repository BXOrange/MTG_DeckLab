"""Printed-order and repeated-visit regressions for compound flickers."""
import pytest

from mtg_analyzer.game.effects.flicker_composites import (
    AcrobaticsEffect, AnotherRoundEffect,
)
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell


def _answer(eng, answer):
    eng.rules.resolve_choice(str(answer))


def test_another_round_fresh_set_each_pass_and_all_exiles_before_returns():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    b = _bf(eng, _creature('B'))
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    spell = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    spell.x_paid = 1
    events = []
    def observe(event):
        if event.type in (EventType.LEAVES_BATTLEFIELD, EventType.ENTERS_BATTLEFIELD):
            events.append(event.type)
    eng.state.subscribe(observe)
    AnotherRoundEffect(spell).apply(eng.rules.context)
    assert str(enemy.instance_id) not in [o['id'] for o in eng.state.pending_choice['options']]
    _answer(eng, a.instance_id)
    _answer(eng, b.instance_id)
    assert a.zone == b.zone == Zone.BATTLEFIELD
    assert events == []  # Selection is complete before any movement.
    _answer(eng, 'done')
    assert events == [EventType.LEAVES_BATTLEFIELD] * 2 + [EventType.ENTERS_BATTLEFIELD] * 2
    a_visit, b_visit = a.zone_incarnation, b.zone_incarnation
    _answer(eng, b.instance_id)
    _answer(eng, 'done')
    assert eng.state.pending_choice is None
    assert a.zone_incarnation == a_visit
    assert b.zone_incarnation > b_visit


def test_another_round_zero_x_still_one_optional_pass_and_zero_selected():
    eng = _engine()
    creature = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    before = creature.zone_incarnation
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, 'done')
    assert creature.zone_incarnation == before
    assert eng.state.pending_choice is None


def test_another_round_cannot_return_tokens_or_keep_stolen_creature():
    eng = _engine()
    token = _bf(eng, _creature('Token'))
    token.is_token = True
    stolen = _bf(eng, _creature('Stolen'), player='p2')
    stolen.controller_id = 'p1'
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    source.x_paid = 1
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, token.instance_id)
    _answer(eng, stolen.instance_id)
    _answer(eng, 'done')
    assert token.zone == Zone.EXILE
    assert stolen.zone == Zone.BATTLEFIELD and stolen.controller_id == 'p2'
    assert eng.state.pending_choice is None  # No creatures remain under p1 control.


@pytest.mark.parametrize('roll, expected_visits', [(1, 1), (9, 1), (10, 3), (20, 3)])
def test_acrobatics_rolls_after_exile_then_tracks_new_exile_visits(roll, expected_visits):
    eng = _engine()
    a = _bf(eng, _creature('A'))
    b = _bf(eng, _creature('B'))
    token = _bf(eng, _creature('Token'))
    token.is_token = True
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    initial = a.zone_incarnation
    def random_int(sides):
        assert sides == 20
        assert a.zone == b.zone == Zone.EXILE
        assert token.zone == enemy.zone == Zone.BATTLEFIELD
        return roll - 1
    eng.rules.random_int = random_int
    AcrobaticsEffect(source).apply(eng.rules.context)
    assert a.zone == b.zone == Zone.EXILE
    assert a.zone_incarnation == initial + expected_visits
    assert len(eng.state.delayed_triggers) == 1
    delayed = eng.state.delayed_triggers[0]
    assert delayed.step == 'end' and delayed.scope == 'any'
    delayed.effects[0].apply(eng.rules.context)
    assert a.zone == b.zone == Zone.BATTLEFIELD
    assert token.zone == enemy.zone == Zone.BATTLEFIELD


def test_acrobatics_delayed_return_never_returns_new_exile_stay():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    eng.rules.random_int = lambda sides: 0
    AcrobaticsEffect(source).apply(eng.rules.context)
    effect = eng.state.delayed_triggers[0].effects[0]
    eng.rules.return_from_exile(a, a.zone_incarnation)
    eng.rules.exile(a)
    effect.apply(eng.rules.context)
    assert a.zone == Zone.EXILE


def test_round_selection_is_clone_safe():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, a.instance_id)
    cloned = eng.state.clone()
    from mtg_analyzer.game.rules_engine import RulesEngine
    rules = RulesEngine(cloned)
    rules.resolve_choice('done')
    assert cloned.find_object(a.instance_id).zone_incarnation > a.zone_incarnation
    assert eng.state.pending_choice is not None


def test_acrobatics_reuses_interactive_ignore_one_and_survives_clone():
    eng = _engine()
    from test_mec117_ignore_one import _put, OTHER_THUMB
    _put(eng, "Krark's Other Thumb", OTHER_THUMB)
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    rolls = iter([19, 0])
    eng.rules.random_int = lambda sides: next(rolls)
    eng.state.interactive_roll_picks = True
    AcrobaticsEffect(source).apply(eng.rules.context)
    pending = eng.state.pending_choice
    assert pending['kind'] == 'choose_die_group'
    assert a.zone == Zone.EXILE
    assert eng.state.delayed_triggers == []
    cloned = eng.state.clone()
    from mtg_analyzer.game.rules_engine import RulesEngine
    rules = RulesEngine(cloned)
    low = next(o['id'] for o in cloned.pending_choice['options'] if o['label'] == '1')
    rules.resolve_choice(low)
    rules.resume_deferred_effects()
    actual = cloned.find_object(a.instance_id)
    assert actual.zone == Zone.EXILE
    assert len(cloned.delayed_triggers) == 1
    assert actual.zone_incarnation == a.zone_incarnation  # Low row never returns immediately.
    assert eng.state.pending_choice is not None


def test_authored_another_round_real_cast_and_choice_resolves_into_graveyard():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    source = _hand(eng, _spell('Another Round', "Exile any number of creatures you control, then return them to the battlefield under their owner's control. Then repeat this process X more times.", 'Sorcery'))
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('C', 10)
    eng.cast_spell(p1, source, x=1)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'flicker_round_selection'
    start = a.zone_incarnation
    for _ in range(2):
        _answer(eng, a.instance_id)
        _answer(eng, 'done')
        eng.resolve_until_stable()
    assert a.zone_incarnation == start + 4
    assert source.zone == Zone.GRAVEYARD
    assert not eng.state.deferred_effects


def test_authored_acrobatics_real_cast_and_actual_delayed_stack():
    eng = _engine()
    a = _bf(eng, _creature('A'))
    text = "Exile all nontoken creatures you control, then roll a d20.\n1—9 | Return those cards to the battlefield under their owner's control at the beginning of the next end step.\n10—20 | Return those cards to the battlefield under their owner's control, then exile them again. Return those cards to the battlefield under their owner's control at the beginning of the next end step."
    source = _hand(eng, _spell("Lae'zel's Acrobatics", text))
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('C', 10)
    eng.rules.random_int = lambda sides: 19
    eng.cast_spell(p1, source)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert a.zone == Zone.EXILE
    eng._fire_delayed_triggers('end')
    assert len(eng.state.stack) == 1
    eng.resolve_until_stable()
    assert a.zone == Zone.BATTLEFIELD
    assert not eng.state.delayed_triggers


def _copy_creature(eng):
    from mtg_analyzer.models.cards.card import Card
    return _bf(eng, Card(id='Clone', name='Clone', type_line='Creature — Shapeshifter',
                        is_creature=True, power=0, toughness=0,
                        oracle_text='You may have Clone enter as a copy of any creature on the battlefield.'))


def test_another_round_waits_for_copy_entry_choice_before_next_selection_after_clone():
    eng = _engine()
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    obj = _copy_creature(eng)
    source = _hand(eng, _spell('Another Round', '', 'Sorcery'))
    source.x_paid = 1
    AnotherRoundEffect(source).apply(eng.rules.context)
    _answer(eng, obj.instance_id)
    _answer(eng, 'done')
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    assert obj.zone == Zone.EXILE
    from mtg_analyzer.game.game_engine import GameEngine
    copied = GameEngine(eng.state.clone())
    copied.rules.resolve_choice(str(enemy.instance_id))
    actual = copied.state.find_object(obj.instance_id)
    assert actual.zone == Zone.BATTLEFIELD and actual.name == 'Enemy'
    assert copied.state.pending_choice['kind'] == 'flicker_round_selection'
    copied.rules.resolve_choice('done')
    assert copied.state.pending_choice is None
    assert obj.zone == Zone.EXILE


def test_acrobatics_high_row_waits_for_copy_choice_before_reexile_after_clone():
    eng = _engine()
    enemy = _bf(eng, _creature('Enemy'), player='p2')
    obj = _copy_creature(eng)
    source = _hand(eng, _spell("Lae'zel's Acrobatics", ''))
    eng.rules.random_int = lambda sides: 19
    AcrobaticsEffect(source).apply(eng.rules.context)
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    assert not eng.state.delayed_triggers
    from mtg_analyzer.game.game_engine import GameEngine
    copied = GameEngine(eng.state.clone())
    copied.rules.resolve_choice(str(enemy.instance_id))
    actual = copied.state.find_object(obj.instance_id)
    assert actual.zone == Zone.EXILE
    assert len(copied.state.delayed_triggers) == 1
    copied._fire_delayed_triggers('end')
    copied.resolve_until_stable()
    assert copied.state.pending_choice['kind'] == 'enter_as_copy'
    copied.rules.resolve_choice(str(enemy.instance_id))
    assert actual.zone == Zone.BATTLEFIELD and actual.name == 'Enemy'


def _fortune(eng):
    from mtg_analyzer.models.cards.card import Card
    return _bf(eng, Card(id='Fortune', name='Fortune, Loyal Steed',
                        type_line='Legendary Creature — Beast Mount', is_creature=True,
                        power=2, toughness=4, oracle_text="When Fortune enters, scry 2.\nWhenever Fortune attacks while saddled, at end of combat, exile it and up to one creature that saddled it this turn, then return those cards to the battlefield under their owner's control.\nSaddle 1"))


def _saddle_and_attack(eng, fortune, saddler):
    player = eng.state.player_by_id('p1')
    eng.activate_ability(player, fortune, ability_index=0, tap_choices=[saddler.instance_id])
    eng.resolve_until_stable()
    assert fortune.saddled_by_incarnations == {saddler.instance_id: saddler.zone_incarnation}
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(player, [fortune])


def test_fortune_real_saddle_attack_endcombat_optional_saddler_and_scry():
    eng = _engine()
    fortune = _fortune(eng)
    saddler = _bf(eng, _creature('Saddler'))
    _saddle_and_attack(eng, fortune, saddler)
    eng.resolve_until_stable()
    assert len(eng.state.delayed_triggers) == 1
    assert eng.state.delayed_triggers[0].step == 'end_combat'
    before = (fortune.zone_incarnation, saddler.zone_incarnation)
    eng._fire_delayed_triggers('end_combat')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'fortune_flicker_saddler'
    _answer(eng, saddler.instance_id)
    eng.resolve_until_stable()
    assert (fortune.zone_incarnation, saddler.zone_incarnation) == (before[0] + 2, before[1] + 2)
    assert eng.state.pending_choice['kind'] == 'scry'
    assert len([o for o in eng.state.pending_choice['options'] if o.get('instance_id')]) == 2


def test_fortune_old_attack_snapshot_survives_mount_blink_before_trigger_resolution():
    eng = _engine()
    fortune = _fortune(eng)
    saddler = _bf(eng, _creature('Saddler'))
    _saddle_and_attack(eng, fortune, saddler)
    eng.rules.blink(fortune)
    # Complete only the new Fortune's ETB scry; old attack event still retains its saddlers.
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        assert eng.state.pending_choice['kind'] == 'scry'
        eng.rules.resolve_choice('decline')
        eng.resolve_until_stable()
    eng._fire_delayed_triggers('end_combat')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'fortune_flicker_saddler'
    mount_visit = fortune.zone_incarnation
    saddler_visit = saddler.zone_incarnation
    _answer(eng, saddler.instance_id)
    assert fortune.zone_incarnation == mount_visit
    assert saddler.zone_incarnation == saddler_visit + 2


def test_fortune_rejects_blinked_saddler_new_visit():
    eng = _engine()
    fortune = _fortune(eng)
    saddler = _bf(eng, _creature('Saddler'))
    _saddle_and_attack(eng, fortune, saddler)
    eng.rules.blink(saddler)
    eng.resolve_until_stable()
    before = saddler.zone_incarnation
    eng._fire_delayed_triggers('end_combat')
    eng.resolve_until_stable()
    # Only Fortune flickers, then its real ETB asks to scry.
    assert saddler.zone_incarnation == before
    assert eng.state.pending_choice['kind'] == 'scry'


def test_eager_copy_persists_same_visit_then_blink_restores_printed_identity():
    eng = _engine()
    original = _bf(eng, _creature('Original', 1, 3))
    copied = _bf(eng, _creature('Copied', 5, 6))
    second = _bf(eng, _creature('Second copy', 7, 8))
    printing = dict(original.physical_printing)
    eng.rules.become_copy(original, copied)
    eng.rules.become_copy(original, second)
    eng.recompute_continuous_effects()
    assert original.name == 'Second copy' and original.power == 7
    eng._step_cleanup()
    assert original.name == 'Second copy'  # Permanent copy has no EOT duration.
    eng.rules.blink(original)
    assert original.name == 'Original' and original.power == 1
    assert original.physical_printing == printing


@pytest.mark.parametrize('back_face', [False, True])
def test_copy_reset_restores_original_dfc_front_after_either_original_face(back_face):
    from mtg_analyzer.models.cards.card import Card
    eng = _engine()
    original = _bf(eng, Card(id='dfc', name='Printed Front', type_line='Creature — Human',
                            is_creature=True, power=1, toughness=2, layout='transform',
                            back_name='Printed Back', back_type_line='Creature — Werewolf',
                            back_power=4, back_toughness=4))
    copied = _bf(eng, _creature('Copied', 5, 6))
    if back_face:
        eng.rules.transform_permanent(original)
        assert original.name == 'Printed Back'
    eng.rules.become_copy(original, copied)
    assert original.name == 'Copied'
    eng.rules.blink(original)
    assert original.name == 'Printed Front'
    assert not original.transformed
    eng.rules.transform_permanent(original)
    eng.recompute_continuous_effects()
    assert original.name == 'Printed Back' and original.power == 4


def test_cleanup_after_blink_cannot_restore_stale_temporary_copy_snapshot():
    eng = _engine()
    original = _bf(eng, _creature('Original', 1, 3))
    permanent = _bf(eng, _creature('Permanent copy', 5, 6))
    temporary = _bf(eng, _creature('Temporary copy', 7, 8))
    eng.rules.become_copy(original, permanent)
    eng.rules.become_copy_until_end_of_turn(original, temporary)
    assert original.name == 'Temporary copy'
    eng.rules.blink(original)
    assert original.name == 'Original'
    eng._step_cleanup()
    assert original.name == 'Original' and original.power == 1


def test_genuine_copy_token_keeps_its_created_identity_when_copy_effect_resets():
    eng = _engine()
    template = _bf(eng, _creature('Created token identity', 3, 4))
    other = _bf(eng, _creature('Temporary other identity', 7, 8))
    token = eng.rules.copy_permanent('p1', template)[0]
    assert token.is_token and token.name == 'Created token identity'
    eng.rules.become_copy(token, other)
    eng.rules.exile(token)
    token.reset_as_new_object()
    assert token.name == 'Created token identity'
    assert eng.rules.return_from_exile(token, token.zone_incarnation) is None
    eng.resolve_until_stable()
    assert token not in eng.state.player_by_id('p1').exile
