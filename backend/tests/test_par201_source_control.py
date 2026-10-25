"""PAR-201: target an opponent to hand away the ability's own permanent."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.control import gain_control
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets, ability_target_specs
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec
from tests.support.deck_batch import card, filler, game, main_phase
from tests.test_mec118_opponent_choice import _db_card, _put
from tests.test_bug4_player_target_recheck import _grant_hexproof

CARDS = ('Avarice Amulet', 'Humble Defector', 'Jinxed Idol', 'Jinxed Ring', 'Measure of Wickedness',
         'Goblin Cadets', 'Sleeper Agent', 'Treacherous Pit-Dweller')


def _game():
    eng = game(players=3)
    main_phase(eng)
    return eng


def _humble():
    eng = _game()
    source = card(eng, 'Humble Defector')
    return eng, source


def _activate_humble(eng, source, recipient='p3', resolve=True):
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0,
                         targets=[eng.state.player_by_id(recipient)])
    if resolve:
        eng.resolve_until_stable()


@pytest.mark.parametrize('name', CARDS)
def test_named_cards_are_modeled(name):
    parsed = parse_oracle(_db_card(name))
    assert parsed.modeled, parsed.unclaimed


def test_targeted_and_untargeted_recipient_specs_remain_distinct():
    assert match_clause('target opponent gains control of ~') == [
        EffectSpec('gain_control_by_source', {'recipient': 'target_opponent'})]
    assert match_clause('an opponent gains control of ~') == [
        EffectSpec('gain_control_by_source', {'recipient': 'opponent'})]
    assert match_clause('target opponent gains control of it') is None
    assert match_clause('target opponent gains control of it', reading=ClauseReading(previous_subject=True)) is None
    assert match_clause('target opponent gains control of it', reading=ClauseReading(group_subject=True)) is None
    assert match_clause('target opponent gains control of it', reading=ClauseReading(self_subject=True))[0].params == {
        'recipient': 'target_opponent'}


@pytest.mark.parametrize('text', (
    'target opponent gains control of target creature',
    'target opponent gains control of ~ until end of turn',
    'each opponent gains control of ~',
    'target player gains control of ~',
    'target opponent gains control of ~ and puts a charge counter on it',
))
def test_unsupported_direct_control_templates_fail_closed(text):
    assert match_clause(text, reading=ClauseReading(self_subject=True)) is None


def test_multiplayer_activation_announces_either_opponent_and_draws_before_transfer():
    eng, source = _humble()
    specs = ability_target_specs(source.activated_abilities[0])
    assert len(specs) == 1 and specs[0].kind == 'opponent'
    assert {item['player_id'] for item in legal_targets(eng.state, 'p1', specs[0], source)} == {'p2', 'p3'}
    _activate_humble(eng, source)
    assert len(eng.state.player_by_id('p1').hand) == 2
    assert source.controller_id == 'p3' and source.tapped and source.summoning_sick
    assert source.owner_id == 'p1'


def test_self_is_not_an_opponent_target():
    eng, source = _humble()
    with pytest.raises(ValueError):
        _activate_humble(eng, source, 'p1')
    assert source.controller_id == 'p1' and not source.tapped


def test_announced_target_survives_stack_clone():
    eng, source = _humble()
    _activate_humble(eng, source, resolve=False)
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(source.instance_id).controller_id == 'p3'
    assert source.controller_id == 'p1'


def test_source_can_change_control_before_resolution_without_changing_who_you_means():
    eng, source = _humble()
    _activate_humble(eng, source, recipient='p2', resolve=False)
    gain_control(eng.state, source, 'p3')
    eng.resolve_until_stable()
    assert source.controller_id == 'p2'
    assert len(eng.state.player_by_id('p1').hand) == 2
    assert not eng.state.player_by_id('p3').hand


def test_transfer_already_to_target_still_records_a_new_control_effect():
    eng, source = _humble()
    _activate_humble(eng, source, recipient='p2', resolve=False)
    gain_control(eng.state, source, 'p2')
    before = len(source.control_effects)
    source.attacking = True
    eng.resolve_until_stable()
    assert source.controller_id == 'p2' and len(source.control_effects) == before + 1
    assert source.attacking  # no new controller change, so RULE 506.4 does not apply


def test_blinked_source_is_not_given_away_by_its_old_activation():
    eng, source = _humble()
    _activate_humble(eng, source, resolve=False)
    eng.rules.blink(source)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.controller_id == 'p1'
    assert len(eng.state.player_by_id('p1').hand) == 2


def test_source_in_graveyard_is_not_given_away():
    eng, source = _humble()
    _activate_humble(eng, source, resolve=False)
    eng.rules.destroy(source)
    eng.resolve_until_stable()
    assert source.zone == Zone.GRAVEYARD and source.controller_id == 'p1'
    assert len(eng.state.player_by_id('p1').hand) == 2


@pytest.mark.parametrize('when', ('before', 'after'))
def test_player_hexproof_is_respected_at_announcement_and_resolution(when):
    eng, source = _humble()
    if when == 'after':
        _activate_humble(eng, source, recipient='p2', resolve=False)
    _grant_hexproof(eng, 'p2')
    if when == 'before':
        spec = source.activated_abilities[0].effects[-1].target_spec
        assert {item['player_id'] for item in legal_targets(eng.state, 'p1', spec, source)} == {'p3'}
    else:
        eng.resolve_until_stable()
        assert source.controller_id == 'p1'
        assert not eng.state.player_by_id('p1').hand  # sole target illegal: entire ability fails


def test_recipient_who_left_the_game_is_not_replaced_by_another_opponent():
    eng, source = _humble()
    _activate_humble(eng, source, recipient='p2', resolve=False)
    eng.state.player_by_id('p2').has_lost = True
    eng.resolve_until_stable()
    assert source.controller_id == 'p1'
    assert not eng.state.player_by_id('p1').hand


@pytest.mark.parametrize('name', ('Jinxed Idol', 'Jinxed Ring'))
def test_sacrificing_a_creature_hands_the_artifact_to_announced_opponent(name):
    eng = _game()
    source = card(eng, name)
    victim = filler(eng, 'Sacrifice fodder', power=1, toughness=1)
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, targets=[eng.state.player_by_id('p3')])
    while eng.state.pending_choice:
        options = eng.state.pending_choice['options']
        eng.resolve_pending_choice(str(options[0]['id']))
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD and source.controller_id == 'p3'


def _answer_recipient(eng, player='p3'):
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice and choice['kind'] == 'trigger_target'
    assert {o['id'] for o in choice['options']} >= {'p2', 'p3'}
    eng.resolve_pending_choice(player)
    eng.resolve_until_stable()


def test_equipped_creature_death_hands_away_the_amulet_itself():
    eng = _game()
    source = card(eng, 'Avarice Amulet')
    victim = filler(eng, 'Equipped', power=1, toughness=1)
    eng.rules.attach_to_target(source, victim)
    eng.recompute_continuous_effects()
    eng.rules.destroy(victim)
    _answer_recipient(eng)
    assert source.controller_id == 'p3' and source.zone == Zone.BATTLEFIELD


def test_another_card_to_graveyard_hands_away_measure_of_wickedness():
    eng = _game()
    source = card(eng, 'Measure of Wickedness')
    discard = filler(eng, 'Discarded', type_line='Artifact', zone=Zone.HAND)
    eng.rules.discard_specific(discard)
    _answer_recipient(eng)
    assert source.controller_id == 'p3'


@pytest.mark.parametrize('name', ('Sleeper Agent', 'Treacherous Pit-Dweller'))
def test_source_pronoun_entry_triggers_target_an_opponent(name):
    eng = _game()
    source = card(eng, name)
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
                                  controller_id='p1', from_zone='graveyard'))
    _answer_recipient(eng)
    assert source.controller_id == 'p3'


def test_goblin_cadets_transfer_removes_it_from_combat():
    eng = _game()
    source = card(eng, 'Goblin Cadets')
    blocker = filler(eng, 'Blocker', player='p2', power=1, toughness=3)
    source.attacking = True
    source.combat_defender = {'kind': 'player', 'id': 'p2'}
    source.blocked_by = [blocker.instance_id]
    blocker.blocking = source.instance_id
    eng.state.fire_event(GameEvent(EventType.BECOMES_BLOCKED, instance_id=source.instance_id,
                                  controller_id='p1'))
    _answer_recipient(eng)
    assert source.controller_id == 'p3' and not source.attacking and source.combat_defender is None
    assert source.blocked_by == [] and blocker.blocking is None


def test_unrepresented_optional_sacrifice_wrapper_stays_fail_closed():
    # This other card shares the recipient wording but also needs an unless
    # sacrifice-a-land payment; do not silently turn that into a mandatory gift.
    assert not parse_oracle(_db_card('Custody Battle')).modeled


def _optional_gift():
    eng = _game()
    source = _put(eng, Card(id='Optional Gift', name='Optional Gift', type_line='Artifact',
        oracle_text='{0}: You may pay {1}. If you do, target opponent gains control of this artifact.'), 'p1')
    assert parse_oracle(source.card).modeled
    eng.state.player_by_id('p1').mana_pool.add('C', 1)
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, targets=[eng.state.player_by_id('p3')])
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'pay_cost_then'
    return eng, source


@pytest.mark.parametrize('answer', ('pay', 'decline'))
def test_optional_payment_transfer_keeps_the_announced_recipient(answer):
    eng, source = _optional_gift()
    eng.resolve_pending_choice(answer)
    eng.resolve_until_stable()
    assert source.controller_id == ('p3' if answer == 'pay' else 'p1')


def test_payment_branch_target_and_source_visit_survive_clone():
    eng, source = _optional_gift()
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('pay')
    clone.resolve_until_stable()
    assert clone.state.find_object(source.instance_id).controller_id == 'p3'
    assert source.controller_id == 'p1'


def test_payment_branch_does_not_give_away_blinked_source():
    eng, source = _optional_gift()
    eng.rules.blink(source)
    eng.resolve_pending_choice('pay')
    eng.resolve_until_stable()
    assert source.controller_id == 'p1'


def test_payment_branch_retains_original_ability_controller_after_control_change():
    eng, source = _optional_gift()
    gain_control(eng.state, source, 'p3')
    eng.resolve_pending_choice('pay')
    eng.resolve_until_stable()
    # p3 was a legal opponent of the original ability controller p1, even
    # though it is now the permanent's own controller.
    assert source.controller_id == 'p3' and len(source.control_effects) == 2


def test_payment_branch_rechecks_the_chosen_opponents_hexproof():
    eng, source = _optional_gift()
    _grant_hexproof(eng, 'p3')
    eng.resolve_pending_choice('pay')
    eng.resolve_until_stable()
    assert source.controller_id == 'p1'


def test_pit_dweller_undying_return_then_gift_uses_the_new_source_visit():
    eng = _game()
    source = card(eng, 'Treacherous Pit-Dweller')
    previous = source.zone_incarnation
    eng.rules.destroy(source)
    _answer_recipient(eng)
    assert source.zone == Zone.BATTLEFIELD and source.zone_incarnation != previous
    assert source.counters.get('+1/+1') == 1 and source.controller_id == 'p3'


def test_sleeper_agent_cast_and_entry_offer_the_recipient_choice():
    eng = _game()
    source = card(eng, 'Sleeper Agent', zone=Zone.HAND)
    eng.state.player_by_id('p1').mana_pool.add('B', 1)
    eng.cast_spell(eng.state.player_by_id('p1'), source)
    _answer_recipient(eng)
    assert source.zone == Zone.BATTLEFIELD and source.controller_id == 'p3'
