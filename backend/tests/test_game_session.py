"""Tests for GameSession: goldfish play, rewind, restart, multiplayer stub.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC3/UC4,
mtg_analyzer/services/game_session.py.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.services.game_session import (
    GameActionError,
    GameSession,
    GameSessionManager,
    MultiplayerNotImplementedError,
    build_goldfish_engine,
)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def bear():
    return Card(
        id="Grizzly Bears",
        name="Grizzly Bears",
        type_line="Creature — Bear",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=2,
        toughness=2,
        color_identity={"G"},
    )


def shock():
    return Card(
        id="Shock",
        name="Shock",
        type_line="Instant",
        mana_cost_string="{R}",
        converted_mana_cost=1,
        is_instant=True,
    )


def foretell_spell():
    return Card(
        id="Foretell Test", name="Foretell Test", type_line="Instant",
        mana_cost_string="{3}{U}", converted_mana_cost=4, is_instant=True,
    )


def make_session(library=None, commanders=None, hand=7):
    library = library if library is not None else [land()] * 30
    engine = build_goldfish_engine(library, commanders=commanders, starting_hand=hand)
    return GameSession(engine)


def advance_until(session, *, turn=None, step=None, limit=80):
    """Single-step the session until (turn, step) is reached (no auto-skip)."""
    for _ in range(limit):
        st = session.engine.state
        if (turn is None or st.internal_turn.number == turn) and (step is None or st.current_step == step):
            return
        session.apply_action({"type": "advance_step"})
    raise AssertionError(f"never reached turn={turn} step={step}")


class TestStackAndChoices:
    def _advance_to_main1(self, session):
        # Single-stepping (no auto-skip): walk untap/upkeep/draw to main1.
        advance_until(session, step="main1")

    def test_cast_leaves_spell_on_stack_and_pass_priority_resolves_it(self):
        # A land + a bear on top of the library so both reach the hand.
        session = make_session(library=[land()] * 10 + [bear(), land()], hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        # Play a land and tap it, then a second land next turn is overkill —
        # give mana directly for a focused test.
        state.active_player.mana_pool.add_many({"G": 1, "C": 1})
        bear_obj = next(o for o in state.active_player.hand if o.card.is_creature)
        view = session.apply_action(
            {"type": "cast_spell", "instance_id": bear_obj.instance_id}
        )
        # The spell is on the stack, not yet resolved.
        assert len(view["state"]["stack"]) == 1
        assert bear_obj.instance_id not in {o["instance_id"] for o in view["state"]["battlefield"]}
        # Passing priority resolves it onto the battlefield.
        view = session.apply_action({"type": "pass_priority"})
        assert len(view["state"]["stack"]) == 0
        assert bear_obj.instance_id in {o["instance_id"] for o in view["state"]["battlefield"]}

    def test_cast_spell_forwards_kicked_to_the_engine(self):
        # RULE 702.33: `kicked` must round-trip from the wire action to
        # `GameEngine.cast_spell` the same way `x` already does — the
        # session's `cast_spell` handler used to silently drop the field, so
        # a kicked cast could never be requested through the API at all even
        # though `legal_actions` already offers `has_kicker`/`max_kicker`.
        session = make_session(library=[land()] * 10 + [bear(), land()], hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        state.active_player.mana_pool.add_many({"G": 1, "C": 1, "R": 1})
        bear_obj = next(o for o in state.active_player.hand if o.card.is_creature)
        bear_obj.parametric_keywords = {"kicker": {"cost": "{R}"}}

        session.apply_action(
            {"type": "cast_spell", "instance_id": bear_obj.instance_id, "kicked": 1}
        )

        assert state.stack[-1].obj.kicker_count == 1
        assert state.active_player.mana_pool.total() == 0

    def test_foretell_action_dispatches_from_the_session_payload(self):
        session = make_session(library=[land()] * 10 + [foretell_spell(), land()], hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        spell = next(o for o in state.active_player.hand if o.name == "Foretell Test")
        spell.parametric_keywords = {"foretell": {"cost": "{1}{U}"}}
        state.active_player.mana_pool.add_many({"C": 2})

        action = next(a for a in session.legal_actions() if a["type"] == "foretell")
        session.apply_action({"type": "foretell", "instance_id": action["instance_id"]})

        assert spell in state.active_player.exile
        assert spell.foretold and spell.face_down_in_exile

    def test_cast_spell_forwards_discard_choices_for_an_additional_cost(self):
        # RULE 601.2b/602.1: a spell's "as an additional cost to cast this
        # spell, discard a card" — *which* card is the caster's own choice,
        # round-tripped through the session action as `discard_choices`. The
        # handler used to drop the field (like `kicked` above), so the engine
        # silently auto-discarded from the back of the hand and the UI had no
        # way to prompt. `legal_actions` now also surfaces the pool.
        from mtg_analyzer.models.game_object import GameObject, Zone
        from mtg_analyzer.game.costs import ActivationCost

        session = make_session(library=[land()] * 20, hand=0)
        self._advance_to_main1(session)
        state = session.engine.state
        p = state.active_player

        spell_obj = GameObject(shock(), owner_id=p.id, zone=Zone.HAND)
        p.hand.append(spell_obj)
        spell_obj.additional_cast_cost = ActivationCost(discard=1)
        keep = GameObject(bear(), owner_id=p.id, zone=Zone.HAND)
        p.hand.append(keep)
        toss = GameObject(land("Mountain"), owner_id=p.id, zone=Zone.HAND)
        p.hand.append(toss)
        p.mana_pool.add("R", 1)

        cast = next(
            a for a in session.legal_actions()
            if a["type"] == "cast_spell" and a["instance_id"] == spell_obj.instance_id
        )
        assert cast["discard_cost"]["count"] == 1
        # The pool is the rest of the hand — never the spell paying the cost.
        offered = {o["instance_id"] for o in cast["discard_cost"]["options"]}
        assert {keep.instance_id, toss.instance_id} <= offered
        assert spell_obj.instance_id not in offered

        session.apply_action({
            "type": "cast_spell",
            "instance_id": spell_obj.instance_id,
            "discard_choices": [toss.instance_id],
        })

        assert toss in p.graveyard
        assert keep in p.hand

    def test_tap_for_mana_with_option_index(self):
        session = make_session(library=[land()] * 10, hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        session.apply_action(
            {"type": "tap_for_mana", "instance_id": land_obj.instance_id, "option_index": 0}
        )
        assert state.active_player.mana_pool.pool["G"] == 1

    def test_tap_for_mana_with_explicit_tap_choices(self):
        # Birchlore Rangers-shaped cost ("tap two untapped Elves you
        # control") — the player's own choice of which two, round-tripped
        # through the session action as `tap_choices` (RULE 602.1).
        from mtg_analyzer.models.game_object import GameObject, Zone

        def elf(name, oracle):
            return Card(
                id=name, name=name, type_line="Creature — Elf Druid",
                is_creature=True, oracle_text=oracle,
            )

        session = make_session(library=[land()] * 5, hand=0)
        self._advance_to_main1(session)
        state = session.engine.state
        source = GameObject(elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ), owner_id="p1", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(source)
        e1 = GameObject(elf("Llanowar Elves", "{T}: Add {G}."), owner_id="p1", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(e1)

        # Sanity: legal_actions offers the eligible pool, itself included.
        action = next(
            a for a in session.legal_actions()
            if a["type"] == "tap_for_mana" and a["instance_id"] == source.instance_id
        )
        pool_ids = {o["instance_id"] for o in action["tap_cost"]["options"]}
        assert pool_ids == {source.instance_id, e1.instance_id}

        session.apply_action({
            "type": "tap_for_mana",
            "instance_id": source.instance_id,
            "option_index": 4,  # green
            "tap_choices": [source.instance_id, e1.instance_id],
        })
        assert state.active_player.mana_pool.pool["G"] == 1
        assert source.tapped and e1.tapped

    def test_pending_search_gates_actions_and_choose_completes_it(self):
        from mtg_analyzer.models.game_state import StackItem
        from mtg_analyzer.game.effects import SearchLibraryEffect

        session = make_session(library=[bear(), land(), bear()], hand=0)
        state = session.engine.state
        player = state.active_player
        ability = SearchLibraryEffect(type_restriction="Creature", player=player)
        state.stack.append(StackItem(kind="ability", controller_id=player.id, effects=[ability]))

        view = session.apply_action({"type": "pass_priority"})
        # A choice is pending; legal_actions offers only choose/decline.
        assert view["pending_choice"] is not None
        types = {a["type"] for a in view["legal_actions"]}
        assert types <= {"choose", "decline"}

        # A non-choice action is rejected while pending.
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_step"})

        target = view["pending_choice"]["eligible"][0]["instance_id"]
        view = session.apply_action({"type": "choose", "instance_id": target})
        assert view["pending_choice"] is None
        assert any(o["instance_id"] == target for o in view["state"]["players"][0]["hand"])


class TestSetup:
    def test_opening_hand_is_dealt_and_commander_in_command_zone(self):
        session = make_session(commanders=[bear()])
        player = session.engine.state.active_player
        assert len(player.hand) == 7
        assert len(player.command) == 1
        assert session.engine.state.internal_turn.number == 1

    def test_view_has_state_and_legal_actions(self):
        view = make_session().view()
        assert view["mode"] == "goldfish"
        assert "state" in view and "legal_actions" in view
        assert view["can_rewind"] is False

    def test_direct_session_construction_skips_the_setup_phase_by_default(self):
        # `make_session()` builds a `GameSession` directly (as most tests in
        # this file do) to exercise the turn loop without a mulligan step in
        # the way; only `GameSessionManager.create_goldfish` (below) opts a
        # real goldfish game into `require_setup`.
        session = make_session()
        assert session.view()["setup"]["complete"] is True


class TestMulligan:
    """UC3: a goldfish game from the manager gates on mulligan/keep_hand first."""

    def _start(self, library=None, commanders=None, hand=7, mulligan_style="london"):
        manager = GameSessionManager()
        library = library if library is not None else [land()] * 30
        return manager.create_goldfish(
            library=library,
            commanders=commanders,
            starting_hand=hand,
            mulligan_style=mulligan_style,
        )

    def test_starts_incomplete_with_only_mulligan_actions(self):
        session = self._start()
        view = session.view()
        assert view["setup"]["complete"] is False
        assert view["setup"]["mulligan_count"] == 0
        assert {a["type"] for a in view["legal_actions"]} == {"mulligan", "keep_hand"}

    def test_non_setup_actions_are_rejected_until_kept(self):
        session = self._start()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_step"})

    def test_mulligan_reshuffles_hand_and_redraws_seven(self):
        session = self._start()
        player = session.engine.state.active_player
        first_hand = {o.instance_id for o in player.hand}
        view = session.apply_action({"type": "mulligan"})
        assert view["setup"]["complete"] is False
        assert view["setup"]["mulligan_count"] == 1
        assert len(player.hand) == 7
        # A fresh 7 from a reshuffled 30-card library of identical basics
        # can't be asserted against by name, but the instances differ.
        assert {o.instance_id for o in player.hand} != first_hand

    def test_first_mulligan_is_free_in_commander(self):
        # RULE 103.4, Commander Rules Committee 2023: every session defaults
        # to the Commander format (`GameState.format_name`), so the first
        # mulligan bottoms nothing.
        session = self._start()
        session.apply_action({"type": "mulligan"})
        player = session.engine.state.active_player
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["setup"]["complete"] is True
        assert view["setup"]["mulligan_count"] == 1
        assert len(player.hand) == 7

    def test_keep_hand_requires_bottoming_one_card_per_mulligan_past_the_first(self):
        session = self._start()
        session.apply_action({"type": "mulligan"})  # free
        session.apply_action({"type": "mulligan"})  # not free
        with pytest.raises(GameActionError):
            session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

        player = session.engine.state.active_player
        bottom_id = player.hand[0].instance_id
        view = session.apply_action(
            {"type": "keep_hand", "bottom_instance_ids": [bottom_id]}
        )
        assert view["setup"]["complete"] is True
        assert view["setup"]["mulligan_count"] == 2
        assert len(player.hand) == 6
        assert player.library[0].instance_id == bottom_id

    def test_no_free_mulligan_outside_commander(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(
            library=[land()] * 30,
            starting_hand=7,
            mulligan_style="london",
            game_format="constructed",
        )
        session.apply_action({"type": "mulligan"})
        with pytest.raises(GameActionError):
            session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

    def test_keeping_the_opening_hand_needs_no_bottoming(self):
        session = self._start()
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["setup"]["complete"] is True
        assert len(session.engine.state.active_player.hand) == 7

    def test_setup_complete_unlocks_normal_actions(self):
        session = self._start()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        # After setup, normal actions unlock; single-step to main1.
        advance_until(session, step="main1")
        assert session.engine.state.current_step == "main1"

    def test_restart_re_enters_the_setup_phase(self):
        session = self._start()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_step"})
        view = session.restart()
        assert view["setup"]["complete"] is False
        assert view["setup"]["mulligan_count"] == 0

    def test_next7_mulligan_redraws_seven_and_never_requires_bottoming(self):
        session = self._start(mulligan_style="next7")
        player = session.engine.state.active_player
        first_hand = {o.instance_id for o in player.hand}
        view = session.apply_action({"type": "mulligan"})
        assert view["setup"]["complete"] is False
        assert view["setup"]["mulligan_count"] == 1
        assert view["setup"]["bottom_count"] == 0
        assert len(player.hand) == 7
        assert {o.instance_id for o in player.hand} != first_hand
        assert {a["type"] for a in view["legal_actions"]} == {"mulligan", "keep_hand"}
        keep_action = next(a for a in view["legal_actions"] if a["type"] == "keep_hand")
        assert keep_action["bottom_count"] == 0

        view = session.apply_action({"type": "mulligan"})
        assert view["setup"]["mulligan_count"] == 2
        assert view["setup"]["bottom_count"] == 0

        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["setup"]["complete"] is True
        assert len(player.hand) == 7


def leyline_card(name="Test Leyline"):
    """The Leyline cycle's shared shape: RULE 103.6a's opening-hand
    battlefield permission on its own line (PLR-11)."""
    return Card(
        id=name,
        name=name,
        type_line="Enchantment",
        mana_cost_string="{2}{W}",
        converted_mana_cost=3,
        oracle_text=(
            "If this card is in your opening hand, you may begin the game "
            "with it on the battlefield."
        ),
    )


class TestOpeningHandBattlefieldPermission:
    """PLR-11 / RULE 103.6a: "you may begin the game with it on the
    battlefield" — a pregame setup choice offered once every seat has kept,
    walked one card at a time the same way Vancouver's post-keep scry is.
    """

    def _start(self, extra_hand_cards=None, mulligan_style="london"):
        manager = GameSessionManager()
        # The opening hand draws from the *end* of the library list
        # (`Player.draw` pops the top; `build_goldfish_engine` appends "as
        # given", so the last entries become the top) — put the card(s)
        # under test last so they're guaranteed to be drawn.
        library = [land()] * (30 - len(extra_hand_cards or [])) + list(extra_hand_cards or [])
        return manager.create_goldfish(library=library, mulligan_style=mulligan_style)

    def test_offered_after_the_opening_hand_is_kept(self):
        session = self._start([leyline_card()])
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["pending_choice"]["kind"] == "opening_hand_battlefield"
        option_ids = {o["id"] for o in view["pending_choice"]["options"]}
        assert option_ids == {"battlefield", "decline"}

    def test_choosing_battlefield_moves_it_there(self):
        session = self._start([leyline_card()])
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        player = session.engine.state.active_player
        leyline = next(o for o in player.hand if o.card.name == "Test Leyline")
        view = session.apply_action({"type": "choose", "option_id": "battlefield"})
        assert view["pending_choice"] is None
        assert leyline not in player.hand
        assert leyline in session.engine.state.battlefield
        assert leyline.controller_id == player.id

    def test_declining_leaves_it_in_hand(self):
        session = self._start([leyline_card()])
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        player = session.engine.state.active_player
        leyline = next(o for o in player.hand if o.card.name == "Test Leyline")
        view = session.apply_action({"type": "decline"})
        assert view["pending_choice"] is None
        assert leyline in player.hand
        assert leyline not in session.engine.state.battlefield

    def test_a_hand_with_no_such_card_opens_no_choice(self):
        session = self._start()
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["pending_choice"] is None
        assert view["setup"]["complete"] is True

    def test_two_qualifying_cards_are_offered_one_at_a_time(self):
        session = self._start([leyline_card("Test Leyline A"), leyline_card("Test Leyline B")])
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["pending_choice"]["kind"] == "opening_hand_battlefield"
        first_prompt = view["pending_choice"]["prompt"]
        view = session.apply_action({"type": "choose", "option_id": "battlefield"})
        assert view["pending_choice"]["kind"] == "opening_hand_battlefield"
        assert view["pending_choice"]["prompt"] != first_prompt
        view = session.apply_action({"type": "decline"})
        assert view["pending_choice"] is None
        # One was put on the battlefield, the other stayed in hand — which
        # is which isn't rules-significant (RULE 103.6: "any order").
        battlefield_names = {o.card.name for o in session.engine.state.battlefield}
        hand_names = {o.card.name for o in session.engine.state.active_player.hand}
        both = {"Test Leyline A", "Test Leyline B"}
        assert len(battlefield_names & both) == 1
        assert (both - battlefield_names) == (hand_names & both)

    def test_unaffected_by_a_card_that_only_looks_similar(self):
        # Gemstone Caverns' extra conditions/costs are a genuinely different
        # shape and must stay unclaimed by the plain Leyline-cycle clause.
        near_miss = Card(
            id="Near Miss",
            name="Near Miss",
            type_line="Land",
            oracle_text=(
                "If this card is in your opening hand and you're not the "
                "starting player, you may begin the game with Near Miss on "
                "the battlefield with a luck counter on it. If you do, "
                "exile a card from your hand."
            ),
        )
        session = self._start([near_miss])
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["pending_choice"] is None


def gemstone_caverns_card(name="Test Gemstone Caverns"):
    """Gemstone Caverns' shape: conditional ("not the starting player"),
    battlefield + a named counter, and a mandatory "if you do, exile a
    card from your hand" tail."""
    return Card(
        id=name,
        name=name,
        type_line="Land",
        oracle_text=(
            f"If this card is in your opening hand and you're not the "
            f"starting player, you may begin the game with {name} on the "
            f"battlefield with a luck counter on it. If you do, exile a "
            f"card from your hand."
        ),
    )


def buried_ogre_card(name="Test Buried Ogre"):
    """Buried Ogre's shape: unconditional, graveyard-destination, with a
    mandatory "if you do, you lose N life" tail."""
    return Card(
        id=name,
        name=name,
        type_line="Creature — Ogre",
        mana_cost_string="{3}{B}",
        converted_mana_cost=4,
        is_creature=True,
        power=4,
        toughness=2,
        oracle_text=(
            f"You may begin the game with {name} in your graveyard. "
            f"If you do, you lose 1 life."
        ),
    )


class TestPregameSetupPermission:
    """PLR-11's own follow-up: the two conditional/costed pregame-setup
    shapes deliberately left unclaimed at the time — Gemstone Caverns
    (conditional battlefield entry + counter + exile cost) and Buried
    Ogre (graveyard destination + life-loss cost).
    """

    def test_graveyard_destination_moves_it_there(self):
        # Unconditional (no starting-player gate), so a solo goldfish game
        # — where the lone human is always the starting player — still
        # offers it.
        manager = GameSessionManager()
        library = [land()] * 29 + [buried_ogre_card()]
        session = manager.create_goldfish(library=library)
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        player = session.engine.state.active_player
        ogre = next(o for o in player.hand if o.card.name == "Test Buried Ogre")
        life_before = player.life
        view = session.apply_action({"type": "choose", "option_id": "graveyard"})
        assert view["pending_choice"] is None
        assert ogre not in player.hand
        assert ogre in player.graveyard
        assert ogre not in session.engine.state.battlefield
        assert player.life == life_before - 1

    def test_graveyard_decline_leaves_it_in_hand_at_full_life(self):
        manager = GameSessionManager()
        library = [land()] * 29 + [buried_ogre_card()]
        session = manager.create_goldfish(library=library)
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        player = session.engine.state.active_player
        life_before = player.life
        view = session.apply_action({"type": "decline"})
        assert view["pending_choice"] is None
        assert any(o.card.name == "Test Buried Ogre" for o in player.hand)
        assert player.life == life_before

    def _multiplayer(self, bob_extra_cards):
        """Ann seated first (the starting player, RULE 103.2 — "seat order
        is turn order"), Bob second — so a Gemstone-Caverns-shaped card in
        Bob's hand qualifies for the "not the starting player" condition
        while the identical card would not in Ann's."""
        manager = GameSessionManager()
        ann_library = [land()] * 30
        bob_library = [land()] * (30 - len(bob_extra_cards)) + list(bob_extra_cards)
        session = manager.create_multiplayer(
            [
                {"player_id": "ann", "name": "Ann", "library": ann_library},
                {"player_id": "bob", "name": "Bob", "library": bob_library},
            ],
        )
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")
        return session

    def test_conditional_battlefield_offered_to_non_starting_player_only(self):
        session = self._multiplayer([gemstone_caverns_card()])
        state = session.engine.state
        assert state.starting_player_id in (None, "ann")  # Ann is seat 0
        choice = state.pending_choice
        assert choice is not None
        assert choice["kind"] == "opening_hand_battlefield"
        assert choice["player_id"] == "bob"
        assert {o["id"] for o in choice["options"]} == {"battlefield", "decline"}

    def test_conditional_battlefield_not_offered_to_the_starting_player(self):
        # The identical card, in Ann's (the starting player's) hand
        # instead — RULE 103.6a's own "and you're not the starting player"
        # condition means it's never queued at all, not offered-then-
        # expected-to-decline.
        manager = GameSessionManager()
        ann_library = [land()] * 29 + [gemstone_caverns_card()]
        bob_library = [land()] * 30
        session = manager.create_multiplayer(
            [
                {"player_id": "ann", "name": "Ann", "library": ann_library},
                {"player_id": "bob", "name": "Bob", "library": bob_library},
            ],
        )
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")
        assert session.engine.state.pending_choice is None

    def test_accepting_enters_with_the_counter_then_asks_which_card_to_exile(self):
        session = self._multiplayer([gemstone_caverns_card()])
        bob = session.engine.state.player_by_id("bob")
        gemstone = next(o for o in bob.hand if o.card.name == "Test Gemstone Caverns")
        other_hand_card = next(o for o in bob.hand if o is not gemstone)
        view = session.apply_action(
            {"type": "choose", "option_id": "battlefield"}, actor_id="bob"
        )
        assert gemstone not in bob.hand
        assert gemstone in session.engine.state.battlefield
        assert gemstone.counters.get("luck") == 1
        # The mandatory "if you do, exile a card from your hand" tail opened
        # its own interactive choice — which card is Bob's to pick.
        choice = view["pending_choice"]
        assert choice["kind"] == "choose_objects"
        assert choice["action"] == "exile"
        option_ids = {o["id"] for o in choice["options"]}
        assert str(other_hand_card.instance_id) in option_ids
        assert str(gemstone.instance_id) not in option_ids
        view = session.apply_action(
            {"type": "choose", "instance_id": other_hand_card.instance_id}, actor_id="bob"
        )
        assert view["pending_choice"] is None
        assert other_hand_card not in bob.hand
        assert other_hand_card in bob.exile

    def test_declining_leaves_it_in_hand_with_no_exile(self):
        session = self._multiplayer([gemstone_caverns_card()])
        bob = session.engine.state.player_by_id("bob")
        hand_before = set(bob.hand)
        view = session.apply_action({"type": "decline"}, actor_id="bob")
        assert view["pending_choice"] is None
        assert set(bob.hand) == hand_before


class TestActions:
    def _advance_to_main1(self, session):
        advance_until(session, step="main1")

    def test_play_land_then_action_is_recorded(self):
        session = make_session()
        self._advance_to_main1(session)
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        session.apply_action(
            {"type": "play_land", "instance_id": land_obj.instance_id, "name": land_obj.name}
        )
        assert land_obj.instance_id in {o.instance_id for o in state.battlefield}
        assert session.can_rewind
        assert session.move_log[-1].startswith("play_land")

    def test_illegal_action_raises_and_leaves_state_untouched(self):
        session = make_session()
        # Trying to play a land during untap is illegal.
        land_obj = next(o for o in session.engine.state.active_player.hand if o.card.is_land)
        before_hand = len(session.engine.state.active_player.hand)
        with pytest.raises(GameActionError):
            session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        assert len(session.engine.state.active_player.hand) == before_hand
        assert not session.can_rewind  # failed action left no undo entry

    def test_unknown_instance_id_raises(self):
        session = make_session()
        self._advance_to_main1(session)
        with pytest.raises(GameActionError):
            session.apply_action({"type": "play_land", "instance_id": 999999})

    def test_unknown_action_type_raises(self):
        session = make_session()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "teleport"})

    def test_auto_turn_plays_out_one_turn_and_is_undoable(self):
        session = make_session()
        session.apply_action({"type": "auto_turn"})
        # Auto-turn drives the cursor (not a fresh begin_turn), ending at
        # the next turn without desyncing.
        assert session.engine.state.internal_turn.number == 2
        # The whole auto-turn is a single undo step back to the opening.
        session.rewind(1)
        assert session.engine.state.internal_turn.number == 1

    def test_auto_turn_resumes_from_a_mid_turn_manual_position(self):
        session = make_session()
        advance_until(session, step="main1")  # manually reach main1 of turn 1
        session.apply_action({"type": "auto_turn"})
        # Finishing turn 1 lands on turn 2 — not turn 3 (no double begin_turn).
        assert session.engine.state.internal_turn.number == 2


class TestSingleStep:
    """"advance_step" advances exactly one step — no auto-skip, no auto-wait."""

    def test_one_advance_moves_one_step(self):
        session = make_session()  # fresh game: cursor before the first step
        view = session.apply_action({"type": "advance_step"})
        assert view["state"]["current_step"] == "untap"

    def test_walks_through_every_step_including_empty_ones(self):
        session = make_session(hand=0)  # empty hand: nothing to do anywhere
        seen = []
        for _ in range(6):
            view = session.apply_action({"type": "advance_step"})
            seen.append(view["state"]["current_step"])
        # Main phases and combat steps are visited, not skipped.
        assert seen[:6] == ["untap", "upkeep", "draw", "main1", "begin_combat", "declare_attackers"]


class TestAdvanceToDecision:
    """"advance_to_decision" fast-forwards to the active player's next choice."""

    def test_stops_at_main1(self):
        session = make_session()
        view = session.apply_action({"type": "advance_to_decision"})
        assert view["state"]["current_step"] == "main1"

    def test_does_not_skip_the_main_phase_to_combat(self):
        # Bug 2: a ready creature and nothing castable must NOT cause the main
        # phase to be skipped straight to combat — the main phase is where the
        # player develops their board, so it's always a stopping point.
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = make_session(library=[bear()] * 10, hand=0)  # nothing castable
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        session.apply_action({"type": "advance_to_decision"})
        assert session.engine.state.current_step == "main1"

    def test_second_press_advances_from_main1_to_combat(self):
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = make_session(library=[bear()] * 10, hand=0)
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        session.apply_action({"type": "advance_to_decision"})  # → main1
        session.apply_action({"type": "advance_to_decision"})  # → combat
        assert session.engine.state.current_step == "declare_attackers"

    def test_generates_individual_advance_steps_for_deterministic_undo(self):
        # Bug 1: the fast-forward is a sequence of real advance_step moves,
        # each logged and undoable one at a time — not one opaque jump.
        session = make_session()
        before = len(session.move_log)
        session.apply_action({"type": "advance_to_decision"})
        added = session.move_log[before:]
        assert added == ["advance_step"] * len(added)
        assert len(added) >= 2  # untap/upkeep/draw/main1 were real steps
        stop = session.engine.state.current_step
        session.rewind(1)  # undoes exactly one step, not the whole skip
        assert session.engine.state.current_step != stop

    def test_works_with_the_dummy_opponent_present(self):
        # Bug 1: deterministic step-by-step advance holds with the opponent.
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_to_decision"})
        assert session.engine.state.current_step == "main1"
        assert session.move_log.count("advance_step") >= 2

    def test_refused_in_a_shared_game_with_interactive_priority(self):
        # RULE 117.4: a step ends only when everyone has passed on an empty
        # stack, never because the active player decided to fast-forward
        # past it — the same refusal `_dispatch` gives a plain
        # "advance_step" in a shared game. This path is special-cased
        # *before* `apply_action` ever reaches `_dispatch`, so it needs its
        # own copy of that guard rather than inheriting it for free.
        session = make_session()
        session.interactive_priority = True
        session.engine.interactive_priority = True
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_to_decision"})


class TestRewind:
    def test_rewind_undoes_last_move(self):
        session = make_session()
        advance_until(session, step="main1")
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        hand_before = len(state.active_player.hand)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        session.rewind(1)
        # Back to before the land drop.
        assert len(session.engine.state.active_player.hand) == hand_before
        assert len(session.engine.state.battlefield) == 0

    def test_rewind_across_turn_boundary_resumes_mid_turn(self):
        session = make_session()
        # Single-step just into turn 2, then rewind the boundary crossing.
        advance_until(session, turn=2, step="untap")
        assert session.engine.state.internal_turn.number == 2
        session.rewind(1)
        # Restored to the last step of turn 1 (cleanup) — the cursor travels
        # with the snapshot, so the turn counter doesn't jump forward.
        assert session.engine.state.internal_turn.number == 1
        assert session.engine.state.current_step == "cleanup"
        # Continuing crosses the boundary again, not an extra turn.
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.internal_turn.number == 2
        assert session.engine.state.current_step == "untap"

    def test_rewind_more_than_history_restarts(self):
        session = make_session()
        session.apply_action({"type": "advance_step"})
        session.rewind(10)
        assert not session.can_rewind
        assert session.engine.state.internal_turn.number == 1

    def test_rewind_requires_positive_steps(self):
        session = make_session()
        with pytest.raises(GameActionError):
            session.rewind(0)


class TestRestart:
    def test_restart_returns_to_opening_state(self):
        session = make_session()
        advance_until(session, step="main1")
        land_obj = next(o for o in session.engine.state.active_player.hand if o.card.is_land)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})

        session.restart()
        state = session.engine.state
        assert state.internal_turn.number == 1
        assert len(state.active_player.hand) == 7
        assert len(state.battlefield) == 0
        assert not session.can_rewind
        assert session.move_log == []

    def test_restart_then_advance_reaches_main1(self):
        session = make_session()
        advance_until(session, step="main2")
        session.restart()
        # From the restored opening state, single-stepping reaches main1 again.
        advance_until(session, step="main1")
        assert session.engine.state.current_step == "main1"
        assert session.engine.state.internal_turn.number == 1


class TestCombat:
    def _to_declare_attackers(self, session):
        engine = session.engine
        while engine.state.current_step != "declare_attackers":
            if engine.advance_step() is None:
                break

    def test_solo_swing_marks_attacking_and_rewind_undoes_it(self):
        session = make_session(hand=0)
        # A ready creature on the battlefield (not summoning-sick).
        from mtg_analyzer.models.game_object import GameObject, Zone

        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        self._to_declare_attackers(session)

        attack = next(
            a for a in session.legal_actions() if a["type"] == "attack"
        )
        assert attack["legal_defenders"] == []  # solo → bare swing
        session.apply_action({"type": "attack", "instance_id": obj.instance_id})
        assert obj.attacking and obj.tapped

        # Rewind restores the pre-attack state — combat lives on the state,
        # so the freshly-restored engine sees the creature un-declared.
        session.rewind(1)
        restored = session.engine.state.find_object(obj.instance_id)
        assert not restored.attacking and not restored.tapped

    def test_attack_serializes_combat_state_to_the_view(self):
        session = make_session(hand=0)
        from mtg_analyzer.models.game_object import GameObject, Zone

        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        self._to_declare_attackers(session)
        view = session.apply_action(
            {"type": "attack", "instance_id": obj.instance_id}
        )
        card = next(
            c for c in view["state"]["battlefield"] if c["instance_id"] == obj.instance_id
        )
        assert card["attacking"] is True
        assert card["type_line"] == "Creature — Bear"
        assert card["is_creature"] is True


class TestGoldfishDummy:
    def _keep(self, session):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

    def test_real_goldfish_has_a_passive_dummy_opponent(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40, starting_life=20)
        players = session.view()["state"]["players"]
        assert len(players) == 2
        dummy = next(p for p in players if p["is_dummy"])
        assert dummy["name"] == "Goldfisch"
        assert dummy["life"] == 20
        assert dummy["hand_count"] == 7  # a hand to discard from, hidden in UI

    def test_dummy_never_becomes_active_player(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        self._keep(session)
        start = session.engine.state.active_player.id
        assert start == "p1"
        # Run several whole turns; the turn always comes back to the human.
        for _ in range(40):
            if session.engine.advance_step() is None:
                break
        assert session.engine.state.active_player.id == "p1"
        assert session.engine.state.internal_turn.number >= 2  # turns did advance

    def test_view_carries_analysis_digest(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        self._keep(session)
        analysis = session.view()["analysis"]
        assert set(analysis["players"]) == {"p1", "goldfish"}
        p1 = analysis["players"]["p1"]
        for key in ("cmc_curve", "mana_per_turn", "cards_played", "avg_cmc"):
            assert key in p1

    def test_attacking_the_goldfish_deals_and_records_damage(self):
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = GameSessionManager().create_goldfish(library=[land()] * 40, starting_life=20)
        self._keep(session)
        st = session.engine.state
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        st.add_to_battlefield(obj)
        while st.current_step != "declare_attackers":
            if session.engine.advance_step() is None:
                break
        session.apply_action({"type": "declare_attackers", "instance_ids": [obj.instance_id]})
        while st.current_step != "combat_damage":
            if session.engine.advance_step() is None:
                break
        view = session.view()
        dummy = next(p for p in view["state"]["players"] if p["is_dummy"])
        assert dummy["life"] == 18  # 2/2 bear
        assert view["analysis"]["players"]["p1"]["damage_dealt"] == 2


class TestManager:
    def test_create_and_get_goldfish(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert manager.get(session.id) is session

    def test_get_unknown_raises_keyerror(self):
        manager = GameSessionManager()
        with pytest.raises(KeyError):
            manager.get("nope")

    def test_remove(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert manager.remove(session.id) is True
        assert manager.remove(session.id) is False

    def test_multiplayer_needs_at_least_two_seats(self):
        # The seat-less entry point behind the legacy `POST /api/game/
        # multiplayer` route: a real game is started from the lobby, which
        # is the only thing that knows the seats (see api/multiplayer.py).
        manager = GameSessionManager()
        with pytest.raises(MultiplayerNotImplementedError):
            manager.create_multiplayer([])


class TestGameFormatThreading:
    """PLR-13: `create_goldfish`/`create_multiplayer` reach `GameEngine.
    _setup_variants` through their own `build_*_engine` (which don't go
    through `GameEngine.new_game`), not just through it."""

    def test_goldfish_no_format_is_unchanged(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert session.engine.state.format_name == "commander"
        assert session.engine.state.planar_deck == []

    def test_goldfish_planechase_commander_sets_life_and_planar_deck(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(
            library=[land()] * 40, game_format="planechase_commander"
        )
        state = session.engine.state
        assert state.format_name == "planechase_commander"
        me = next(p for p in state.players if not p.is_dummy)
        assert me.life == 40
        assert len(state.planar_deck) > 0

    def test_multiplayer_archenemy_sets_the_named_seat(self):
        manager = GameSessionManager()
        session = manager.create_multiplayer(
            [
                {"player_id": "ann", "name": "Ann", "library": [land()] * 30},
                {"player_id": "bob", "name": "Bob", "library": [land()] * 30},
            ],
            game_format="archenemy",
            archenemy_id="bob",
        )
        state = session.engine.state
        assert state.archenemy_id == "bob"
        bob = next(p for p in state.players if p.id == "bob")
        ann = next(p for p in state.players if p.id == "ann")
        assert bob.life == 40  # RULE 904.4
        assert ann.life == 20
        assert len(bob.scheme_deck) > 0

    def test_multiplayer_no_format_is_unchanged(self):
        manager = GameSessionManager()
        session = manager.create_multiplayer(
            [
                {"player_id": "ann", "name": "Ann", "library": [land()] * 30},
                {"player_id": "bob", "name": "Bob", "library": [land()] * 30},
            ],
        )
        assert session.engine.state.format_name == "commander"
        assert session.engine.state.archenemy_id is None
