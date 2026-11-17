"""PAR-284: "<noun> <discarded|sacrificed> this way" tallies as an amount in any slot (RULE 608.2c).

A discard / sacrifice can pause for the affected player's answer, so its tally is read from the `mark_event_log`
window (`effect_amounts.THIS_WAY_EVENTS`). The body-level pass `open_this_way_window` opens that window in front of the
instruction the amount measures, and refuses a body with no such instruction (an additional cost's sacrifice happened
at cast time, before any window).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _types(specs):
    return [s.type for s in specs]


def _amounts(specs):
    return [s.params["amount"] for s in specs if s.type == "bind"]


# -- parse -------------------------------------------------------------------------------------------------------


def test_discard_hand_then_draw_that_many_opens_the_window():
    specs = parse_effect_body("discard your hand. draw x cards, where x is the number of cards discarded this way.")
    assert _types(specs) == ["mark_event_log", "discard", "bind"]
    assert _amounts(specs) == [{"kind": "this_way_count", "pool": "discarded"}]


def test_optional_discard_is_still_the_measured_instruction():
    specs = parse_effect_body(
        "you may discard your hand. draw x cards, where x is the number of cards discarded this way.")
    assert _types(specs) == ["mark_event_log", "optional", "bind"]


def test_greatest_characteristic_over_the_pool():
    specs = parse_effect_body(
        "each player sacrifices a creature of their choice. you gain life equal to the greatest power among creatures "
        "sacrificed this way.")
    assert _amounts(specs) == [{"kind": "this_way_max", "pool": "sacrificed", "characteristic": "power", "card_type": "creature"}]
    assert specs[0].type == "mark_event_log"


def test_total_characteristic_over_the_pool():
    specs = parse_effect_body(
        "each player discards a card. you gain life equal to the total mana value of cards discarded this way.")
    assert _amounts(specs) == [{"kind": "this_way_sum", "pool": "discarded", "characteristic": "mana_value"}]


@pytest.mark.parametrize("type_line, oracle", [
    # an additional cost's sacrifice is not an instruction of this body: there is no window to read (Vicious Betrayal)
    ("Instant", "Target creature gets +2/+2 until end of turn for each creature sacrificed this way."),
    ("Sorcery", "Draw X cards, where X is the number of cards discarded this way."),
    # the later sentence's own X is not the one the earlier "where X is" defines (Balin, Loremaster)
    ("Creature — Dwarf", "Whenever ~ enters, you may discard your hand. Draw X cards, where X is the number of cards "
                         "discarded this way. If you have an enduring story, ~ deals X damage to each opponent."),
])
def test_ability_without_its_window_or_with_a_dangling_x_stays_unclaimed(type_line, oracle):
    result = parse_oracle(_card("Odd", type_line, oracle, is_sorcery=type_line == "Sorcery", is_instant=type_line == "Instant"))
    assert not result.modeled


# -- engine ------------------------------------------------------------------------------------------------------


def _card(name, type_line, oracle="", mv=1, **kw):
    return Card(id=name, name=name, type_line=type_line, mana_cost_string="{1}", converted_mana_cost=mv,
                oracle_text=oracle, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _creature(eng, name, owner, power):
    card = _card(name, "Creature — Bear", is_creature=True, power=power, toughness=power)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


def _cast(eng, oracle, *, type_line="Sorcery"):
    card = _card("Probe Spell", type_line, oracle, is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    return p1


def test_discard_hand_draws_as_many_as_were_discarded():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(3):
        p1.hand.append(GameObject(_card(f"H{i}", "Instant"), owner_id="p1", zone=Zone.HAND))
    for i in range(6):
        p1.library.append(GameObject(_card(f"L{i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    _cast(eng, "Discard your hand. Draw X cards, where X is the number of cards discarded this way.")
    # the spell itself left the hand when cast, so exactly the three cards were discarded and three drawn
    assert [c.card.name for c in p1.hand].count("Probe Spell") == 0
    assert len(p1.hand) == 3
    assert len(p1.graveyard) == 3 + 1  # the discards and the resolved spell


def test_edict_life_gain_reads_the_greatest_power_actually_sacrificed():
    eng = _engine()
    _creature(eng, "Small", "p2", 1)
    _creature(eng, "Big", "p2", 5)
    p1 = _cast(eng, "Each opponent sacrifices a creature with the greatest power among creatures they control. "
                    "You gain life equal to the greatest power among creatures sacrificed this way.")
    assert p1.life == 20 + 5


def test_nothing_sacrificed_measures_zero():
    eng = _engine()
    p1 = _cast(eng, "Each opponent sacrifices a creature with the greatest power among creatures they control. "
                    "You gain life equal to the greatest power among creatures sacrificed this way.")
    assert p1.life == 20


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Shadowgrange Archfiend", "Creature — Demon",
     "When this creature enters, each opponent sacrifices a creature with the greatest power among creatures they "
     "control. You gain life equal to the greatest power among creatures sacrificed this way."),
    ("Ill-Timed Explosion", "Sorcery",
     "Draw two cards. Then you may discard two cards. When you do, Ill-Timed Explosion deals X damage to each "
     "creature, where X is the greatest mana value among cards discarded this way."),
    ("U.S.S. Enterprise-C, Time-Tossed", "Artifact — Spacecraft",
     "When U.S.S. Enterprise-C enters or dies, you may discard your hand. If you do, draw a card for each card "
     "discarded this way."),
])
def test_real_cards_are_modeled(name, type_line, oracle):
    result = parse_oracle(_card(name, type_line, oracle, is_sorcery=type_line == "Sorcery"))
    assert result.modeled, result.unclaimed


def test_paid_discard_window_measures_the_cards_just_discarded():
    """Ill-Timed Explosion shape: the "you may discard 2 cards" payment is the measured instruction itself."""
    eng = _engine()
    p1 = eng.state.players[0]
    big = GameObject(_card("Big", "Creature — Bear", mv=5, is_creature=True, power=1, toughness=9), owner_id="p2",
                     zone=Zone.BATTLEFIELD)
    big.controller_id = "p2"
    eng.state.battlefield.append(big)
    for name, mv in (("Cheap", 1), ("Dear", 4), ("Extra", 0)):
        p1.library.append(GameObject(_card(name, "Instant", mv=mv), owner_id="p1", zone=Zone.LIBRARY))
    card = _card("Blast", "Sorcery",
                 "Draw two cards. Then you may discard two cards. When you do, ~ deals X damage to each creature, "
                 "where X is the greatest mana value among cards discarded this way.", is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    for _ in range(8):  # pay the optional discard, then pick the first offered cards
        pending = eng.state.pending_choice
        if not pending:
            break
        if pending["kind"] == "pay_cost_then":
            eng.resolve_pending_choice("pay")
        else:
            raise AssertionError(f"unscripted choice: {pending}")
        eng.resolve_until_stable()
    discarded = [c for c in p1.graveyard if c.card.name != "Blast"]
    assert len(discarded) == 2
    assert big.damage_marked == max(c.card.converted_mana_cost for c in discarded) > 0
