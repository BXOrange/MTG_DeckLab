"""Tables of three and four seats (UC4).

Reference: mtg_analyzer/services/lobby.py (`MAX_SEATS`), mtg_analyzer/
services/game_session.py, mtg_analyzer/api/multiplayer.py.

The engine was always written for N players (`GameState.next_active_index`,
`GameEngine.legal_defenders_for`, the RULE 800.4a deferred-leave sweep) —
the lobby simply refused to open a table bigger than two. These cover the
seat machinery at a pod's size and the rules consequences that only exist
with 3+ players: turn order rotating through everyone, an attacker
choosing *which* opponent to hit (RULE 508.1a), only the attacked player
blocking (RULE 509.1a), a priority round going all the way around (RULE
117.3), and a concession leaving a game the survivors keep playing.
"""

import random

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameActionError, GameSessionManager
from mtg_analyzer.services.lobby import MAX_SEATS, MIN_SEATS, Lobby, LobbyError


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def bear(name="Grizzly Bears"):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=2,
        toughness=2,
        color_identity={"G"},
    )


SEATS = ("ann", "bob", "cid", "dot")


def make_pod(seats=SEATS, library=None, mulligan_style="none"):
    """An N-seat game, every seat holding the same 30-card pile."""
    deck = library if library is not None else [land()] * 30
    return GameSessionManager().create_multiplayer(
        [
            {"player_id": pid, "name": pid.title(), "library": list(deck)}
            for pid in seats
        ],
        mulligan_style=mulligan_style,
    )


def keep_all(session, seats=SEATS):
    for pid in seats:
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)


def advance_until(session, *, step=None, turn=None, limit=400):
    """Play forward by passing priority — the only way a step ends (RULE 117.4)."""
    for _ in range(limit):
        state = session.engine.state
        if (step is None or state.current_step == step) and (
            turn is None or state.turn_number == turn
        ):
            return
        holder = state.priority_player
        if holder is None or state.game_over:
            raise AssertionError("nobody holds priority and the target step never came")
        session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
    raise AssertionError("step never reached")


class TestLobbySeats:
    """The lobby half: opening, filling and resizing a bigger table."""

    def test_four_is_the_cap(self):
        assert (MIN_SEATS, MAX_SEATS) == (2, 4)

    def test_a_table_can_be_opened_for_four(self):
        lobby = Lobby()
        host = lobby.connect("Ann")
        game = lobby.create(host.id, num_players=4)
        assert game.num_players == 4
        assert not game.is_full  # one of four seats taken

    def test_more_than_four_is_clamped_down(self):
        lobby = Lobby()
        game = lobby.create(lobby.connect("Ann").id, num_players=9)
        assert game.num_players == MAX_SEATS

    def test_fewer_than_two_is_clamped_up(self):
        lobby = Lobby()
        game = lobby.create(lobby.connect("Ann").id, num_players=1)
        assert game.num_players == MIN_SEATS

    def test_four_players_can_all_sit_down_and_the_fifth_cannot(self):
        lobby = Lobby()
        players = [lobby.connect(name) for name in ("Ann", "Bob", "Cid", "Dot", "Eve")]
        game = lobby.create(players[0].id, num_players=4)
        for player in players[1:4]:
            lobby.join(game.id, player.id)
        assert game.is_full
        assert [s.name for s in game.seats] == ["Ann", "Bob", "Cid", "Dot"]
        with pytest.raises(LobbyError):
            lobby.join(game.id, players[4].id)

    def test_the_host_can_resize_the_table(self):
        lobby = Lobby()
        host = lobby.connect("Ann")
        game = lobby.create(host.id)
        assert game.num_players == 2
        lobby.set_options(game.id, host.id, num_players=3)
        assert game.num_players == 3

    def test_resizing_cannot_evict_a_seated_player(self):
        lobby = Lobby()
        host, bob, cid = (lobby.connect(n) for n in ("Ann", "Bob", "Cid"))
        game = lobby.create(host.id, num_players=4)
        lobby.join(game.id, bob.id)
        lobby.join(game.id, cid.id)
        lobby.set_options(game.id, host.id, num_players=2)
        assert game.num_players == 3  # the three who are already sitting there

    def test_all_four_seats_must_accept_before_the_game_starts(self):
        lobby = Lobby()
        players = [lobby.connect(n) for n in ("Ann", "Bob", "Cid", "Dot")]
        game = lobby.create(players[0].id, num_players=4)
        for player in players[1:]:
            lobby.join(game.id, player.id)
        for player in players:
            lobby.set_deck(game.id, player.id, deck_id="deck-1")
        for player in players[:3]:
            lobby.set_ready(game.id, player.id)
        assert not game.all_ready
        lobby.set_ready(game.id, players[3].id)
        assert game.all_ready

    def test_a_four_seat_table_survives_one_player_leaving_in_setup(self):
        lobby = Lobby()
        players = [lobby.connect(n) for n in ("Ann", "Bob", "Cid", "Dot")]
        game = lobby.create(players[0].id, num_players=4)
        for player in players[1:]:
            lobby.join(game.id, player.id)
        assert lobby.leave(game.id, players[2].id) is game
        assert [s.name for s in game.seats] == ["Ann", "Bob", "Dot"]
        assert game.num_players == 4  # the seat is free again, not deleted


class TestPodSetup:
    """Every seat mulligans for itself, however many there are."""

    def test_every_seat_gets_an_opening_hand(self):
        session = make_pod()
        assert [len(p.hand) for p in session.engine.state.players] == [7, 7, 7, 7]

    def test_play_waits_for_the_last_of_four_keeps(self):
        session = make_pod(mulligan_style="london")
        for pid in SEATS[:3]:
            session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
            assert not session._setup_complete
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="dot")
        assert session._setup_complete

    def test_a_seat_that_has_kept_is_not_offered_anything_else(self):
        session = make_pod(mulligan_style="london")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        assert session.legal_actions("ann") == []
        assert {a["type"] for a in session.legal_actions("bob")} == {"mulligan", "keep_hand"}


class TestPodTurnLoop:
    """RULE 500.1/117.3: the turn and priority go all the way round."""

    def test_turn_order_rotates_through_every_seat(self):
        session = make_pod()
        keep_all(session)
        seen = []
        for _ in range(5):
            seen.append(session.engine.state.active_player.id)
            advance_until(session, turn=session.engine.state.turn_number + 1)
        assert seen == ["ann", "bob", "cid", "dot", "ann"]

    def test_a_priority_round_visits_all_four_seats(self):
        session = make_pod()
        keep_all(session)
        advance_until(session, step="main1")
        holders = []
        for _ in range(4):
            holder = session.engine.state.priority_player
            holders.append(holder.id)
            session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
        # APNAP from the active player, and only then does the step end.
        assert holders == ["ann", "bob", "cid", "dot"]
        assert session.engine.state.current_step != "main1"

    def test_only_the_priority_holder_may_act(self):
        session = make_pod()
        keep_all(session)
        advance_until(session, step="main1")
        for pid in ("bob", "cid", "dot"):
            with pytest.raises(GameActionError):
                session.apply_action({"type": "pass_priority"}, actor_id=pid)


class TestPodCombat:
    """RULE 508.1a: with three opponents, "who am I attacking" is a real choice."""

    def setup_attack(self):
        """A pod with one creature on Ann's side, ready to swing.

        Put onto the battlefield directly — the point here is who it may be
        declared against, not how it got there.
        """
        session = make_pod()
        keep_all(session)
        state = session.engine.state
        attacker = GameObject(bear("Attacker"), owner_id="ann", zone=Zone.BATTLEFIELD)
        attacker.controller_id = "ann"
        attacker.summoning_sick = False
        state.add_to_battlefield(attacker)
        return session, attacker

    def test_every_opponent_is_offered_as_a_defender(self):
        session, attacker = self.setup_attack()
        advance_until(session, step="declare_attackers")
        offer = next(
            a
            for a in session.legal_actions("ann")
            if a["type"] == "attack" and a["instance_id"] == attacker.instance_id
        )
        players = [d["id"] for d in offer["legal_defenders"] if d["kind"] == "player"]
        assert players == ["bob", "cid", "dot"]

    def test_only_the_attacked_player_may_block(self):
        session, attacker = self.setup_attack()
        advance_until(session, step="declare_attackers")
        session.apply_action(
            {
                "type": "declare_attackers",
                "instance_ids": [attacker.instance_id],
                "defender": {"kind": "player", "id": "cid"},
            },
            actor_id="ann",
        )
        advance_until(session, step="declare_blockers")
        # RULE 509.1a: Bob and Dot aren't being attacked, so there is nothing
        # for them to declare — and the engine refuses it, not just the UI.
        for pid in ("bob", "dot"):
            assert [a for a in session.legal_actions(pid) if a["type"] == "declare_blockers"] == []
        with pytest.raises(ValueError):
            session.engine.declare_blockers(
                session.engine.state.player_by_id("bob"), [(attacker, attacker)]
            )

    def test_combat_damage_hits_only_the_chosen_opponent(self):
        session, attacker = self.setup_attack()
        advance_until(session, step="declare_attackers")
        session.apply_action(
            {
                "type": "declare_attackers",
                "instance_ids": [attacker.instance_id],
                "defender": {"kind": "player", "id": "dot"},
            },
            actor_id="ann",
        )
        advance_until(session, step="end")
        lives = {p.id: p.life for p in session.engine.state.players}
        assert lives["dot"] == 38
        assert lives["bob"] == lives["cid"] == 40


class TestPodConcession:
    """RULE 104.3a: a pod keeps playing after somebody drops out."""

    def test_the_survivors_play_on(self):
        session = make_pod()
        keep_all(session)
        session.concede("cid")
        state = session.engine.state
        assert state.player_by_id("cid").has_lost
        assert not state.game_over
        assert [p.id for p in state.living_players()] == ["ann", "bob", "dot"]

    def test_a_conceded_seat_is_skipped_in_the_turn_order(self):
        session = make_pod()
        keep_all(session)
        session.concede("bob")
        advance_until(session, turn=2)
        assert session.engine.state.active_player.id == "cid"

    def test_the_last_player_standing_wins(self):
        session = make_pod()
        keep_all(session)
        for pid in ("bob", "cid", "dot"):
            session.concede(pid)
        assert session.engine.state.game_over


class TestFirstDrawStep:
    """RULE 103.8a vs. 103.8c — who skips the draw on turn one.

    103.8a is a *two-player* rule. 103.8c: "In all other multiplayer games,
    no player skips the draw step of their first turn." The engine used to
    gate the skip on `len(players) > 1`, which carried the two-player rule
    into every pod and cost the starting seat a card.
    """

    def hand_size_on_turn(self, session, turn, seat):
        # Read it in main1: by then this turn's draw step has been and gone,
        # and nothing else has touched the hand.
        advance_until(session, step="main1", turn=turn)
        player = next(p for p in session.engine.state.players if p.id == seat)
        return len(player.hand)

    def test_nobody_skips_the_first_draw_at_a_pod(self):
        session = make_pod()
        keep_all(session)
        # Every seat, including the one that started, is on eight cards
        # after its own first draw step.
        for turn, seat in enumerate(SEATS, start=1):
            assert self.hand_size_on_turn(session, turn, seat) == 8, seat

    def test_the_starting_player_still_skips_it_at_two_seats(self):
        session = make_pod(seats=("ann", "bob"))
        keep_all(session, seats=("ann", "bob"))
        assert self.hand_size_on_turn(session, 1, "ann") == 7
        assert self.hand_size_on_turn(session, 2, "bob") == 8


class TestSeatingAndStartingPlayer:
    """RULE 103.1/103.2 as two table settings (`LobbyGame.seating_order`)."""

    def table(self, **options):
        lobby = Lobby()
        host = lobby.connect("Ann")
        game = lobby.create(host.id, num_players=4)
        for name in ("Bob", "Cid", "Dot"):
            lobby.join(game.id, lobby.connect(name).id)
        if options:
            lobby.set_options(game.id, host.id, **options)
        return lobby, game

    def names(self, seats):
        return [s.name for s in seats]

    def test_join_order_is_the_default(self):
        _, game = self.table()
        assert self.names(game.seating_order()) == ["Ann", "Bob", "Cid", "Dot"]
        assert not game.randomize_seating and not game.random_starting_player

    def test_randomized_seating_is_a_permutation_of_the_same_seats(self):
        _, game = self.table(randomize_seating=True)
        order = game.seating_order(rng=random.Random(7))
        assert sorted(self.names(order)) == ["Ann", "Bob", "Cid", "Dot"]

    def test_randomized_seating_actually_reorders_across_rolls(self):
        _, game = self.table(randomize_seating=True)
        rolls = {tuple(self.names(game.seating_order(rng=random.Random(s)))) for s in range(25)}
        assert len(rolls) > 1

    def test_a_random_starting_player_only_rotates_the_ring(self):
        """Seating is who sits next to whom — a different starting point
        must not disturb it, so every result is a rotation."""
        _, game = self.table(random_starting_player=True)
        joined = ["Ann", "Bob", "Cid", "Dot"]
        rotations = {tuple(joined[i:] + joined[:i]) for i in range(len(joined))}
        seen = {tuple(self.names(game.seating_order(rng=random.Random(s)))) for s in range(30)}
        assert seen <= rotations
        assert len(seen) > 1  # it does move

    def test_both_options_together_still_seat_everyone_once(self):
        _, game = self.table(randomize_seating=True, random_starting_player=True)
        order = game.seating_order(rng=random.Random(3))
        assert sorted(self.names(order)) == ["Ann", "Bob", "Cid", "Dot"]

    def test_only_the_host_may_change_them(self):
        lobby, game = self.table()
        guest = next(s.player_id for s in game.seats if s.player_id != game.host_id)
        with pytest.raises(LobbyError):
            lobby.set_options(game.id, guest, randomize_seating=True)

    def test_the_settings_are_on_the_wire(self):
        _, game = self.table(randomize_seating=True)
        payload = game.to_dict()
        assert payload["randomize_seating"] is True
        assert payload["random_starting_player"] is False


class TestPodRedaction:
    """RULE 400.2 with three opponents rather than one."""

    def test_a_seat_sees_only_its_own_hand(self):
        session = make_pod()
        view = session.view(perspective="cid")
        hands = {p["id"]: p["hand"] for p in view["state"]["players"]}
        assert len(hands["cid"]) == 7
        assert hands["ann"] == hands["bob"] == hands["dot"] == []
        # The counts are public — the board still draws the right number of backs.
        assert {p["id"]: p["hand_count"] for p in view["state"]["players"]} == {
            "ann": 7,
            "bob": 7,
            "cid": 7,
            "dot": 7,
        }
