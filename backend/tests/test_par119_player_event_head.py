"""PAR-119 — player-event heads as one grammar: actor scope × verb × tails.

"Whenever `<a player | an opponent | you>` cycles a card / loses life / plays a land / draws
their third card", with "during your turn" and "for the first time each turn". Parse tests pin
the table; execute tests fire the real events and read who was allowed to trigger it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.player_event_head import parse_player_event_head

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _put
from tests import turn_history_events as history


@pytest.mark.parametrize(
    "cond, expected",
    [
        ("a player cycles a card", ("CYCLED", {"subject": "player", "scope": "any"}, {})),
        ("an opponent loses life", ("LIFE_LOST", {"subject": "player", "scope": "not_you"}, {})),
        ("you lose life during your turn", ("LIFE_LOST", {"subject": "you"}, {"phase_relation": "you"})),
        ("you gain life for the first time each turn", ("LIFE_GAINED", {"subject": "you"}, {"limit": True})),
        ("you draw your third card in a turn", ("DRAW", {"subject": "you"}, {"is_nth_draw_this_turn": 3})),
        ("a player plays a land", ("LAND_PLAYED", {"subject": "player", "scope": "any"}, {})),
    ],
)
def test_the_player_event_grammar(cond, expected):
    assert parse_player_event_head(cond) == expected


@pytest.mark.parametrize("cond", ["you frobnicate", "an opponent loses life during a full moon", "you draw two cards"])
def test_the_player_event_grammar_fails_closed(cond):
    assert parse_player_event_head(cond) is None


@pytest.mark.parametrize(
    "name",
    ["Bloodthirsty Conqueror", "Lightning Rift", "Shadowheart, Cleric of Trickery", "Sneaky Snacker",
     "Pangosaur", "Punishing Fire", "Warped Researcher", "Vampire Scrivener"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def _life(state, pid):
    return state.player_by_id(pid).life


def test_an_opponent_losing_life_drains_it_to_you_but_your_own_loss_does_not():
    engine, state = _engine()
    _put(state, "Whenever an opponent loses life, you gain that much life.", name="Conqueror",
         types="Creature — Vampire")
    mine = _life(state, "p1")
    engine.rules.lose_life(state.player_by_id("p1"), 3)
    engine.resolve_until_stable()
    assert _life(state, "p1") == mine - 3          # your own loss is not "an opponent's"
    engine.rules.lose_life(state.player_by_id("p2"), 4)
    engine.resolve_until_stable()
    assert _life(state, "p1") == mine - 3 + 4      # their 4 became your 4
    assert _life(state, "p2") == 16


def test_a_player_cycling_triggers_for_either_player():
    engine, state = _engine()
    source = _put(state, "Whenever a player cycles a card, put a +1/+1 counter on this creature.",
                  name="Champion", types="Creature — Bear")
    for actor in ("p1", "p2"):
        state.fire_event(history.GameEvent("CYCLED", controller_id=actor, player_id=actor))
        engine.resolve_until_stable()
    assert source.counters.get("+1/+1") == 2


def test_during_your_turn_gates_on_whose_turn_it_is():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "Whenever you lose life during your turn, put a +1/+1 counter on this creature.",
                  name="Scrivener", types="Creature — Vampire")
    engine.rules.lose_life(state.player_by_id("p1"), 1)      # p1 is the active player
    engine.resolve_until_stable()
    assert source.counters.get("+1/+1") == 1
    state.active_player_index = 1
    engine.rules.lose_life(state.player_by_id("p1"), 1)
    engine.resolve_until_stable()
    assert source.counters.get("+1/+1") == 1                 # not on p2's turn


def test_the_third_card_drawn_in_a_turn_fires_once():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    for i in range(6):
        p1.library.append(history.GameObject(history.Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id="p1", zone=history.Zone.LIBRARY))
    source = _put(state, "When you draw your third card in a turn, put a +1/+1 counter on this creature.",
                  name="Snacker", types="Creature — Bear")
    for _ in range(4):
        engine.rules.draw(p1, 1)
        engine.resolve_until_stable()
    assert source.counters.get("+1/+1") == 1


def test_player_damage_heads_scope_the_recipient_not_the_source():
    engine, state = _engine()
    listener = _put(state, "Whenever you're dealt damage, put a +1/+1 counter on this creature.",
                    name="Recipient", types="Creature — Bear")
    dealer = _put(state, "", name="Dealer", owner="p2")
    engine.rules.deal_damage(state.player_by_id("p1"), 3, source=dealer)
    engine.resolve_until_stable()
    assert listener.counters.get("+1/+1") == 1
    # The same source hitting a creature or the other player doesn't trigger it.
    engine.rules.deal_damage(dealer, 1, source=dealer)
    engine.rules.deal_damage(state.player_by_id("p2"), 1, source=dealer)
    engine.resolve_until_stable()
    assert listener.counters.get("+1/+1") == 1


def test_opponent_combat_damage_head_checks_player_and_damage_kind():
    engine, state = _engine()
    listener = _put(state, "Whenever an opponent is dealt combat damage, you gain that much life.",
                    name="Watcher", types="Enchantment")
    dealer = _put(state, "", name="Dealer")
    engine.rules.deal_damage(state.player_by_id("p2"), 3, source=dealer, combat=True)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 23
    engine.rules.deal_damage(state.player_by_id("p2"), 2, source=dealer, combat=False)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 23


def test_proliferating_twice_triggers_twice_even_when_no_counters_exist():
    from mtg_analyzer.game.effects.core import ProliferateEffect

    engine, state = _engine()
    listener = _put(state, "Whenever you proliferate, you gain 1 life.", types="Enchantment")
    theirs = _put(state, "", name="Their Source", owner="p2")
    ProliferateEffect(times=2, source=listener).apply(engine.rules.context)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 22
    ProliferateEffect(source=theirs).apply(engine.rules.context)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 22


def test_tapping_a_land_for_mana_uses_the_existing_mana_event():
    engine, state = _engine()
    _put(state, "Whenever an opponent taps a land for mana, you gain 1 life.", types="Enchantment")
    land = _put(state, "{T}: Add {G}.", name="Their Land", owner="p2", types="Land", is_land=True)
    engine.tap_for_mana(state.player_by_id("p2"), land)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21
    rock = _put(state, "{T}: Add {G}.", name="Their Rock", owner="p2", types="Artifact")
    engine.tap_for_mana(state.player_by_id("p2"), rock)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21


def test_draw_exclusions_reset_each_draw_step_and_only_apply_to_own_draw_step():
    engine, state = _engine()
    _put(state, "Whenever an opponent draws a card except the first two they draw in each of their draw steps, you gain 1 life.",
         name="Draw Watcher", types="Enchantment")
    p2 = state.player_by_id("p2")
    p2.library.extend(history.GameObject(history.Card(id=f"D{i}", name=f"D{i}", type_line="Land"),
                                        owner_id="p2", zone=history.Zone.LIBRARY) for i in range(12))
    state.active_player_index = 1
    state.current_step = "draw"
    state.fire_event(history.GameEvent("STEP_BEGIN", step="draw"))
    engine.rules.draw(p2, 3)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21
    # A second draw step in the same turn has its own first two draws.
    state.fire_event(history.GameEvent("STEP_BEGIN", step="draw"))
    engine.rules.draw(p2, 2)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 21
    # Drawing during somebody else's draw step never gets the exemption.
    state.active_player_index = 0
    engine.rules.draw(p2, 2)
    engine.resolve_until_stable()
    assert state.player_by_id("p1").life == 23


# ---------------------------------------------------------------------------
# "otherwise" negates the gate of the clause before it, decided once
# ---------------------------------------------------------------------------


def test_otherwise_is_one_if_else_not_a_second_gate_read_after_the_first_branch():
    # "Draw a card if you have no cards in hand. Otherwise, discard a card." Reading the hand
    # again for the second branch would see the card the first one just drew.
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [node] = parse_effect_body("draw a card if you have no cards in hand. otherwise, discard a card")
    assert node.type == "if_else"
    assert [e["type"] for e in node.params["then"]] == ["draw"]
    assert [e["type"] for e in node.params["else"]] == ["discard"]


def test_a_bare_otherwise_with_nothing_to_negate_stays_unclaimed():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body("draw a card. otherwise, discard a card") is None


def test_if_a_and_b_gates_both_effects():
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    specs = parse_effect_body("if you control a demon, each opponent loses 2 life and you gain 2 life")
    assert [s.type for s in specs] == ["lose_life", "gain_life"]
    assert all(s.condition for s in specs)


def test_the_flubs_trigger_draws_or_discards_never_both():
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    for i in range(6):
        p1.library.append(history.GameObject(history.Card(id=f"L{i}", name=f"L{i}", type_line="Land"),
                                             owner_id="p1", zone=history.Zone.LIBRARY))
    _put(state, "Whenever you play a land or cast a spell, draw a card if you have no cards in hand. "
                "Otherwise, discard a card.", name="Flubs", types="Creature — Frog")
    history_events = history  # noqa: F841
    state.fire_event(history.GameEvent("LAND_PLAYED", player_id="p1"))
    engine.resolve_until_stable()
    assert len(p1.hand) == 1                    # empty hand: drew, and did not then discard it
    state.fire_event(history.GameEvent("LAND_PLAYED", player_id="p1"))
    engine.resolve_until_stable()
    assert len(p1.hand) == 0                    # a card in hand: discarded it, drew nothing
