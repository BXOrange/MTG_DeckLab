"""Offline support evidence survives conversion, faces, copies and migration."""
import json
import sqlite3
import pytest
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.support_policy import unsupported_reason
from mtg_analyzer.services import card_database
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.raw_card_store import RawCardStore
from mtg_analyzer.services.scryfall_client import card_from_scryfall_data


def raw(**extra):
    return {'id':'printing', 'oracle_id':'oracle', 'name':'Metadata fixture',
            'type_line':'Artifact', 'oracle_text':'', **extra}


def evidence(card):
    return card.digital, card.games, card.legalities


def test_converter_roundtrip_faces_and_copy_preserve_independent_evidence():
    data = raw(digital=True, games=['arena'], legalities=dict.fromkeys(
        ('commander','legacy','vintage'), 'not_legal'), layout='modal_dfc',
        card_faces=[{'name':'Front','type_line':'Artifact'},
                    {'name':'Back','type_line':'Artifact'}])
    card = card_from_scryfall_data(data)
    for copied in (Card.from_dict(card.to_dict()), card.as_copy(), card.back_face()):
        assert evidence(copied) == evidence(card)
        assert unsupported_reason(copied) == 'digital_only'
        copied.games.append('paper')
        copied.legalities['commander'] = 'legal'
        assert evidence(card) == (True, ['arena'], dict.fromkeys(
            ('commander','legacy','vintage'), 'not_legal'))


@pytest.mark.parametrize('name,games,status', [
    ('Palinchron', ['mtgo'], 'legal'),
    ('Wyluli Wolf', ['mtgo'], 'legal'),
    ('Raging Goblin', ['arena'], 'legal'),
    ('Pyrogoyf', ['arena'], 'legal'),
    ('Paper card banned in a paper format', ['arena'], 'banned'),
    ('Paper card restricted in Vintage', ['arena'], 'restricted'),
])
def test_digital_representative_print_does_not_exclude_paper_card(name,games,status):
    card = card_from_scryfall_data(raw(name=name,digital=True,games=games,
        legalities=dict.fromkeys(('commander','legacy','vintage'),status)))
    assert unsupported_reason(card) is None


def test_legacy_serialization_remains_unknown():
    card = Card.from_dict({'id':'legacy','name':'Legacy','type_line':'Artifact'})
    assert evidence(card) == (None, [], {})
    assert unsupported_reason(card) is None


@pytest.mark.parametrize('defaults_present', [False, True])
@pytest.mark.parametrize('raw_available', [True, False])
@pytest.mark.parametrize('predecessor', [card_database._SUPPORT_METADATA_PREDECESSOR,
    '9689054c477b2c30672c3ac9f8c5e3fb6e760ccefdbebc3d3b651b70ab109fc0'])
def test_verified_previous_cache_migrates_locally_without_replacing_printings(tmp_path, monkeypatch,raw_available,predecessor,defaults_present):
    raw_path = tmp_path / 'raw.db'
    monkeypatch.setattr(card_database,'DEFAULT_RAW_STORE_PATH',raw_path)
    printed = raw(digital=True,games=['arena'],legalities=dict.fromkeys(
        ('commander','legacy','vintage'), 'not_legal'))
    if raw_available:
        with RawCardStore(raw_path) as store:
            store.upsert_many([printed])
    path = tmp_path/'cards.db'
    card = card_from_scryfall_data(printed)
    card.id = 'cached-other-printing'
    card.image_uri_normal = 'keep-image'
    with CardDatabase(path) as db:
        db.save_card(card)
        db.save_alias('Local alias',card.name)
    data = card.to_dict()
    data.pop('unsupported_reason', None)
    data.pop('unsupported', None)
    for key in ('digital','games','legalities'):
        if defaults_present:
            data[key] = {'digital': None, 'games': [], 'legalities': {}}[key]
        else:
            data.pop(key)
    data['future_opaque_field'] = 'preserve'
    with sqlite3.connect(path) as conn:
        conn.execute('UPDATE cards SET data=?',(json.dumps(data),))
        conn.execute("UPDATE schema_meta SET value=? WHERE key='schema_hash'",
                     (predecessor,))
    with CardDatabase(path) as db:
        assert db.schema_migrated and not db.schema_reset
        loaded = db.get_card('Local alias')
        assert loaded.id == card.id and loaded.image_uri_normal == 'keep-image'
        assert unsupported_reason(loaded) == ('digital_only' if raw_available else None)
    with sqlite3.connect(path) as conn:
        stored = json.loads(conn.execute('SELECT data FROM cards').fetchone()[0])
        assert all(stored[k] == v for k,v in data.items() if k not in ('digital','games','legalities'))
    with CardDatabase(path) as db:
        assert not db.schema_migrated and not db.schema_reset
        assert db.get_card('Local alias') is not None
    assert raw_path.exists() == raw_available
