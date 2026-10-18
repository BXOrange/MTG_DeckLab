"""Return control, printed-type filters and face-down entry compose."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.services.card_database import CardDatabase
from test_mec106_gift import _engine, _bf, _creature


@pytest.mark.parametrize('name,controller', [('Cold Storage', 'p1'), ('Synod Sanctum', 'p1'), ('Endless Sands', 'p2')])
def test_cached_pool_activations_preserve_return_controller_after_sacrifice(name, controller):
    eng = _engine()
    source = _bf(eng, CardDatabase(DB_PATH).get_card(name))
    assert parse_oracle(source.card).modeled
    stolen = _bf(eng, _creature('Stolen'), 'p2')
    stolen.controller_id = 'p1'
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 20)
    eng.activate_ability(player, source, 0, targets=[stolen])
    eng.resolve_until_stable()
    assert stolen.zone == Zone.EXILE
    source.tapped = False
    eng.activate_ability(player, source, 1)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert stolen.zone == Zone.BATTLEFIELD and stolen.controller_id == controller


def test_printed_type_filter_preserves_other_pool_members_for_later_return():
    eng = _engine()
    source = _bf(eng, _creature('Pool source'))
    creature = _bf(eng, Card(id='golem', name='Golem', type_line='Artifact Creature — Golem',
        is_creature=True, power=2, toughness=2))
    artifact = _bf(eng, Card(id='stone', name='Stone', type_line='Artifact'))
    for obj in (creature, artifact):
        eng.rules.exile(obj)
        eng.state.track_exiled_with(source, obj)
    specs = parse_effect_body('return each artifact creature card exiled with ~ '
        'to the battlefield tapped under your control.')
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)
    assert creature.zone == Zone.BATTLEFIELD and creature.tapped
    assert artifact.zone == Zone.EXILE
    for effect in build_effects(parse_effect_body('return all cards exiled with ~ '
            'to the battlefield under your control.'), source):
        effect.apply(eng.rules.context)
    assert artifact.zone == Zone.BATTLEFIELD


def test_shorecrasher_returns_face_down_and_keeps_printed_megamorph_route():
    eng = _engine()
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Shorecrasher Elemental'))
    assert parse_oracle(source.card).modeled
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'U': 2, 'C': 4})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.face_down
    assert (source.power, source.toughness) == (2, 2)
    assert not source.activated_abilities
    clone = GameEngine(eng.state.clone())
    copied = clone.state.find_object(source.instance_id)
    clone.turn_face_up(clone.state.player_by_id('p1'), copied)
    assert not copied.face_down and copied.name == 'Shorecrasher Elemental'
    assert copied.counters.get('+1/+1') == 1
    assert source.face_down


@pytest.mark.parametrize('owner,controller', [('p1', 'p1'), ('p2', 'p1'), ('p1', 'p2')])
def test_gatekeeper_branches_on_pre_exile_control_and_preserves_token_recipient(owner, controller):
    eng = _engine()
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Unyielding Gatekeeper'))
    assert parse_oracle(source.card).modeled
    target = _bf(eng, _creature('Branch target'), owner)
    target.controller_id = controller
    eng.rules.turn_face_down(source, 'disguise')
    eng.rules.turn_face_up(source)
    eng.resolve_until_stable()
    pending = eng.state.pending_choice
    assert pending and pending['kind'] == 'trigger_target'
    assert str(source.instance_id) not in {str(o.get('instance_id')) for o in pending['options']}
    eng.resolve_pending_choice(str(target.instance_id))
    detectives = [obj for obj in eng.state.battlefield if obj.name == 'Detective']
    if controller == 'p1':
        assert target.zone == Zone.BATTLEFIELD and target.tapped
        assert target.controller_id == owner and not detectives
    else:
        assert target.zone == Zone.EXILE
        assert len(detectives) == 1 and detectives[0].controller_id == controller


def test_unregistered_control_branch_composes_with_delayed_entry_counters_and_other_body():
    eng = _engine()
    text = ('{1}: Exile target creature. If you controlled it, return it to the battlefield '
        "under its owner's control with a dream counter on it at the beginning of your next upkeep. "
        'Otherwise, its controller draws two cards.')
    source = _bf(eng, _creature('Branch Example', oracle_text=text))
    assert parse_oracle(source.card).modeled
    target = _bf(eng, _creature('Own target'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    eng.activate_ability(player, source, targets=[target])
    eng.resolve_until_stable()
    assert target.zone == Zone.EXILE
    eng._fire_delayed_triggers('upkeep')
    eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD and target.counters.get('dream') == 1


@pytest.mark.parametrize('subtype,drawn', [('Bird', 1), ('Frog', 1), ('Otter', 1), ('Rat', 1), ('Elf', 0)])
def test_splash_portal_draws_for_returned_subtype_union(subtype, drawn):
    from test_par136_delayed_blink import _cast
    eng = _engine()
    card = CardDatabase(DB_PATH).get_card('Splash Portal')
    assert parse_oracle(card).modeled
    target = _bf(eng, Card(id=subtype, name='Returned', type_line=f'Creature — {subtype}',
        is_creature=True, power=2, toughness=2))
    player = eng.state.player_by_id('p1')
    before = len(player.hand)
    _cast(eng, player, card.oracle_text, targets=[target])
    assert target.zone == Zone.BATTLEFIELD and len(player.hand) == before + drawn


def test_return_subtype_rider_waits_for_entry_copy_choice_and_reads_new_face():
    from test_par136_delayed_blink import _cast
    eng = _engine()
    bird = _bf(eng, Card(id='bird', name='Bird model', type_line='Creature — Bird',
        is_creature=True, power=2, toughness=2))
    elf = _bf(eng, Card(id='elf', name='Elf model', type_line='Creature — Elf',
        is_creature=True, power=2, toughness=2))
    target = _bf(eng, _creature('Clone', 0, 0, oracle_text=
        'You may have Clone enter as a copy of any creature on the battlefield.'))
    eng.rules.become_copy(target, bird)
    player = eng.state.player_by_id('p1')
    before = len(player.hand)
    _cast(eng, player, CardDatabase(DB_PATH).get_card('Splash Portal').oracle_text, targets=[target])
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'enter_as_copy'
    assert len(player.hand) == before
    eng.resolve_pending_choice(str(elf.instance_id))
    assert target.zone == Zone.BATTLEFIELD and target.name == 'Elf model'
    assert len(player.hand) == before


def test_unseen_return_type_union_and_adversarial_condition():
    tail = "exile target creature. return it to the battlefield under its owner's control. "
    assert parse_effect_body(tail + 'if that creature is a warrior or wizard, gain 2 life.')
    assert parse_effect_body(tail + 'if that creature is a bird, frog, or imaginarytype, draw a card.') is None
    # An ordinary destructive tail still has no live permanent to inspect.
    assert parse_effect_body('destroy target creature. if that creature is a bird, draw a card.') is None


def test_target_controller_body_survives_draw_choice_and_clone_after_exile():
    eng = _engine()
    source = _bf(eng, _creature('Scoped body source'))
    target = _bf(eng, _creature('Borrowed target'))
    target.controller_id = 'p2'
    dredger = _bf(eng, _creature('Dredger', oracle_text='Dredge 1', keywords=['Dredge']), 'p2')
    eng.rules.put_into_graveyard(dredger)
    effects = parse_effect_body('exile target creature. draw a card. gain 2 life.')
    wrapper = EffectSpec('trigger_subject_referent', {'referent': 'target', 'acting': 'controller',
        'effects': [spec.to_dict() for spec in effects]})
    build_effects([wrapper], source)[0].apply(eng.rules.context, [target])
    assert target.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'dredge'
    assert eng.state.pending_choice['player_id'] == 'p2'
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(dredger.instance_id))
    assert clone.state.player_by_id('p2').life == 22
    assert clone.state.player_by_id('p1').life == 20
    assert eng.state.player_by_id('p2').life == 20


@pytest.mark.parametrize('departure', ['destroy', 'exile'])
def test_helvault_links_both_activations_but_returns_only_on_death(departure):
    eng = _engine()
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Helvault'))
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 20)
    own = _bf(eng, _creature('Own'))
    opponent = _bf(eng, _creature('Opponent'), 'p2')
    for index, target in enumerate((own, opponent)):
        source.tapped = False
        eng.activate_ability(player, source, index, targets=[target])
        eng.resolve_until_stable()
        assert target.zone == Zone.EXILE
    getattr(eng.rules, departure)(source)
    eng.resolve_until_stable()
    if departure == 'destroy':
        assert own.zone == opponent.zone == Zone.BATTLEFIELD
        assert own.controller_id == 'p1' and opponent.controller_id == 'p2'
    else:
        assert own.zone == opponent.zone == Zone.EXILE


def test_promise_of_tomorrow_exiles_dying_creature_then_returns_under_ability_controller():
    eng = _engine()
    source = _bf(eng, CardDatabase(DB_PATH).get_card('Promise of Tomorrow'))
    stolen = _bf(eng, _creature('Borrowed'), 'p2')
    stolen.controller_id = 'p1'
    eng.rules.destroy(stolen)
    eng.resolve_until_stable()
    assert stolen.zone == Zone.EXILE
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', phase='ending'))
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD
    assert stolen.zone == Zone.BATTLEFIELD and stolen.controller_id == 'p1'


@pytest.mark.parametrize('text', [
    'return all cards exiled with ~ to the battlefield under your control and invent an ability',
    'return each mysterious card exiled with ~ to the battlefield under your control',
    "exile ~, then return it to the battlefield transformed face down under its owner's control",
])
def test_unknown_return_variants_stay_unclaimed(text):
    assert parse_effect_body(text) is None
