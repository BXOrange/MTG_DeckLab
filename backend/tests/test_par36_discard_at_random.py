"""PAR-36 — "…discards a card at random." (RULE 701.8d).

`DiscardEffect` gained a `random` param routing to the new
`RulesEngine.discard_random` (uniform pick from the hand, no chooser —
distinct from the interactive `discard_choice` and from `discard`'s
auto-pick-the-last), and the `discard` / `that_player_discards` handlers
gained an optional `(?P<at_random> at random)` tail. Real cards: Hymn to
Tourach / Hypnotic Specter / Black Cat / Stupor / Mind Knives (targeted),
Burning Inquiry / Goblin Lore (each player), Bottomless Pit (each player's
upkeep → that player).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _fill_hand(state, pid, n):
    p = state.player_by_id(pid)
    for i in range(n):
        p.hand.append(GameObject(Card(id=f"{pid}h{i}", name=f"Card {i}", type_line="Sorcery"),
                                 owner_id=pid, zone=Zone.HAND))
    return p


# --- parse -----------------------------------------------------------------


def test_discard_at_random_parses():
    assert parse_effect_body("target opponent discards a card at random") == [
        EffectSpec("discard", {"count": 1, "target_kind": "player", "random": True})
    ]
    assert parse_effect_body("target player discards 2 cards at random") == [
        EffectSpec("discard", {"count": 2, "target_kind": "player", "random": True})
    ]


def test_each_player_discard_at_random_parses():
    assert parse_effect_body("each player discards 3 cards at random") == [
        EffectSpec("discard", {"count": 3, "scope": "each_player", "random": True})
    ]


def test_plain_discard_still_has_no_random_flag():
    assert parse_effect_body("target opponent discards a card") == [
        EffectSpec("discard", {"count": 1, "target_kind": "player"})
    ]


def test_that_player_discards_at_random_parses():
    assert parse_effect_body("that player discards a card at random") == [
        EffectSpec("discard", {"count": 1, "previous_subject": True, "random": True})
    ]


def test_real_cards_modeled():
    hymn = Card(id="htt", name="Hymn to Tourach", type_line="Sorcery", is_sorcery=True,
                oracle_text="Target player discards two cards at random.")
    assert parse_oracle(hymn).coverage != UNMODELED, parse_oracle(hymn).unclaimed

    inquiry = Card(id="bi", name="Burning Inquiry", type_line="Sorcery", is_sorcery=True,
                   oracle_text="Each player draws three cards, then discards three cards at random.")
    assert parse_oracle(inquiry).coverage != UNMODELED, parse_oracle(inquiry).unclaimed

    black_cat = Card(id="bc", name="Black Cat", type_line="Creature — Cat", is_creature=True,
                     power=1, toughness=1,
                     oracle_text="When Black Cat dies, target opponent discards a card at random.")
    assert parse_oracle(black_cat).coverage != UNMODELED, parse_oracle(black_cat).unclaimed


# --- execute -------------------------------------------------------------------


def test_discard_random_removes_a_card_without_a_pending_choice():
    eng = _engine()
    state = eng.state
    _fill_hand(state, "p2", 4)
    src = GameObject(Card(id="src", name="Hymn", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("discard", {
        "count": 2, "target_kind": "player", "random": True,
    })], src)[0].apply(GameContext(state, eng.rules), [state.player_by_id("p2")])

    assert len(state.player_by_id("p2").hand) == 2
    assert len(state.player_by_id("p2").graveyard) == 2
    assert state.pending_choice is None  # random = no chooser


def test_discard_random_is_a_noop_on_an_empty_hand():
    eng = _engine()
    state = eng.state
    src = GameObject(Card(id="src", name="Hymn", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("discard", {
        "count": 3, "target_kind": "player", "random": True,
    })], src)[0].apply(GameContext(state, eng.rules), [state.player_by_id("p2")])

    assert state.player_by_id("p2").graveyard == []


def test_discard_random_picks_uniformly_over_many_trials():
    # Not a strict statistical test — just that it doesn't always take the
    # same slot (which `discard`'s `.pop()` would).
    seen_first_card_gone = 0
    for _ in range(40):
        eng = _engine()
        state = eng.state
        p = _fill_hand(state, "p2", 5)
        first_id = p.hand[0].instance_id
        src = GameObject(Card(id="s", name="s", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK)
        src.controller_id = "p1"
        build_effects([EffectSpec("discard", {
            "count": 1, "target_kind": "player", "random": True,
        })], src)[0].apply(GameContext(state, eng.rules), [state.player_by_id("p2")])
        if all(o.instance_id != first_id for o in state.player_by_id("p2").hand):
            seen_first_card_gone += 1
    assert 0 < seen_first_card_gone < 40  # neither never nor always the first slot
