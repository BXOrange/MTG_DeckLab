"""PAR-222: phase subjects and qualified player sets retain player identity."""
import pytest

from mtg_analyzer.models.game.events import GameEvent, EventType
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.game import creature
from tests.test_par210_player_references import board, DB
from tests.test_par210_object_phrases import cast
from tests.test_par211_quantifier_scopes import multiplayer


@pytest.mark.parametrize('scope', ["each player's", "each opponent's", "enchanted player's"])
@pytest.mark.parametrize('step', ['upkeep', 'end'])
def test_phase_player_and_ability_controller_keep_separate_draws(scope, step):
    eng = multiplayer()
    card = creature('Scoped', oracle_text=f'At the beginning of {scope} {step} step, that player draws a card. You gain 2 life.')
    assert parse_oracle(card).modeled
    source = board(eng, card)
    source.attached_to = 'p2'
    eng.state.active_player_index = 1
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step))
    eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [0, 1, 0]
    assert [p.life for p in eng.state.players] == [22, 20, 20]
    assert not source.triggered_abilities[0].effects[0].target_specs


def test_phase_sacrifice_uses_active_players_choice_and_survives_clone():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = multiplayer()
    board(eng, creature('Edict', oracle_text="At the beginning of each player's upkeep, that player sacrifices a creature of their choice."))
    for n in range(2):
        board(eng, creature(f'Victim {n}'), 'p2')
    eng.state.active_player_index = 1
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng = GameEngine(eng.state.clone())
    eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
    eng.resolve_until_stable()
    assert len(eng.state.players[1].graveyard) == 1
    assert not eng.state.players[0].graveyard


def test_qualified_life_history_selects_members_but_keeps_you_as_controller():
    eng = multiplayer()
    eng.rules.lose_life(eng.state.players[1], 2)
    cast(eng, 'For each opponent who lost life this turn, you draw a card.')
    assert [len(p.hand) for p in eng.state.players] == [1, 0, 0]
    cast(eng, 'Each opponent who lost life this turn gains 3 life.')
    assert [p.life for p in eng.state.players] == [20, 21, 20]


def test_qualified_control_uses_each_candidates_permanents():
    eng = multiplayer()
    board(eng, creature('White', cost='{W}'), 'p2')
    cast(eng, 'Each player who controls a white creature draws a card.')
    assert [len(p.hand) for p in eng.state.players] == [0, 1, 0]


@pytest.mark.parametrize('text', [
    'Each player who ate lunch draws a card.',
    'Each opponent who lost life this turn and sang draws a card.',
    'Each opponent who controls more creatures than you draws a card.',
    'Each player who discarded a card this way draws a card.',
])
def test_unknown_or_unbound_qualifications_fail_closed(text):
    assert not parse_oracle(creature('Invalid', oracle_text=text)).modeled


@pytest.mark.parametrize('name', ['Depopulate', 'Shatter the Sky', 'Thornbow Archer'])
def test_real_cards_are_modeled(name):
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled


def test_discard_outcome_waits_for_all_players_and_survives_clone():
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = multiplayer()
    # Clone prunes older-turn events: the recorded cursor must not depend
    # on their positions in the full journal.
    old = GameEvent(EventType.DISCARD_CARD, player_id='p3', object_types=['creature'])
    old.turn = eng.state.internal_turn.number - 1
    eng.state.event_log.insert(0, old)
    # Earlier discards this turn must not count toward this instruction.
    earlier = GameObject(creature('Earlier'), owner_id='p3', zone=Zone.HAND)
    eng.state.players[2].hand.append(earlier)
    eng.rules.discard(eng.state.players[2], 1)
    for n in range(2):
        eng.state.players[1].hand.append(GameObject(creature(f'Discard {n}'), owner_id='p2', zone=Zone.HAND))
    cast(eng, "Each opponent discards a card. For each opponent who can't, you draw a card.")
    assert eng.state.pending_choice['player_id'] == 'p2'
    assert not eng.state.players[0].hand
    eng = GameEngine(eng.state.clone())
    eng.resolve_pending_choice(eng.state.pending_choice['options'][0]['id'])
    eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [1, 1, 0]


def test_typed_discard_outcome_uses_actual_discarded_card_types():
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = multiplayer()
    eng.state.players[1].hand.append(GameObject(creature('Creature'), owner_id='p2', zone=Zone.HAND))
    eng.state.players[2].hand.append(GameObject(Card(id='land', name='Land', type_line='Land', is_land=True), owner_id='p3', zone=Zone.HAND))
    cast(eng, "Each opponent discards a card, then each opponent who didn't discard a nonland card this way loses 3 life.")
    assert [p.life for p in eng.state.players] == [20, 20, 17]


@pytest.mark.parametrize('name', ['Cruel Grimnarch', 'Nezumi Informant', 'Cut a Deal'])
def test_real_outcome_cards(name):
    card = DB.get_card(name)
    assert card is not None and parse_oracle(card).modeled


@pytest.mark.parametrize('name', ['Academy Loremaster', 'Collapsing Borders', "Teferi's Puzzle Box"])
def test_existing_phase_bodies_remain_modeled(name):
    assert parse_oracle(DB.get_card(name)).modeled


def test_qualified_negative_control_filters_each_opponent_independently():
    eng = multiplayer()
    board(eng, creature('Elf', type_line='Creature — Elf'), 'p2')
    cast(eng, "Each opponent who doesn't control an Elf loses 1 life.")
    assert [p.life for p in eng.state.players] == [20, 20, 19]


def test_discard_success_count_comes_from_the_payoff_not_the_antecedent():
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = multiplayer()
    eng.state.players[1].hand.append(GameObject(creature('Only card'), owner_id='p2', zone=Zone.HAND))
    cast(eng, 'Each opponent discards 2 cards. Each opponent who discarded a card this way draws a card.')
    assert [len(p.hand) for p in eng.state.players] == [0, 1, 0]


def test_optional_discard_outcome_asks_members_and_ignores_declines():
    from mtg_analyzer.models.game.game_object import GameObject, Zone
    eng = multiplayer()
    for player in eng.state.players[1:]:
        player.hand.append(GameObject(creature(f'{player.id} card'), owner_id=player.id, zone=Zone.HAND))
    cast(eng, 'Each opponent may discard a card. Each opponent who discarded a card this way draws a card.')
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng.resolve_pending_choice('yes')
    eng.resolve_until_stable()
    assert eng.state.pending_choice['player_id'] == 'p3'
    assert not eng.state.players[1].hand  # payoff waits for every offer
    eng.resolve_pending_choice('no')
    eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [0, 1, 1]
    assert [len(p.graveyard) for p in eng.state.players[1:]] == [1, 0]


def test_real_grimnarch_gains_life_for_each_opponent_unable_to_discard():
    eng = multiplayer()
    source = board(eng, DB.get_card('Cruel Grimnarch'))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id, controller_id='p1'))
    eng.resolve_until_stable()
    assert [p.life for p in eng.state.players] == [28, 20, 20]


def test_additional_draw_and_controller_draw_are_separate_instructions():
    eng = multiplayer()
    board(eng, creature('Shared Draw', oracle_text="At the beginning of each player's draw step, that player draws an additional card and you draw a card."))
    eng.state.active_player_index = 1
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='draw'))
    eng.resolve_until_stable()
    assert [len(p.hand) for p in eng.state.players] == [1, 1, 0]
