"""Return receipts compose existing keyword, counter and tap effects."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell, _cast
from test_par157_back_selections import _cached


@pytest.mark.parametrize('owner', ['p1', 'p2'])
@pytest.mark.parametrize('change_after_entry', [False, True])
def test_return_condition_reads_entry_controller_and_counter_or_tap_uses_returned_object(owner, change_after_entry):
    eng = _engine()
    target = _bf(eng, _creature('Visitor'), owner)
    target.controller_id = 'p2' if owner == 'p1' else 'p1'
    if change_after_entry:
        eng.state.subscribe(lambda event: setattr(target, 'controller_id', 'p2' if owner == 'p1' else 'p1')
                            if event.type == EventType.ENTERS_BATTLEFIELD
                            and event.get('instance_id') == target.instance_id else None)
    text = ("Exile target nonlegendary creature, then return it to the battlefield under its owner's control. "
            'If it entered under your control, put a +1/+1 counter on it. Otherwise, tap it.')
    spell = _hand(eng, _spell('Unregistered Return Rider', text))
    assert parse_oracle(spell.card).modeled
    _cast(eng, spell, targets=[target])
    assert target.zone == Zone.BATTLEFIELD
    assert target.entry_controller_id == owner
    assert target.counters == ({'+1/+1': 1} if owner == 'p1' else {})
    assert target.tapped == (owner == 'p2')
    assert not spell.counters


@pytest.mark.parametrize('keywords', ['haste', 'flying and vigilance'])
@pytest.mark.parametrize('timing', ['', ' at the beginning of your next upkeep'])
def test_existing_keyword_rider_applies_after_exact_return_and_expires(keywords, timing):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    visitor = _bf(eng, _creature('Visitor'))
    specs = parse_effect_body("exile target creature, then return it to the battlefield under its owner's control"
                              + timing + '. it gains ' + keywords + ' until end of turn')
    assert specs and len(specs) == 1 and specs[0].type == 'blink'
    effect = build_effects(specs, source)[0]
    effect.apply(eng.rules.context, [visitor])
    if timing:
        assert visitor.zone == Zone.EXILE
        eng._fire_delayed_triggers('upkeep')
        eng.resolve_until_stable()
    assert visitor.zone == Zone.BATTLEFIELD
    assert set(keywords.split(' and ')) <= visitor.granted_keywords
    assert not source.granted_keywords
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert not visitor.granted_keywords


@pytest.mark.full_cache
def test_hallowed_respite_uses_the_same_composed_return_body():
    card = _cached('Hallowed Respite')
    assert parse_oracle(card).modeled


def test_failed_return_does_not_run_either_entry_controller_branch():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    visitor = _bf(eng, _creature('Token'))
    visitor.is_token = True
    specs = parse_effect_body("exile target creature, then return it to the battlefield under its owner's control. "
                              'if it entered under your control, put a +1/+1 counter on it. otherwise, tap it')
    assert specs
    build_effects(specs, source)[0].apply(eng.rules.context, [visitor])
    assert visitor.zone != Zone.BATTLEFIELD and not visitor.counters and not visitor.tapped


@pytest.mark.parametrize('subject', ['target creature', '~'])
@pytest.mark.parametrize('timing,step', [
    (' at the beginning of the next end step', 'end'),
    (' at the beginning of your next upkeep', 'upkeep'),
])
def test_successful_exile_prefix_does_not_shift_delayed_return_capture(subject, timing, step):
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    visitor = source if subject == '~' else _bf(eng, _creature('Visitor'))
    text = ('exile ' + subject + ". if you do, return it to the battlefield under its owner's control"
            + timing + ' and it gains haste')
    specs = parse_effect_body(text)
    assert specs and len(specs) == 1 and specs[0].type == 'blink'
    build_effects(specs, source)[0].apply(eng.rules.context, [] if subject == '~' else [visitor])
    assert visitor.zone == Zone.EXILE
    eng._fire_delayed_triggers(step)
    eng.resolve_until_stable()
    assert visitor.zone == Zone.BATTLEFIELD and 'haste' in visitor.granted_keywords
    if visitor is not source:
        assert 'haste' not in source.granted_keywords
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert 'haste' in visitor.granted_keywords  # ordinary duration is rest_of_game
