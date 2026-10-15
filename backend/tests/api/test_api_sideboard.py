"""Actual decklist and saved seats supply outside-game cards."""
from fastapi.testclient import TestClient
from mtg_analyzer.api.app import app
from mtg_analyzer.api.game import resolve_seat_deck
from mtg_analyzer.models.decks.deck import Deck
from test_api_game import _setup, _teardown, _FakeLoader, _forest, _commander, LEGAL_DECK
from mtg_analyzer.models.cards.card import Card


def test_goldfish_text_and_saved_seat_sideboards_load():
    outside=Card(id='Outside',name='Outside',type_line='Artifact',oracle_text='')
    loader=_FakeLoader({'Forest':_forest(),'Test Commander':_commander(),'Outside':outside})
    _,db=_setup(loader._cards)
    try:
        response=TestClient(app).post('/api/game/goldfish',json={**LEGAL_DECK,'sideboardText':'1 Outside'})
        assert response.status_code==200,response.text
        player=response.json()['state']['players'][0]
        assert player['sideboard'][0]['name']=='Outside'
        assert player['sideboard'][0]['zone'] is None
        assert player['library_count']==92
        deck=Deck(name='With sideboard',commander_text='1 Test Commander',mainboard_text='99 Forest',sideboard_text='1 Outside')
        db.save_deck(deck)
        assert len(resolve_seat_deck(deck.id,db,loader))==3
        library,commanders,errors,sideboard=resolve_seat_deck(deck.id,db,loader,include_sideboard=True)
        assert not errors and len(library)==99 and sideboard==[outside]
        saved=TestClient(app).post('/api/game/goldfish',json={'deckId':deck.id,'shuffle':False})
        assert saved.status_code==200 and saved.json()['state']['players'][0]['sideboard'][0]['name']=='Outside'
    finally:_teardown()


def test_solo_loads_all_saved_seat_sideboards_and_redacts_bot():
    from mtg_analyzer.api.solo import SOLO_HUMAN_ID
    _,db=_setup({'Forest':_forest(),'Test Commander':_commander(),'Outside':Card(id='Outside',name='Outside',type_line='Artifact')})
    try:
        deck=Deck(name='Sideboard seats',commander_text='1 Test Commander',mainboard_text='99 Forest',sideboard_text='1 Outside');db.save_deck(deck)
        response=TestClient(app).post('/api/solo/start',json={'deckId':deck.id,'opponents':[{'kind':'goldfish','deckId':deck.id}]})
        assert response.status_code==200,response.text
        view=response.json();players=view['state']['players']
        assert next(p for p in players if p['id']==SOLO_HUMAN_ID)['sideboard'][0]['name']=='Outside'
        assert all(p['sideboard_count']==1 for p in players)
        assert all(p['sideboard']==[] for p in players if p['id']!=SOLO_HUMAN_ID)
    finally:_teardown()


def test_multiplayer_loads_each_saved_sideboard_but_only_owner_identity():
    from mtg_analyzer.api.dependencies import get_lobby
    from mtg_analyzer.services.lobby import Lobby
    _,db=_setup({'Forest':_forest(),'Test Commander':_commander(),'Outside':Card(id='Outside',name='Outside',type_line='Artifact')})
    app.dependency_overrides[get_lobby]=lambda:lobby
    lobby=Lobby();client=TestClient(app)
    try:
        deck=Deck(name='Sideboard seats',commander_text='1 Test Commander',mainboard_text='99 Forest',sideboard_text='1 Outside');db.save_deck(deck)
        ids=[client.post('/api/multiplayer/connect',json={'name':name}).json()['player']['id'] for name in ['Ann','Bob']]
        gid=client.post('/api/multiplayer/games',json={'playerId':ids[0],'name':'Table'}).json()['game']['id']
        client.post(f'/api/multiplayer/games/{gid}/join',json={'playerId':ids[1]})
        for pid in ids:client.post(f'/api/multiplayer/games/{gid}/deck',json={'playerId':pid,'deckId':deck.id})
        for pid in ids:client.post(f'/api/multiplayer/games/{gid}/ready',json={'playerId':pid})
        response=client.post(f'/api/multiplayer/games/{gid}/start',json={'playerId':ids[0]})
        assert response.status_code==200,response.text
        players=response.json()['view']['state']['players']
        assert next(p for p in players if p['id']==ids[0])['sideboard'][0]['name']=='Outside'
        assert next(p for p in players if p['id']==ids[1])['sideboard']==[]
        assert all(p['sideboard_count']==1 for p in players)
    finally:
        app.dependency_overrides.pop(get_lobby,None);_teardown()
