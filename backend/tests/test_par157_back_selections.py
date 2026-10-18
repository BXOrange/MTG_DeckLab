"""Back-face selection bodies reuse untargeted choices and structured groups."""
import json
import sqlite3
from pathlib import Path

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature


def _cached(name):
    with sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro', uri=True) as conn:
        row = conn.execute('SELECT data FROM cards WHERE name = ?', (name,)).fetchone()
    assert row is not None
    return Card.from_dict(json.loads(row[0]))


def _resolve(eng):
    eng.resolve_until_stable()
    while eng.state.pending_choice and any(
        option.get('id') == 'do' for option in eng.state.pending_choice['options']
    ):
        eng.resolve_pending_choice('do')
        eng.resolve_until_stable()


def _to_back(eng, card):
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    _resolve(eng)
    for _ in range(2):
        eng.rules.advance_sagas(eng.state.player_by_id('p1'))
        _resolve(eng)
    assert source.zone == Zone.BATTLEFIELD and source.transformed
    assert source.name == card.back_name
    return source


@pytest.mark.full_cache
def test_azusa_reaches_back_and_untaps_only_chosen_lands_you_control():
    eng = _engine()
    source = _to_back(eng, _cached("Azusa's Many Journeys // Likeness of the Seeker"))
    own = [_bf(eng, Card(id=str(i), name=f'Own {i}', type_line='Land', is_land=True)) for i in range(4)]
    other = _bf(eng, Card(id='other', name='Other', type_line='Land', is_land=True), 'p2')
    for land in [*own, other]:
        land.tapped = True
    eng.state.fire_event(GameEvent(EventType.BECOMES_BLOCKED, instance_id=source.instance_id))
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'choose_objects'
    options = {str(option['id']) for option in eng.state.pending_choice['options']}
    assert str(other.instance_id) not in options
    eng.resolve_pending_choice(str(own[0].instance_id))
    assert not own[0].tapped
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(str(own[1].instance_id))
    assert not clone.state.find_object(own[1].instance_id).tapped and own[1].tapped


def test_unrestricted_land_choice_can_untap_an_opponents_land():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    other = _bf(eng, Card(id='other', name='Other', type_line='Land', is_land=True), 'p2')
    other.tapped = True
    effects = build_effects(parse_effect_body('untap up to 2 lands'), source)
    assert not effects[0].target_specs
    effects[0].apply(eng.rules.context)
    assert str(other.instance_id) in {str(option['id']) for option in eng.state.pending_choice['options']}
    eng.resolve_pending_choice(str(other.instance_id))
    assert not other.tapped


@pytest.mark.full_cache
def test_horobi_reaches_back_and_takes_rat_tokens_without_granting_haste_or_untapping():
    eng = _engine()
    rat = _bf(eng, Card(id='Rat token', name='Rat token', is_creature=True, power=2, toughness=2, type_line='Creature — Rat'), 'p2')
    rat.is_token = True
    rat.tapped = True
    nontoken = _bf(eng, Card(id='Rat card', name='Rat card', is_creature=True, power=2, toughness=2, type_line='Creature — Rat'), 'p2')
    mouse = _bf(eng, Card(id='Mouse token', name='Mouse token', is_creature=True, power=2, toughness=2, type_line='Creature — Mouse'), 'p2')
    mouse.is_token = True
    source = _to_back(eng, _cached("Tribute to Horobi // Echo of Death's Wail"))
    assert rat.controller_id == 'p1' and rat.tapped
    assert nontoken.controller_id == mouse.controller_id == 'p2'
    assert not rat.granted_keywords
    eng.rules.put_into_graveyard(source)
    assert rat.controller_id == 'p1'


@pytest.mark.parametrize('duration', ['', ' until end of turn'])
def test_mass_control_combines_type_token_controller_and_duration_axes(duration):
    eng = _engine()
    text = 'At the beginning of your upkeep, gain control of all artifact tokens your opponents control' + duration + '.'
    source = _bf(eng, Card(id='source', name='Source', type_line='Enchantment', oracle_text=text))
    assert parse_oracle(source.card).modeled
    artifact = _bf(eng, Card(id='token', name='Artifact', type_line='Artifact'), 'p2')
    artifact.is_token = True
    artifact.tapped = True
    ordinary = _bf(eng, Card(id='ordinary', name='Ordinary', type_line='Artifact'), 'p2')
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    source.controller_id = 'p2'
    eng.resolve_until_stable()
    assert artifact.controller_id == 'p1' and artifact.tapped
    assert ordinary.controller_id == 'p2'
    eng._step_cleanup()
    assert artifact.controller_id == ('p2' if duration else 'p1')


@pytest.mark.parametrize('body', [
    'gain control of all imaginary objects',
    'gain control of all rat tokens forever and draw a card',
    'untap up to 3 lands you secretly own',
])
def test_unknown_selection_qualifiers_are_not_claimed(body):
    assert parse_effect_body(body) is None
