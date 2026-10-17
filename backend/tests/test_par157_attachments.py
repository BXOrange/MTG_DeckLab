"""Actual linked host/Aura returns and persistent source-release delayed triggers."""
import pytest

from test_mec106_gift import _engine, _bf, _creature
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.game.card_catalogue.f import flickerform  # noqa: F401
from mtg_analyzer.game.card_catalogue.t import tawnoss_coffin  # noqa: F401


def _aura(eng, host, name='Flickerform', owner='p1', restriction='creature'):
    text = {'Flickerform': "Enchant creature\n{2}{W}{W}: Exile enchanted creature and all Auras attached to it. At the beginning of the next end step, return that card to the battlefield under its owner's control. If you do, return the other cards exiled this way to the battlefield under their owners' control attached to that creature."}.get(name, f'Enchant {restriction}')
    obj = _bf(eng, Card(id=name, name=name, type_line='Enchantment — Aura',
                        oracle_text=text, keywords=['Enchant']), owner)
    obj.attached_to = host.instance_id
    return obj


def _coffin(eng):
    return _bf(eng, Card(id='coffin', name="Tawnos's Coffin", type_line='Artifact',
        oracle_text="You may choose not to untap this artifact during your untap step.\n{3}, {T}: Exile target creature and all Auras attached to it. Note the number and kind of counters that were on that creature. When this artifact leaves the battlefield or becomes untapped, return that exiled card to the battlefield under its owner's control tapped with the noted number and kind of counters on it. If you do, return the other exiled cards to the battlefield under their owner's control attached to that permanent."))


def _activate(eng, obj, targets=None):
    p = eng.state.player_by_id('p1')
    p.mana_pool.add('W', 10)
    p.mana_pool.add('C', 10)
    eng.activate_ability(p, obj, targets=targets or [])
    eng.resolve_until_stable()


def _end(eng):
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()


def test_flickerform_returns_host_then_auras_under_owners_control():
    eng = _engine()
    host = _bf(eng, _creature('Bear'), 'p2')
    aura = _aura(eng, host)
    other = _aura(eng, host, 'Second Aura', 'p2')
    _activate(eng, aura)
    assert all(o.zone == Zone.EXILE for o in (host, aura, other))
    _end(eng)
    assert all(o.zone == Zone.BATTLEFIELD for o in (host, aura, other))
    assert aura.attached_to == other.attached_to == host.instance_id
    assert host.controller_id == other.controller_id == 'p2'
    assert aura.controller_id == 'p1'


@pytest.mark.parametrize('moved', ['host', 'aura'])
def test_revisited_exile_never_rejoins_group(moved):
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host)
    _activate(eng, aura)
    obj = host if moved == 'host' else aura
    eng.rules.return_to_hand(obj); eng.rules.exile(obj)
    _end(eng)
    assert obj.zone == Zone.EXILE
    assert aura.zone == Zone.EXILE
    assert host.zone == (Zone.EXILE if moved == 'host' else Zone.BATTLEFIELD)


def test_token_host_never_returns_or_brings_auras():
    eng = _engine(); host = _bf(eng, _creature('Token')); host.is_token = True
    aura = _aura(eng, host)
    _activate(eng, aura); _end(eng)
    assert host.zone != Zone.BATTLEFIELD
    assert aura.zone == Zone.EXILE


def test_prospective_owner_controller_governs_aura_legality():
    eng = _engine(); host = _bf(eng, _creature('Bear'), 'p2')
    aura = _aura(eng, host)
    other = _aura(eng, host, 'Own Creature Aura', owner='p1', restriction='creature you control')
    # Initially legal under a temporary control effect; returning host reverts to owner.
    host.controller_id = 'p1'
    _activate(eng, aura); _end(eng)
    assert host.controller_id == 'p2'
    assert aura.zone == Zone.BATTLEFIELD
    assert other.zone == Zone.EXILE


@pytest.mark.parametrize('release', ['untap', 'leave'])
def test_coffin_restores_every_counter_tapped_and_returns_auras(release):
    eng = _engine(); host = _bf(eng, _creature('Bear', 2, 9)); aura = _aura(eng, host, 'Second Aura')
    host.counters.update({'+1/+1': 3, 'charge': 2})
    coffin = _coffin(eng)
    _activate(eng, coffin, [host])
    assert host.zone == aura.zone == Zone.EXILE
    assert len(eng.state.turn_scoped_triggers) == 1
    if release == 'untap': eng.rules.set_tapped(coffin, False)
    else: eng.rules.return_to_hand(coffin)
    eng.resolve_until_stable()
    assert host.zone == aura.zone == Zone.BATTLEFIELD
    assert host.tapped and host.counters == {'+1/+1': 3, 'charge': 2}
    assert aura.attached_to == host.instance_id
    assert not eng.state.turn_scoped_triggers


def test_source_leaving_before_coffin_resolution_is_not_retroactive():
    eng = _engine(); host = _bf(eng, _creature('Bear')); coffin = _coffin(eng)
    eng.state.player_by_id('p1').mana_pool.add('C', 3)
    eng.activate_ability(eng.state.player_by_id('p1'), coffin, targets=[host])
    eng.rules.return_to_hand(coffin)
    eng.resolve_until_stable()
    assert host.zone == Zone.EXILE
    _end(eng)
    assert host.zone == Zone.EXILE


def test_coffin_trigger_survives_clone_and_fires_once():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host, 'Second Aura'); coffin = _coffin(eng)
    _activate(eng, coffin, [host])
    cloned = GameEngine(eng.state.clone())
    cloned_coffin = cloned.state.find_object(coffin.instance_id)
    cloned.rules.set_tapped(cloned_coffin, False)
    cloned.resolve_until_stable()
    assert cloned.state.find_object(host.instance_id).zone == Zone.BATTLEFIELD
    assert cloned.state.find_object(aura.instance_id).attached_to == host.instance_id
    assert host.zone == Zone.EXILE  # No closure points into the pre-clone state.
    cloned.rules.return_to_hand(cloned_coffin); cloned.resolve_until_stable()
    assert not cloned.state.turn_scoped_triggers


def test_stun_prevented_untap_does_not_release_group():
    eng = _engine(); host = _bf(eng, _creature('Bear')); coffin = _coffin(eng)
    _activate(eng, coffin, [host]); coffin.counters['stun'] = 1
    eng.rules.set_tapped(coffin, False); eng.resolve_until_stable()
    assert host.zone == Zone.EXILE and coffin.tapped
    eng.rules.set_tapped(coffin, False); eng.resolve_until_stable()
    assert host.zone == Zone.BATTLEFIELD


def test_untapping_before_resolution_does_not_return_new_exile_group():
    eng = _engine(); host = _bf(eng, _creature('Bear')); coffin = _coffin(eng)
    eng.state.player_by_id('p1').mana_pool.add('C', 3)
    eng.activate_ability(eng.state.player_by_id('p1'), coffin, targets=[host])
    eng.rules.set_tapped(coffin, False)
    eng.resolve_until_stable()
    assert host.zone == Zone.EXILE
    eng.rules.set_tapped(coffin, True); eng.rules.set_tapped(coffin, False)
    eng.resolve_until_stable()
    assert host.zone == Zone.BATTLEFIELD


def test_missing_host_leaves_auras_exiled_and_coffin_releases_only_once():
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host, 'Second Aura'); coffin = _coffin(eng)
    _activate(eng, coffin, [host])
    eng.rules.return_to_hand(host)
    eng.rules.set_tapped(coffin, False); eng.resolve_until_stable()
    assert host.zone == Zone.HAND and aura.zone == Zone.EXILE
    assert not eng.state.turn_scoped_triggers


def test_auras_are_attached_before_their_etb_events():
    from mtg_analyzer.models.game.events import EventType
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host)
    other = _aura(eng, host, 'Second Aura')
    seen = []
    def record(event):
        if event.type == EventType.ENTERS_BATTLEFIELD:
            obj = eng.state.find_object(event.get('instance_id'))
            if obj is other:
                seen.append((obj.attached_to, aura.zone))
    eng.state.subscribe(record)
    _activate(eng, aura); _end(eng)
    assert seen == [(host.instance_id, Zone.BATTLEFIELD)]


def test_coffin_noted_counters_add_to_native_entry_counters_before_etb():
    from mtg_analyzer.models.game.events import EventType
    eng = _engine()
    host = _bf(eng, _creature('Counter Bear', 2, 20,
        oracle_text='This creature enters with two +1/+1 counters on it.'))
    host.counters['+1/+1'] = 3
    coffin = _coffin(eng)
    seen = []
    def record(event):
        if event.type == EventType.ENTERS_BATTLEFIELD and event.get('instance_id') == host.instance_id:
            seen.append(dict(host.counters))
    eng.state.subscribe(record)
    _activate(eng, coffin, [host])
    eng.rules.set_tapped(coffin, False); eng.resolve_until_stable()
    assert host.counters == {'+1/+1': 5}
    assert seen == [{'+1/+1': 5}]


def test_coffin_noted_counters_use_actual_counter_replacements():
    eng = _engine(); host = _bf(eng, _creature('Bear', 2, 20)); coffin = _coffin(eng)
    host.counters['+1/+1'] = 3
    _bf(eng, Card(id='season', name='Doubling Season', type_line='Enchantment'))
    _activate(eng, coffin, [host])
    eng.rules.set_tapped(coffin, False); eng.resolve_until_stable()
    assert host.counters == {'+1/+1': 6}


@pytest.mark.parametrize('release', ['end', 'untap'])
def test_linked_return_waits_for_copy_choice_and_survives_clone(release):
    from mtg_analyzer.game.game_engine import GameEngine
    eng = _engine()
    bear = _bf(eng, _creature('Bear'))
    host = _bf(eng, _creature('Clone', oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    aura = _aura(eng, host)
    if release == 'end':
        _activate(eng, aura)
        _end(eng)
    else:
        coffin = _coffin(eng)
        _activate(eng, coffin, [host])
        eng.rules.set_tapped(coffin, False)
        eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'enter_as_copy'
    assert host.zone == aura.zone == Zone.EXILE
    cloned = GameEngine(eng.state.clone())
    cloned.rules.resolve_choice(str(bear.instance_id))
    cloned.resolve_until_stable()
    returned = cloned.state.find_object(host.instance_id)
    returned_aura = cloned.state.find_object(aura.instance_id)
    assert returned.zone == returned_aura.zone == Zone.BATTLEFIELD
    assert returned.name == 'Bear'
    assert returned_aura.attached_to == returned.instance_id
    assert host.zone == aura.zone == Zone.EXILE


def test_aura_legality_uses_completed_host_entry_choice():
    eng = _engine()
    bear = _bf(eng, _creature('Bear'))
    host = _bf(eng, _creature('Clone', oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    aura = _aura(eng, host)
    narrow = _aura(eng, host, 'Bear Aura', restriction='Bear')
    _activate(eng, aura)
    _end(eng)
    assert narrow.zone == Zone.EXILE
    eng.rules.resolve_choice(str(bear.instance_id))
    eng.resolve_until_stable()
    assert narrow.zone == Zone.BATTLEFIELD and narrow.attached_to == host.instance_id


def test_aura_entry_choice_cannot_attach_to_a_later_host_visit():
    eng = _engine(); host = _bf(eng, _creature('Bear')); source = _aura(eng, host)
    aura = _bf(eng, Card(id='prism', name='Prism Aura', type_line='Enchantment — Aura',
        oracle_text='Enchant creature\nAs this enchantment enters, choose a color.'))
    aura.attached_to = host.instance_id
    _activate(eng, source); _end(eng)
    assert eng.state.pending_choice['kind'] == 'choose_color'
    assert host.zone == Zone.BATTLEFIELD and aura.zone == Zone.EXILE
    eng.rules.exile(host); eng.rules.return_from_exile(host, host.zone_incarnation)
    eng.resolve_pending_choice('U')
    assert aura.zone == Zone.EXILE


def _announce_flickerform(eng, aura):
    eng.state.player_by_id('p1').mana_pool.add('W', 4)
    eng.activate_ability(eng.state.player_by_id('p1'), aura)


def test_departed_source_aura_uses_last_attachment_relationship():
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host)
    _announce_flickerform(eng, aura)
    eng.rules.return_to_hand(aura)
    eng.resolve_until_stable()
    assert host.zone == Zone.EXILE and aura.zone == Zone.HAND
    _end(eng)
    assert host.zone == Zone.BATTLEFIELD and aura.zone == Zone.HAND


def test_reattached_source_uses_relationship_just_before_departure():
    eng = _engine(); first = _bf(eng, _creature('First')); second = _bf(eng, _creature('Second'))
    aura = _aura(eng, first)
    _announce_flickerform(eng, aura)
    eng.rules.attach_to_target(aura, second)
    eng.rules.return_to_hand(aura)
    eng.resolve_until_stable()
    assert first.zone == Zone.BATTLEFIELD and second.zone == Zone.EXILE
    _end(eng)
    assert second.zone == Zone.BATTLEFIELD


def test_blinked_source_uses_old_relationship_instead_of_new_host():
    eng = _engine(); first = _bf(eng, _creature('First')); second = _bf(eng, _creature('Second'))
    aura = _aura(eng, first)
    _announce_flickerform(eng, aura)
    eng.rules.exile(aura)
    eng.rules.return_from_exile(aura, aura.zone_incarnation, attach_to=second)
    eng.resolve_until_stable()
    assert first.zone == Zone.EXILE and second.zone == aura.zone == Zone.BATTLEFIELD
    assert aura.attached_to == second.instance_id
    _end(eng)
    assert first.zone == Zone.BATTLEFIELD
    assert aura.attached_to == second.instance_id


def test_departed_source_never_follows_blinked_host_replacement():
    eng = _engine(); host = _bf(eng, _creature('Bear')); aura = _aura(eng, host)
    _announce_flickerform(eng, aura)
    eng.rules.return_to_hand(aura)
    eng.rules.blink(host)
    eng.resolve_until_stable()
    assert host.zone == Zone.BATTLEFIELD
    assert not eng.state.delayed_triggers
