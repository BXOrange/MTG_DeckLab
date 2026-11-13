"""PAR-271: group reveals are measured before resumable APNAP draws."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, advance_to


NAMES = ["Alexander, Ship's Fool", "Ambassador K'Ehleyr"]


def top(engine, pid, name):
    obj = GameObject(get_cached_card(name), pid, Zone.LIBRARY)
    bind_from_catalogue(obj)
    engine.state.player_by_id(pid).library.append(obj)
    return obj


def fire(engine, player, source):
    if source.name == NAMES[0]:
        engine.activate_ability(player, source)
    else:
        advance_to(engine, 'begin_combat')
    engine.resolve_until_stable()


@pytest.mark.parametrize('name', NAMES)
def test_real_cards_are_modeled(name):
    result = parse_oracle(get_cached_card(name))
    assert result.modeled, result.unclaimed
    effects = result.specs[-1].effects
    assert [effect.type for effect in effects] == ['reveal_top', 'bind']
    assert effects[1].params['amount']['pool'] == 'revealed'


def test_alexander_reveals_all_before_any_draw_and_uses_greatest_mana_value():
    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, NAMES[0])
    first = top(eng, player.id, 'Grizzly Bears')
    second = top(eng, opponent.id, 'Darksteel Colossus')
    start = len(eng.state.event_log)
    hands = [len(p.hand) for p in (player, opponent)]
    fire(eng, player, source)
    assert source.tapped
    assert first in player.hand and second in opponent.hand
    assert [len(p.hand) for p in (player, opponent)] == [n + 1 for n in hands]
    assert player.life == 20 and opponent.life == 9
    events = eng.state.event_log[start:]
    relevant = [e for e in events if e.type in (EventType.REVEAL, EventType.DRAW)]
    assert [e.type for e in relevant] == [EventType.REVEAL, EventType.REVEAL, EventType.DRAW, EventType.DRAW]
    assert [e.get('player_id') for e in relevant] == ['p1', 'p2', 'p1', 'p2']


@pytest.mark.parametrize('cards,count', [(['Forest', 'Island'], 0), (['Forest', 'Grizzly Bears'], 1),
                                         (['Grizzly Bears', 'Darksteel Colossus'], 2)])
def test_ambassador_counts_nonlands_not_mana_value(cards, count):
    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, NAMES[1])
    objects = [top(eng, p.id, name) for p, name in zip((player, opponent), cards)]
    fire(eng, player, source)
    assert source.counters.get('+1/+1', 0) == count
    assert all(obj in p.hand for obj, p in zip(objects, (player, opponent)))


@pytest.mark.parametrize('name', NAMES)
def test_measurement_survives_abundance_pause_and_clone(name):
    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, name)
    on_battlefield(eng, player.id, 'Abundance')
    top(eng, player.id, 'Grizzly Bears')
    top(eng, player.id, 'Darksteel Colossus')
    second = top(eng, opponent.id, 'Grizzly Bears')
    fire(eng, player, source)
    assert eng.state.pending_choice['kind'] == 'optional_draw_dig'
    assert second in opponent.library  # APNAP draw loop has not reached p2
    assert source.counters.get('+1/+1', 0) == 0 and opponent.life == 20
    snapshot = eng.state.clone()
    # Accept the land replacement: the revealed nonland is not the card drawn.
    eng.resolve_pending_choice('land')
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None  # order the nonmatching cards
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        eng.resolve_pending_choice(str(choice['remaining'][0]))
        eng.resolve_until_stable()
    restored = GameEngine(snapshot)
    restored.resolve_pending_choice('decline')
    restored.resolve_until_stable()
    for instance in (eng, restored):
        actual = instance.state.find_object(source.instance_id)
        assert instance.state.pending_choice is None
        if name == NAMES[0]:
            assert instance.state.player_by_id('p2').life == 9
        else:
            assert actual.counters.get('+1/+1', 0) == 2
        assert instance.state.find_object(second.instance_id).zone == Zone.HAND


@pytest.mark.parametrize('name', NAMES)
def test_empty_library_contributes_nothing_but_still_attempts_draw(name):
    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, name)
    player.library.clear()
    top(eng, opponent.id, 'Grizzly Bears')
    fire(eng, player, source)
    if name == NAMES[0]:
        assert opponent.life == 18
    else:
        assert source.counters.get('+1/+1', 0) == 1
    reveals = [e for e in eng.state.event_log if e.type == EventType.REVEAL]
    assert len(reveals) == 1 and reveals[0].get('player_id') == 'p2'


@pytest.mark.parametrize('body', [
    'each player reveals the bottom card of their library, then draws a card',
    'each player reveals the top card of their library, then draws two cards',
    'each player reveals the top card of their library, then draws a card. sacrifice the revealed cards',
    'each player reveals the top card of their library, then draws a card. ~ deals x damage to a random opponent, where x is the greatest nonsense among cards revealed this way',
])
def test_nearby_unsupported_wording_fails_closed(body):
    assert parse_effect_body(body) is None


def test_random_opponent_is_untargeted_and_uses_seeded_game_randomness():
    eng = GameEngine.new_game([(f'p{i}', f'Player {i}', []) for i in range(1, 4)],
                              starting_hand=0, starting_life=20)
    eng.begin_turn()
    eng.state.current_step = 'main1'
    player = eng.state.player_by_id('p1')
    source = on_battlefield(eng, 'p1', NAMES[0])
    top(eng, 'p1', 'Forest')
    top(eng, 'p2', 'Grizzly Bears')
    top(eng, 'p3', 'Darksteel Colossus')
    snapshot = eng.state.clone()
    fire(eng, player, source)
    restored = GameEngine(snapshot)
    fire(restored, restored.state.player_by_id('p1'), restored.state.find_object(source.instance_id))
    life = [p.life for p in eng.state.players]
    assert life[0] == 20 and sorted(life[1:]) == [9, 20]
    assert [p.life for p in restored.state.players] == life
    assert eng.state.pending_choice is None


@pytest.mark.parametrize('name', NAMES)
def test_prevented_draw_does_not_remove_card_from_revealed_measurement(name):
    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, name)
    on_battlefield(eng, player.id, 'Spirit of the Labyrinth')
    eng.rules.draw(player)
    first = top(eng, player.id, 'Darksteel Colossus')
    top(eng, opponent.id, 'Grizzly Bears')
    fire(eng, player, source)
    assert first in player.library  # p1 has already drawn its allowed card this turn
    if name == NAMES[0]:
        assert opponent.life == 9
    else:
        assert source.counters.get('+1/+1', 0) == 2


@pytest.mark.parametrize('name', NAMES)
def test_rewind_restores_group_draw_pause_and_frozen_measurement(name):
    from mtg_analyzer.services.game_session import GameSession

    eng, player, opponent = game(via_steps=True)
    source = on_battlefield(eng, player.id, name)
    on_battlefield(eng, player.id, 'Pavel Chekov, First Posting')
    top(eng, player.id, 'Darksteel Colossus')
    top(eng, opponent.id, 'Grizzly Bears')
    fire(eng, player, source)
    session = GameSession(eng)
    session.apply_action({'type': 'choose', 'option_id': 'land'}, actor_id='p1')
    session.rewind()
    assert session.engine.state.pending_choice['kind'] == 'optional_draw_dig'
    session.apply_action({'type': 'choose', 'option_id': 'decline'}, actor_id='p1')
    session.engine.resolve_until_stable()
    actual = session.engine.state.find_object(source.instance_id)
    if name == NAMES[0]:
        assert session.engine.state.player_by_id('p2').life == 9
    else:
        assert actual.counters.get('+1/+1', 0) == 2


def test_member_relative_for_each_is_not_scaled_against_one_previous_object():
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading

    specs = parse_effect_body('for each permanent exiled this way, its controller draws a card',
                              reading=ClauseReading(previous_subject=True))
    assert not specs or all(spec.type != 'bind' for spec in specs)


@pytest.mark.parametrize('name', ['Bladewing, Deathless Tyrant', 'Vraska, Regal Gorgon'])
def test_shared_leading_quantifier_gains_execute_using_creature_graveyard_count(name):
    eng, player, opponent = game()
    for card_name in ('Grizzly Bears', 'Llanowar Elves', 'Forest'):
        obj = top(eng, player.id, card_name)
        player.library.remove(obj)
        obj.zone = Zone.GRAVEYARD
        player.graveyard.append(obj)
    source = on_battlefield(eng, player.id, name)
    bear = on_battlefield(eng, player.id, 'Grizzly Bears')
    other = on_battlefield(eng, opponent.id, 'Grizzly Bears')
    if name.startswith('Bladewing'):
        eng.rules.deal_damage(opponent, 1, source=source, combat=True)
        eng.rules.put_triggers_on_stack()
        eng.resolve_until_stable()
        zombies = [o for o in eng.state.battlefield if o.is_token and o.name == 'Zombie Knight']
        assert len(zombies) == 2
        assert all(o.power == 2 and o.toughness == 2 and combat.has(o, 'menace') for o in zombies)
    else:
        source.counters['loyalty'] = 10
        eng.activate_ability(player, source, ability_index=2)
        eng.resolve_until_stable()
        assert bear.counters.get('+1/+1', 0) == 2
        assert other.counters.get('+1/+1', 0) == 0
