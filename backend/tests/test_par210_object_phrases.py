"""PAR-210: one operand grammar composes the existing operations, with real target/selector behavior."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.object_phrase import parse_operand
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_player_references import board, game


def cast(eng, text, targets=None):
    card = Card(id='operand-spell', name='Operand Spell', type_line='Sorcery', is_sorcery=True,
                mana_cost_string='{0}', oracle_text=text)
    assert parse_oracle(card).modeled, text
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    eng.state.player_by_id('p1').hand.append(spell)
    eng.cast_spell(eng.state.player_by_id('p1'), spell, targets=targets or [])
    eng.resolve_until_stable()
    return spell


@pytest.mark.parametrize('phrase,count,optional', [
    ('target creature', 1, False), ('up to 2 target creatures', 2, True),
    ('3 target creatures you control', 3, False), ('up to two target creatures', 2, True),
])
def test_quantified_target_grammar(phrase, count, optional):
    operand = parse_operand(phrase, ClauseReading())
    assert operand is not None and operand.kind == 'target'
    assert (operand.count, operand.optional) == (count, optional)


@pytest.mark.parametrize('text', [
    'goad it', 'goad that creature', 'goad those creatures', 'goad them',
])
def test_a_missing_referent_is_never_invented(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('text', [
    'Goad up to two target creatures.', 'Regenerate up to two target creatures.',
    'Up to two target creatures gain haste until end of turn.',
    'Up to two target creatures get +1/+1 until end of turn.',
    'Prevent all damage that would be dealt to up to two target creatures this turn.',
])
def test_existing_operations_share_quantified_target_announcement(text):
    eng = game()
    first = board(eng, creature('First'), 'p2')
    second = board(eng, creature('Second'), 'p2')
    spell = cast(eng, text, [first, second])
    specs = [s for e in spell.spell_effects for s in e.target_specs]
    assert len(specs) == 1 and specs[0].count == 2 and specs[0].optional
    if text.startswith('Goad'):
        assert first.goaded_by == second.goaded_by == {'p1'}
    elif 'gain haste' in text:
        eng.recompute_continuous_effects()
        assert 'haste' in first.granted_keywords and 'haste' in second.granted_keywords
    elif 'get +1/+1' in text:
        eng.recompute_continuous_effects()
        assert first.power == second.power == 3
    elif text.startswith('Prevent'):
        eng.rules.deal_damage(first, 2)
        eng.rules.deal_damage(second, 2)
        assert first.damage_marked == second.damage_marked == 0
    else:
        eng.rules.destroy(first)
        eng.rules.destroy(second)
        assert first.zone is second.zone is Zone.BATTLEFIELD


def test_zero_optional_targets_does_not_reach_an_earlier_target_group():
    eng = game()
    bear = board(eng, creature('Bear'), 'p2')
    cast(eng, 'Goad up to two target creatures.', [])
    assert not bear.goaded_by


@pytest.mark.parametrize('noun', ['each creature', 'all creatures'])
def test_group_operands_are_untargeted_and_include_hexproof(noun):
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy', oracle_text='Hexproof'), 'p2')
    spell = cast(eng, f'Goad {noun} your opponents control.')
    assert not any(e.target_specs for e in spell.spell_effects)
    assert not own.goaded_by and enemy.goaded_by == {'p1'}


@pytest.mark.parametrize('tail', ['Goad that creature.', 'Untap that creature.'])
def test_singular_reference_uses_the_previous_pick(tail):
    eng = game()
    first = board(eng, creature('First'), 'p2')
    other = board(eng, creature('Other'), 'p2')
    cast(eng, 'Tap target creature. ' + tail, [first])
    assert not other.goaded_by and not other.tapped
    assert first.goaded_by == {'p1'} if tail.startswith('Goad') else not first.tapped


def test_plural_reference_applies_to_every_previously_chosen_creature():
    eng = game()
    first = board(eng, creature('First'), 'p2')
    second = board(eng, creature('Second'), 'p2')
    other = board(eng, creature('Other'), 'p2')
    cast(eng, 'Tap two target creatures. Goad those creatures.', [first, second])
    assert first.goaded_by == second.goaded_by == {'p1'}
    assert not other.goaded_by


def test_a_plural_reference_cannot_use_a_single_prior_pick():
    card = creature('Ambiguous', oracle_text='Tap target creature. Goad those creatures.')
    assert not parse_oracle(card).modeled


def test_group_reference_uses_the_same_controller_scope_as_the_antecedent():
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'Tap each creature your opponents control. Goad those creatures.')
    assert enemy.tapped and enemy.goaded_by == {'p1'}
    assert not own.tapped and not own.goaded_by


def test_created_group_reference_uses_tokens_rather_than_an_earlier_target():
    eng = game()
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'Tap target creature. Create two 1/1 green Elf creature tokens. Goad those creatures.', [enemy])
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 2 and all(obj.goaded_by == {'p1'} for obj in tokens)
    assert enemy.tapped and not enemy.goaded_by


@pytest.mark.parametrize('text', [
    'Tap two target creatures. Goad that creature.',
    'Target player draws a card. Goad that creature.',
])
def test_incompatible_or_ambiguous_reference_is_not_claimed(text):
    assert not parse_oracle(Card(id='ambiguous', name='Ambiguous', type_line='Sorcery',
                                is_sorcery=True, oracle_text=text)).modeled


def test_plural_destruction_is_one_event_batch():
    eng = game()
    first = board(eng, creature('First', oracle_text='Vigilance'), 'p2')
    second = board(eng, creature('Second', oracle_text='Vigilance'), 'p2')
    batches = []
    eng.state.subscribe(lambda event: batches.append(event) if event.type == 'EVENT_BATCH' else None)
    cast(eng, 'Destroy up to two target creatures with vigilance.', [first, second])
    deaths = [event for event in batches if event.get('batch_of') == 'DIES']
    assert len(deaths) == 1 and len(deaths[0].get('members')) == 2
    assert not eng.state._batch_hold and not eng.state.deferred_effects


def test_sacrifice_pronoun_and_group_are_untargeted_and_controller_limited():
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'Sacrifice each creature.')
    assert own.zone is Zone.GRAVEYARD and enemy.zone is Zone.BATTLEFIELD
    other = board(eng, creature('Other'))
    cast(eng, 'Tap target creature. Sacrifice that creature.', [other])
    assert other.zone is Zone.GRAVEYARD


@pytest.mark.parametrize('clone', [False, True])
def test_plural_move_keeps_its_batch_and_remaining_members_across_commander_choice(clone):
    eng = game()
    first = board(eng, creature('Commander', oracle_text='Vigilance'), 'p2')
    first.is_commander = True
    second = board(eng, creature('Second', oracle_text='Vigilance'), 'p2')
    first_id, second_id = first.instance_id, second.instance_id
    cast(eng, "Return up to two target creatures with vigilance to their owners' hands.", [first, second])
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'commander_zone'
    assert eng.state._batch_hold
    assert second.zone is Zone.BATTLEFIELD
    if clone:
        eng = GameEngine(eng.state.clone())
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    hand_ids = {obj.instance_id for obj in eng.state.player_by_id('p2').hand}
    assert {first_id, second_id} <= hand_ids
    assert not eng.state.pending_choice and not eng.state.deferred_effects and not eng.state._batch_hold


def cast_named(eng, name, targets=None):
    from tests.test_par210_player_references import DB
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1 = eng.state.player_by_id('p1')
    p1.hand.append(spell)
    p1.mana_pool.add_many({'W': 8, 'U': 8, 'B': 8, 'R': 8, 'G': 8, 'C': 8})
    eng.cast_spell(p1, spell, targets=targets or [])
    eng.resolve_until_stable()
    return spell


def test_applied_geometry_puts_counters_on_the_copy_and_keeps_the_original_unchanged():
    eng = game()
    original = board(eng, creature('Original'))
    cast_named(eng, 'Applied Geometry', [original])
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 1
    assert tokens[0].counters.get('+1/+1') == 6
    assert not original.counters and original.power == 2
    assert tokens[0].power == tokens[0].toughness == 6


def test_hellion_eruption_measures_the_actual_sacrifices_instead_of_a_missing_trigger():
    eng = game()
    own = [board(eng, creature(f'Victim {i}')) for i in range(2)]
    enemy = board(eng, creature('Enemy'), 'p2')
    cast_named(eng, 'Hellion Eruption')
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 2 and all(obj.power == obj.toughness == 4 for obj in tokens)
    assert all(obj.zone is Zone.GRAVEYARD for obj in own)
    assert enemy.zone is Zone.BATTLEFIELD


@pytest.mark.parametrize('clone,accept', [(False, True), (True, True), (True, False)])
def test_cori_steel_cutters_optional_attachment_remembers_the_created_token(clone, accept):
    from tests.test_par210_player_references import DB
    eng = game()
    cutter = board(eng, DB.get_card('Cori-Steel Cutter'))
    cutter_id = cutter.instance_id
    cast(eng, 'You gain 1 life.')
    cast(eng, 'You gain 1 life.')
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'composite_optional'
    if clone:
        eng = GameEngine(eng.state.clone())
    eng.resolve_pending_choice('yes' if accept else 'decline')
    eng.resolve_until_stable()
    cutter = eng.state.find_object(cutter_id)
    tokens = [obj for obj in eng.state.battlefield if obj.is_token]
    assert len(tokens) == 1
    assert cutter.attached_to == (tokens[0].instance_id if accept else None)


@pytest.mark.parametrize('separator', ['and', ', then'])
def test_elided_player_actions_share_one_target_and_keep_the_player(separator):
    eng = game()
    p2 = eng.state.player_by_id('p2')
    discarded = GameObject(creature('Discarded'), owner_id='p2', zone=Zone.HAND)
    p2.hand.append(discarded)
    spell = cast(eng, f'Target player discards a card {separator} draws a card.', [p2])
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(next(o['id'] for o in choice['options'] if o['id'] != 'decline'))
        eng.resolve_until_stable()
    assert discarded.zone is Zone.GRAVEYARD
    assert len(p2.hand) == 1 and not eng.state.player_by_id('p1').hand
    assert sum(len(effect.target_specs) for effect in spell.spell_effects) == 1


def test_group_x_is_measured_once_before_any_member_changes_the_measurement():
    eng = game()
    first = board(eng, creature('First', power=2, toughness=2))
    second = board(eng, creature('Second', power=4, toughness=4))
    cast(eng, 'Each creature you control gets +X/+X until end of turn, where X is the greatest power among creatures you control.')
    eng.recompute_continuous_effects()
    assert (first.power, second.power) == (6, 8)


@pytest.mark.parametrize('name', ['Necropolis Regent', 'Aveline de Grandpré'])
def test_existing_damage_count_riders_still_put_counters_on_the_firing_creature(name):
    from tests.test_par210_player_references import DB
    eng = game()
    source = board(eng, DB.get_card(name))
    attacker = board(eng, creature('Attacker', oracle_text='Deathtouch'))
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 3, source=attacker, combat=True)
    eng.resolve_until_stable()
    assert attacker.counters.get('+1/+1') == 3
    assert not source.counters


def test_full_moons_rise_regenerates_only_its_controllers_werewolves():
    from tests.test_par210_player_references import DB
    eng = game()
    rise = board(eng, DB.get_card("Full Moon's Rise"))
    wolf = board(eng, creature('Werewolf', type_line='Creature — Werewolf'))
    bear = board(eng, creature('Bear'))
    enemy = board(eng, creature('Enemy Werewolf', type_line='Creature — Werewolf'), 'p2')
    eng.activate_ability(eng.state.player_by_id('p1'), rise)
    eng.resolve_until_stable()
    for obj in [wolf, bear, enemy]:
        eng.rules.destroy(obj)
    assert wolf.zone is Zone.BATTLEFIELD and wolf.tapped
    assert bear.zone is enemy.zone is Zone.GRAVEYARD


def test_ancestral_katanas_paid_attachment_retains_the_attackers_referent():
    from tests.test_par210_player_references import DB
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng = game()
    katana = board(eng, DB.get_card('Ancestral Katana'))
    attacker = board(eng, creature('Samurai', type_line='Creature — Samurai'))
    eng.state.player_by_id('p1').mana_pool.add('C', 1)
    eng.state.fire_event(GameEvent(EventType.ATTACKS_ALONE, instance_id=attacker.instance_id,
                                  player_id='p1', controller_id='p1', object_types=['creature'],
                                  object_subtypes=['Samurai']))
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'pay_cost_then'
    eng.resolve_pending_choice('pay')
    eng.resolve_until_stable()
    assert katana.attached_to == attacker.instance_id


@pytest.mark.parametrize('plural', [False, True])
def test_reference_nouns_reuse_the_shared_subtype_vocabulary(plural):
    eng = game()
    elves = [board(eng, creature(f'Elf {i}', type_line='Creature — Elf'), 'p2') for i in range(2)]
    if plural:
        cast(eng, 'Tap up to two target Elves. Goad those Elves.', elves)
        assert all(obj.goaded_by == {'p1'} for obj in elves)
    else:
        cast(eng, 'Tap target Elf. Goad that Elf.', [elves[0]])
        assert elves[0].goaded_by == {'p1'} and not elves[1].goaded_by


def test_rhonas_group_keyword_goes_to_the_creatures_that_were_doubled():
    from mtg_analyzer.game.binding.core import bind_from_catalogue as bind
    eng = game()
    p1 = eng.state.player_by_id('p1')
    mine = board(eng, creature('A', power=2, toughness=2), 'p1')
    theirs = board(eng, creature('Opp'), 'p2')
    card = Card(id='rhonas', name='God-Eternal Rhonas', type_line='Legendary Creature — Zombie God', is_creature=True,
                power=5, toughness=5, mana_cost_string='{3}{G}{G}', converted_mana_cost=5,
                oracle_text='Deathtouch\nWhen God-Eternal Rhonas enters, double the power of each other creature you '
                            'control until end of turn. Those creatures gain vigilance until end of turn.')
    assert parse_oracle(card).modeled
    rhonas = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind(rhonas)
    p1.hand.append(rhonas)
    p1.mana_pool.add_many({'G': 3, 'C': 6})
    eng.cast_spell(p1, rhonas)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert mine.power == 4 and 'vigilance' in [k.lower() for k in mine.granted_keywords]
    assert theirs.power == 2 and 'vigilance' not in [k.lower() for k in theirs.granted_keywords]


def test_that_creature_after_an_equipped_trigger_is_not_the_equipped_host():
    # Sword of Kaldra: "that creature" is the damaged creature, not the host the bare "it" would name.
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading as CR
    assert parse_effect_body('exile that creature', reading=CR(attached_subject=True)) is None
