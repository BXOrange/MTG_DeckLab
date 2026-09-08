"""Interactive scry (RULE 701.18), surveil (RULE 701.31) and the Vancouver
mulligan (RULE 103.4).

Reference: mtg_analyzer/game/rules_engine.py (`_LOOK_TOP_KINDS`, `scry`/
`surveil`, `_resolve_look_top_choice`), mtg_analyzer/services/
game_session.py (`MULLIGAN_STYLES`, `_mulligan`, `_start_vancouver_scries`).

Both keyword actions used to be stubs that kept every looked-at card on
top, which is why Vancouver — whose only difference from a plain "draw
one fewer" mulligan *is* the scry — was deliberately absent from
`MULLIGAN_STYLES`. They are one decision with one parameter changed
(scry's cards go to the bottom of the library, surveil's to the
graveyard), so they share an implementation; these cover both, plus the
mulligan style built on top of scry.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject
from mtg_analyzer.models.game_state import GameState, Zone
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.game_session import (
    GameSession,
    GameSessionManager,
    build_goldfish_engine,
)


def card(name):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def make_engine(library_names):
    """A one-player engine whose library is ``library_names`` bottom-first
    (so the *last* name is the top card, matching `Player.library`)."""
    player = Player(id="p1", name="You", life=40)
    for name in library_names:
        player.library.append(GameObject(card(name), owner_id="p1", zone=Zone.LIBRARY))
    return GameEngine(GameState(players=[player]))


def library_names(player):
    """The library top-first, which is how a player reads it."""
    return [obj.name for obj in reversed(player.library)]


class TestInteractiveScry:
    """RULE 701.18: look at N, bottom any number, order the rest on top."""

    def test_scry_opens_a_choice_naming_the_looked_at_cards(self):
        engine = make_engine(["deep", "c", "b", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 3)

        choice = engine.state.pending_choice
        assert choice["kind"] == "scry"
        assert choice["player_id"] == "p1"
        assert choice["phase"] == "away"
        # Top card first, and never a card deeper than the scry looked.
        assert [o["label"] for o in choice["options"]] == ["a", "b", "c", "Rest oben lassen"]

    def test_declining_twice_keeps_every_card_on_top_in_order(self):
        engine = make_engine(["deep", "c", "b", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 3)
        engine.resolve_pending_choice("decline")  # bottom nothing
        # Three cards still headed for the top is a real ordering decision,
        # so it's asked — with its own one-click "leave them as they are".
        assert engine.state.pending_choice["phase"] == "order"
        engine.resolve_pending_choice("decline")

        assert engine.state.pending_choice is None
        assert library_names(player) == ["a", "b", "c", "deep"]

    def test_bottoming_moves_the_chosen_card_under_the_library(self):
        engine = make_engine(["deep", "c", "b", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 3)
        top = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(top["a"])
        # Still asking: two cards are undecided, so "which else?" re-opens.
        assert engine.state.pending_choice["phase"] == "away"
        engine.resolve_pending_choice("decline")
        engine.resolve_pending_choice("decline")  # keep b over c

        assert engine.state.pending_choice is None
        assert library_names(player) == ["b", "c", "deep", "a"]

    def test_two_kept_cards_are_ordered_by_the_player(self):
        engine = make_engine(["deep", "c", "b", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 3)
        options = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(options["b"])  # b to the bottom
        engine.resolve_pending_choice("decline")  # a and c stay on top

        # Two cards left on top is a genuine ordering decision (RULE 701.18's
        # "in any order"), so a second phase opens rather than finishing.
        choice = engine.state.pending_choice
        assert choice["kind"] == "scry" and choice["phase"] == "order"
        assert [o["label"] for o in choice["options"]] == ["a", "c", "Reihenfolge behalten"]

        order = {o["label"]: o["id"] for o in choice["options"]}
        engine.resolve_pending_choice(order["c"])  # c on top, a under it

        assert engine.state.pending_choice is None
        assert library_names(player) == ["c", "a", "deep", "b"]

    def test_bottoming_everything_finishes_without_an_ordering_phase(self):
        engine = make_engine(["deep", "b", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 2)
        options = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(options["a"])
        options = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(options["b"])

        assert engine.state.pending_choice is None
        assert library_names(player) == ["deep", "a", "b"]

    def test_scry_one_asks_a_single_top_or_bottom_question(self):
        engine = make_engine(["deep", "a"])
        player = engine.state.players[0]
        engine.rules.scry(player, 1)
        choice = engine.state.pending_choice
        assert [o["id"] for o in choice["options"]][-1] == "decline"
        assert len(choice["options"]) == 2

        engine.resolve_pending_choice(choice["options"][0]["id"])
        assert engine.state.pending_choice is None
        assert library_names(player) == ["deep", "a"]

    def test_an_empty_library_asks_nothing(self):
        engine = make_engine([])
        engine.rules.scry(engine.state.players[0], 2)
        assert engine.state.pending_choice is None

    def test_scry_looks_at_no_more_than_the_library_holds(self):
        engine = make_engine(["a"])
        engine.rules.scry(engine.state.players[0], 5)
        choice = engine.state.pending_choice
        assert [o["label"] for o in choice["options"]] == ["a", "Rest oben lassen"]

    def test_the_scry_event_still_fires_for_watching_triggers(self):
        engine = make_engine(["deep", "b", "a"])
        seen = []
        engine.state.subscribe(
            lambda e: seen.append(e) if e.type == EventType.SCRY else None
        )
        engine.rules.scry(engine.state.players[0], 2)
        assert [e.data["count"] for e in seen] == [2]

    def test_answering_an_unoffered_card_is_refused(self):
        engine = make_engine(["deep", "b", "a"])
        engine.rules.scry(engine.state.players[0], 1)
        with pytest.raises(ValueError):
            engine.resolve_pending_choice("9999")


class TestInteractiveSurveil:
    """RULE 701.31: look at N, graveyard any number, order the rest on top.

    Scry's decision with one parameter changed, so these check the half
    that actually differs (where the chosen cards *go*) rather than
    re-covering the phase machinery above.
    """

    def graveyard_names(self, player):
        return [obj.name for obj in player.graveyard]

    def test_surveil_opens_its_own_choice_kind(self):
        engine = make_engine(["deep", "b", "a"])
        engine.rules.surveil(engine.state.players[0], 2)
        choice = engine.state.pending_choice
        assert choice["kind"] == "surveil"
        assert choice["phase"] == "away"
        assert [o["label"] for o in choice["options"]] == ["a", "b", "Rest oben lassen"]
        assert "Friedhof" in choice["prompt"]

    def test_a_chosen_card_goes_to_the_graveyard_not_the_bottom(self):
        engine = make_engine(["deep", "b", "a"])
        player = engine.state.players[0]
        engine.rules.surveil(player, 2)
        options = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(options["a"])
        engine.resolve_pending_choice("decline")

        assert engine.state.pending_choice is None
        assert self.graveyard_names(player) == ["a"]
        assert library_names(player) == ["b", "deep"]
        assert player.library[0].name == "deep"  # nothing was bottomed

    def test_declining_keeps_everything_on_top(self):
        engine = make_engine(["deep", "b", "a"])
        player = engine.state.players[0]
        engine.rules.surveil(player, 2)
        engine.resolve_pending_choice("decline")
        engine.resolve_pending_choice("decline")  # keep a over b

        assert player.graveyard == []
        assert library_names(player) == ["a", "b", "deep"]

    def test_the_kept_cards_can_be_reordered(self):
        engine = make_engine(["deep", "c", "b", "a"])
        player = engine.state.players[0]
        engine.rules.surveil(player, 3)
        options = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(options["b"])  # b to the graveyard
        engine.resolve_pending_choice("decline")
        order = {o["label"]: o["id"] for o in engine.state.pending_choice["options"]}
        engine.resolve_pending_choice(order["c"])  # c on top of a

        assert self.graveyard_names(player) == ["b"]
        assert library_names(player) == ["c", "a", "deep"]

    def test_surveilling_everything_empties_the_top(self):
        engine = make_engine(["deep", "b", "a"])
        player = engine.state.players[0]
        engine.rules.surveil(player, 2)
        for _ in range(2):
            options = engine.state.pending_choice["options"]
            engine.resolve_pending_choice(options[0]["id"])

        assert engine.state.pending_choice is None
        assert self.graveyard_names(player) == ["a", "b"]
        assert library_names(player) == ["deep"]

    def test_an_empty_library_asks_nothing(self):
        engine = make_engine([])
        engine.rules.surveil(engine.state.players[0], 2)
        assert engine.state.pending_choice is None

    def test_the_surveil_event_fires_for_watching_triggers(self):
        engine = make_engine(["deep", "b", "a"])
        seen = []
        engine.state.subscribe(
            lambda e: seen.append(e) if e.type == EventType.SURVEIL else None
        )
        engine.rules.surveil(engine.state.players[0], 2)
        assert [e.data["count"] for e in seen] == [2]

    def test_surveil_is_not_a_mill(self):
        """RULE 701.31 vs 701.13: the rules keep them distinct, so nothing
        watching for milling should see a surveil."""
        engine = make_engine(["deep", "b", "a"])
        seen = []
        engine.state.subscribe(
            lambda e: seen.append(e) if e.type in (EventType.MILL, EventType.MILL_CARD) else None
        )
        engine.rules.surveil(engine.state.players[0], 2)
        options = engine.state.pending_choice["options"]
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_pending_choice("decline")
        assert seen == []


class TestScrySurveilTriggers:
    """RULE 603.1 with a *player* subject: "whenever you scry/surveil".

    The first trigger family in this grammar whose subject isn't an object
    at all (`segmenter._PLAYER_TRIGGER_CONDITIONS` →
    `effect_binder._subject_condition`'s ``{"subject": "you"}``), so the
    scoping — *whose* scry — is the whole point.
    """

    def parse(self, name, type_line, text):
        return parse_oracle(Card(id=name, name=name, type_line=type_line, oracle_text=text))

    def test_whenever_you_scry_is_recognised_and_scoped(self):
        res = self.parse(
            "Chance-Met Elves", "Creature — Elf Scout",
            "Whenever you scry, put a +1/+1 counter on this creature.",
        )
        assert res.coverage == "MODELED"
        (spec,) = res.specs
        assert spec.trigger == {"event": "SCRY", "condition": {"subject": "you"}}

    def test_whenever_you_surveil_is_recognised_and_scoped(self):
        res = self.parse(
            "Dimir Spybug", "Creature — Insect",
            "Whenever you surveil, put a +1/+1 counter on this creature.",
        )
        assert res.coverage == "MODELED"
        (spec,) = res.specs
        assert spec.trigger == {"event": "SURVEIL", "condition": {"subject": "you"}}

    def test_scry_or_surveil_becomes_one_ability_per_event(self):
        res = self.parse(
            "Matoya, Archon Elder", "Legendary Creature — Human Wizard",
            "Whenever you scry or surveil, draw a card.",
        )
        assert res.coverage == "MODELED"
        assert [s.trigger["event"] for s in res.specs] == ["SCRY", "SURVEIL"]
        # Each ability gets its *own* effect instances, never a shared list.
        assert res.specs[0].effects[0] is not res.specs[1].effects[0]

    def test_a_once_per_turn_qualifier_is_now_modeled(self):
        """Whispering Snitch's "for the first time each turn" (PAR-14)
        folds into `AbilitySpec.trigger["limit"]`, backed by the
        pre-existing `TriggeredAbility.once_per_turn`/`_last_triggered_turn`
        mechanism (built for Dionus, Elvish Archdruid's granted ability) —
        see test_par14_trigger_once_per_turn.py for the engine-level
        "fires once per turn, not once per firing" behavior."""
        res = self.parse(
            "Whispering Snitch", "Creature — Vampire",
            "Whenever you surveil for the first time each turn, this creature "
            "deals 1 damage to each opponent and you gain 1 life.",
        )
        assert res.coverage == "MODELED"
        assert res.specs[0].trigger["limit"] is True

    def test_the_trigger_fires_for_its_own_controller(self):
        engine = make_engine(["deep", "b", "a"])
        state = engine.state
        spybug = GameObject(
            Card(
                id="Dimir Spybug", name="Dimir Spybug", type_line="Creature — Insect",
                is_creature=True, power=1, toughness=1,
                oracle_text="Whenever you surveil, put a +1/+1 counter on this creature.",
            ),
            owner_id="p1",
            zone=Zone.BATTLEFIELD,
        )
        spybug.controller_id = "p1"
        bind_from_catalogue(spybug)
        state.add_to_battlefield(spybug)

        engine.rules.surveil(state.players[0], 1)
        engine.resolve_pending_choice("decline")
        engine.rules.check_state_based_actions()
        engine.pass_priority()
        assert spybug.counters.get("+1/+1") == 1

    def test_the_trigger_does_not_fire_for_an_opponent(self):
        """The scoping this subject exists for: an opponent surveilling is
        not "you" surveilling (RULE 603.1)."""
        engine = make_engine(["deep", "b", "a"])
        state = engine.state
        opponent = Player(id="p2", name="Them", life=40)
        for name in ("x", "y"):
            opponent.library.append(
                GameObject(card(name), owner_id="p2", zone=Zone.LIBRARY)
            )
        state.players.append(opponent)
        spybug = GameObject(
            Card(
                id="Dimir Spybug", name="Dimir Spybug", type_line="Creature — Insect",
                is_creature=True, power=1, toughness=1,
                oracle_text="Whenever you surveil, put a +1/+1 counter on this creature.",
            ),
            owner_id="p1",
            zone=Zone.BATTLEFIELD,
        )
        spybug.controller_id = "p1"
        bind_from_catalogue(spybug)
        state.add_to_battlefield(spybug)

        engine.rules.surveil(opponent, 1)
        engine.resolve_pending_choice("decline")
        engine.rules.check_state_based_actions()
        assert state.stack == []
        assert spybug.counters.get("+1/+1", 0) == 0


class TestVancouverMulligan:
    """RULE 103.4 (pre-London): redraw one fewer, then scry 1 on keeping."""

    def make_goldfish(self, style="vancouver"):
        engine = build_goldfish_engine([card(f"c{i}") for i in range(40)])
        return GameSession(engine, require_setup=True, mulligan_style=style)

    def test_it_is_an_offerable_style(self):
        from mtg_analyzer.services.game_session import MULLIGAN_STYLES

        assert "vancouver" in MULLIGAN_STYLES
        assert self.make_goldfish().mulligan_style == "vancouver"

    def test_each_mulligan_redraws_one_card_fewer(self):
        session = self.make_goldfish()
        player = session.engine.state.player_by_id("p1")
        assert len(player.hand) == 7

        session.apply_action({"type": "mulligan"})
        assert len(player.hand) == 6
        session.apply_action({"type": "mulligan"})
        assert len(player.hand) == 5

    def test_keeping_never_bottoms_a_card(self):
        session = self.make_goldfish()
        session.apply_action({"type": "mulligan"})
        assert session.bottom_count_for("p1") == 0
        # London would demand one card back here; Vancouver already took it
        # out of the draw.
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert len(session.engine.state.player_by_id("p1").hand) == 6

    def test_keeping_a_mulliganed_hand_opens_a_scry(self):
        session = self.make_goldfish()
        session.apply_action({"type": "mulligan"})
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

        choice = session.engine.state.pending_choice
        assert choice["kind"] == "scry" and choice["player_id"] == "p1"
        # The setup phase is over, so the scry is answered like any other
        # in-game decision.
        assert session._setup_complete
        session.apply_action({"type": "decline"})
        assert session.engine.state.pending_choice is None

    def test_keeping_the_opening_seven_scries_nothing(self):
        session = self.make_goldfish()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert session.engine.state.pending_choice is None

    def test_london_is_unaffected(self):
        session = self.make_goldfish(style="london")
        session.apply_action({"type": "mulligan"})  # free (Commander default)
        session.apply_action({"type": "mulligan"})
        assert len(session.engine.state.player_by_id("p1").hand) == 7
        assert session.bottom_count_for("p1") == 1
        hand = session.engine.state.player_by_id("p1").hand
        session.apply_action(
            {"type": "keep_hand", "bottom_instance_ids": [hand[0].instance_id]}
        )
        assert session.engine.state.pending_choice is None

    def test_restarting_mid_scry_drops_the_queue(self):
        session = self.make_goldfish()
        session.apply_action({"type": "mulligan"})
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert session.engine.state.pending_choice is not None

        session.restart()
        # Back at a fresh opening hand: no stale scry owed, and no deferred
        # priority window left pointing at a position that no longer exists.
        assert session.engine.state.pending_choice is None
        assert session._pending_scries == []
        assert not session._priority_window_pending
        assert not session._setup_complete
        assert len(session.engine.state.player_by_id("p1").hand) == 7

    def test_the_view_reports_the_next_hand_size(self):
        session = self.make_goldfish()
        assert session.view()["setup"]["next_hand_size"] == 6
        session.apply_action({"type": "mulligan"})
        assert session.view()["setup"]["next_hand_size"] == 5


class TestVancouverAtATable:
    """Every seat that mulliganed scries — in turn order, one at a time."""

    def make_table(self, seats=("ann", "bob")):
        manager = GameSessionManager()
        return manager.create_multiplayer(
            [
                {"player_id": pid, "name": pid.title(), "library": [card(f"c{i}") for i in range(40)]}
                for pid in seats
            ],
            mulligan_style="vancouver",
        )

    def test_scries_are_queued_rather_than_opened_at_once(self):
        session = self.make_table()
        session.apply_action({"type": "mulligan"}, actor_id="ann")
        session.apply_action({"type": "mulligan"}, actor_id="bob")
        session.apply_action(
            {"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann"
        )
        # Still waiting on Bob: nothing is scried until the whole table has kept.
        assert session.engine.state.pending_choice is None
        session.apply_action(
            {"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob"
        )

        # Turn order: Ann sat down first, so Ann scries first.
        assert session.engine.state.pending_choice["player_id"] == "ann"
        session.apply_action({"type": "decline"}, actor_id="ann")
        assert session.engine.state.pending_choice["player_id"] == "bob"
        session.apply_action({"type": "decline"}, actor_id="bob")
        assert session.engine.state.pending_choice is None

    def test_only_the_seats_that_mulliganed_scry(self):
        session = self.make_table()
        session.apply_action({"type": "mulligan"}, actor_id="bob")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")
        assert session.engine.state.pending_choice["player_id"] == "bob"
        session.apply_action({"type": "decline"}, actor_id="bob")
        assert session.engine.state.pending_choice is None

    def test_the_first_priority_window_waits_for_the_last_scry(self):
        session = self.make_table()
        session.apply_action({"type": "mulligan"}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")

        # The turn hasn't started running yet: advancing into the first
        # RULE 117 window would step the game around an open decision.
        assert session.engine.state.pending_choice is not None
        assert session.engine.state.current_step in ("", "untap")
        session.apply_action({"type": "decline"}, actor_id="ann")
        assert session.engine.state.current_step == "upkeep"
        assert session.engine.state.priority_player is not None

    def test_the_scrying_seat_is_the_only_one_offered_the_choice(self):
        session = self.make_table()
        session.apply_action({"type": "mulligan"}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")

        assert [a["type"] for a in session.legal_actions("bob")] == []
        assert {a["type"] for a in session.legal_actions("ann")} == {"choose", "decline"}
        # RULE 400.2: the card Ann is looking at is not sent to Bob.
        assert session.view(perspective="bob")["pending_choice"] is None
        assert session.view(perspective="bob")["state"]["waiting_on_choice"]["player_id"] == "ann"
