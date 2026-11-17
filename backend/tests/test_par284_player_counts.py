"""PAR-284 milestone 17: counts of players satisfying a per-player predicate (RULE 102.2, 608.2h).

"for each opponent who controls fewer creatures than you", "the number of opponents with 4 or more cards in hand",
"for each opponent who was dealt damage this turn" are one selector, ``{"players": scope, "where": predicate}``
(`game/player_counts.players_matching_count`), read through every amount slot by `count_phrase.parse_count_phrase`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_amount_phrase, parse_count_phrase
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_this_way_windows import _card, _cast, _creature


def _three_player_engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cy", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _fill_hand(player, n):
    for i in range(n):
        player.hand.append(GameObject(_card(f"H{player.id}{i}", "Instant"), owner_id=player.id, zone=Zone.HAND))


def _land(eng, name, owner):
    obj = GameObject(_card(name, "Land"), owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


@pytest.mark.parametrize("phrase, where", [
    ("opponents who control more lands than you", {"kind": "controls_compared", "compare": "more"}),
    ("opponent who controls fewer creatures than you", {"kind": "controls_compared", "compare": "fewer"}),
    ("your opponents with 4 or more cards in hand", {"kind": "hand_size", "min": 4}),
    ("opponents who have 3 or more poison counters", {"kind": "counters", "counter": "poison", "min": 3}),
    ("opponent who drew 2 or more cards this turn", {"kind": "drew_this_turn", "min": 2}),
    ("opponent who had 2 or more lands enter the battlefield under their control this turn",
     {"kind": "lands_entered_this_turn", "min": 2}),
    ("opponent who was dealt damage this turn", {"kind": "dealt_damage_this_turn", "combat": False}),
    ("player who was dealt combat damage this turn", {"kind": "dealt_damage_this_turn", "combat": True}),
])
def test_player_count_phrases_parse(phrase, where):
    selector = parse_count_phrase(phrase)
    assert selector is not None and selector["where"].items() >= where.items()
    assert parse_amount_phrase(f"the number of {phrase}") == selector


@pytest.mark.parametrize("phrase", [
    "players who control more lands than you",  # "than you" only reads against an opponent scope
    "opponents who control more experience counters than you",  # not a battlefield selector
    "opponents who were dealt damage by a Goblin this turn",
])
def test_unknown_player_predicates_fail_closed(phrase):
    assert parse_count_phrase(phrase) is None


def test_hand_size_and_poison_predicates_count_only_opponents():
    eng = _three_player_engine()
    p1, p2, p3 = eng.state.players
    _fill_hand(p1, 5)  # the controller never counts for "opponents"
    _fill_hand(p2, 4)
    _fill_hand(p3, 3)
    p2.poison, p3.poison = 3, 2
    hand = parse_count_phrase("your opponents with 4 or more cards in hand")
    poison = parse_count_phrase("opponents who have 3 or more poison counters")
    assert count_selector(eng.state, "p1", hand) == 1
    assert count_selector(eng.state, "p1", poison) == 1
    p3.poison = 3
    assert count_selector(eng.state, "p1", poison) == 2
    assert count_selector(eng.state, "p2", poison) == 1  # p3 only: the other opponent of p2 that has 3 poison


def test_comparative_control_predicates_read_the_controller_against_each_opponent():
    eng = _three_player_engine()
    for i in range(2):
        _land(eng, f"A{i}", "p1")
    for i in range(3):
        _land(eng, f"B{i}", "p2")
    _land(eng, "C0", "p3")
    more = parse_count_phrase("opponents who control more lands than you")
    fewer = parse_count_phrase("opponents who control fewer lands than you")
    assert count_selector(eng.state, "p1", more) == 1
    assert count_selector(eng.state, "p1", fewer) == 1
    assert count_selector(eng.state, "p2", more) == 0


def test_damage_predicate_distinguishes_combat_and_any_damage_and_ignores_zero():
    eng = _three_player_engine()
    p1, p2, p3 = eng.state.players
    src = _creature(eng, "Hitter", "p1", 2)
    eng.rules.deal_damage(p2, 2, source=src, combat=True)
    eng.rules.deal_damage(p3, 1, source=src, combat=False)
    any_damage = parse_count_phrase("opponent who was dealt damage this turn")
    combat = parse_count_phrase("opponent who was dealt combat damage this turn")
    assert count_selector(eng.state, "p1", any_damage) == 2
    assert count_selector(eng.state, "p1", combat) == 1


def test_drew_and_land_entry_predicates_read_this_turns_history():
    eng = _three_player_engine()
    p1, p2, p3 = eng.state.players
    for player in (p2, p3):
        for i in range(3):
            player.library.append(GameObject(_card(f"L{player.id}{i}", "Instant"), owner_id=player.id, zone=Zone.LIBRARY))
    eng.rules.draw(p2, 2)
    eng.rules.draw(p3, 1)
    drew = parse_count_phrase("opponent who drew 2 or more cards this turn")
    assert count_selector(eng.state, "p1", drew) == 1
    for who, lands in (("p2", 2), ("p3", 1)):
        for _ in range(lands):
            eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=who, object_types=["land"]))
    entered = parse_count_phrase("opponent who had 2 or more lands enter the battlefield under their control this turn")
    assert count_selector(eng.state, "p1", entered) == 1


@pytest.mark.parametrize("oracle, type_line", [
    ("When this creature enters, draw a card for each opponent who controls fewer creatures than you.", "Creature — Bear"),
    ("At the beginning of your upkeep, create X 2/2 green Wolf creature tokens, where X is the number of your opponents "
     "with four or more cards in hand.", "Enchantment"),
    ("At the beginning of your end step, put a +1/+1 counter on this creature for each opponent who was dealt damage this "
     "turn.", "Creature — Bear"),
    ("Target player draws a card for each basic land type among lands they control.", "Sorcery"),
    ("{3}, {T}: Draw a card for each experience counter you have, then discard a card.", "Creature — Bear"),
    ("At the beginning of your upkeep, create a 1/1 Insect creature token for each poison counter your opponents have.",
     "Creature — Bear"),
])
def test_player_count_hosts_are_modeled(oracle, type_line):
    card = _card("Probe", type_line, oracle, is_creature=type_line.startswith("Creature"), is_sorcery=type_line == "Sorcery")
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_draw_a_card_for_each_opponent_with_fewer_creatures_resolves_in_the_engine():
    eng = _three_player_engine()
    p1 = eng.state.players[0]
    for i in range(3):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    for i in range(2):
        _creature(eng, f"Mine{i}", "p1", 1)
    _creature(eng, "Theirs", "p2", 1)  # p2 has fewer than p1's two; p3 has none: both count
    _cast(eng, "Draw a card for each opponent who controls fewer creatures than you.")
    assert len(p1.hand) == 2


def test_energy_counter_total_reads_through_the_named_player_counter_table():
    eng = _three_player_engine()
    p1 = eng.state.players[0]
    p1.counters["energy"] = 3
    p1.counters["experience"] = 2
    assert count_selector(eng.state, "p1", "energy_counters_you_have") == 3
    assert count_selector(eng.state, "p1", "experience_counters_you_have") == 2
    assert parse_amount_phrase("the amount of {e} you have") == "energy_counters_you_have"


def test_tokens_for_each_opponent_with_more_lands_resolve_in_the_engine():
    eng = _three_player_engine()
    _land(eng, "Mine", "p1")
    for i in range(2):
        _land(eng, f"B{i}", "p2")
    _land(eng, "C0", "p3")  # equal to p1's one land: does not count
    before = len(eng.state.battlefield)
    _cast(eng, "Create X 1/1 white Spirit creature tokens with flying, where X is the number of opponents who control "
               "more lands than you.")
    assert len(eng.state.battlefield) - before == 1


def test_domain_of_the_target_player_resolves_with_that_players_lands():
    eng = _three_player_engine()
    p1, p2 = eng.state.players[:2]
    for i in range(3):
        p2.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p2", zone=Zone.LIBRARY))
    for name, subtype in (("Isle", "Island"), ("Wood", "Forest"), ("Isle2", "Island")):
        land = GameObject(_card(name, f"Basic Land — {subtype}", is_land=True), owner_id="p2",
                          zone=Zone.BATTLEFIELD)
        land.controller_id = "p2"
        eng.state.battlefield.append(land)
    card = _card("Allied", "Sorcery", "Target player draws a card for each basic land type among lands they control.",
                 is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj, targets=[p2])
    eng.resolve_until_stable()
    assert len(p2.hand) == 2 and not p1.hand  # Island + Forest, counted as the target player; the caster drew nothing
