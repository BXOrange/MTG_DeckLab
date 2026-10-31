"""PAR-214: verb-phrase rows over the shared object phrase, executed against a real engine."""
from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_object_phrases import cast
from tests.test_par210_player_references import board, game


def lost_abilities(eng, obj):
    eng.recompute_continuous_effects()
    return bool(getattr(obj, 'loses_all_abilities', False))


def test_target_loses_all_abilities_until_end_of_turn():
    eng = game()
    target = board(eng, creature('Flier', oracle_text='Flying'), 'p2')
    bystander = board(eng, creature('Bystander', oracle_text='Flying'), 'p2')
    cast(eng, 'Target creature loses all abilities until end of turn.', [target])
    assert lost_abilities(eng, target) and 'flying' not in target.granted_keywords
    assert not lost_abilities(eng, bystander)
    eng.advance_step() if False else None
    eng._step_cleanup()
    assert not lost_abilities(eng, target)


def test_ability_loss_with_base_power_toughness_rider_shares_one_target():
    eng = game()
    target = board(eng, creature('Big', power=5, toughness=5, oracle_text='Trample'), 'p2')
    other = board(eng, creature('Other', power=4, toughness=4), 'p2')
    cast(eng, 'Target creature loses all abilities and has base power and toughness 0/1 until end of turn.', [target])
    eng.recompute_continuous_effects()
    assert lost_abilities(eng, target) and (target.power, target.toughness) == (0, 1)
    assert (other.power, other.toughness) == (4, 4)


def test_group_operand_removes_abilities_from_exactly_the_group():
    eng = game()
    theirs = board(eng, creature('Theirs', oracle_text='Flying'), 'p2')
    mine = board(eng, creature('Mine', oracle_text='Flying'))
    cast(eng, 'Each creature your opponents control loses all abilities until end of turn.')
    assert lost_abilities(eng, theirs) and not lost_abilities(eng, mine)


def test_pronoun_follow_up_binds_the_tapped_target_not_the_source():
    eng = game()
    target = board(eng, creature('Target', oracle_text='Flying'), 'p2')
    bystander = board(eng, creature('Bystander', oracle_text='Flying'), 'p2')
    source = cast(eng, 'Tap target creature an opponent controls. It loses all abilities until end of turn.', [target])
    assert target.tapped and lost_abilities(eng, target)
    assert not lost_abilities(eng, bystander) and not lost_abilities(eng, source)


def test_plural_reference_follows_the_chosen_set():
    eng = game()
    a = board(eng, creature('A', oracle_text='Flying'), 'p2')
    b = board(eng, creature('B', oracle_text='Flying'), 'p2')
    c = board(eng, creature('C', oracle_text='Flying'), 'p2')
    cast(eng, 'Tap two target creatures. They lose all abilities until end of turn.', [a, b])
    assert lost_abilities(eng, a) and lost_abilities(eng, b) and not lost_abilities(eng, c)


def test_permanent_duration_when_no_clock_is_printed():
    eng = game()
    target = board(eng, creature('Victim', oracle_text='Flying'), 'p2')
    cast(eng, 'Target creature loses all abilities.', [target])
    eng._step_cleanup()
    assert lost_abilities(eng, target)


# --- stand-alone "can't be regenerated" riders -------------------------------------------------------------------

@pytest.mark.parametrize('body', [
    "destroy target creature. a creature destroyed this way can't be regenerated",
    "destroy target creature and it can't be regenerated",
    "destroy target creature. it can't be regenerated",
])
def test_rider_after_a_destroy_denies_regeneration(body):
    specs = parse_effect_body(body)
    assert specs and "'can_be_regenerated': False" in str([s.to_dict() for s in specs])


def test_composed_destroy_rider_is_flagged_on_the_destroy_inside_the_wrapper():
    specs = parse_effect_body("destroy target wall. it can't be regenerated")
    assert [s.type for s in specs] == ['seq']
    assert "'can_be_regenerated': False" in str(specs[0].to_dict())


def test_this_way_rider_is_refused_when_two_destructions_make_it_ambiguous():
    assert parse_effect_body(
        "destroy target creature. destroy target land. a creature destroyed this way can't be regenerated") is None


def test_regeneration_is_actually_denied_at_resolution():
    eng = game()
    wall = board(eng, creature('Wall', type_line='Creature — Wall'), 'p2')
    eng.rules.regenerate(wall)
    cast(eng, "Destroy target creature. It can't be regenerated.", [wall])
    assert wall.zone is Zone.GRAVEYARD


def test_plain_destroy_still_lets_regeneration_happen():
    eng = game()
    bear = board(eng, creature('Regen Bear'), 'p2')
    eng.rules.regenerate(bear)
    cast(eng, 'Destroy target creature.', [bear])
    assert bear.zone is Zone.BATTLEFIELD


# --- untap-and-steal and exiled-card casting windows -------------------------------------------------------------

def test_untap_and_gain_control_is_the_existing_steal_with_untap_and_haste():
    eng = game()
    victim = board(eng, creature('Victim'), 'p2')
    victim.tapped = True
    cast(eng, 'Untap target creature and gain control of it until end of turn. That creature gains haste until end of turn.', [victim])
    eng.recompute_continuous_effects()
    assert victim.controller_id == 'p1' and not victim.tapped and 'haste' in victim.granted_keywords


def test_conditional_play_window_is_a_filter_on_the_single_exiled_card():
    specs = parse_effect_body("exile the top card of your library. if it's a goblin or an artifact card, you may play it this turn")
    assert specs[1].params['card_filter'] == {'any_of': [{'subtype': 'goblin'}, {'card_type': 'artifact'}]}
    assert parse_effect_body("exile the top 2 cards of your library. if it's a land card, you may play it this turn") is None


def test_exiled_card_pool_noun_for_a_single_exile():
    specs = parse_effect_body('exile target nonland permanent. you may cast the exiled card this turn')
    assert [s.type for s in specs] == ['exile', 'cast_window_exiled_pool']


@pytest.mark.parametrize('type_line,mv,offered', [
    ('Creature — Goblin', 1, True), ('Artifact', 1, True), ('Creature — Elf', 1, False),
])
def test_goblin_savant_window_only_covers_the_matching_exiled_card(type_line, mv, offered):
    from tests.support.deck_batch import activate, card, filler, stack_library
    eng = game_with_library()
    savant = card(eng, 'Goblin Savant')
    stats = dict(power=1, toughness=1) if 'Creature' in type_line else {}
    top = filler(eng, 'Exiled Top', type_line=type_line, mv=0, zone=Zone.LIBRARY, **stats)
    stack_library(eng, 'p1', top)
    activate(eng, savant)
    assert top.zone is Zone.EXILE
    assert any('Exiled Top' in str(a) for a in _castable_names_raw(eng)) is offered


def game_with_library():
    from tests.support.deck_batch import game as deck_game
    return deck_game(library=5)


def _castable_names_raw(eng):
    from tests.support.deck_batch import main_phase
    main_phase(eng)
    return eng.legal_actions(eng.state.player_by_id('p1'))


def test_loses_all_abilities_and_becomes_replaces_type_colour_and_base_stats():
    eng = game()
    bear = board(eng, creature('Dragon', power=5, toughness=5, oracle_text='Flying', type_line='Creature — Dragon'), 'p2')
    cast(eng, 'Until end of turn, target creature loses all abilities and becomes a green Snake with base power and toughness 1/1.', [bear])
    eng.recompute_continuous_effects()
    assert lost_abilities(eng, bear) and (bear.power, bear.toughness) == (1, 1)
    assert bear._derived_subtypes == {'Snake'} and bear.colors == {'G'}
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (5, 5) and not lost_abilities(eng, bear)


def test_unknown_becomes_word_stays_unclaimed():
    assert parse_effect_body('target creature loses all abilities and becomes a blue zzzz with base power and toughness 1/1') is None


def test_wondrous_wasp_removes_abilities_only_while_it_stays():
    from tests.support.deck_batch import card, filler, put_on_battlefield, answer
    eng = game_with_library()
    victim = filler(eng, 'Victim', power=2, toughness=2, player='p2', oracle_text='Flying')
    wasp = put_on_battlefield(eng, 'The Wondrous Wasp')
    answer(eng)
    eng.recompute_continuous_effects()
    assert victim.tapped and lost_abilities(eng, victim)
    eng.rules.destroy(wasp)
    eng.resolve_until_stable()
    assert not lost_abilities(eng, victim)


# --- "destroy target <kind> if it's <colour>": the colour is a resolution check, not a target restriction ----------

def _colored(eng, name, colors, owner='p2', **kw):
    from tests.support.deck_batch import filler
    # RULE 202.2: a card's colour comes from its mana cost.
    obj = filler(eng, name, player=owner, power=2, toughness=2, mana_cost_string=''.join('{%s}' % c for c in colors), **kw)
    eng.recompute_continuous_effects()
    return obj


def _spell(eng, name):
    from tests.support.deck_batch import card
    return card(eng, name, 'p1', zone=Zone.HAND)


def test_colour_condition_is_not_a_target_restriction():
    specs = parse_effect_body("destroy target creature if it's white")
    assert "'color': 'W'" not in str(specs[0].params.get('effects', [])[0]) and 'color' not in specs[0].params['effects'][0]['params']
    assert 'is_color' in str(specs)


def test_target_white_creature_stays_a_target_filter():
    specs = parse_effect_body('destroy target white creature')
    assert specs[0].params == {'target_kind': 'creature', 'creature_filter': {'color': 'W'}}


@pytest.mark.parametrize('name,colour,mode', [('Soul Rend', 'W', None), ('Hydroblast', 'R', 1), ('Pyroblast', 'U', 1)])
def test_matching_colour_target_is_destroyed(name, colour, mode):
    from tests.support.deck_batch import cast
    eng = game_with_library()
    victim = _colored(eng, 'Matching', [colour])
    kw = {'mode': [mode]} if mode is not None else {}
    cast(eng, _spell(eng, name), targets=[victim], **kw)
    assert victim.zone is Zone.GRAVEYARD


@pytest.mark.parametrize('name,colour,mode', [('Soul Rend', 'W', None), ('Hydroblast', 'R', 1), ('Pyroblast', 'U', 1)])
def test_non_matching_target_is_legal_and_survives(name, colour, mode):
    from tests.support.deck_batch import cast
    eng = game_with_library()
    other = 'B' if colour != 'B' else 'G'
    victim = _colored(eng, 'Mismatch', [other])
    spell = _spell(eng, name)
    kw = {'mode': [mode]} if mode is not None else {}
    cast(eng, spell, targets=[victim], **kw)  # a restricted target would have been refused here
    assert victim.zone is Zone.BATTLEFIELD
    assert spell.zone is Zone.GRAVEYARD


def test_soul_rend_non_matching_target_still_sets_up_its_delayed_draw():
    from tests.support.deck_batch import cast, step
    eng = game_with_library()
    victim = _colored(eng, 'Mismatch', ['B'])
    cast(eng, _spell(eng, 'Soul Rend'), targets=[victim])
    hand = len(eng.state.player_by_id('p1').hand)
    step(eng, 'upkeep', 'p1')
    assert victim.zone is Zone.BATTLEFIELD
    assert len(eng.state.player_by_id('p1').hand) == hand + 1


def test_soul_rend_denies_regeneration_to_a_matching_target():
    from tests.support.deck_batch import cast
    eng = game_with_library()
    victim = _colored(eng, 'White Wall', ['W'])
    eng.rules.regenerate(victim)
    cast(eng, _spell(eng, 'Soul Rend'), targets=[victim])
    assert victim.zone is Zone.GRAVEYARD
