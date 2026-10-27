"""PAR-211: quantified sets share the real target operations and selector resolver."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading, Referent, PLAYER
from mtg_analyzer.parser.oracle.catalogue.quantifier_scope import quantified_set
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_object_phrases import cast
from tests.test_par210_player_references import DB, board, game


def multiplayer():
    eng = game()
    p3 = Player(id='p3', name='Third', life=20)
    for i in range(4):
        p3.library.append(GameObject(creature(f'Third library {i}'), owner_id='p3', zone=Zone.LIBRARY))
    eng.state.players.append(p3)
    return eng


@pytest.mark.parametrize('scope,counts', [
    ('each player', [1, 1, 1]), ('each opponent', [0, 1, 1]),
    ('each other player', [0, 1, 1]),
])
def test_player_sets_execute_for_every_member_without_announcing_targets(scope, counts):
    eng = multiplayer()
    before = [len(p.hand) for p in eng.state.players]
    spell = cast(eng, f'{scope} draws a card.')
    assert [len(p.hand) - n for p, n in zip(eng.state.players, before)] == counts
    assert not any(e.target_specs for e in spell.spell_effects)


def test_optional_player_members_choose_for_themselves_and_resume_after_clone():
    eng = multiplayer()
    cast(eng, 'Each other player may draw a card.')
    assert eng.state.pending_choice['player_id'] == 'p2'
    # A continuation must survive the same state copy used by undo.
    eng = GameEngine(eng.state.clone())
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id'] == 'p3'
    eng.resolve_pending_choice('no')
    eng.resolve_until_stable()
    assert len(eng.state.players[1].hand) == 1
    assert not eng.state.players[2].hand
    assert not eng.state.pending_choice
    assert not eng.state._batch_hold


def test_other_player_token_creators_are_the_members_not_the_spell_controller():
    eng = multiplayer()
    cast(eng, 'Each other player creates a 3/3 black Angel creature token with flying.')
    angels = [o for o in eng.state.battlefield if o.is_token]
    assert sorted(o.controller_id for o in angels) == ['p2', 'p3']
    assert all(o.power == o.toughness == 3 and 'flying' in o.card.keywords for o in angels)


@pytest.mark.parametrize('quantifier', ['each', 'all'])
def test_qualified_object_scope_keeps_filter_and_duration(quantifier):
    eng = game()
    own = board(eng, creature('Own'))
    flying = board(eng, creature('Flying', oracle_text='Flying\nHexproof'), 'p2')
    ground = board(eng, creature('Ground'), 'p2')
    spell = cast(eng, f'{quantifier} other creature your opponents control with flying gets +2/+1 until end of turn.')
    eng.recompute_continuous_effects()
    assert (own.power, flying.power, flying.toughness, ground.power) == (2, 4, 3, 2)
    assert not any(e.target_specs for e in spell.spell_effects)
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert (flying.power, flying.toughness) == (2, 2)


def test_contextual_player_controller_is_the_earlier_pick():
    eng = multiplayer()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy', oracle_text='Hexproof'), 'p2')
    other = board(eng, creature('Other'), 'p3')
    spell = cast(eng, 'Target player gains 1 life. Goad each creature that player controls.', [eng.state.players[1]])
    assert enemy.goaded_by == {'p1'}
    assert not own.goaded_by and not other.goaded_by
    assert sum(len(e.target_specs) for e in spell.spell_effects) == 1


def test_contextual_permanent_controller_is_the_earlier_pick():
    eng = game()
    enemy = board(eng, creature('Enemy'), 'p2')
    own = board(eng, creature('Own'))
    cast(eng, "Tap target creature. Goad each creature that creature's controller controls.", [enemy])
    assert enemy.goaded_by == {'p1'} and not own.goaded_by


@pytest.mark.parametrize('text', [
    'Goad each creature that player controls.',
    "Goad each creature that planeswalker's controller controls.",
    'Goad all creatures with an unknown quality.',
    'For each land you control, destroy target creature.',
    'Each other player draws a card unless the moon is blue.',
])
def test_missing_bindings_and_unsupported_bodies_fail_closed(text):
    card = creature('Unbound scope', oracle_text=text)
    assert not parse_oracle(card).modeled


def test_leading_repeat_executes_separate_instructions():
    eng = game()
    for n in range(3):
        board(eng, Card(id=f'land-{n}', name=f'Land {n}', type_line='Land', is_land=True))
    card = DB.get_card("Brass's Bounty")
    assert card is not None and parse_oracle(card).modeled
    cast(eng, card.oracle_text)
    treasures = [o for o in eng.state.battlefield if o.is_token and o.card.name == 'Treasure']
    assert len(treasures) == 3 and all(o.controller_id == 'p1' for o in treasures)


@pytest.mark.parametrize('name,amount,group_amount', [
    ('Flame Wave', 4, 4), ("Chandra's Fury", 4, 1), ('Bonfire of the Damned', 3, 3),
])
@pytest.mark.parametrize('target_kind', ['player', 'planeswalker'])
def test_real_damage_cards_hit_the_target_and_its_controllers_creatures(name, amount, group_amount, target_kind):
    eng = multiplayer()
    own = board(eng, creature('Own', toughness=10))
    victims = [board(eng, creature(f'Victim {i}', toughness=10, oracle_text='Hexproof'), 'p2') for i in range(2)]
    other = board(eng, creature('Other', toughness=10), 'p3')
    walker = board(eng, Card(id='walker', name='Walker', type_line='Planeswalker'), 'p2')
    walker.counters['loyalty'] = 10
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    payer = eng.state.players[0]
    payer.hand.append(spell)
    payer.mana_pool.add_many({'R': 10, 'C': 30})
    target = eng.state.players[1] if target_kind == 'player' else walker
    eng.cast_spell(payer, spell, targets=[target], x=amount if name == 'Bonfire of the Damned' else 0)
    eng.resolve_until_stable()
    assert len(spell.spell_effects[0].target_specs) == 1
    assert all(o.damage_marked == group_amount for o in victims)
    assert not own.damage_marked and not other.damage_marked
    assert eng.state.players[1].life == (20 - amount if target_kind == 'player' else 20)
    assert walker.counters['loyalty'] == (10 - amount if target_kind == 'planeswalker' else 10)


def test_plural_combat_prevention_shields_every_player_but_no_creature_or_noncombat_damage():
    eng = multiplayer()
    bear = board(eng, creature('Bear', toughness=10))
    card = DB.get_card('Commencement of Festivities')
    assert parse_oracle(card).modeled
    cast(eng, card.oracle_text)
    for player in eng.state.players:
        eng.rules.deal_damage(player, 2, source=bear, combat=True)
        assert player.life == 20
        eng.rules.deal_damage(player, 1, source=bear)
        assert player.life == 19
    eng.rules.deal_damage(bear, 2, source=bear, combat=True)
    assert bear.damage_marked == 2
    eng._step_cleanup()
    eng.rules.deal_damage(eng.state.players[1], 2, source=bear, combat=True)
    assert eng.state.players[1].life == 17


def test_quantified_set_uses_the_same_object_selector_shape():
    reading = ClauseReading(referents=(Referent(PLAYER),))
    assert quantified_set('each creature that player controls', reading) == {
        'selector': {'zone': 'battlefield', 'of': 'context', 'controller_ref': 'previous_player',
                     'filter': {'card_type': 'creature'}}}


def test_player_relative_amount_is_measured_separately_for_each_member():
    eng = multiplayer()
    for index, player in enumerate(eng.state.players):
        for n in range(index + 1):
            board(eng, Card(id=f'land-{index}-{n}', name='Land', type_line='Land', is_land=True), player.id)
    cast(eng, '~ deals damage to each player equal to the number of lands they control.')
    assert [p.life for p in eng.state.players] == [19, 18, 17]


def test_leading_player_loop_binds_that_player_to_the_current_member():
    eng = multiplayer()
    cast(eng, 'For each player, that player gains 2 life.')
    assert [p.life for p in eng.state.players] == [22, 22, 22]


def test_leading_object_loop_uses_the_current_object():
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'For each creature your opponents control, goad it.')
    assert enemy.goaded_by == {'p1'} and not own.goaded_by


def test_all_objects_that_match_a_condition_keep_the_condition():
    eng = game()
    red = board(eng, creature('Red', cost='{R}'))
    green = board(eng, creature('Green', cost='{G}'))
    cast(eng, 'All creatures that are red gain haste until end of turn.')
    eng.recompute_continuous_effects()
    assert 'haste' in red.granted_keywords and 'haste' not in green.granted_keywords


def test_radiating_lightning_uses_the_announced_player_without_a_trigger_event():
    eng = game()
    victim = board(eng, creature('Enemy'), 'p2')
    own = board(eng, creature('Own'))
    cast(eng, '~ deals 3 damage to target player and 1 damage to each creature that player controls.', [eng.state.players[1]])
    assert eng.state.players[1].life == 17
    assert victim.damage_marked == 1 and not own.damage_marked


def test_haunted_angel_death_creates_an_angel_for_every_other_player():
    eng = multiplayer()
    angel = board(eng, DB.get_card('Haunted Angel'))
    assert parse_oracle(angel.card).modeled
    eng.rules.destroy(angel)
    eng.resolve_until_stable()
    assert angel.zone is Zone.EXILE
    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert sorted(o.controller_id for o in tokens) == ['p2', 'p3']
    assert all(o.power == o.toughness == 3 and 'flying' in o.card.keywords for o in tokens)


def test_each_other_player_excludes_the_triggering_caster_even_when_opponent_controls_the_source():
    eng = multiplayer()
    board(eng, DB.get_card('Zenith Chronicler'))
    payer = eng.state.players[1]
    spell = GameObject(Card(id='multicolor', name='Multicolor', type_line='Instant', is_instant=True,
                            mana_cost_string='{W}{U}', oracle_text='You gain 1 life.'),
                       owner_id=payer.id, zone=Zone.HAND)
    bind_from_catalogue(spell)
    payer.hand.append(spell)
    payer.mana_pool.add_many({'W': 1, 'U': 1})
    eng.cast_spell(payer, spell)
    eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [1, 0, 1]


def test_each_other_player_excludes_a_previously_named_player():
    eng = multiplayer()
    cast(eng, 'Target player gains 1 life. Each other player draws a card.', [eng.state.players[1]])
    assert [len(p.hand) for p in eng.state.players] == [1, 0, 1]


def test_contextual_group_followup_remembers_the_selected_creatures():
    eng = game()
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    cast(eng, 'Target player gains 1 life. Tap each creature that player controls. Goad those creatures.', [eng.state.players[1]])
    assert enemy.tapped and enemy.goaded_by == {'p1'}
    assert not own.tapped and not own.goaded_by


def test_trigger_player_scope_uses_the_damaged_player():
    eng = multiplayer()
    source = board(eng, creature('Scoper', oracle_text='Whenever Scoper deals combat damage to a player, goad each creature that player controls.'))
    own = board(eng, creature('Own'))
    enemy = board(eng, creature('Enemy'), 'p2')
    assert parse_oracle(source.card).modeled
    eng.rules.deal_damage(eng.state.players[1], 1, source=source, combat=True)
    eng.resolve_until_stable()
    assert enemy.goaded_by == {'p1'} and not own.goaded_by


def test_syphon_mind_keeps_discard_choices_and_the_total_across_players():
    eng = multiplayer()
    for player in eng.state.players[1:]:
        player.hand.append(GameObject(creature(f'{player.id} discard'), owner_id=player.id, zone=Zone.HAND))
    card = DB.get_card('Syphon Mind')
    assert parse_oracle(card).modeled
    cast(eng, card.oracle_text)
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(choice['options'][0]['id'])
        eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [2, 0, 0]
    assert [len(p.graveyard) for p in eng.state.players[1:]] == [1, 1]


@pytest.mark.parametrize('phrase', ['each creature that player controls with flying',
                                  'each creature with flying that player controls'])
def test_contextual_controller_and_filter_compose_in_either_order(phrase):
    eng = game()
    flying = board(eng, creature('Flyer', oracle_text='Flying'), 'p2')
    ground = board(eng, creature('Ground'), 'p2')
    cast(eng, f'Target player gains 1 life. Goad {phrase}.', [eng.state.players[1]])
    assert flying.goaded_by == {'p1'} and not ground.goaded_by


def test_grave_pact_implicit_sacrifice_choice_executes_for_each_other_player():
    eng = multiplayer()
    card = Card(id='pact', name='Pact', type_line='Enchantment',
                oracle_text='Whenever a creature you control dies, each other player sacrifices a creature.')
    assert parse_oracle(card).modeled
    board(eng, card)
    dying = board(eng, creature('Dying'))
    own = board(eng, creature('Own'))
    victims = [board(eng, creature(f'Enemy {p.id} {n}'), p.id) for p in eng.state.players[1:] for n in range(2)]
    eng.rules.destroy(dying)
    eng.resolve_until_stable()
    while eng.state.pending_choice:
        eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
        eng.resolve_until_stable()
    assert own.zone is Zone.BATTLEFIELD
    assert [sum(o.zone is Zone.GRAVEYARD for o in victims if o.owner_id == p.id)
            for p in eng.state.players[1:]] == [1, 1]


def test_balefire_dragon_retains_the_damaged_player_and_event_amount():
    eng = multiplayer()
    dragon = board(eng, DB.get_card('Balefire Dragon'))
    own = board(eng, creature('Own', toughness=10))
    victim = board(eng, creature('Victim', toughness=10), 'p2')
    other = board(eng, creature('Other', toughness=10), 'p3')
    eng.rules.deal_damage(eng.state.players[1], 4, source=dragon, combat=True)
    eng.resolve_until_stable()
    assert victim.damage_marked == 4
    assert not own.damage_marked and not other.damage_marked


def test_leading_destroy_loop_executes_the_bound_object_operation():
    eng = game()
    first = board(eng, creature('First'))
    second = board(eng, creature('Second', oracle_text='Shroud'))
    enemy = board(eng, creature('Enemy'), 'p2')
    spell = cast(eng, 'For each creature you control, destroy it.')
    assert first.zone is second.zone is Zone.GRAVEYARD
    assert enemy.zone is Zone.BATTLEFIELD
    assert not any(e.target_specs for e in spell.spell_effects)
