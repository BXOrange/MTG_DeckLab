"""PAR-279: optional replacement choices survive ordering, multi-draw and clone."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield


@pytest.mark.parametrize('name', ['Abundance', 'Pavel Chekov, First Posting'])
def test_real_cards(name):
    result = parse_oracle(get_cached_card(name))
    assert result.coverage == 'MODELED'
    assert result.specs[0].effects[0].type == 'optional_draw_dig'


def setup(name='Abundance', cards=('Forest', 'Island', 'Mountain', 'Grizzly Bears')):
    eng, player, _ = game()
    player.library.clear()
    for name_in_library in cards:
        obj = GameObject(get_cached_card(name_in_library), owner_id='p1', zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        player.library.append(obj)
    on_battlefield(eng, 'p1', name)
    return eng, player


def draws(eng):
    return [e for e in eng.state.event_log if e.type == EventType.DRAW]


def test_decline_draws_once():
    eng, player = setup()
    before = len(player.hand)
    eng.rules.draw(player)
    assert len(player.hand) == before
    eng.resolve_pending_choice('decline')
    assert len(player.hand) == before + 1
    assert eng.state.pending_choice is None


def test_accept_is_not_a_draw_and_does_not_exile():
    eng, player = setup('Pavel Chekov, First Posting')
    before = len(player.hand)
    eng.rules.draw(player)
    eng.resolve_pending_choice('land')
    assert len(player.hand) == before + 1 and player.hand[-1].name == 'Mountain'
    assert len(player.library) == 3 and not player.exile
    assert not draws(eng)
    assert not any(e.type == EventType.EXILE for e in eng.state.event_log)


def test_abundance_order_and_clone_before_next_draw():
    eng, player = setup(cards=('Grizzly Bears', 'Forest', 'Island', 'Mountain'))
    before = len(player.hand)
    eng.rules.draw(player, 2)
    eng.resolve_pending_choice('nonland')
    choice = eng.state.pending_choice
    assert choice['kind'] == 'library_bottom'
    restored = GameEngine(eng.state.clone())
    ids = list(choice['remaining'])
    restored.resolve_pending_choice(str(ids[1]))
    restored.resolve_pending_choice(str(ids[0]))
    assert restored.state.pending_choice['kind'] == 'optional_draw_dig'
    q = restored.state.player_by_id('p1')
    assert [o.instance_id for o in q.library] == [ids[2], ids[0], ids[1]]
    restored.resolve_pending_choice('decline')
    assert len(q.hand) == before + 2
    assert len(player.hand) == before + 1
    assert eng.state.pending_choice['kind'] == 'library_bottom'


def test_no_hit_and_empty_library_replace_without_empty_draw_loss():
    eng, player = setup(cards=('Forest',))
    before = len(player.hand)
    eng.rules.draw(player)
    eng.resolve_pending_choice('nonland')
    assert len(player.hand) == before and len(player.library) == 1
    player.library.clear()
    eng.rules.draw(player)
    eng.resolve_pending_choice('land')
    assert not getattr(player, 'attempted_draw_from_empty', False)


def test_other_player_draw_is_not_replaced():
    eng, player = setup()
    other = eng.state.player_by_id('p2')
    eng.rules.draw(other)
    assert eng.state.pending_choice is None


@pytest.mark.parametrize('first', [0, 1])
def test_multiplier_order_and_individual_replacing_draws(first):
    eng, player = setup('Pavel Chekov, First Posting')
    on_battlefield(eng, 'p1', 'Thought Reflection')
    before = len(player.hand)
    eng.rules.draw(player)
    assert eng.state.pending_choice['kind'] == 'replacement_order'
    eng.resolve_pending_choice(str(first))
    eng.resolve_pending_choice('land')
    if first == 1:  # multiplier first: each replacing draw gets its own choice
        assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
        eng.resolve_pending_choice('nonland')
    assert len(player.hand) == before + (2 if first == 1 else 1)
    assert not draws(eng)


def test_decline_after_clone_uses_current_state():
    eng, player = setup()
    before = len(player.hand)
    eng.rules.draw(player)
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline')
    assert len(restored.state.player_by_id('p1').hand) == before + 1
    assert len(player.hand) == before


def test_unrecognized_category_or_tail_stays_unclaimed():
    card = get_cached_card('Abundance')
    text = card.oracle_text.lower()
    assert replacement_clause_specs(text.replace('land or nonland', 'red or blue')) is None
    assert replacement_clause_specs(text + ' Draw a card.') is None


def test_declining_one_copy_still_offers_the_other():
    eng, player = setup()
    on_battlefield(eng, 'p1', 'Pavel Chekov, First Posting')
    eng.rules.draw(player)
    eng.resolve_pending_choice('0')
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    eng.resolve_pending_choice('land')
    assert eng.state.pending_choice is None and not draws(eng)


def test_multiplier_then_declines_draws_twice_without_reapplying_multiplier():
    eng, player = setup('Pavel Chekov, First Posting')
    on_battlefield(eng, 'p1', 'Thought Reflection')
    before = len(player.hand)
    eng.rules.draw(player)
    eng.resolve_pending_choice('1')
    eng.resolve_pending_choice('decline')
    assert len(player.hand) == before + 1
    eng.resolve_pending_choice('decline')
    assert len(player.hand) == before + 2
    assert eng.state.pending_choice is None


def test_spell_waits_for_ordering_and_all_draws():
    from tests.support.star_trek import cast, game

    eng, player, _ = game('Concentrate')
    for name in ('Forest', 'Island', 'Mountain', 'Grizzly Bears', 'Grizzly Bears'):
        player.library.append(GameObject(get_cached_card(name), owner_id='p1', zone=Zone.LIBRARY))
    on_battlefield(eng, 'p1', 'Abundance')
    cast(eng, player, player.hand[0])
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    eng.resolve_pending_choice('land')
    assert eng.state.pending_choice['kind'] == 'library_bottom'
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    eng.resolve_pending_choice('nonland')
    eng.resolve_pending_choice('decline')
    if eng.state.pending_choice:  # any ordering needed by the second replacement
        eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert len(player.hand) == 3
    assert eng.state.pending_choice is None


def test_session_rewind_restores_optional_choice():
    from mtg_analyzer.services.game_session import GameSession

    eng, player = setup('Pavel Chekov, First Posting')
    eng.rules.draw(player)
    session = GameSession(eng)
    session.apply_action({'type': 'choose', 'option_id': 'land'}, actor_id='p1')
    assert player.hand[-1].name == 'Mountain'
    session.rewind()
    assert session.engine.state.pending_choice['kind'] == 'optional_draw_dig'
    session.apply_action({'type': 'choose', 'option_id': 'decline'}, actor_id='p1')
    assert session.engine.state.player_by_id('p1').hand[-1].name == 'Grizzly Bears'


def test_draw_limit_stops_remaining_modified_draws():
    eng, player = setup('Pavel Chekov, First Posting')
    on_battlefield(eng, 'p1', 'Spirit of the Labyrinth')
    on_battlefield(eng, 'p1', 'Thought Reflection')
    eng.rules.draw(player)
    eng.resolve_pending_choice('1')
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice is None
    assert len(draws(eng)) == 1


def test_miracle_pause_preserves_remaining_modified_draw_and_clone():
    eng, player = setup('Pavel Chekov, First Posting', cards=('Forest', 'Terminus'))
    on_battlefield(eng, 'p1', 'Thought Reflection')
    before = len(player.hand)
    eng.rules.draw(player)
    eng.resolve_pending_choice('1')
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice['kind'] == 'miracle_reveal'
    restored = GameEngine(eng.state.clone())
    restored.resolve_pending_choice('decline')
    assert restored.state.pending_choice['kind'] == 'optional_draw_dig'
    restored.resolve_pending_choice('decline')
    assert len(restored.state.player_by_id('p1').hand) == before + 2
    assert len(player.hand) == before + 1


def test_later_spell_instruction_waits_until_draw_replacement_finishes():
    from mtg_analyzer.models.cards.card import Card
    from tests.support.star_trek import cast

    eng, player = setup(cards=('Forest', 'Island', 'Mountain', 'Grizzly Bears'))
    spell = GameObject(Card(id='par279-spell', name='Draw and Recover', type_line='Sorcery', is_sorcery=True,
                            oracle_text='Draw two cards. You gain 3 life.'), 'p1', Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    life = player.life
    cast(eng, player, spell)
    assert player.life == life
    eng.resolve_pending_choice('land')
    assert player.life == life
    eng.resolve_pending_choice('decline')
    eng.resolve_until_stable()
    assert player.life == life + 3
