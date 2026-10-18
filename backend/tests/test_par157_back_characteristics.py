"""Printed back-face counters and compatible offline cache migration."""
import json
import sqlite3

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services import card_database
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.raw_card_store import RawCardStore
from mtg_analyzer.services.scryfall_client import card_from_scryfall_data


def _raw(back_type='Legendary Planeswalker — Example', **values):
    return {'id': 'printed-card', 'oracle_id': 'oracle-card', 'name': 'Front // Back', 'layout': 'transform',
        'card_faces': [
            {'name': 'Front', 'type_line': 'Creature — Human', 'power': '2', 'toughness': '2',
             'oracle_text': '', 'mana_cost': '{1}{W}'},
            {'name': 'Back', 'type_line': back_type, 'oracle_text': '', 'mana_cost': '', **values},
        ]}


@pytest.mark.parametrize('back_type,values,field,amount', [
    ('Legendary Planeswalker — Example', {'loyalty': '4'}, 'loyalty', 4),
    ('Battle — Siege', {'defense': '6'}, 'defense', 6),
    ('Legendary Planeswalker — Example', {'loyalty': '0'}, 'loyalty', 0),
])
def test_printed_back_values_survive_conversion_serialization_and_copy(back_type, values, field, amount):
    card = card_from_scryfall_data(_raw(back_type, **values))
    assert getattr(card, field) is None  # front-face values remain independent
    assert getattr(card, 'back_' + field) == amount
    for copy in (card, Card.from_dict(card.to_dict()), card.as_copy()):
        assert getattr(copy.back_face(), field) == amount


@pytest.mark.parametrize('raw_available', [True, False])
def test_legacy_cache_migrates_without_losing_printings_aliases_or_unrelated_fields(tmp_path, monkeypatch, raw_available):
    raw_path = tmp_path / 'raw.db'
    monkeypatch.setattr(card_database, 'DEFAULT_RAW_STORE_PATH', raw_path)
    if raw_available:
        with RawCardStore(raw_path) as raw:
            raw.upsert_many([_raw(loyalty='4')])
    path = tmp_path / 'cards.db'
    card = card_from_scryfall_data(_raw(loyalty='4'))
    card.image_uri_normal = 'cached-printing-image'
    with CardDatabase(path) as db:
        db.save_card(card)
        db.save_alias('Local front alias', card.name)
    original = card.to_dict()
    original.pop('back_loyalty')
    original.pop('back_defense')
    original['future_opaque_field'] = {'preserve': True}
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE cards SET data = ?', (json.dumps(original),))
        conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_hash'",
                     (card_database._BACK_CHARACTERISTICS_PREDECESSOR,))
    with CardDatabase(path) as db:
        assert db.schema_migrated and not db.schema_reset
        migrated = db.get_card('Local front alias')
        assert migrated.id == card.id and migrated.image_uri_normal == 'cached-printing-image'
        assert migrated.back_loyalty == (4 if raw_available else None)
    with sqlite3.connect(path) as conn:
        stored = json.loads(conn.execute('SELECT data FROM cards').fetchone()[0])
        assert {k: stored[k] for k in original} == original
    with CardDatabase(path) as db:
        assert not db.schema_migrated and not db.schema_reset
        assert db.get_card('Front // Back') is not None
    assert raw_path.exists() == raw_available  # migration never creates a raw store


def test_unknown_schema_drift_still_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(card_database, 'DEFAULT_RAW_STORE_PATH', tmp_path / 'absent.db')
    path = tmp_path / 'cards.db'
    with CardDatabase(path) as db:
        db.save_card(Card(id='keep', name='Old', type_line='Artifact'))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_meta SET value = 'unknown-layout' WHERE key = 'schema_hash'")
    with CardDatabase(path) as db:
        assert db.schema_reset and not db.schema_migrated
        assert db.get_card('Old') is None


@pytest.mark.parametrize('back_type,values,field,amount', [
    ('Legendary Planeswalker — Example', {'loyalty': '4'}, 'loyalty', 4),
    ('Battle — Siege', {'defense': '6'}, 'defense', 6),
])
def test_transformed_return_enters_with_native_back_face_counters(back_type, values, field, amount):
    from test_mec106_gift import _engine, _bf
    from mtg_analyzer.models.game.game_object import Zone
    raw = _raw(back_type, **values)
    raw['card_faces'][0]['oracle_text'] = ('{1}: Exile Front, then return it to the battlefield '
        "transformed under its owner's control.")
    card = card_from_scryfall_data(raw)
    eng = _engine()
    source = _bf(eng, card)
    player = eng.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    eng.activate_ability(player, source)
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.transformed
    assert source.name == 'Back' and source.counters.get(field) == amount


def test_failed_migration_does_not_erase_rows_or_stamp_new_hash(tmp_path, monkeypatch):
    raw_path = tmp_path / 'raw.db'
    monkeypatch.setattr(card_database, 'DEFAULT_RAW_STORE_PATH', raw_path)
    with RawCardStore(raw_path) as raw:
        raw.upsert_many([_raw(loyalty='4')])
    path = tmp_path / 'cards.db'
    with CardDatabase(path) as db:
        db.save_card(card_from_scryfall_data(_raw(loyalty='4')))
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_hash'",
                     (card_database._BACK_CHARACTERISTICS_PREDECESSOR,))
        original = conn.execute('SELECT data FROM cards').fetchone()[0]
    with sqlite3.connect(raw_path) as conn:
        conn.execute("UPDATE raw_cards SET json = 'broken json'")
    with pytest.raises(json.JSONDecodeError):
        CardDatabase(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT data FROM cards').fetchone()[0] == original
        assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_hash'").fetchone()[0] == card_database._BACK_CHARACTERISTICS_PREDECESSOR


def test_transforming_in_place_keeps_counters_and_does_not_add_starting_loyalty():
    from test_mec106_gift import _engine, _bf
    eng = _engine()
    for initial in (0, 2):
        source = _bf(eng, card_from_scryfall_data(_raw(loyalty='4')))
        if initial:
            source.counters['loyalty'] = initial
        assert eng.rules.transform_permanent(source)
        assert source.counters.get('loyalty', 0) == initial


def test_returning_copy_of_planeswalker_receives_native_loyalty_once():
    from test_mec106_gift import _engine, _bf, _creature
    from mtg_analyzer.models.game.game_object import Zone
    from mtg_analyzer.game.effects.choices_actions import ReturnSpecificToBattlefieldEffect
    eng = _engine()
    walker = _bf(eng, Card(id='walker', name='Walker', type_line='Planeswalker — Example', loyalty=4))
    source = _bf(eng, _creature('Copy Example', 0, 0, oracle_text=
        'You may have Copy Example enter as a copy of any nonland permanent on the battlefield.'))
    eng.rules.exile(source)
    ReturnSpecificToBattlefieldEffect([source]).apply(eng.rules.context)
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'enter_as_copy'
    eng.resolve_pending_choice(str(walker.instance_id))
    assert source.zone == Zone.BATTLEFIELD and source.card.is_planeswalker
    assert source.counters.get('loyalty') == 4


@pytest.mark.parametrize('sign', ['-', '−'])
def test_back_face_negative_x_loyalty_uses_announced_x_for_cost_and_target(sign):
    from test_mec106_gift import _engine, _bf
    from mtg_analyzer.models.game.game_object import Zone
    from mtg_analyzer.parser.oracle import parse_oracle
    eng = _engine()
    raw = _raw(loyalty='4')
    raw['card_faces'][1]['oracle_text'] = (sign + 'X: Return target nonlegendary creature card '
        'with mana value X from your graveyard to the battlefield.')
    card = card_from_scryfall_data(raw)
    assert parse_oracle(card.back_face()).modeled
    source = _bf(eng, card.back_face())
    target = _bf(eng, Card(id='two', name='Two', type_line='Creature',
        is_creature=True, power=2, toughness=2, mana_cost_string='{2}', converted_mana_cost=2))
    eng.rules.put_into_graveyard(target)
    player = eng.state.player_by_id('p1')
    eng.activate_ability(player, source, targets=[target], x=2)
    assert source.counters['loyalty'] == 2
    eng.resolve_until_stable()
    assert target.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize('cost', ['+x', 'x'])
def test_unrepresented_positive_or_unsigned_x_loyalty_stays_unclaimed(cost):
    from mtg_analyzer.parser.oracle import parse_oracle
    card = Card(id='unsupported', name='Unsupported', type_line='Planeswalker',
        loyalty=4, oracle_text=cost + ': Draw a card.')
    assert not parse_oracle(card).modeled


def test_vehicle_back_keeps_printed_pt_and_crew_on_its_own_face():
    raw = _raw('Legendary Artifact — Vehicle', power='3', toughness='3')
    raw['keywords'] = ['Crew']
    raw['card_faces'][1]['oracle_text'] = 'Crew 1'
    card = card_from_scryfall_data(raw)
    assert card.back_power == card.back_toughness == 3
    assert card.keywords == [] and card.back_keywords == ['Crew']
    for copy in (card, Card.from_dict(card.to_dict()), card.as_copy()):
        back = copy.back_face()
        assert back.vehicle_power == back.vehicle_toughness == 3
        assert not back.is_creature and back.power is None and back.toughness is None
        assert back.keywords == ['Crew']


def test_keyword_printed_on_both_faces_is_retained_on_both():
    raw = _raw('Creature — Bird', power='3', toughness='3')
    raw['keywords'] = ['Flying']
    for face in raw['card_faces']:
        face['oracle_text'] = 'Flying'
    card = card_from_scryfall_data(raw)
    assert card.keywords == card.back_keywords == card.back_face().keywords == ['Flying']


@pytest.mark.parametrize('own_face', [0, 1])
def test_granting_keywords_does_not_give_them_to_the_face_that_grants_them(own_face):
    raw = _raw('Creature — Bird', power='3', toughness='3')
    raw['keywords'] = ['Flying', 'Vigilance']
    raw['card_faces'][own_face]['oracle_text'] = 'Flying, vigilance'
    raw['card_faces'][1 - own_face]['oracle_text'] = 'Creatures you control have flying, vigilance, and haste.'
    card = card_from_scryfall_data(raw)
    assert [card.keywords, card.back_keywords][own_face] == ['Flying', 'Vigilance']
    assert not [card.keywords, card.back_keywords][1 - own_face]


@pytest.mark.parametrize('predecessor', sorted(card_database._BACK_CHARACTERISTICS_PREDECESSORS))
def test_verified_cache_formats_recover_vehicle_back_metadata_offline(tmp_path, monkeypatch, predecessor):
    raw_path = tmp_path / 'raw.db'
    monkeypatch.setattr(card_database, 'DEFAULT_RAW_STORE_PATH', raw_path)
    raw = _raw('Legendary Artifact — Vehicle', power='3', toughness='3')
    raw['keywords'] = ['Crew']
    raw['card_faces'][1]['oracle_text'] = 'Crew 1'
    with RawCardStore(raw_path) as store:
        store.upsert_many([raw])
    card = card_from_scryfall_data(raw)
    path = tmp_path / 'cards.db'
    with CardDatabase(path) as db:
        db.save_card(card)
        db.save_alias('Alias', card.name)
    legacy = card.to_dict()
    legacy.update(back_power=None, back_toughness=None, back_keywords=[], keywords=['Crew', 'Custom'])
    legacy['future_field'] = {'keep': 'yes'}
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE cards SET data=?', (json.dumps(legacy),))
        conn.execute("UPDATE schema_meta SET value=? WHERE key='schema_hash'", (predecessor,))
    with CardDatabase(path) as db:
        assert db.schema_migrated and not db.schema_reset
        result = db.get_card('Alias')
        assert result.id == card.id and result.back_power == result.back_toughness == 3
        assert result.back_keywords == ['Crew'] and result.keywords == ['Custom']
    with sqlite3.connect(path) as conn:
        stored = json.loads(conn.execute('SELECT data FROM cards').fetchone()[0])
    expected = {**legacy, 'back_power': 3, 'back_toughness': 3,
                'back_keywords': ['Crew'], 'keywords': ['Custom']}
    assert stored == expected
