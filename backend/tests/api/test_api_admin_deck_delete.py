"""VIS-22: deleting a global deck on /admin needs no typed name; player deletion still does.

Reuses the throwaway-store fixtures of test_api_admin (nothing here touches ``data/*.db``).
"""

import pytest

from mtg_analyzer.models.decks.deck import Deck
from tests.api.test_api_admin import (  # noqa: F401  (fixtures)
    admin_headers, basic, client, env, make_player, pytestmark,
)


def _global(env, **kw):
    deck = Deck(**{"name": "Doomed", "mainboard_text": "1 Island\n\n1 Swamp", **kw})
    env["decks"].save_global(deck)
    return deck


def test_delete_without_body_and_audit(client, env):
    h = admin_headers(env)
    deck = _global(env)
    assert client.post(f"/api/admin/decks/{deck.id}/delete", headers=h).json() == {"deleted": True}
    assert env["decks"].get_global(deck.id) is None
    entries, _ = env["store"].list_audit(limit=10)
    assert any(e["action"] == "deck.deleted" and e["target"] == f"deck:{deck.id}" and e["result"] == "ok"
               for e in entries)


@pytest.mark.parametrize("body", [{}, {"confirm_name": "wrong"}])
def test_delete_with_empty_or_stale_body_ignores_extra_fields(client, env, body):
    deck = _global(env, name="")
    r = client.post(f"/api/admin/decks/{deck.id}/delete", headers=admin_headers(env), json=body)
    assert r.status_code == 200 and env["decks"].get_global(deck.id) is None


def test_delete_still_needs_admin_auth(client, env):
    admin_headers(env)
    deck = _global(env)
    assert client.post(f"/api/admin/decks/{deck.id}/delete").status_code == 401
    assert client.post(f"/api/admin/decks/{deck.id}/delete", headers=basic("boss", "wrong-wrong-wrong-1")).status_code == 401
    assert env["decks"].get_global(deck.id) is not None


def test_private_and_missing_ids_are_404(client, env):
    h = admin_headers(env)
    alice = make_player(env)
    env["decks"].save_private(Deck(name="TOPSECRET"), alice.player_uuid)
    private_id = env["decks"].list_decks(alice.player_uuid)[0].id
    assert client.post(f"/api/admin/decks/{private_id}/delete", headers=h).status_code == 404
    assert client.post("/api/admin/decks/nope/delete", headers=h).status_code == 404
    assert env["decks"].count_private(alice.player_uuid) == 1


def test_preview_returns_author_and_created_at_only_public_fields(client, env):
    h = admin_headers(env)
    deck = _global(env, author="Boss")
    assert client.get(f"/api/admin/decks/{deck.id}/delete-preview", headers=h).json() == {
        "name": "Doomed", "lines": 2, "author": "Boss", "created_at": deck.created_at}
    anon = _global(env, name="", author=None)
    got = client.get(f"/api/admin/decks/{anon.id}/delete-preview", headers=h).json()
    assert got["name"] == "" and got["author"] is None and got["created_at"]


def test_player_delete_still_requires_confirm_name(client, env):
    h = admin_headers(env)
    alice = make_player(env)
    url = f"/api/admin/players/{alice.player_uuid}/delete"
    assert client.post(url, headers=h).status_code == 422
    assert client.post(url, headers=h, json={"confirm_name": "wrong"}).status_code == 400
    assert client.post(url, headers=h, json={"confirm_name": "Alice"}).status_code == 200
