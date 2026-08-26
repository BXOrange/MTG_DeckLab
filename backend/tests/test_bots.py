"""Tests for the seat-filling bots (UC5).

Reference: mtg_analyzer/services/bots.py.

Two things are being checked here and they are quite different. One is
*behaviour*: the goldfish only ever plays lands, the greedy bot casts,
attacks and blocks. The other is the property that makes a bot legitimate
at all — it plays through the same redacted view and the same
`legal_actions`/`apply_action` pair a browser does, so it can neither see
nor do anything a human client couldn't.
"""

import random

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.bots import (
    BOT_TYPES,
    Bot,
    GoldfishBot,
    GreedyBot,
    ManaMaximizerBot,
    bot_catalogue,
    create_bot,
    run_bots,
)
from mtg_analyzer.services.game_session import GameSessionManager


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def bear(name="Grizzly Bears", cost="{1}{G}", cmc=2, power=2, toughness=2):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear",
        mana_cost_string=cost,
        converted_mana_cost=cmc,
        is_creature=True,
        power=power,
        toughness=toughness,
        color_identity={"G"},
    )


def make_game(ann_deck=None, bob_deck=None, ann_commanders=None):
    """A two-seat game. Seat order is turn order, so "ann" is on the play."""
    manager = GameSessionManager()
    return manager.create_multiplayer(
        [
            {
                "player_id": "ann",
                "name": "Ann",
                "library": list(ann_deck or [land()] * 30),
                "commanders": list(ann_commanders or []),
            },
            {"player_id": "bob", "name": "Bob", "library": list(bob_deck or [land()] * 30)},
        ],
        mulligan_style="none",
    )


def keep(session, *player_ids):
    for pid in player_ids:
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)


def drive(session, bots, human_ids=(), limit=400):
    """Run the table forward: bots decide, humans do nothing but pass.

    The "human" here is the least interesting opponent possible on purpose
    — passing is what a client with auto-pass on does, and it lets a test
    watch the bot's line without a second policy muddying it.
    """
    for _ in range(limit):
        if session.engine.state.game_over:
            return
        if run_bots(session, bots):
            continue
        holder = session.engine.state.priority_player
        if holder is None or holder.id not in human_ids:
            return
        session.apply_action({"type": "pass_priority"}, actor_id=holder.id)


def run_to_turn(session, bots, turn, human_ids=(), limit=4000):
    for _ in range(limit):
        if session.engine.state.game_over or session.engine.state.turn_number >= turn:
            return
        if run_bots(session, bots, max_actions=20):
            continue
        holder = session.engine.state.priority_player
        if holder is None:
            return
        if holder.id in human_ids:
            session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
        else:
            return
    raise AssertionError(f"never reached turn {turn}")


class TestRegistry:
    def test_all_bots_are_registered_and_described(self):
        assert set(BOT_TYPES) == {"goldfish", "greedy", "mana_maximizer"}
        catalogue = bot_catalogue()
        assert {b["kind"] for b in catalogue} == {"goldfish", "greedy", "mana_maximizer"}
        assert all(b["label"] and b["description"] for b in catalogue)

    def test_create_bot_rejects_an_unknown_kind(self):
        with pytest.raises(KeyError):
            create_bot("mindslaver", "bot:1")


class TestSetup:
    def test_a_bot_keeps_its_opening_hand_without_being_asked(self):
        session = make_game()
        bots = {"bob": GoldfishBot("bob", "Bob")}
        run_bots(session, bots)
        assert session.view(perspective="ann")["setup"]["waiting_for"] == ["ann"]

    def test_a_bot_never_mulligans(self):
        session = make_game()
        session.mulligan_style = "london"
        run_bots(session, {"bob": GreedyBot("bob")})
        assert session.mulligan_count_for("bob") == 0

    def test_two_bots_start_the_game_between_them(self):
        session = make_game()
        bots = {"ann": GoldfishBot("ann"), "bob": GoldfishBot("bob")}
        run_bots(session, bots, max_actions=30)
        assert session.view()["setup"]["complete"] is True


class TestGoldfishBot:
    def test_plays_one_land_a_turn_and_nothing_else(self):
        session = make_game(ann_deck=[land()] * 30, bob_deck=[land(), bear()] * 15)
        bots = {"bob": GoldfishBot("bob")}
        keep(session, "ann")
        run_to_turn(session, bots, turn=5, human_ids=("ann",))
        bob = session.engine.state.player_by_id("bob")
        board = session.engine.state.permanents_controlled_by("bob")
        assert board, "the goldfish should at least be playing its lands"
        assert all(o.card.is_land for o in board), "it cast something"
        # One land drop per own turn (RULE 305.2): Bob's turns are the even
        # ones, so by turn 5 it has had two of them.
        assert len(board) == 2
        assert any(not o.card.is_land for o in bob.hand), "it should still hold its spells"

    def test_never_attacks_or_blocks(self):
        session = make_game()
        goldfish = GoldfishBot("bob")
        view = {
            "state": {"active_player_id": "bob", "current_step": "declare_attackers"},
            "setup": {"complete": True},
        }
        attack = {"type": "attack", "instance_id": 1, "legal_defenders": []}
        assert goldfish.play(view, [attack]) is None
        assert goldfish.blocks(view, [{"instance_id": 2, "legal_attackers": [{"instance_id": 1}]}]) == []


class TestManaMaximizerBot:
    def test_plays_lands_and_taps_them_but_never_casts(self):
        # A one-drop it could easily afford — the whole point of this bot
        # is that it never reaches for it.
        deck = [land(), bear("Llanowar Elves", "{G}", 1, 1, 1)] * 15
        session = make_game(ann_deck=deck, bob_deck=[land()] * 30)
        bots = {"ann": ManaMaximizerBot("ann")}
        keep(session, "bob")
        drive(session, bots, human_ids=("bob",))
        ann = session.engine.state.player_by_id("ann")
        board = session.engine.state.permanents_controlled_by("ann")
        assert board, "should at least have played its lands"
        assert all(o.card.is_land for o in board), "it cast something"
        assert all(o.tapped for o in board), "every land should be tapped for mana"
        assert any(not o.card.is_land for o in ann.hand), "it should still hold its spells"

    def test_never_attacks_or_blocks(self):
        session = make_game()
        bot = ManaMaximizerBot("bob")
        view = {
            "state": {"active_player_id": "bob", "current_step": "declare_attackers"},
            "setup": {"complete": True},
        }
        attack = {"type": "attack", "instance_id": 1, "legal_defenders": []}
        assert bot.play(view, [attack]) is None
        assert bot.blocks(view, [{"instance_id": 2, "legal_attackers": [{"instance_id": 1}]}]) == []


class TestGreedyBot:
    def test_plays_a_land_taps_it_and_casts(self):
        # A one-drop so the very first turn is enough to see the whole line.
        deck = [land(), bear("Llanowar Elves", "{G}", 1, 1, 1)] * 15
        session = make_game(ann_deck=deck, bob_deck=[land()] * 30)
        bots = {"ann": GreedyBot("ann")}
        keep(session, "bob")
        drive(session, bots, human_ids=("bob",))
        board = session.engine.state.permanents_controlled_by("ann")
        assert any(o.card.is_land for o in board)
        assert any(o.is_creature for o in board), "the greedy bot never cast anything"

    def test_attacks_with_everything_at_a_player(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {"active_player_id": "ann", "current_step": "declare_attackers"},
            "setup": {"complete": True},
        }
        defenders = [
            {"kind": "planeswalker", "instance_id": 9, "label": "Jace"},
            {"kind": "player", "id": "bob", "label": "Bob"},
        ]
        action = greedy.play(
            view,
            [
                {"type": "attack", "instance_id": 1, "name": "A", "legal_defenders": defenders},
                {"type": "attack", "instance_id": 2, "name": "B", "legal_defenders": defenders},
            ],
        )
        assert action["type"] == "attack"
        assert action["instance_ids"] == [1, 2]
        assert action["defender"]["kind"] == "player"

    def test_in_a_pod_it_attacks_whoever_is_closest_to_dead(self):
        """PLR-8: at a table of 3+ there are multiple *player* defenders on
        offer, and the old code just took whichever the engine happened to
        list first — not a decision. Life total (already in the view) is a
        real, zero-lookahead tie-break."""
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "declare_attackers",
                "players": [
                    {"id": "ann", "life": 20},
                    {"id": "bob", "life": 14},
                    {"id": "cate", "life": 3},
                ],
            },
            "setup": {"complete": True},
        }
        defenders = [
            {"kind": "player", "id": "bob", "label": "Bob"},
            {"kind": "player", "id": "cate", "label": "Cate"},
        ]
        action = greedy.play(
            view,
            [{"type": "attack", "instance_id": 1, "name": "A", "legal_defenders": defenders}],
        )
        assert action["defender"]["id"] == "cate"

    def test_falls_back_to_the_first_defender_without_life_totals(self):
        """A caller that hands `play` a minimal state (no ``players`` list,
        the shape `test_attacks_with_everything_at_a_player` above uses)
        still gets a legal answer rather than an error."""
        greedy = GreedyBot("ann")
        view = {
            "state": {"active_player_id": "ann", "current_step": "declare_attackers"},
            "setup": {"complete": True},
        }
        defenders = [
            {"kind": "player", "id": "bob", "label": "Bob"},
            {"kind": "player", "id": "cate", "label": "Cate"},
        ]
        action = greedy.play(
            view,
            [{"type": "attack", "instance_id": 1, "name": "A", "legal_defenders": defenders}],
        )
        assert action["defender"]["id"] == "bob"

    def test_blocks_spread_over_attackers_before_doubling_up(self):
        greedy = GreedyBot("bob")
        attackers = [{"instance_id": 10, "name": "X"}, {"instance_id": 11, "name": "Y"}]
        offers = [
            {"type": "declare_blockers", "instance_id": i, "legal_attackers": attackers}
            for i in (1, 2, 3)
        ]
        assignments = greedy.blocks({}, offers)
        assert [a["blocker"] for a in assignments] == [1, 2, 3]
        # Both attackers get a blocker before either gets a second one.
        assert sorted(a["attacker"] for a in assignments) == [10, 10, 11]

    def test_blocks_in_a_real_game(self):
        deck = [land(), bear()] * 15
        session = make_game(ann_deck=deck, bob_deck=deck)
        bots = {"bob": GreedyBot("bob")}
        keep(session, "ann")
        run_to_turn(session, bots, turn=6, human_ids=("ann",))
        # Bob has been developing and Ann has done nothing, so Bob's board
        # is the only one that could have blocked — but the real assertion
        # is simply that a full game with a greedy bot in it runs to turn 6
        # without the bot wedging the table.
        assert session.engine.state.turn_number >= 6

    def test_casts_its_commander_instead_of_starving_it_with_cheap_spells(self):
        """A commander must not lose the mana race to hand spells forever.

        Plain cheapest-first sorting alone would starve a 4-mana commander
        indefinitely in a low-curve deck: there is always some 1- or 2-drop
        in hand to spend the turn's mana on first, and since the hand keeps
        refilling every turn, the commander's turn as "cheapest available"
        never comes. `_cast_or_activate` gives the command zone first claim
        on the turn's mana instead, so it's cast the moment it's affordable.
        """
        commander = bear("Test Commander", "{2}{G}{G}", 4, 4, 4)
        deck = [land()] * 20 + [bear(f"Bear{i}", "{G}", 1) for i in range(20)]
        random.Random(3).shuffle(deck)  # draw order matters: a real opening hand needs a land
        session = make_game(ann_deck=deck, bob_deck=[land()] * 40, ann_commanders=[commander])
        bots = {"ann": GreedyBot("ann"), "bob": GreedyBot("bob")}
        keep(session, "bob")
        drive(session, bots, human_ids=("bob",), limit=2000)
        ann = session.engine.state.player_by_id("ann")
        assert not any(o.name == "Test Commander" for o in ann.command)
        assert any(
            o.name == "Test Commander" for o in session.engine.state.permanents_controlled_by("ann")
        )

    def test_does_not_touch_the_no_untap_toggle(self):
        """`set_skip_untap` is a toggle, so a bot that "does everything"
        would flip it forever. It has to be excluded explicitly."""
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        toggle = {"type": "set_skip_untap", "instance_id": 1, "name": "Rubinia"}
        assert greedy.play(view, [toggle]) is None

    def test_taps_a_dual_for_the_colour_it_has_least_of(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {"G": 2, "W": 0}}],
            },
            "setup": {"complete": True},
        }
        action = greedy.play(
            view,
            [
                {
                    "type": "tap_for_mana",
                    "instance_id": 1,
                    "ability_index": 0,
                    "options": [
                        {"index": 0, "mana": {"G": 1}},
                        {"index": 1, "mana": {"W": 1}},
                    ],
                }
            ],
        )
        assert action["option_index"] == 1

    def test_prefers_playing_a_land_that_enters_untapped(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [
                {"type": "play_land", "instance_id": 1, "name": "Bojuka Bog", "enters_tapped": True},
                {"type": "play_land", "instance_id": 2, "name": "Forest", "enters_tapped": False},
                {"type": "play_land", "instance_id": 3, "name": "Shockland", "enters_tapped": None},
            ],
        )
        assert chosen["instance_id"] == 2

    def test_still_plays_a_tapped_land_when_thats_the_only_option(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [{"type": "play_land", "instance_id": 1, "name": "Bojuka Bog", "enters_tapped": True}],
        )
        assert chosen["instance_id"] == 1

    def test_casts_instead_of_manually_tapping_mana_first(self):
        """A `cast_spell` offer is only ever made once mana-potential can pay
        for it (`_castable_now_or_via_potential`), which auto-taps for the
        exact cost on cast — so a bot that taps a source manually first,
        ahead of casting, can only strand the wrong colour. `_develop_board`
        tries casting before falling back to a manual tap."""
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [
                {"type": "tap_for_mana", "instance_id": 1, "ability_index": 0, "options": [{"index": 0, "mana": {"G": 1}}]},
                {"type": "cast_spell", "instance_id": 2, "mana_value": 1},
            ],
        )
        assert chosen["type"] == "cast_spell"

    def test_orders_equip_after_other_abilities(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [
                {"type": "activate_ability", "instance_id": 1, "ability_index": 0, "attach_kind": "equip"},
                {"type": "activate_ability", "instance_id": 2, "ability_index": 0},
            ],
        )
        assert chosen["instance_id"] == 2

    def test_still_equips_when_nothing_else_is_offered(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [{"type": "activate_ability", "instance_id": 1, "ability_index": 0, "attach_kind": "equip"}],
        )
        assert chosen["instance_id"] == 1

    def test_skips_an_x_spell_it_could_only_cast_for_zero(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        fireball = {
            "type": "cast_spell",
            "instance_id": 1,
            "name": "Fireball",
            "has_x": True,
            "max_x": 0,
            "mana_value": 1,
        }
        assert greedy.play(view, [fireball]) is None

    def test_casts_cheap_spells_before_x_spells(self):
        greedy = GreedyBot("ann")
        view = {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
            },
            "setup": {"complete": True},
        }
        chosen = greedy.play(
            view,
            [
                {"type": "cast_spell", "instance_id": 1, "has_x": True, "max_x": 4, "mana_value": 1},
                {"type": "cast_spell", "instance_id": 2, "mana_value": 3},
            ],
        )
        assert chosen["instance_id"] == 2


class TestTargeting:
    def _view(self):
        return {
            "state": {
                "active_player_id": "ann",
                "current_step": "main1",
                "stack": [],
                "players": [{"id": "ann", "mana_pool": {}}],
                "battlefield": [
                    {"instance_id": 1, "controller_id": "ann"},
                    {"instance_id": 2, "controller_id": "bob"},
                ],
            },
            "setup": {"complete": True},
        }

    def test_greedy_points_at_the_opponents_things_first(self):
        greedy = GreedyBot("ann")
        bolt = {
            "type": "cast_spell",
            "instance_id": 5,
            "mana_value": 1,
            "requires_target": True,
            "targets": [
                {
                    "kind": "creature",
                    "count": 1,
                    "optional": False,
                    "options": [{"instance_id": 1, "name": "Mine"}, {"instance_id": 2, "name": "Theirs"}],
                }
            ],
        }
        action = greedy.play(self._view(), [bolt])
        assert action["targets"] == [{"instance_id": 2, "name": "Theirs"}]
        assert "requires_target" not in action or action["targets"]

    def test_a_beneficial_effect_points_at_its_own_things_first(self):
        """PLR-7: `polarity="beneficial"` (a pump/protection spell's own
        `targeting.TargetSpec.polarity`, threaded onto the requirement by
        `game/targeting.py`) reverses the default — pointing a buff at an
        opponent's creature would be self-sabotage, not just unambitious."""
        greedy = GreedyBot("ann")
        growth = {
            "type": "cast_spell",
            "instance_id": 5,
            "mana_value": 1,
            "requires_target": True,
            "targets": [
                {
                    "kind": "creature",
                    "count": 1,
                    "optional": False,
                    "polarity": "beneficial",
                    "options": [{"instance_id": 1, "name": "Mine"}, {"instance_id": 2, "name": "Theirs"}],
                }
            ],
        }
        action = greedy.play(self._view(), [growth])
        assert action["targets"] == [{"instance_id": 1, "name": "Mine"}]

    def test_a_player_target_is_never_the_bot_itself(self):
        greedy = GreedyBot("ann")
        picks = greedy.pick_targets(
            self._view(),
            {
                "targets": [
                    {
                        "kind": "player",
                        "count": 1,
                        "optional": False,
                        "options": [{"player_id": "ann"}, {"player_id": "bob"}],
                    }
                ]
            },
        )
        assert picks == [{"player_id": "bob"}]

    def test_an_unsatisfiable_requirement_yields_no_action(self):
        greedy = GreedyBot("ann")
        picks = greedy.pick_targets(
            self._view(),
            {
                "targets": [
                    {"kind": "creature", "count": 2, "optional": False, "options": [{"instance_id": 2}]}
                ]
            },
        )
        assert picks is None


class TestPlayingFair:
    """A bot must not be able to see or do more than a browser can."""

    def test_a_bot_only_ever_sees_its_own_hand(self):
        session = make_game()
        seen = {}

        class Spy(Bot):
            def decide(self, view, actions):
                seen["view"] = view
                return super().decide(view, actions)

        run_bots(session, {"bob": Spy("bob")}, max_actions=3)
        players = {p["id"]: p for p in seen["view"]["state"]["players"]}
        assert players["bob"]["hand"], "a bot must see its own hand"
        assert players["ann"]["hand"] == [], "a bot must not see the opponent's hand"
        assert players["bob"]["library"] == [], "nobody sees a library (RULE 400.2)"

    def test_a_bot_cannot_act_out_of_turn(self):
        """The bot is only ever handed `legal_actions` for its own seat, so
        RULE 117's priority gate applies to it exactly as to a client."""
        session = make_game()
        keep(session, "ann", "bob")
        state = session.engine.state
        assert state.priority_player.id == "ann"
        assert session.legal_actions(perspective="bob") == []

    def test_a_failing_choice_does_not_wedge_the_table(self):
        session = make_game()
        keep(session, "ann", "bob")

        class Broken(Bot):
            def play(self, view, actions):
                return {"type": "play_land", "instance_id": -1}

        bot = Broken("ann")  # Ann is on the play, so Ann holds priority
        run_bots(session, {"ann": bot}, max_actions=10)
        # It gave up on the bad offer and passed instead of retrying it.
        assert bot._failed
        assert session.engine.state.priority_player is not None

    def test_the_action_cap_stops_a_runaway_bot(self):
        session = make_game()
        keep(session, "ann", "bob")

        class Spinner(Bot):
            def play(self, view, actions):
                return None  # always passes → always "moves"

        moved = run_bots(
            session, {"ann": Spinner("ann"), "bob": Spinner("bob")}, max_actions=5
        )
        assert moved is True
