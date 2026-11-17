"""PAR-284: "for each / the number of <object> that <died|...> this turn" and "<object> you've <cast|discarded|
sacrificed> this turn" as an amount in any slot.

The measure is the shared ``event_count`` amount over the turn's event log (RULE 608.2h: re-measured when the ability
resolves), built from the same trigger-shaped predicate the "if a creature died this turn" conditions read, so
"for each Zubera that died this turn" means what "whenever a Zubera dies" means. Parse tests pin the grammar and what
stays unclaimed; engine tests resolve real wordings against a turn log.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.history_phrase import parse_history_count
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.game.binding.core import attach_to_object


def _event_counts(clause):
    specs = parse_effect_body(clause)
    assert specs, clause
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("kind") == "event_count":
                found.append(node["trigger"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk([s.to_dict() for s in specs])
    return found


# -- parse -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, event, controller, filt", [
    ("creature that died this turn", "DIES", "any", {"card_type": "creature"}),
    ("zubera that died this turn", "DIES", "any", {"subtype": "zubera"}),
    ("creature that died under your control this turn", "DIES", "you", {"card_type": "creature"}),
    ("the number of nontoken creatures that died this turn", "DIES", "any", {"nontoken": True, "card_type": "creature"}),
    ("the number of foods you've sacrificed this turn", "SACRIFICE", "you", {"subtype": "food"}),
])
def test_object_history_phrases_become_the_trigger_predicate(phrase, event, controller, filt):
    trigger = parse_history_count(phrase)
    assert trigger["event"] == event
    assert trigger["condition"]["controller"] == controller
    assert trigger["condition"].get("filter") == filt


def test_put_into_your_graveyard_is_the_owner_scoped_dies_head():
    trigger = parse_history_count("creature put into your graveyard from the battlefield this turn")
    assert trigger["event"] == "DIES" and trigger["condition"]["owner"] == "you"


@pytest.mark.parametrize("clause, event", [
    ("target opponent discards a card for each zubera that died this turn", "DIES"),
    ("draw a card for each card you've discarded this turn", "DISCARD_CARD"),
    ("you gain 1 life for each spell you've cast this turn", "SPELL_CAST"),
])
def test_clauses_bind_the_event_count(clause, event):
    [trigger] = _event_counts(clause)
    assert trigger["event"] == event


@pytest.mark.parametrize("phrase", [
    "creature that died",                    # no turn window: not a turn-log count
    "creature that will die this turn",      # not a past event
    "spell you've drawn this turn",          # a verb the history grammar has no event for
    "tapped creature that died this turn",   # live-state filter: the snapshot does not say it was tapped
])
def test_other_phrases_stay_unclaimed(phrase):
    assert parse_history_count(phrase) is None


# -- engine ------------------------------------------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _creature(eng, name, owner="p1", subtype="Bear"):
    card = Card(id=name, name=name, type_line=f"Creature — {subtype}", mana_cost_string="{1}", converted_mana_cost=1,
                is_creature=True, power=2, toughness=2)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


def _spell(eng, oracle):
    card = Card(id="Test Spell", name="Test Spell", type_line="Sorcery", mana_cost_string="{1}", converted_mana_cost=1,
                is_sorcery=True, oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    eng.state.players[0].hand.append(obj)
    return obj


def _library(eng, n=6):
    for i in range(n):
        eng.state.players[0].library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Instant"),
                                                       owner_id="p1", zone=Zone.LIBRARY))


def test_draws_one_card_per_creature_that_died_this_turn():
    eng = _engine()
    _library(eng)
    doomed = [_creature(eng, f"Doomed{i}", owner="p2") for i in range(2)]
    for obj in doomed:
        eng.rules.destroy(obj)
    spell = _spell(eng, "Draw a card for each creature that died this turn.")
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 1})
    before = len(p1.hand)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len(p1.hand) == before - 1 + 2  # the spell left the hand; two creatures died


def test_under_your_control_ignores_the_opponents_deaths():
    eng = _engine()
    _library(eng)
    eng.rules.destroy(_creature(eng, "Mine", owner="p1"))
    eng.rules.destroy(_creature(eng, "Theirs", owner="p2"))
    spell = _spell(eng, "Draw a card for each creature that died under your control this turn.")
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 1})
    before = len(p1.hand)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len(p1.hand) == before - 1 + 1


def test_subtype_count_only_counts_that_subtype():
    eng = _engine()
    _library(eng)
    eng.rules.destroy(_creature(eng, "Zubera A", owner="p2", subtype="Zubera Spirit"))
    eng.rules.destroy(_creature(eng, "Bear B", owner="p2", subtype="Bear"))
    spell = _spell(eng, "Draw a card for each zubera that died this turn.")
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 1})
    before = len(p1.hand)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len(p1.hand) == before - 1 + 1


# -- a count phrase that names its own target player (RULE 115.1) -----------------------------------------------


@pytest.mark.parametrize("clause, noun_filter, multiplier", [
    ("you gain 2 life for each mountain target opponent controls", {"subtype": "mountain"}, 2),
    ("draw a card for each tapped creature target player controls", {"tapped": True, "card_type": "creature"}, None),
])
def test_for_each_target_player_phrase_announces_that_player(clause, noun_filter, multiplier):
    specs = parse_effect_body(clause)
    assert [s.type for s in specs] == ["choose_targets", "bind"]
    amount = specs[1].params["amount"]
    assert amount["of"] == "target" and amount["selector"]["filter"] == noun_filter
    assert amount.get("multiply") == multiplier


def test_a_body_with_its_own_target_leaves_the_target_player_phrase_unclaimed():
    assert parse_effect_body("target creature gets -1/-1 until end of turn for each creature target opponent controls") is None


def test_gain_life_per_card_in_the_targeted_opponents_hand():
    eng = _engine()
    opponent = eng.state.player_by_id("p2")
    for i in range(3):
        opponent.hand.append(GameObject(Card(id=f"H{i}", name=f"H{i}", type_line="Instant"), owner_id="p2", zone=Zone.HAND))
    p1 = eng.state.players[0]
    # The same phrase counted for the other player would read 0: p1's own hand is empty.
    spell = _spell(eng, "You gain 1 life for each card in target opponent's hand.")
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell, targets=[opponent])
    eng.resolve_until_stable()
    assert p1.life == 20 + 3


def test_life_per_mountain_target_opponent_controls():
    eng = _engine()
    for i in range(2):
        mountain = _creature(eng, f"Mountain{i}", owner="p2", subtype="Mountain")
        mountain.card.is_creature = False
    spell = _spell(eng, "You gain 2 life for each Mountain target opponent controls.")
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, spell, targets=[eng.state.player_by_id("p2")])
    eng.resolve_until_stable()
    assert p1.life == 20 + 4
