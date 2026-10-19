"""Named-source return riders follow only the operation's successful visit."""
import pytest

from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.models.game.game_object import Zone
from test_mec106_gift import _engine, _bf, _creature


@pytest.mark.parametrize('rider', ['Source gains haste until end of turn.', 'Put a +1/+1 counter on Source.'])
@pytest.mark.parametrize('timing', ['', ' at the beginning of your next upkeep'])
def test_native_self_return_named_rider(rider, timing):
    eng = _engine()
    card = _creature('Source', oracle_text='{0}: Exile Source, then return it to the battlefield under your control' + timing + '. ' + rider)
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    eng.resolve_until_stable()
    if timing:
        assert source.zone == Zone.EXILE
        eng._fire_delayed_triggers('upkeep')
        eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert ('haste' in source.granted_keywords) if 'haste' in rider else source.counters == {'+1/+1': 1}


@pytest.mark.parametrize('rider', ['Source gains haste until end of turn.', 'Put a +1/+1 counter on Source.'])
def test_native_dying_source_return_named_rider(rider):
    eng = _engine()
    card = _creature('Source', oracle_text='When Source dies, return Source to the battlefield under your control. ' + rider)
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    eng.rules.destroy(source)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD
    assert ('haste' in source.granted_keywords) if 'haste' in rider else source.counters == {'+1/+1': 1}


@pytest.mark.parametrize('rider', ['Source gains haste until end of turn.', 'Put a +1/+1 counter on Source.'])
@pytest.mark.parametrize('failed', ['token', 'stale'])
def test_delayed_self_return_never_follows_failed_or_stale_exile_visit(rider, failed):
    eng = _engine()
    card = _creature('Source', oracle_text='{0}: Exile Source, then return it to the battlefield under your control at the beginning of your next upkeep. ' + rider)
    source = _bf(eng, card)
    source.is_token = failed == 'token'
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    eng.resolve_until_stable()
    if failed == 'stale':
        eng.rules.return_to_hand(source)
        eng.rules.exile(source)
    eng._fire_delayed_triggers('upkeep')
    eng.resolve_until_stable()
    assert source.zone != Zone.BATTLEFIELD
    assert not source.counters and 'haste' not in source.granted_keywords


@pytest.mark.parametrize('timing', ['', ' at the beginning of your next upkeep'])
@pytest.mark.parametrize('reenter', [False, True])
def test_target_return_named_source_rider_keeps_its_original_source_capture(timing, reenter):
    eng = _engine()
    card = _creature('Source', oracle_text='{0}: Exile target creature, then return it to the battlefield under your control' + timing + '. Put a +1/+1 counter on Source.')
    source = _bf(eng, card)
    visitor = _bf(eng, _creature('Visitor'))
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, targets=[visitor])
    if reenter:
        eng.rules.blink(source)
    eng.resolve_until_stable()
    if timing:
        # An additional reentry after scheduling must not replace its capture.
        if reenter:
            eng.rules.blink(source)
        eng._fire_delayed_triggers('upkeep')
        eng.resolve_until_stable()
    assert visitor.zone == Zone.BATTLEFIELD and not visitor.counters
    assert source.counters == ({} if reenter else {'+1/+1': 1})


@pytest.mark.parametrize('mechanism', ['blink', 'death'])
@pytest.mark.parametrize('stale', [False, True])
def test_native_named_source_return_rider_survives_entry_choice_clone(mechanism, stale):
    from mtg_analyzer.game.game_engine import GameEngine
    eng = _engine()
    body = ('{0}: Exile Source, then return it to the battlefield under your control.' if mechanism == 'blink'
            else 'When Source dies, return Source to the battlefield under your control.')
    card = _creature('Source', oracle_text='You may have Source enter as a copy of any creature on the battlefield.\n' + body + ' Put a +1/+1 counter on Source.')
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    visitor = _bf(eng, _creature('Visitor'))
    if mechanism == 'blink':
        eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    else:
        eng.rules.destroy(source)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    clone = GameEngine(eng.state.clone())
    current = clone.state.find_object(source.instance_id)
    if stale:
        clone.rules.return_to_hand(current)
        clone.rules.exile(current)
    clone.rules.resolve_choice(str(visitor.instance_id))
    clone.resolve_until_stable()
    assert current.counters == ({} if stale else {'+1/+1': 1})
    assert current.zone == (Zone.EXILE if stale else Zone.BATTLEFIELD)
    assert not source.counters


@pytest.mark.parametrize('rider', ['Source gains haste until end of turn.', 'Put a +1/+1 counter on Source.'])
def test_dying_source_return_rejects_later_graveyard_visit_but_keeps_global_instruction(rider):
    eng = _engine()
    card = _creature('Source', oracle_text='When Source dies, return Source to the battlefield under your control. ' + rider + ' Draw a card.')
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    eng.rules.destroy(source)
    eng.rules.return_to_hand(source)
    eng.rules.discard(eng.state.player_by_id('p1'), 1)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert not source.counters and 'haste' not in source.granted_keywords
    assert len(eng.state.player_by_id('p1').hand) == 1


def test_group_return_does_not_adopt_an_independently_reentered_source():
    eng = _engine()
    card = _creature('Source', oracle_text='{0}: Exile all creatures you control, then return them to the battlefield under your control. Put a +1/+1 counter on Source.')
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0)
    eng.rules.blink(source)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and not source.counters


def test_successful_source_return_restores_outer_source_capture():
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    context = eng.rules.context
    captured = source.zone_incarnation
    context.resolving_source_incarnation = captured
    effects = build_effects(parse_effect_body('exile ~, then return it to the battlefield under your control. put a +1/+1 counter on ~'), source)
    effects[0].apply(context)
    assert source.counters == {'+1/+1': 1}
    assert source.zone_incarnation != captured
    assert context.resolving_source_incarnation == captured


@pytest.mark.parametrize('zone', ['hand', 'library'])
def test_ordinary_entry_batch_needs_no_return_capture(zone):
    from mtg_analyzer.game.effects.battlefield_batches import start_battlefield_batch
    from mtg_analyzer.models.game.game_object import GameObject
    eng = _engine()
    obj = GameObject(_creature('Ordinary entrant'), owner_id='p1', zone=Zone(zone))
    getattr(eng.state.player_by_id('p1'), zone).append(obj)
    start_battlefield_batch(eng.rules, [obj], 'p1')
    assert obj.zone == Zone.BATTLEFIELD
    assert obj in eng.state.battlefield
