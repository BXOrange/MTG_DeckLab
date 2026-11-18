"""PAR-284 milestone 21: a difference of two measured counts (RULE 107.1b: a negative X counts as 0).

"where X is the number of cards in your hand minus the number of cards in that player's hand" (Bulwark, Dark
Suspicions) and "where X is 7 minus the number of cards in that creature's controller's hand" (Flunk): the minuend
amount carries the subtrahend amount as ``minus`` (`effect_amounts.amount_of`), floored at ``minimum`` 0.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError
from tests.test_par284_counter_amounts import _board_creature
from tests.test_par284_event_amounts import _board
from tests.test_par284_history_amounts import _spell
from tests.test_par284_this_way_windows import _card, _engine

BULWARK = ("At the beginning of your upkeep, ~ deals X damage to target opponent, where X is the number of cards in "
           "your hand minus the number of cards in that player's hand.")
SUSPICIONS = ("At the beginning of each opponent's upkeep, that player loses X life, where X is the number of cards in "
              "that player's hand minus the number of cards in your hand.")
FLUNK = "Target creature gets -X/-X until end of turn, where X is 7 minus the number of cards in that creature's controller's hand."


def _hand(player, n):
    for i in range(n):
        player.hand.append(GameObject(_card(f"H{player.id}{i}", "Instant"), owner_id=player.id, zone=Zone.HAND))


@pytest.mark.parametrize("type_line, oracle", [("Enchantment", BULWARK), ("Enchantment", SUSPICIONS), ("Sorcery", FLUNK)])
def test_difference_cards_are_modeled(type_line, oracle):
    assert parse_oracle(_card("Diff", type_line, oracle, is_sorcery=type_line == "Sorcery")).modeled


@pytest.mark.parametrize("phrase", [
    # a second subtrahend, or arithmetic already on a side, is not one difference
    "~ deals x damage to target opponent, where x is the number of cards in your hand minus the number of cards in that player's hand minus 1",
    # "that player" on the subtrahend only has no single holder
    "that player loses x life, where x is the number of cards in your hand minus the number of cards in that player's hand",
    # the creature's controller is only named by a body that targets exactly one creature
    "target player loses x life, where x is 7 minus the number of cards in that creature's controller's hand",
])
def test_unsafe_differences_stay_unclaimed(phrase):
    assert parse_effect_body(phrase) is None


def test_subtrahend_amount_is_validated_recursively():
    effects = parse_effect_body("~ deals x damage to target opponent, where x is the number of cards in your hand "
                                "minus the number of cards in that player's hand")
    assert effects[0].params["amount"]["minus"]["of"] == "target"
    bad = {"kind": "count_selector", "selector": {"zone": "hand", "of": "you"}, "minus": {"selector": "x"}}
    with pytest.raises(SpecValidationError):
        AbilitySpec._validate_amount_spec(bad)


def test_bulwark_deals_the_hand_size_difference_each_upkeep():
    eng = _engine()
    p1, p2 = eng.state.players
    _board(eng, BULWARK, name="Bulwark", type_line="Enchantment")
    _hand(p1, 5)
    _hand(p2, 2)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    eng.resolve_pending_choice("p2")  # the trigger's "target opponent"
    eng.resolve_until_stable()
    assert p2.life == 20 - 3


def test_bulwark_floors_a_negative_difference_at_zero():
    eng = _engine()
    p1, p2 = eng.state.players
    _board(eng, BULWARK, name="Bulwark", type_line="Enchantment")
    _hand(p1, 1)
    _hand(p2, 4)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    assert p2.life == 20 and p1.life == 20


def test_dark_suspicions_reads_the_step_players_hand_against_the_controllers():
    eng = _engine()
    p1, p2 = eng.state.players
    eng.state.active_player_index = 1  # RULE 503.1: p2's upkeep, which the opponent-upkeep head watches
    _board(eng, SUSPICIONS, name="Dark Suspicions", type_line="Enchantment")
    _hand(p1, 2)
    _hand(p2, 6)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p2", controller_id="p2"))
    eng.resolve_until_stable()
    assert p2.life == 20 - 4 and p1.life == 20


def test_flunk_shrinks_by_seven_minus_the_controllers_hand():
    eng = _engine()
    p2 = eng.state.players[1]
    victim = _board_creature(eng, _card("Big", "Creature — Bear", is_creature=True, power=9, toughness=9), "p2")
    _hand(p2, 3)
    _spell(eng, "Flunk", FLUNK, targets=[victim])
    assert victim.toughness == 9 - (7 - 3)
