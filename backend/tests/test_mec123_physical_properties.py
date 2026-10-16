"""Factual physical print-layout observations, announcements and Alexander."""
import pytest

from mtg_analyzer.game import physical_properties as physical
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from test_mec106_gift import _engine, _bf, _creature, _hand, _spell

ALEXANDER = "Whenever you cast a wordy spell, scry 2. (A spell is wordy if it has four or more lines of rules text.)\n{1}{R}, {T}: Choose target creature you don't control. Reveal the top card of your library. Alexander Clamilton gets +X/+0 until end of turn, where X is the number of lines of rules text of the revealed card. Alexander Clamilton fights that creature."


def alexander(eng):
    return _bf(eng, _creature('Alexander Clamilton', 0, 4, oracle_text=ALEXANDER))


def spell(eng, name='Spell'):
    return _hand(eng, _spell(name, 'Draw a card.'))


def pay(eng):
    player = eng.state.player_by_id('p1')
    for color in ('C', 'U', 'R'):
        player.mana_pool.add(color, 20)
    return player


def cast_unknown(eng, obj, **kwargs):
    eng.cast_spell(pay(eng), obj, **kwargs)
    assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    assert obj.zone == Zone.HAND
    assert not eng.state.stack


@pytest.mark.parametrize('lines', [0, 3, 4, 15])
def test_wordy_is_actual_fact_not_oracle_wrapping_and_only_casts_after_input(lines):
    eng = _engine()
    alexander(eng)
    obj = spell(eng)
    before = list(eng.state.event_log)
    cast_unknown(eng, obj)
    assert not [e for e in eng.state.event_log[len(before):] if e.type == 'SPELL_CAST']
    eng.resolve_pending_choice(str(lines))
    assert obj.zone == Zone.STACK
    assert len(eng.rules.pending_triggers) == (1 if lines >= 4 else 0)
    assert physical.measured(eng.state, obj) == lines


@pytest.mark.parametrize('answer', ['', '-1', '1.5', ' 4', '+4', '４', '١', '10001', 'decline', None])
def test_invalid_fact_keeps_choice_and_cast_pending(answer):
    eng = _engine(); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    choice = eng.state.pending_choice
    with pytest.raises(ValueError):
        eng.resolve_pending_choice(answer)
    assert eng.state.pending_choice is choice
    assert eng.state.pending_physical_cast is not None
    assert physical.measured(eng.state, obj) is None
    assert obj.zone == Zone.HAND


def test_two_alexanders_request_one_fact_and_receive_two_real_triggers():
    eng = _engine(); alexander(eng); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    eng.resolve_pending_choice('4')
    assert not eng.state.pending_choice
    assert len(eng.rules.pending_triggers) == 2


def test_cast_pending_clone_replays_current_objects_only():
    eng = _engine(); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('3')
    assert clone.state.find_object(obj.instance_id).zone == Zone.STACK
    assert obj.zone == Zone.HAND
    assert physical.measured(eng.state, obj) is None


def test_stale_cast_source_rejected_after_incarnation_change():
    eng = _engine(); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    obj.zone = Zone.EXILE
    obj.zone = Zone.HAND
    eng.resolve_pending_choice('4')
    assert eng.state.pending_choice is None
    assert eng.state.pending_physical_cast is None
    assert not eng.state.stack


def activate_unknown(eng, *, library=True):
    source = alexander(eng)
    enemy = _bf(eng, _creature('Enemy', 1, 20), player='p2')
    player = pay(eng)
    player.library.clear()
    revealed = GameObject(Card(id='physical-print', name='Visible printing', type_line='Land', is_land=True), owner_id='p1', zone=Zone.LIBRARY)
    if library:
        player.library.append(revealed)
    eng.activate_ability(player, source, 0, target_groups=[[enemy]])
    eng.resolve_until_stable()
    if library:
        assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    return source, enemy, revealed


def test_revealed_count_pumps_source_then_fights_original_enemy():
    eng = _engine()
    source, enemy, revealed = activate_unknown(eng)
    assert source.tapped and enemy.damage_marked == 0
    eng.resolve_pending_choice('5')
    assert source.power == 5 and enemy.damage_marked == 5 and source.damage_marked == 1
    assert eng.state.player_by_id('p1').library[-1] is revealed
    assert not eng.state.pending_choice


def test_reveal_measurement_clone_keeps_original_target_groups():
    eng = _engine()
    source, enemy, revealed = activate_unknown(eng)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('6')
    assert clone.state.find_object(enemy.instance_id).damage_marked == 6
    assert enemy.damage_marked == 0 and source.power == 0


def test_empty_library_reveal_never_fabricates_fact():
    eng = _engine()
    source, enemy, revealed = activate_unknown(eng, library=False)
    assert not eng.state.pending_choice
    assert source.power == 0 and enemy.damage_marked == 0
    assert source.damage_marked == 1  # Impossible reveal does not suppress the remaining fight.
    assert not eng.state.physical_property_facts


def test_blinked_source_during_observation_does_not_gain_pump_or_fight():
    eng = _engine()
    source, enemy, revealed = activate_unknown(eng)
    eng.rules.context.blink(source)
    eng.resolve_pending_choice('5')
    assert source.power == 0 and enemy.damage_marked == 0


def test_same_name_different_printings_have_distinct_facts_and_faces():
    eng = _engine()
    a = spell(eng, 'Same name'); b = spell(eng, 'Same name')
    b.physical_printing['printing_id'] = 'other-printing'
    eng.state.physical_property_facts[physical.key(a)] = 4
    assert physical.measured(eng.state, b) is None
    assert physical.measured(eng.state, a, 'back') is None
    assert physical.measured(eng.state, a) == 4


def test_unpayable_api_cast_never_opens_mandatory_observation():
    from mtg_analyzer.services.game_session import GameSession
    eng = _engine(); alexander(eng); obj = spell(eng)
    session = GameSession(eng, require_setup=False)
    from mtg_analyzer.services.game_session import GameActionError
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'cast_spell', 'instance_id': obj.instance_id}, actor_id='p1')
    assert session.engine.state.pending_choice is None
    assert session.engine.state.pending_physical_cast is None


def test_illegal_announced_target_is_rejected_before_prompt_or_costs():
    eng = _engine(); alexander(eng)
    obj = _hand(eng, _spell('Creature Bolt', 'Creature Bolt deals 3 damage to target creature.'))
    player = pay(eng)
    before = player.mana_pool.to_dict()
    with pytest.raises(ValueError):
        eng.cast_spell(player, obj, targets=[player])
    assert eng.state.pending_choice is None
    assert player.mana_pool.to_dict() == before


def test_cast_choice_subject_is_private_and_waiting_prompt_generic():
    from mtg_analyzer.services.game_session import GameSession
    import json
    eng = _engine(); alexander(eng); obj = spell(eng, 'Secret hand printing')
    cast_unknown(eng, obj)
    session = GameSession(eng, require_setup=False)
    owner = session.view(perspective='p1')
    opponent = session.view(perspective='p2')
    assert owner['state']['pending_choice']['subject']['name'] == 'Secret hand printing'
    assert 'Secret hand printing' not in json.dumps(opponent)
    assert 'subject' not in opponent['state']['waiting_on_choice']
    assert 'physical_property_facts' not in opponent['state']


def test_cast_fact_and_full_announcement_are_rewound_together():
    from mtg_analyzer.services.game_session import GameSession
    eng = _engine(); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    session = GameSession(eng, require_setup=False)
    session.apply_action({'type': 'choose', 'option_id': '3'}, actor_id='p1')
    assert session.engine.state.find_object(obj.instance_id).zone == Zone.STACK
    session.rewind()
    assert session.engine.state.pending_choice['kind'] == 'physical_property_measurement'
    restored = session.engine.state.find_object(obj.instance_id)
    assert restored.zone == Zone.HAND and physical.measured(session.engine.state, restored) is None
    session.apply_action({'type': 'choose', 'option_id': '4'}, actor_id='p1')
    assert restored.zone == Zone.STACK


def test_controlled_turn_private_fact_routes_to_controller():
    from mtg_analyzer.models.game.game_state import TurnControl
    from mtg_analyzer.services.game_session import GameSession
    eng = _engine(); alexander(eng); obj = spell(eng, 'Controlled hand printing')
    turn = TurnControl('p1', 'p2', eng.state.internal_turn.number, 'turn', 'Mindslaver')
    turn.phase = 'active'
    eng.state.turn_controls.append(turn)
    cast_unknown(eng, obj)
    session = GameSession(eng, require_setup=False)
    assert session.view(perspective='p2')['state']['pending_choice']['subject']['name'] == obj.name
    assert session.view(perspective='p1')['state']['pending_choice'] is None
    session.apply_action({'type': 'choose', 'option_id': '3'}, actor_id='p2')
    assert obj.zone == Zone.STACK


@pytest.mark.parametrize('lines', [3, 4])
def test_resolution_free_cast_waits_for_fact_then_finishes_outer_tail_once(lines):
    from mtg_analyzer.game.effects.core import GainLifeEffect
    eng = _engine(); alexander(eng)
    player = eng.state.player_by_id('p1')
    obj = spell(eng)
    player.hand.remove(obj); obj.zone = Zone.EXILE; player.exile.append(obj)
    eng.state.deferred_effects.append({'effects': [GainLifeEffect(amount=2)], 'targets': None,
                                       'target_groups': None, 'source': alexander(eng)})
    eng.rules._request_resolution_play(player, [obj])
    eng.play_resolution_card(player, obj)
    assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    assert obj.zone == Zone.EXILE and player.life == 20
    eng.resolve_pending_choice(str(lines))
    assert obj.zone == Zone.STACK and player.life == 22
    assert not eng.state.pending_choice and not eng.state.deferred_effects
    assert len(eng.rules.pending_triggers) == (2 if lines >= 4 else 0)


def three_player_engine():
    eng = GameEngine.new_game([(f'p{i}', f'Player{i}', []) for i in range(1, 4)], starting_hand=0)
    eng.begin_turn(); eng.state.current_step = 'main1'
    return eng


def test_cast_observer_concession_cancels_prompt_without_casting():
    eng = three_player_engine(); alexander(eng); obj = spell(eng)
    cast_unknown(eng, obj)
    eng.rules.concede(eng.state.player_by_id('p1'))
    eng.resolve_until_stable()
    assert eng.state.pending_physical_cast is None
    assert eng.state.pending_choice is None
    assert not eng.state.stack and not eng.state._batch_hold


def test_reveal_observer_concession_cancels_owned_tail_without_missing_fact_crash():
    eng = three_player_engine()
    source, enemy, revealed = activate_unknown(eng)
    eng.rules.concede(eng.state.player_by_id('p1'))
    eng.resolve_until_stable()
    assert not eng.state.pending_choice and not eng.state._batch_hold
    assert enemy.damage_marked == 0


def test_target_concedes_during_cast_fact_then_valid_input_aborts_without_lock():
    from mtg_analyzer.services.game_session import GameSession
    eng = three_player_engine(); alexander(eng)
    target = _bf(eng, _creature('Target', 1, 20), player='p2')
    obj = _hand(eng, _spell('Target spell', 'Target spell deals 3 damage to target creature.'))
    player = pay(eng)
    before = player.mana_pool.to_dict()
    eng.cast_spell(player, obj, targets=[target])
    eng.rules.concede(eng.state.player_by_id('p2'))
    session = GameSession(eng, require_setup=False)
    session.apply_action({'type': 'choose', 'option_id': '3'}, actor_id='p1')
    assert session.engine.state.pending_choice is None
    assert session.engine.state.pending_physical_cast is None
    assert session.engine.state.find_object(obj.instance_id).zone == Zone.HAND
    assert session.engine.state.player_by_id('p1').mana_pool.to_dict() == before


@pytest.mark.full_cache
def test_actual_cached_alexander_binds_and_resolves_real_paid_activation():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    card = CardDatabase(DB_PATH).get_card('Alexander Clamilton')
    assert card is not None and parse_oracle(card).modeled
    eng = _engine(); source = _bf(eng, card)
    enemy = _bf(eng, _creature('Actual enemy', 1, 20), player='p2')
    eng.activate_ability(pay(eng), source, 0, target_groups=[[enemy]])
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    eng.resolve_pending_choice('5')
    assert source.power == 5 and enemy.damage_marked == 5 and source.damage_marked == 1


def test_blind_controlled_sideboard_cast_observation_stays_with_private_owner():
    import json
    from mtg_analyzer.models.game.game_state import TurnControl
    from mtg_analyzer.services.game_session import GameSession, GameActionError
    from test_mec120_sideboard_casting import engine, card, permission
    eng = engine([card('Secret Outside Printing')]); permission(eng); alexander(eng)
    player = eng.state.player_by_id('p1'); player.mana_pool.add('C', 1)
    obj = player.sideboard[0]
    turn = TurnControl('p1', 'p2', eng.state.internal_turn.number, 'turn', 'Mindslaver')
    turn.phase = 'active'; eng.state.turn_controls.append(turn)
    session = GameSession(eng, require_setup=False)
    session.apply_action({'type': 'cast_spell', 'instance_id': obj.instance_id}, actor_id='p2')
    private = session.view('p1'); blind = session.view('p2')
    assert private['state']['pending_choice']['subject']['name'] == 'Secret Outside Printing'
    assert 'Secret Outside Printing' not in json.dumps(blind)
    assert obj in player.sideboard and obj.zone is None
    assert len(private['legal_actions']) == 1 and not blind['legal_actions']
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'choose', 'option_id': '3'}, actor_id='p2')
    session.apply_action({'type': 'choose', 'option_id': '3'}, actor_id='p1')
    restored = session.engine.state.find_object(obj.instance_id)
    assert restored.zone == Zone.STACK
    assert session.view('p2')['state']['stack'][-1]['object']['name'] == 'Secret Outside Printing'


def test_preflight_does_not_mutate_live_mana_gift_flags_face_rng_or_events():
    import copy
    eng = _engine(); alexander(eng); obj = spell(eng)
    player = pay(eng)
    original = copy.deepcopy((player.mana_pool.to_dict(), obj.card, obj.gift_promised,
                              (eng.state.rng_seed, eng.state.rng_counter), [event.to_dict() for event in eng.state.event_log]))
    eng.cast_spell(player, obj)
    assert player.mana_pool.to_dict() == original[0]
    assert obj.card.name == original[1].name and obj.gift_promised == original[2]
    assert (eng.state.rng_seed, eng.state.rng_counter) == original[3] and [event.to_dict() for event in eng.state.event_log] == original[4]


def test_lower_level_cast_does_not_treat_unknown_as_zero():
    eng = _engine(); alexander(eng); obj = spell(eng)
    player = pay(eng)
    with pytest.raises(ValueError, match='must be measured'):
        eng.rules.cast_spell(player, obj)
    assert obj.zone == Zone.HAND
    eng.state.physical_property_facts[physical.key(obj)] = 0
    eng.rules.cast_spell(player, obj)
    assert obj.zone == Zone.STACK and not eng.rules.pending_triggers


@pytest.mark.full_cache
def test_modal_fight_announcement_preserves_mode_and_target_groups():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase
    eng = _engine(); alexander(eng)
    own = _bf(eng, _creature('Friendly fighter', 3, 20))
    enemy = _bf(eng, _creature('Enemy fighter', 1, 20), player='p2')
    obj = _hand(eng, CardDatabase(DB_PATH).get_card('Temur Charm'))
    player = pay(eng); player.mana_pool.add('G', 1)
    eng.cast_spell(player, obj, mode=0, target_groups=[[own], [enemy]])
    assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    eng.resolve_pending_choice('3')
    eng.resolve_until_stable()
    assert own.power == 4 and enemy.damage_marked == 4 and own.damage_marked == 1


def test_known_fact_avoids_trial_clone_and_second_prompt(monkeypatch):
    eng = _engine(); alexander(eng); obj = spell(eng)
    eng.state.physical_property_facts[physical.key(obj)] = 3
    def forbidden(*args, **kwargs):
        pytest.fail('cached physical count must not require a trial or prompt')
    monkeypatch.setattr(physical, 'validate_cast', forbidden)
    eng.cast_spell(pay(eng), obj)
    assert obj.zone == Zone.STACK and eng.state.pending_choice is None


def test_back_face_observation_precedes_live_face_swap_and_is_distinct():
    eng = _engine(); alexander(eng)
    card = Card(id='double-print', name='Front // Back', type_line='Land', is_land=True,
                layout='modal_dfc', back_name='Back Spell', back_type_line='Instant',
                back_oracle_text='Draw a card.', back_mana_cost_string='{1}')
    obj = _hand(eng, card)
    original_card = obj.card
    eng.cast_spell(pay(eng), obj, face='back')
    assert obj.card is original_card
    assert eng.state.pending_choice['subject']['face'] == 'back'
    assert eng.state.pending_choice['subject']['name'] == 'Back Spell'
    eng.resolve_pending_choice('4')
    assert obj.zone == Zone.STACK and obj.card.name == 'Back Spell'
    assert physical.measured(eng.state, obj, 'back') == 4
    assert physical.measured(eng.state, obj, 'front') is None
    assert len(eng.rules.pending_triggers) == 1


def test_copy_effect_does_not_change_actual_physical_printing_key():
    eng = _engine()
    source = _bf(eng, _creature('Original printing', 2, 20))
    template = _bf(eng, _creature('Copied face', 4, 20))
    original = physical.subject(source)
    eng.state.physical_property_facts[physical.key(source)] = 7
    eng.rules.become_copy(source, template)
    assert source.card.name == template.card.name
    assert physical.subject(source) == original
    assert physical.measured(eng.state, source) == 7



@pytest.mark.parametrize("owned_payoff", [False, True])
def test_conceded_observed_free_cast_revokes_owned_window_and_runs_surviving_tail_once(owned_payoff):
    from mtg_analyzer.game.effects.core import GainLifeEffect
    eng = three_player_engine()
    alexander(eng)
    owner = eng.state.player_by_id('p1')
    survivor = eng.state.player_by_id('p2')
    outer_source = _bf(eng, _creature('Surviving outer source', 2, 20), player='p2')
    obj = spell(eng)
    owner.hand.remove(obj); obj.zone = Zone.EXILE; owner.exile.append(obj)
    eng.state.free_cast_instance_ids.add(987654)
    eng.state.deferred_effects.append({
        'effects': [GainLifeEffect(amount=2, source=outer_source)],
        'source': outer_source, 'targets': None, 'target_groups': None,
    })
    eng.rules._request_resolution_play(owner, [obj])
    if owned_payoff:
        eng.state.resolution_play_choice.update({
            'owner_life_loss': True,
            'owner_life_losses': [{'owner_id': 'p2', 'amount': 7}],
        })
        eng.state.resolution_play_followup = {'player_id': 'p1', 'instance_ids': []}
    eng.play_resolution_card(owner, obj)
    assert eng.state.pending_choice['kind'] == 'physical_property_measurement'
    assert eng.state.resolution_play_waiting
    before = survivor.life
    eng.rules.concede(owner)
    eng.resolve_until_stable()
    assert survivor.life == before + 2
    assert not eng.state.pending_choice and not eng.state.pending_physical_cast
    assert eng.state.resolution_play_choice is None
    assert eng.state.resolution_play_followup is None
    assert not eng.state.resolution_play_waiting
    assert obj.instance_id not in eng.state.free_cast_instance_ids
    assert obj.instance_id not in eng.state.free_cast_ignore_timing_instance_ids
    assert 987654 in eng.state.free_cast_instance_ids
    assert not eng.state.deferred_effects and not eng.state._batch_hold
    eng.resolve_until_stable()
    assert survivor.life == before + 2
