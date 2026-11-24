"""PAR-314: "for each time it was kicked" / "the number of times ~ was kicked" as an amount in any slot.

The measure is `continuous.count_selector`'s ``source_kicker_count`` (RULE 702.33d/702.33e, Multikicker): the
payment count recorded at cast on the object the ability belongs to. Parse tests pin the shared amount tables;
the engine tests resolve real spells and ETB triggers with Multikicker paid 0, 1 and 3 times, a copy of a kicked
spell (RULE 707.10), and a permanent that re-enters with nothing recorded (RULE 400.7).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

KICKER_COUNT_SELECTOR = "source_kicker_count"
KICKED_AMOUNT = {"kind": "count_selector", "selector": KICKER_COUNT_SELECTOR}

WOLFBRIAR = (
    "Multikicker {G} (You may pay an additional {G} any number of times as you cast this spell.)\n"
    "When this creature enters, create a 2/2 green Wolf creature token for each time it was kicked."
)
CONTORTION = (
    "Multikicker {1} (You may pay an additional {1} any number of times as you cast this spell.)\n"
    "You gain 2 life for each time Contortion Test was kicked."
)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _in_hand(eng, name, type_line, oracle):
    creature = "Creature" in type_line
    card = Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}", converted_mana_cost=1,
                is_creature=creature, is_instant=type_line == "Instant", power=2 if creature else None, toughness=2 if creature else None,
                oracle_text=oracle)
    card.keywords = ["Multikicker"]
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    eng.state.players[0].hand.append(obj)
    return obj


def _cast(eng, obj, kicked, color="G"):
    p1 = eng.state.players[0]
    # One Multikicker payment of ``color`` per kick plus the base {1}.
    p1.mana_pool.add_many({"C": 1, color: kicked} if kicked else {"C": 1})
    return eng.cast_spell(p1, obj, kicked=kicked)


def _target_opponent(eng):
    """Answer the enters trigger's "target player / opponent" prompt with p2, then let the stack resolve."""
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()


def _wolves(eng):
    return [o for o in eng.state.battlefield if o.is_token and o.name == "Wolf"]


# -- parse: the one measure reaches every amount slot -------------------------------------------------------------


@pytest.mark.parametrize("clause", [
    "you gain 2 life for each time ~ was kicked",
    "target opponent discards a card for each time it was kicked",
    "create a 2/2 green wolf creature token for each time it was kicked",
    "draw a card for each time ~ was kicked",
    "~ deals damage to target player or planeswalker equal to twice the number of times it was kicked",
])
def test_every_amount_slot_binds_the_kicker_count(clause):
    specs = parse_effect_body(clause)
    assert specs, clause
    assert KICKER_COUNT_SELECTOR in repr([s.to_dict() for s in specs])


def test_a_different_kicker_phrase_stays_unclaimed():
    assert parse_effect_body("you gain 2 life for each time it was cast") is None


# -- engine: the reader -------------------------------------------------------------------------------------------


def test_reader_is_zero_without_a_recorded_count_or_source():
    eng = _engine()
    obj = _in_hand(eng, "Wolfbriar Test", "Creature — Elemental", WOLFBRIAR)
    assert count_selector(eng.state, "p1", KICKER_COUNT_SELECTOR, source=obj) == 0
    assert count_selector(eng.state, "p1", KICKER_COUNT_SELECTOR, source=None) == 0
    obj.kicker_count = -4  # clamped, never negative
    assert count_selector(eng.state, "p1", KICKER_COUNT_SELECTOR, source=obj) == 0


@pytest.mark.parametrize("kicked", [0, 1, 3])
def test_etb_trigger_reads_the_permanents_count(kicked):
    eng = _engine()
    obj = _in_hand(eng, "Wolfbriar Test", "Creature — Elemental", WOLFBRIAR)
    _cast(eng, obj, kicked)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD
    assert obj.kicker_count == kicked
    assert len(_wolves(eng)) == kicked


def test_permanent_reentering_without_a_cast_has_count_zero():
    eng = _engine()
    obj = _in_hand(eng, "Wolfbriar Test", "Creature — Elemental", WOLFBRIAR)
    _cast(eng, obj, 3)
    eng.resolve_until_stable()
    assert len(_wolves(eng)) == 3
    # RULE 400.7: it dies and is returned as a new object that was never cast, so nothing is recorded and its
    # enters trigger makes no Wolf.
    eng.rules.put_into_graveyard(obj)
    assert obj.zone == Zone.GRAVEYARD
    specs = parse_effect_body("return target creature card from your graveyard to the battlefield")
    _apply_effects_partitioned(build_effects(specs, obj), eng.rules.context, [obj], None, source=obj)
    eng.resolve_until_stable()
    assert obj.zone == Zone.BATTLEFIELD and obj.kicker_count == 0
    assert len(_wolves(eng)) == 3  # no new Wolves


@pytest.mark.parametrize("kicked", [0, 1, 3])
def test_spell_effect_reads_the_spells_count(kicked):
    eng = _engine()
    spell = _in_hand(eng, "Contortion Test", "Instant", CONTORTION)
    _cast(eng, spell, kicked)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == 20 + 2 * kicked


def test_a_copy_of_a_kicked_spell_keeps_the_count():
    eng = _engine()
    spell = _in_hand(eng, "Contortion Test", "Instant", CONTORTION)
    item = _cast(eng, spell, 3)
    [copy_item] = eng.rules.copy_spell(item, "p2")
    assert copy_item.obj.kicker_count == 3  # RULE 707.10
    eng.resolve_until_stable()
    # Original (p1) and copy (p2) each gain from the *spell's* recorded count.
    assert eng.state.player_by_id("p1").life == 20 + 2 * 3
    assert eng.state.player_by_id("p2").life == 20 + 2 * 3


DEATHFORGE = (
    "Multikicker {R} (You may pay an additional {R} any number of times as you cast this spell.)\n"
    "When this creature enters, it deals damage to target player or planeswalker equal to twice the number of "
    "times it was kicked."
)
BLOODHUSK = (
    "Multikicker {B} (You may pay an additional {B} any number of times as you cast this spell.)\n"
    "When this creature enters, target opponent discards a card for each time it was kicked."
)


@pytest.mark.parametrize("kicked", [0, 1, 3])
def test_etb_damage_is_twice_the_kicker_count(kicked):
    eng = _engine()
    obj = _in_hand(eng, "Deathforge Test", "Creature — Shaman", DEATHFORGE)
    _cast(eng, obj, kicked, "R")
    eng.resolve_until_stable()
    if kicked:
        _target_opponent(eng)
    assert eng.state.player_by_id("p2").life == 20 - 2 * kicked


@pytest.mark.parametrize("kicked", [0, 1, 3])
def test_etb_discard_is_one_card_per_kick(kicked):
    eng = _engine()
    opponent = eng.state.player_by_id("p2")
    for i in range(4):
        card = Card(id=f"H{i}", name=f"H{i}", type_line="Instant")
        opponent.hand.append(GameObject(card, owner_id="p2", zone=Zone.HAND))
    obj = _in_hand(eng, "Bloodhusk Test", "Creature — Vampire", BLOODHUSK)
    _cast(eng, obj, kicked, "B")
    eng.resolve_until_stable()
    if eng.state.pending_choice is not None and eng.state.pending_choice["kind"] == "trigger_target":
        _target_opponent(eng)
    while eng.state.pending_choice is not None:  # the opponent picks which card to discard
        eng.resolve_pending_choice(eng.state.pending_choice["options"][0].get("instance_id")
                                   or eng.state.pending_choice["options"][0]["id"])
        eng.resolve_until_stable()
    assert len(opponent.hand) == 4 - kicked
