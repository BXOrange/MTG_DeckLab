"""PAR-30 (Vote residue) — plain "take an extra turn after this one".

The plainest Time Walk / Temporal Manipulation body, and the modelable
half of Plea for Power's "Will of the Council" vote outcome. Nothing in
the parser emitted the pre-existing ``take_extra_turn`` effect type
(`effects.TakeExtraTurnEffect` / `GameState.extra_turns`) before v166.

Riders on other extra-turn cards ("skip the untap step of that turn",
"…you lose the game", "…for each coin that comes up heads") are their own
clauses / tickets and must still fail closed.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse ---------------------------------------------------------------


def test_plain_body_parses():
    # "one" normalises to "1"
    assert match_clause("take an extra turn after this 1") == [
        EffectSpec("take_extra_turn", {})
    ]


def test_leading_you_is_the_same_action():
    assert match_clause("you take an extra turn after this 1") == [
        EffectSpec("take_extra_turn", {})
    ]


def test_riders_do_not_fullmatch_and_stay_unclaimed():
    # each is a distinct clause the segmenter splits off; none is modeled
    for text in (
        "take an extra turn after this 1 for each coin that comes up heads",
        "take an extra turn after this 1 if an opponent cast a blue spell this turn",
        "skip the untap step of that turn",
    ):
        assert match_clause(text) is None, text


def test_time_walk_modeled_including_the_exile_self_rider():
    c = Card(id="TW", name="Time Walk", type_line="Sorcery", is_sorcery=True,
             oracle_text="Take an extra turn after this one.")
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed

    tm = Card(id="TM", name="Temporal Mastery", type_line="Sorcery", is_sorcery=True,
              oracle_text="Take an extra turn after this one. Exile Temporal Mastery.")
    assert parse_oracle(tm).coverage != UNMODELED, parse_oracle(tm).unclaimed


def test_plea_for_power_vote_outcome_modeled():
    # (the "Will of the council —" ability-word prefix is stripped by the
    # normalizer only for real cached cards; drop it here — the real card
    # is confirmed MODELED via parser_probe)
    c = Card(id="PfP", name="Plea for Power", type_line="Sorcery", is_sorcery=True,
             oracle_text=(
                 "Starting with you, each player votes for "
                 "time or knowledge. If time gets more votes, take an extra turn "
                 "after this one. If knowledge gets more votes or the vote is tied, "
                 "draw three cards."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed
    vote = next(e for s in res.specs for e in s.effects if e.type == "vote")
    assert vote.params["majority_specs"][0] == [
        {"type": "take_extra_turn", "params": {}}
    ]
    assert vote.params["majority_specs"][1] == [
        {"type": "draw", "params": {"count": 3}}
    ]


def test_savor_the_moment_still_unmodeled_on_its_skip_untap_rider():
    c = Card(id="StM", name="Savor the Moment", type_line="Sorcery", is_sorcery=True,
             oracle_text="Take an extra turn after this one. Skip the untap step of that turn.")
    assert parse_oracle(c).coverage == UNMODELED


def test_expropriate_per_vote_extra_turn_stays_fail_closed():
    # "take an extra turn … for each time vote" can't scale by tally, so
    # `_vote_per_vote` must reject the whole card rather than half-model it.
    assert match_clause(
        "starting with you, each player votes for time or money. "
        "take an extra turn after this 1 for each time vote. "
        "you draw a card for each money vote."
    ) is None


# --- execute -----------------------------------------------------------------


def test_resolving_queues_an_extra_turn_for_the_controller():
    eng, state = _engine()
    src = GameObject(Card(id="tw", name="Time Walk", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    assert state.extra_turns == []
    build_effects([EffectSpec("take_extra_turn", {})], src)[0].apply(
        GameContext(state, eng.rules), None
    )
    assert state.extra_turns == ["p1"]


def test_extra_turn_is_actually_taken_by_the_turn_loop():
    eng, state = _engine()
    eng.begin_turn()  # turn 1 → p1
    assert state.active_player.id == "p1"

    src = GameObject(Card(id="tw", name="Time Walk", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    build_effects([EffectSpec("take_extra_turn", {})], src)[0].apply(
        GameContext(state, eng.rules), None
    )

    # RULE 500.7: begin_turn takes p1's queued extra turn instead of
    # rotating to p2
    eng.begin_turn()
    assert state.active_player.id == "p1"
    assert state.extra_turns == []
    eng.begin_turn()  # queue empty now → normal rotation
    assert state.active_player.id == "p2"
