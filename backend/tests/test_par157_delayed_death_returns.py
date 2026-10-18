"""Death subjects compose with return timing, recipients and entry counters."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from test_mec106_gift import _engine, _bf, _creature


@pytest.mark.parametrize('recipient', ["its owner's", 'your'])
@pytest.mark.parametrize('timing,step', [('the next end step', 'end'), ('your next upkeep', 'upkeep')])
def test_death_return_captures_visit_controller_timing_and_counters(recipient, timing, step):
    eng = _engine()
    source = _bf(eng, Card(id='observer', name='Observer', type_line='Enchantment', oracle_text=
        f'Whenever a creature dies, return it to the battlefield tapped under {recipient} control '
        f'with two +1/+1 counters on it at the beginning of {timing}.'))
    assert parse_oracle(source.card).modeled
    dead = _bf(eng, _creature('Visitor'), 'p2')
    eng.rules.put_into_graveyard(dead)
    eng.resolve_until_stable()
    assert dead.zone == Zone.GRAVEYARD and len(eng.state.delayed_triggers) == 1
    assert eng.state.delayed_triggers[0].scope == ('controller' if timing.startswith('your') else 'any')
    clone = GameEngine(eng.state.clone())
    clone._fire_delayed_triggers(step)
    clone.resolve_until_stable()
    returned = clone.state.find_object(dead.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.tapped
    assert returned.controller_id == ('p1' if recipient == 'your' else 'p2')
    assert returned.counters.get('+1/+1') == 2
    assert dead.zone == Zone.GRAVEYARD


def test_delayed_death_return_cannot_claim_a_later_graveyard_visit():
    eng = _engine()
    source = _bf(eng, _creature('Observer', oracle_text=
        "Whenever a creature dies, return it to the battlefield under your control at the beginning of the next end step."))
    dead = _bf(eng, _creature('Visitor'))
    eng.rules.put_into_graveyard(dead)
    eng.resolve_until_stable()
    eng.rules.exile(dead)
    eng.rules.put_into_graveyard(dead)
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()
    assert dead.zone == Zone.GRAVEYARD


def test_delayed_death_return_preserves_once_per_turn_head_limit():
    eng = _engine()
    source = _bf(eng, Card(id='limited', name='Limited', type_line='Enchantment', oracle_text=
        'Whenever a creature dies for the first time each turn, return it to the battlefield '
        "under its owner's control at the beginning of the next end step."))
    assert parse_oracle(source.card).modeled
    first, second = [_bf(eng, _creature(name)) for name in ('First', 'Second')]
    eng.rules.put_into_graveyard(first)
    eng.resolve_until_stable()
    eng.rules.put_into_graveyard(second)
    eng.resolve_until_stable()
    assert len(eng.state.delayed_triggers) == 1
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()
    assert first.zone == Zone.BATTLEFIELD and second.zone == Zone.GRAVEYARD


def test_delayed_death_return_does_not_return_a_token():
    eng = _engine()
    _bf(eng, Card(id='observer', name='Observer', type_line='Enchantment', oracle_text=
        'Whenever a creature dies, return it to the battlefield under your control '
        'at the beginning of the next end step.'))
    token = _bf(eng, _creature('Token'))
    token.is_token = True
    eng.rules.put_into_graveyard(token)
    eng.resolve_until_stable()
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()
    assert token not in eng.state.battlefield


def test_liliana_back_face_emblem_returns_opponents_creature_under_emblem_controller():
    eng = _engine()
    card = Card(id='liliana', name='Liliana, Defiant Necromancer',
        type_line='Legendary Planeswalker — Liliana', loyalty=8,
        oracle_text='+2: Each player discards a card.\n'
        '−X: Return target nonlegendary creature card with mana value X from your graveyard to the battlefield.\n'
        '−8: You get an emblem with "Whenever a creature dies, return it to the battlefield '
        'under your control at the beginning of the next end step."')
    assert parse_oracle(card).modeled
    source = _bf(eng, card)
    eng.activate_ability(eng.state.player_by_id('p1'), source, 2)
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p1').emblems
    dead = _bf(eng, _creature('Opponent creature'), 'p2')
    eng.rules.put_into_graveyard(dead)
    eng.resolve_until_stable()
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()
    assert dead.zone == Zone.BATTLEFIELD and dead.controller_id == 'p1'


@pytest.mark.parametrize('text', [
    "Whenever a creature enters, return it to the battlefield under your control at the beginning of the next end step.",
    "Whenever a creature dies, return target creature card to the battlefield under your control at the beginning of the next end step.",
    "Whenever a creature dies, return it to the battlefield under your control at the beginning of the next end step. Draw a card.",
])
def test_other_events_new_targets_and_unparsed_tails_are_not_claimed_as_death_returns(text):
    card = Card(id='unsafe', name='Unsafe', type_line='Enchantment', oracle_text=text)
    assert not parse_oracle(card).modeled
