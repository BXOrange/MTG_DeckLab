"""PAR-284 milestone 15: turn-history and referent amounts in effect hosts (RULE 608.2h, 700.4, 903.8, 601.2i).

"for each time you've cast a commander from the command zone this game", "where X is 2 plus the number of other spells
you've cast this turn", "for each other instant and sorcery spell you've cast this turn", "for each spell you've cast
this turn from anywhere other than your hand", a 72-character "for each nontoken creature put into your graveyard from
the battlefield this turn" and "where X is the power of the creature that died"."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_counter_amounts import _board_creature
from tests.test_par284_this_way_windows import _card, _engine

COMMANDER_TOKENS = ("When this creature enters, create a 1/1 white Human Soldier creature token for each time you've "
                    "cast a commander from the command zone this game.")
SALVO = "Salvo deals X damage to target creature, where X is 2 plus the number of other spells you've cast this turn."
LOCK = "Draw a card, then draw a card for each other instant and sorcery spell you've cast this turn."
SURGE = "Draw a card for each spell you've cast this turn from anywhere other than your hand."
CALLER = ("When this creature enters, create a 2/2 green Bear creature token for each nontoken creature put into "
          "your graveyard from the battlefield this turn.")
PRESENCE = ("Whenever a creature you control dies, put X +1/+1 counters on target creature you control, where X is "
            "the power of the creature that died.")


@pytest.mark.parametrize("type_line, oracle", [
    ("Creature — Bear", COMMANDER_TOKENS), ("Instant", SALVO), ("Instant", LOCK), ("Instant", SURGE),
    ("Creature — Bear", CALLER), ("Enchantment", PRESENCE),
    ("Creature — Bear", "Whenever this creature attacks, Pirates you control get +1/+1 until end of turn for each "
                        "time you've cast your commander from the command zone this game."),
])
def test_history_amounts_are_modeled(type_line, oracle):
    creature = {"is_creature": True, "power": 1, "toughness": 1} if "Creature" in type_line else {}
    result = parse_oracle(_card("Salvo", type_line, oracle, is_instant=type_line == "Instant", **creature))
    assert result.modeled, result.unclaimed


def test_plus_head_is_a_literal_addend_over_the_count():
    [bound] = parse_effect_body(
        "~ deals x damage to target creature, where x is 2 plus the number of other spells you've cast this turn")
    assert bound.params["amount"]["plus"] == 2
    assert bound.params["amount"]["kind"] == "event_count"


@pytest.mark.parametrize("phrase", [
    "~ deals x damage to target creature, where x is 2 plus the number of cards in your hand and 1",
    "~ deals x damage to target creature, where x is 2 plus 3",
])
def test_plus_head_needs_a_counted_phrase(phrase):
    assert parse_effect_body(phrase) is None


def _spell(eng, name, oracle, type_line="Instant", targets=None, **kw):
    card = _card(name, type_line, oracle, is_instant=type_line == "Instant", is_sorcery=type_line == "Sorcery", **kw)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj, targets=targets)
    eng.resolve_until_stable()
    return obj


def _library(eng, n=6):
    p1 = eng.state.players[0]
    for i in range(n):
        p1.library.append(GameObject(_card(f"L{i}", "Land"), owner_id="p1", zone=Zone.LIBRARY))
    return p1


def test_thunder_salvo_adds_two_to_the_other_spells_cast():
    eng = _engine()
    victim = _board_creature(eng, _card("Big", "Creature — Bear", is_creature=True, power=9, toughness=9), "p2")
    _spell(eng, "Cantrip", "You gain 1 life.")
    _spell(eng, "Salvo", SALVO, targets=[victim])
    assert victim.damage_marked == 2 + 1


def test_thunder_salvo_alone_deals_the_printed_two():
    eng = _engine()
    victim = _board_creature(eng, _card("Big", "Creature — Bear", is_creature=True, power=9, toughness=9), "p2")
    _spell(eng, "Salvo", SALVO, targets=[victim])
    assert victim.damage_marked == 2


def test_lock_and_load_counts_only_other_instants_and_sorceries():
    eng = _engine()
    p1 = _library(eng)
    _spell(eng, "Cantrip", "You gain 1 life.")
    _spell(eng, "Rite", "You gain 1 life.", type_line="Sorcery")
    _spell(eng, "Lock", LOCK)
    assert len(p1.hand) == 1 + 2


def test_surge_of_brilliance_ignores_spells_cast_from_hand():
    eng = _engine()
    p1 = _library(eng)
    _spell(eng, "Cantrip", "You gain 1 life.")
    _spell(eng, "Surge", SURGE)
    assert len(p1.hand) == 0


def test_commander_cast_tally_scales_the_token_count():
    eng = _engine()
    p1 = eng.state.players[0]
    p1.commander_casts = {"c1": 2}
    card = _card("Jirina Probe", "Creature — Human", COMMANDER_TOKENS, is_creature=True, power=1, toughness=1)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(card).specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert sum(1 for o in eng.state.battlefield if o.card.name == "Human Soldier") == 2


def test_caller_of_the_claw_counts_only_nontoken_creatures_put_into_your_graveyard():
    eng = _engine()
    for name in ("A", "B"):
        eng.rules.destroy(_board_creature(eng, _card(name, "Creature — Bear", is_creature=True, power=1, toughness=1), "p1"))
    eng.rules.destroy(_board_creature(eng, _card("Theirs", "Creature — Bear", is_creature=True, power=1, toughness=1), "p2"))
    p1 = eng.state.players[0]
    card = _card("Caller Probe", "Creature — Bear", CALLER, is_creature=True, power=1, toughness=1)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(card).specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert sum(1 for o in eng.state.battlefield if o.card.name == "Bear") == 2


def test_deaths_presence_puts_the_dead_creatures_power_in_counters():
    eng = _engine()
    host = GameObject(_card("Presence", "Enchantment", PRESENCE), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(host)
    eng.state.add_to_battlefield(host)
    survivor = _board_creature(eng, _card("Survivor", "Creature — Bear", is_creature=True, power=2, toughness=2), "p1")
    victim = _board_creature(eng, _card("Victim", "Creature — Bear", is_creature=True, power=4, toughness=4), "p1")
    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice(eng.state.pending_choice["options"][0]["id"])
    eng.resolve_until_stable()
    assert survivor.counters.get("+1/+1", 0) == 4
