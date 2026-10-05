"""PLR-3 (2026-08-04): a face-down card in exile wasn't redacted.

RULE 701.20a (Beseech the Mirror-shaped): a card exiled face down
(`GameObject.face_down_in_exile`) has no characteristics visible to anyone
but its owner. `_redact_hidden_zones` already stripped whole *zones* (hand,
library) per RULE 400.2, but shipped a face-down-in-exile object's
`name`/`card_id`/`type_line`/derived characteristics in full regardless of
viewer — solo modes (goldfish/Replay) are always viewed by the card's own
owner, so this never showed up there, but a multiplayer opponent (or a
spectator) would have seen the real card.

Fixed with a new `_redact_face_down_exile`, called from `_redact_hidden_
zones`: for every player who isn't the requested ``perspective``, any
`face_down_in_exile` object in their exile zone has its identity fields
reset to an "unknown card" placeholder. The frontend already rendered the
*image* correctly regardless of viewer (`gameBoardView.js`'s
`resolveImageUrl` checks `face_down_in_exile` before anything else) — only
the wire payload's text/type fields were the gap.

Reference: mtg_analyzer/services/game_session.py.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSessionManager


def _land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _make_game():
    manager = GameSessionManager()
    deck = [_land()] * 30
    return manager.create_multiplayer(
        [
            {"player_id": "ann", "name": "Ann", "library": list(deck)},
            {"player_id": "bob", "name": "Bob", "library": list(deck)},
        ],
    )


def _keep_all(session):
    for pid in ("ann", "bob"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)


def _exile_face_down(session, owner_id, name="Secret Ritual"):
    player = session.engine.state.player_by_id(owner_id)
    card = Card(
        id=name, name=name, type_line="Instant", is_instant=True,
        mana_cost_string="{B}", converted_mana_cost=1,
        power=None, toughness=None,
    )
    obj = GameObject(card, owner_id=owner_id, zone=Zone.EXILE)
    obj.face_down_in_exile = True
    player.add_to_zone(obj, Zone.EXILE)
    return obj


def _find(view, owner_id, instance_id):
    player = next(p for p in view["state"]["players"] if p["id"] == owner_id)
    return next(o for o in player["exile"] if o["instance_id"] == instance_id)


class TestFaceDownExileRedaction:
    def test_owner_still_sees_the_real_card(self):
        session = _make_game()
        _keep_all(session)
        obj = _exile_face_down(session, "ann")

        view = session.view(perspective="ann")
        payload = _find(view, "ann", obj.instance_id)
        assert payload["name"] == "Secret Ritual"
        assert payload["card_id"] == "Secret Ritual"
        assert payload["type_line"] == "Instant"
        assert payload["face_down_in_exile"] is True

    def test_opponent_sees_no_identity_at_all(self):
        session = _make_game()
        _keep_all(session)
        obj = _exile_face_down(session, "ann")

        view = session.view(perspective="bob")
        payload = _find(view, "ann", obj.instance_id)
        assert payload["name"] == ""
        assert payload["card_id"] is None
        assert payload["type_line"] == ""
        assert payload["is_creature"] is False
        assert payload["is_land"] is False
        assert payload["is_artifact"] is False
        assert payload["is_enchantment"] is False
        assert payload["is_planeswalker"] is False
        assert payload["power"] is None
        assert payload["toughness"] is None
        # The object itself (and the fact that *something* sits there face
        # down) is still visible — only its identity is hidden.
        assert payload["face_down_in_exile"] is True
        assert payload["instance_id"] == obj.instance_id

    def test_observer_sees_no_identity_either(self):
        session = _make_game()
        _keep_all(session)
        obj = _exile_face_down(session, "ann")

        view = session.observer_view()
        payload = _find(view, "ann", obj.instance_id)
        assert payload["name"] == ""
        assert payload["card_id"] is None

    def test_solo_view_is_never_redacted(self):
        # Goldfish/Replay always call view() with no perspective at all —
        # `_redact_hidden_zones` isn't even invoked, so a solo player's own
        # face-down-in-exile card must show its real identity unconditionally.
        session = _make_game()
        _keep_all(session)
        obj = _exile_face_down(session, "ann")

        view = session.view()
        assert view["perspective"] is None
        payload = _find(view, "ann", obj.instance_id)
        assert payload["name"] == "Secret Ritual"

    def test_a_normal_exiled_card_is_unaffected(self):
        # Only `face_down_in_exile` objects are touched — an ordinary,
        # face-up exiled card (Bojuka Bog-shaped graveyard hate, etc.) keeps
        # shipping its real identity to everyone, same as before.
        session = _make_game()
        _keep_all(session)
        player = session.engine.state.player_by_id("ann")
        card = Card(id="Plain Exile", name="Plain Exile", type_line="Sorcery", is_sorcery=True)
        obj = GameObject(card, owner_id="ann", zone=Zone.EXILE)
        player.add_to_zone(obj, Zone.EXILE)

        view = session.view(perspective="bob")
        payload = _find(view, "ann", obj.instance_id)
        assert payload["name"] == "Plain Exile"
        assert payload["face_down_in_exile"] is False

