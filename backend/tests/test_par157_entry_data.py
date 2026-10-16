"""Return-entry data belongs to the new visit and precedes its ETB event."""
import pytest
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.choices_actions import ReturnSpecificToBattlefieldEffect
from mtg_analyzer.game.effects.returns_graveyards import BlinkEffect
from mtg_analyzer.models.game.game_object import Zone
from test_par136_delayed_blink import _engine, _bf, _card


def test_return_entry_counters_are_additive_and_replaced_before_etb(monkeypatch):
    eng, player = _engine()
    doubler = _bf(eng, _card('Doubling Season', 'Enchantment'), bind=True)
    card = _card('Walker', 'Legendary Creature Planeswalker — Test', loyalty=3)
    obj = _bf(eng, card)
    eng.rules.exile(obj)
    seen = []
    fire = eng.state.fire_event
    def observe(event):
        if event.type == 'ENTERS_BATTLEFIELD' and event.data.get('instance_id') == obj.instance_id:
            seen.append(dict(obj.counters))
        return fire(event)
    monkeypatch.setattr(eng.state, 'fire_event', observe)
    returned = eng.rules.return_from_exile(obj, obj.zone_incarnation,
        typed_entry_counters=[{'kind': '+1/+1', 'count': 1, 'types': ['creature']},
                              {'kind': 'loyalty', 'count': 1, 'types': ['planeswalker']}])
    assert returned is obj
    assert obj.counters == {'loyalty': 8, '+1/+1': 2}
    assert seen == [obj.counters]


def test_return_receipt_only_contains_successful_exact_visits():
    eng, player = _engine()
    first = _bf(eng, _card('First'))
    stale = _bf(eng, _card('Stale'))
    eng.rules.exile(first); eng.rules.exile(stale)
    effect = ReturnSpecificToBattlefieldEffect([first, stale], entry_counters={'+1/+1': 2}, tapped=True)
    eng.rules.return_to_hand(stale); eng.rules.exile(stale)
    effect.apply(eng.rules.context)
    assert effect.returned_objects == [first]
    assert first.tapped and first.counters == {'+1/+1': 2}
    assert stale.zone == Zone.EXILE and not stale.counters


def test_plural_blink_exiles_complete_set_before_any_return(monkeypatch):
    eng, player = _engine()
    first = _bf(eng, _card('First'))
    second = _bf(eng, _card('Second'))
    events = []
    exile = eng.rules.exile
    fire = eng.state.fire_event
    def note_exile(obj):
        events.append(('exile', obj.instance_id)); return exile(obj)
    def note_return(event):
        if event.type == 'ENTERS_BATTLEFIELD' and getattr(eng.state, '_deferred_entry_events', None) is None:
            events.append(('return', event.get('instance_id')))
        return fire(event)
    monkeypatch.setattr(eng.rules, 'exile', note_exile)
    monkeypatch.setattr(eng.state, 'fire_event', note_return)
    effect = BlinkEffect(entry_counters={'+1/+1': 1})
    effect.apply(eng.rules.context, [first, second])
    assert [x[0] for x in events] == ['exile', 'exile', 'return', 'return']
    assert effect.returned_objects == [first, second]
    assert first.counters == second.counters == {'+1/+1': 1}


def test_return_entry_data_is_not_applied_to_stale_or_token_visit():
    eng, player = _engine()
    obj = _bf(eng, _card('Token')); obj.is_token = True
    eng.rules.exile(obj)
    assert eng.rules.return_from_exile(obj, obj.zone_incarnation, entry_counters={'+1/+1': 4}) is None
    assert not obj.counters


def test_counter_prevention_does_not_restore_native_loyalty_after_entry(monkeypatch):
    eng, player = _engine()
    obj = _bf(eng, _card('Creature Walker', 'Creature Planeswalker — Test', loyalty=3))
    eng.rules.exile(obj)
    # A replacement preventing every counter placement must leave zero;
    # the battlefield-admission fallback cannot recreate the base loyalty.
    monkeypatch.setattr(eng.rules, 'add_counters', lambda *args, **kwargs: None)
    eng.rules.return_from_exile(obj, obj.zone_incarnation, entry_counters={'loyalty': 1})
    assert obj.counters == {'loyalty': 0}
