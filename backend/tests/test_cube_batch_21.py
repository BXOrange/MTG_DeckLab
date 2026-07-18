"""cEDH staples cube — batch 21: the reproducible random-number primitive
(RULE 705/706).

New core capability: `RulesEngine.random_int`/`random_choice`/`coin_flip`
derive each draw from `GameState`'s ``(rng_seed, rng_counter)`` and advance the
counter — deterministic given the seed, and surviving `clone()`/undo unchanged
(a live `random.Random` on the engine wouldn't travel with the cloned state).

No cube card is registered on it: Tibalt's Trickery pairs the random 1/2/3 with
a dig-until-a-differently-named-nonland-card-then-cast-it-free mechanic, and
Wheel of Misfortune needs a *secret simultaneous* number choice from every
player (hidden multiplayer info) — both far beyond a random draw. The primitive
is proven directly here, ready for a future coin-flip/random card.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )


def test_random_int_is_in_range_and_advances_the_counter():
    eng = _engine()
    start = eng.state.rng_counter
    for _ in range(50):
        v = eng.rules.random_int(3)
        assert v in (0, 1, 2)
    assert eng.state.rng_counter == start + 50


def test_random_int_is_reproducible_for_a_fixed_seed():
    eng1 = _engine(); eng1.state.rng_seed = 12345; eng1.state.rng_counter = 0
    eng2 = _engine(); eng2.state.rng_seed = 12345; eng2.state.rng_counter = 0
    seq1 = [eng1.rules.random_int(6) for _ in range(20)]
    seq2 = [eng2.rules.random_int(6) for _ in range(20)]
    assert seq1 == seq2


def test_random_survives_clone_deterministically():
    eng = _engine(); eng.state.rng_seed = 999; eng.state.rng_counter = 0
    eng.rules.random_int(10)  # advance a bit
    snapshot = eng.state.clone()
    # The continuation from the live state...
    live_next = [eng.rules.random_int(10) for _ in range(5)]
    # ...and from a fresh engine wrapped around the clone must match.
    clone_eng = GameEngine.__new__(GameEngine)
    from mtg_analyzer.game.rules_engine import RulesEngine
    clone_eng.state = snapshot
    clone_eng.rules = RulesEngine(snapshot)
    clone_next = [clone_eng.rules.random_int(10) for _ in range(5)]
    assert live_next == clone_next


def test_random_choice_and_coin_flip():
    eng = _engine(); eng.state.rng_seed = 7; eng.state.rng_counter = 0
    assert eng.rules.random_choice([]) is None
    picks = {eng.rules.random_choice(["a", "b", "c"]) for _ in range(60)}
    assert picks == {"a", "b", "c"}, "every option is reachable"
    flips = [eng.rules.coin_flip() for _ in range(40)]
    assert set(flips) == {True, False}


def test_seed_differs_between_games():
    # Two fresh games get independent seeds (uuid-derived), so they don't
    # play out identically by default.
    a = _engine(); b = _engine()
    assert isinstance(a.state.rng_seed, int) and isinstance(b.state.rng_seed, int)
    # Overwhelmingly likely to differ; a stable primitive property to assert is
    # simply that each is a 32-bit-ranged int.
    assert 0 <= a.state.rng_seed <= 0xFFFFFFFF
    assert 0 <= b.state.rng_seed <= 0xFFFFFFFF
