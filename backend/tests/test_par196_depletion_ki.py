"""PAR-196: conditional untap restrictions and optional ki-counter flips."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from tests.test_mec118_opponent_choice import _db_card, _engine, _put
from tests.support.deck_batch import step

LANDS = ('Land Cap', 'Lava Tubes', 'River Delta', 'Timberline Ridge', 'Veldt')
KI_CARDS = ('Budoka Pupil', 'Callow Jushi', 'Cunning Bandit', 'Faithful Squire', 'Hired Muscle')


@pytest.mark.parametrize('name', LANDS + KI_CARDS)
def test_real_cards_are_fully_modeled(name):
    result = parse_oracle(_db_card(name))
    assert result.modeled, result.unclaimed


def test_counter_condition_is_preserved_on_the_static():
    specs = static_effect_specs("~ doesn't untap during your untap step if it has a depletion counter on it")
    assert len(specs) == 1 and specs[0].type == 'no_untap'
    assert specs[0].params == {'affects': 'self', 'active_if': {
        'kind': 'source_counters', 'counter': 'depletion', 'min': 1,
    }}


@pytest.mark.parametrize('text', (
    "~ doesn't untap during your untap step if a goat sneezed",
    "~ doesn't untap during your untap step if target creature has a depletion counter on it",
    "~ doesn't untap during your untap step if it has a depletion counter on it and draw a card",
))
def test_unknown_untap_conditions_fail_closed(text):
    assert static_effect_specs(text) is None


def test_flip_pronoun_needs_the_source_reading():
    assert match_clause('flip it') is None
    assert match_clause('flip it', reading=ClauseReading(previous_subject=True)) is None
    assert match_clause('flip it', reading=ClauseReading(group_subject=True)) is None
    assert match_clause('flip it', reading=ClauseReading(self_subject=True))[0].type == 'flip'
    assert match_clause('flip ~')[0].type == 'flip'
    assert match_clause('flip it and draw a card', reading=ClauseReading(self_subject=True)) is None


@pytest.mark.parametrize('name', LANDS)
def test_depletion_skips_one_untap_then_upkeep_removes_it(name):
    eng = _engine()
    land = _put(eng, _db_card(name), 'p1')
    assert eng.tap_for_mana(eng.state.player_by_id('p1'), land)
    assert land.tapped and land.counters.get('depletion') == 1
    eng._step_untap()
    assert land.tapped and land.counters.get('depletion') == 1
    step(eng, 'upkeep')
    assert land.counters.get('depletion', 0) == 0 and land.tapped
    eng._step_untap()
    assert not land.tapped


def test_other_counters_do_not_block_untap_and_direct_untap_is_allowed():
    eng = _engine()
    land = _put(eng, _db_card('Land Cap'), 'p1')
    land.tapped = True
    land.counters['charge'] = 1
    eng._step_untap()
    assert not land.tapped
    land.counters['depletion'] = 1
    land.tapped = True
    eng.rules.set_tapped(land, False)
    assert not land.tapped


def _ki_trigger(name='Budoka Pupil', counters=2, resolve=True, player='p1'):
    eng = _engine()
    obj = _put(eng, _db_card(name), 'p1')
    obj.counters['ki'] = counters
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id=player))
    eng.rules.put_triggers_on_stack()
    if resolve:
        eng.resolve_until_stable()
    return eng, obj


@pytest.mark.parametrize('name', KI_CARDS)
def test_flip_is_optional_and_keeps_the_counters(name):
    eng, obj = _ki_trigger(name)
    assert not obj.flipped
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    assert obj.flipped and obj.counters.get('ki') == 2
    eng.recompute_continuous_effects()
    assert obj.card.is_legendary


def test_declining_the_flip_keeps_the_front():
    eng, obj = _ki_trigger()
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert not obj.flipped and obj.counters.get('ki') == 2


def test_opponents_end_step_also_offers_the_flip():
    eng, obj = _ki_trigger(player='p2')
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('yes')
    assert obj.flipped


def test_condition_is_checked_at_trigger_time():
    eng, obj = _ki_trigger(counters=1, resolve=False)
    assert not eng.state.stack
    obj.counters['ki'] = 2
    eng.resolve_until_stable()
    assert not obj.flipped and eng.state.pending_choice is None


def test_condition_is_rechecked_before_resolution():
    eng, obj = _ki_trigger(resolve=False)
    assert len(eng.state.stack) == 1
    obj.counters['ki'] = 1
    eng.resolve_until_stable()
    assert not obj.flipped and eng.state.pending_choice is None


def test_optional_flip_survives_clone():
    eng, obj = _ki_trigger()
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('yes')
    clone.resolve_until_stable()
    assert clone.state.find_object(obj.instance_id).flipped
    assert not obj.flipped


def test_blinked_source_is_not_flipped_by_the_old_optional_choice():
    eng, obj = _ki_trigger()
    eng.rules.blink(obj)
    obj.counters['ki'] = 2
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    assert not obj.flipped


def test_blinked_source_uses_its_old_counter_information_but_cannot_flip_the_new_visit():
    eng, obj = _ki_trigger(resolve=False)
    eng.rules.blink(obj)
    obj.counters['ki'] = 2
    eng.resolve_until_stable()
    # RULE 608.2h: the old visit had two counters, so its condition holds
    # using LKI; the returning permanent is still a different object.
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice('yes')
    assert not obj.flipped


@pytest.mark.parametrize('name', KI_CARDS)
def test_spirit_spell_cast_can_put_the_ki_counter_on_the_source(name):
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import Zone

    eng = _engine()
    source = _put(eng, _db_card(name), 'p1')
    spirit = _put(eng, Card(id='Spirit test', name='Spirit test', type_line='Creature — Spirit',
                           is_creature=True, power=1, toughness=1), 'p1', Zone.HAND)
    eng.cast_spell(eng.state.player_by_id('p1'), spirit)
    eng.resolve_until_stable()
    assert eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('do')
    eng.resolve_until_stable()
    assert source.counters.get('ki') == 1


def test_depletion_restriction_does_not_prevent_other_players_untap_step_grants():
    eng = _engine()
    land = _put(eng, _db_card('Land Cap'), 'p2')
    _put(eng, _db_card('Seedborn Muse'), 'p2')
    land.tapped = True
    land.counters['depletion'] = 1
    # RULE 502.3: the land only forbids its controller's own untap step.
    eng._step_untap()
    assert not land.tapped


def test_alirios_reuses_the_conditional_untap_grammar_with_a_subtype_condition():
    from tests.support.deck_batch import enter

    eng = _engine()
    source = _put(eng, _db_card('Alirios, Enraptured'), 'p1')
    assert parse_oracle(source.card).modeled
    enter(eng, source)
    reflection = next(obj for obj in eng.state.battlefield if obj.is_token)
    source.tapped = True
    eng._step_untap()
    assert source.tapped
    eng.rules.destroy(reflection)
    eng.resolve_until_stable()
    eng._step_untap()
    assert not source.tapped
