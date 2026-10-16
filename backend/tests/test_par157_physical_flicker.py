"""Real paper-card observations, fresh counts and exact linked return batches."""
import pytest

from test_mec106_gift import _engine, _bf, _creature, _hand, _spell, _cast
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.game.card_catalogue.d import drive_to_work  # noqa: F401
from mtg_analyzer.game.card_catalogue.n import now_you_see_me  # noqa: F401
from mtg_analyzer.game.card_catalogue.l import landfill  # noqa: F401

MIRRORS = 'Exile target creature you control, then return it to the battlefield under its owner\'s control with X +1/+1 counters on it, where X is the number of mirrors on walls you can see from your seat.'
DRIVE = "Exile target creature or Vehicle. At the beginning of the next end step, return that card to the battlefield under its owner's control. Then you may share a story or fun fact about that card. If you do, you gain 3 life."
LANDFILL = 'Choose a land type. Exile all lands you control of that type. Drop those cards, one at a time, onto the playing area from a height of at least one foot. Destroy each permanent completely covered by those cards. Then return the cards you dropped to the battlefield tapped.'


def _answer(eng, answer):
    eng.resolve_pending_choice(answer)


def _end(eng):
    eng._fire_delayed_triggers('end'); eng.resolve_until_stable()


@pytest.mark.parametrize('answer,life', [('shared', 23), ('decline', 20)])
def test_drive_to_work_actual_return_then_optional_story(answer, life):
    eng = _engine(); target = _bf(eng, _creature('Passenger'), 'p2')
    _cast(eng, _hand(eng, _spell('Drive to Work', DRIVE)), targets=[target])
    assert target.zone == Zone.EXILE
    assert eng.state.pending_choice is None
    _end(eng)
    assert target.zone == Zone.BATTLEFIELD
    assert eng.state.pending_choice['kind'] == 'physical_card_story'
    assert eng.state.player_by_id('p1').life == 20
    _answer(eng, answer)
    assert eng.state.player_by_id('p1').life == life


def test_drive_to_work_accepts_uncrewed_vehicle_but_not_plain_artifact():
    from mtg_analyzer.game.targeting import legal_targets
    eng = _engine()
    vehicle = _bf(eng, Card(id='vehicle', name='Vehicle', type_line='Artifact — Vehicle'))
    artifact = _bf(eng, Card(id='artifact', name='Artifact', type_line='Artifact'))
    obj = _hand(eng, _spell('Drive to Work', DRIVE))
    legal = legal_targets(eng.state, 'p1', obj.spell_effects[0].target_spec, obj)
    ids = {option.get('instance_id') for option in legal}
    assert vehicle.instance_id in ids and artifact.instance_id not in ids
    _cast(eng, obj, targets=[vehicle]); _end(eng)
    assert vehicle.zone == Zone.BATTLEFIELD


def test_drive_stale_visit_does_not_return_but_story_instruction_still_runs():
    eng = _engine(); target = _bf(eng, _creature('Passenger'))
    _cast(eng, _hand(eng, _spell('Drive to Work', DRIVE)), targets=[target])
    eng.rules.return_to_hand(target); eng.rules.exile(target)
    _end(eng)
    assert target.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'physical_card_story'
    _answer(eng, 'shared')
    assert eng.state.player_by_id('p1').life == 23


@pytest.mark.parametrize('value', ['0', '4'])
def test_mirror_count_is_reported_after_exile_and_used_before_entry(value):
    from mtg_analyzer.models.game.events import EventType
    eng = _engine(); target = _bf(eng, _creature('Mirror Visitor', 2, 20))
    seen = []
    eng.state.subscribe(lambda event: seen.append(dict(target.counters))
        if event.type == EventType.ENTERS_BATTLEFIELD and event.get('instance_id') == target.instance_id else None)
    _cast(eng, _hand(eng, _spell('Now You See Me . . .', MIRRORS)), targets=[target])
    assert target.zone == Zone.EXILE
    assert eng.state.pending_choice['kind'] == 'physical_environment_measurement'
    assert not eng.state.physical_property_facts
    _answer(eng, value)
    assert target.zone == Zone.BATTLEFIELD
    assert target.counters.get('+1/+1', 0) == int(value)
    assert seen == [target.counters]
    assert not eng.state.physical_property_facts


@pytest.mark.parametrize('invalid', ['', '-1', '1.5', '1e2', '٤', '10001', 'decline'])
def test_mirror_invalid_count_preserves_pending_observation(invalid):
    eng = _engine(); target = _bf(eng, _creature('Visitor'))
    _cast(eng, _hand(eng, _spell('Now You See Me . . .', MIRRORS)), targets=[target])
    with pytest.raises(ValueError):
        _answer(eng, invalid)
    assert eng.state.pending_choice['kind'] == 'physical_environment_measurement'
    assert target.zone == Zone.EXILE


def test_mirror_clone_resume_and_fresh_next_resolution():
    eng = _engine(); target = _bf(eng, _creature('Visitor', 2, 20))
    _cast(eng, _hand(eng, _spell('Now You See Me . . .', MIRRORS)), targets=[target])
    first_id = eng.state.pending_choice['observation_id']
    clone = GameEngine(eng.state.clone()); _answer(clone, '2')
    returned = clone.state.find_object(target.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and target.zone == Zone.EXILE
    _cast(clone, _hand(clone, _spell('Now You See Me . . .', MIRRORS)), targets=[returned])
    assert clone.state.pending_choice['observation_id'] != first_id
    _answer(clone, '5')
    assert returned.counters['+1/+1'] == 5
    assert not clone.state.physical_property_facts


def _land(eng, name, subtype='Forest', owner='p1'):
    return _bf(eng, Card(id=name, name=name, type_line=f'Land — {subtype}', is_land=True), owner)


def _landfill(eng):
    _cast(eng, _hand(eng, _spell('Landfill', LANDFILL, 'Sorcery')))
    assert eng.state.pending_choice['kind'] == 'landfill_land_type'


def test_landfill_reports_any_covered_permanents_and_returns_original_lands_tapped():
    eng = _engine(); land = _land(eng, 'Own forest'); otherland = _land(eng, 'Other forest', owner='p2')
    own = _bf(eng, _creature('Own casualty')); enemy = _bf(eng, _creature('Enemy casualty'), 'p2')
    _landfill(eng); _answer(eng, 'Forest')
    assert land.zone == Zone.EXILE and otherland.zone == Zone.BATTLEFIELD
    assert eng.state.pending_choice['kind'] == 'landfill_covered_report'
    _answer(eng, str(own.instance_id)); _answer(eng, str(enemy.instance_id)); _answer(eng, 'done')
    assert own.zone == enemy.zone == Zone.GRAVEYARD
    assert land.zone == Zone.BATTLEFIELD and land.tapped
    assert otherland.zone == Zone.BATTLEFIELD


def test_landfill_nonbasic_landtype_and_explicit_zero_covered_report():
    eng = _engine(); land = _land(eng, 'Cave', subtype='Cave'); forest = _land(eng, 'Forest')
    _landfill(eng)
    assert any(o['id'] == 'Cave' for o in eng.state.pending_choice['options'])
    _answer(eng, 'Cave')
    assert land.zone == Zone.EXILE and forest.zone == Zone.BATTLEFIELD
    _answer(eng, 'done')
    assert land.zone == Zone.BATTLEFIELD and land.tapped
    assert forest.zone == Zone.BATTLEFIELD


def test_landfill_covered_toggle_and_indestructible_are_real_rules_operations():
    eng = _engine(); land = _land(eng, 'Forest')
    survivor = _bf(eng, _creature('Indestructible', keywords=['Indestructible']))
    toggled = _bf(eng, _creature('Uncovered'))
    _landfill(eng); _answer(eng, 'Forest')
    for obj in (survivor, toggled, toggled): _answer(eng, str(obj.instance_id))
    _answer(eng, 'done')
    assert survivor.zone == toggled.zone == land.zone == Zone.BATTLEFIELD


def test_landfill_clone_remembers_report_and_exact_land_visit():
    eng = _engine(); land = _land(eng, 'Forest'); enemy = _bf(eng, _creature('Covered'), 'p2')
    _landfill(eng); _answer(eng, 'Forest'); _answer(eng, str(enemy.instance_id))
    clone = GameEngine(eng.state.clone())
    moved = clone.state.find_object(land.instance_id)
    clone.rules.return_to_hand(moved); clone.rules.exile(moved)
    _answer(clone, 'done')
    assert moved.zone == Zone.EXILE
    assert clone.state.find_object(enemy.instance_id).zone == Zone.GRAVEYARD
    assert enemy.zone == Zone.BATTLEFIELD


def test_landfill_no_selected_type_lands_needs_no_fabricated_drop_report():
    eng = _engine(); _land(eng, 'Forest'); _landfill(eng); _answer(eng, 'Island')
    assert eng.state.pending_choice is None


def test_mirror_session_authorization_hidden_waiting_and_undo():
    from mtg_analyzer.services.game_session import GameSession, GameActionError
    eng = _engine(); target = _bf(eng, _creature('Visitor', 2, 20))
    _cast(eng, _hand(eng, _spell('Now You See Me . . .', MIRRORS)), targets=[target])
    session = GameSession(eng, require_setup=False)
    assert session.view(perspective='p2')['state']['pending_choice'] is None
    waiting = session.view(perspective='p2')['state']['waiting_on_choice']
    assert 'subject' not in waiting and 'exile_visit' not in waiting
    assert session.legal_actions(perspective='p2') == []
    assert session.legal_actions(perspective='p1')[0]['free_text'] is True
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'choose', 'option_id': '4'}, actor_id='p2')
    session.apply_action({'type': 'choose', 'option_id': '4'}, actor_id='p1')
    assert session.engine.state.find_object(target.instance_id).counters['+1/+1'] == 4
    session.rewind()
    assert session.engine.state.pending_choice['kind'] == 'physical_environment_measurement'
    assert session.engine.state.find_object(target.instance_id).zone == Zone.EXILE
    session.apply_action({'type': 'choose', 'option_id': '1'}, actor_id='p1')
    assert session.engine.state.find_object(target.instance_id).counters['+1/+1'] == 1


def test_mirror_controlled_turn_routes_to_normal_decider():
    from mtg_analyzer.models.game.game_state import TurnControl
    from mtg_analyzer.services.game_session import GameSession
    eng = _engine(); target = _bf(eng, _creature('Visitor'))
    turn = TurnControl('p1', 'p2', eng.state.internal_turn.number, 'turn', 'Mindslaver')
    turn.phase = 'active'; eng.state.turn_controls.append(turn)
    _cast(eng, _hand(eng, _spell('Now You See Me . . .', MIRRORS)), targets=[target])
    session = GameSession(eng, require_setup=False)
    assert session.view(perspective='p1')['state']['pending_choice'] is None
    assert session.view(perspective='p2')['state']['pending_choice']['property'] == 'visible_wall_mirrors'
    session.apply_action({'type': 'choose', 'option_id': '2'}, actor_id='p2')
    assert target.counters['+1/+1'] == 2


@pytest.mark.parametrize('card', ['mirror', 'landfill', 'story'])
def test_concession_cancels_physical_observation_without_stale_choice(card):
    eng = GameEngine.new_game([('p1', 'One', []), ('p2', 'Two', []), ('p3', 'Three', [])],
        starting_life=20, starting_hand=0)
    eng.begin_turn(); eng.state.current_step = 'main1'
    if card == 'landfill':
        _land(eng, 'Forest'); _landfill(eng); _answer(eng, 'Forest')
    else:
        target = _bf(eng, _creature('Visitor', 2, 20))
        name, text = ('Now You See Me . . .', MIRRORS) if card == 'mirror' else ('Drive to Work', DRIVE)
        _cast(eng, _hand(eng, _spell(name, text)), targets=[target])
        if card == 'story': _end(eng)
    assert eng.state.pending_choice is not None
    from mtg_analyzer.game.effects.core import GainLifeEffect
    outer_source = _bf(eng, _creature('Surviving source'), 'p2')
    eng.state.deferred_effects.insert(0, {
        'effects': [GainLifeEffect(amount=2, source=outer_source)],
        'source': outer_source, 'targets': None, 'target_groups': None,
    })
    eng.rules.concede(eng.state.player_by_id('p1')); eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert not eng.state.deferred_effects
    assert not eng.state.resolution_play_waiting and not eng.state._batch_hold
    assert eng.state.player_by_id('p2').life == 22
    assert eng.state.player_by_id('p3').life == 20
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 22


def test_landfill_only_its_decider_may_submit_covered_report():
    from mtg_analyzer.services.game_session import GameSession, GameActionError
    eng = _engine(); land = _land(eng, 'Forest'); _landfill(eng); _answer(eng, 'Forest')
    session = GameSession(eng, require_setup=False)
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'choose', 'option_id': 'done'}, actor_id='p2')
    assert session.engine.state.pending_choice['kind'] == 'landfill_covered_report'
    session.apply_action({'type': 'choose', 'option_id': 'done'}, actor_id='p1')
    assert session.engine.state.find_object(land.instance_id).zone == Zone.BATTLEFIELD
