"""PAR-284 milestone 2: "where X is <referent>'s power / toughness / mana value" with the referent bound safely.

Pinned here: the definite spellings ("the exiled card's", "the spell's", "the mana value of that spell"), nouns the
pronoun grammar lacked ("that enchantment's"), a pronoun naming the one permanent target of its own clause, "that
spell's mana value" under a cast trigger (read off the firing event, claimed only there), and "-X" magnitudes bound
through the same measurement. Parse tests pin what stays unclaimed; engine tests resolve the real wordings.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.catalogue.clause_reading import STANDALONE


def _card(name, type_line, oracle, cost="{1}", mv=1, **kw):
    kw.pop("is_enchantment", None)  # `Card` has no such flag; the type line carries it
    kw.setdefault("is_instant", type_line.startswith("Instant"))
    kw.setdefault("is_sorcery", type_line.startswith("Sorcery"))
    kw.setdefault("is_creature", "Creature" in type_line)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=mv,
                oracle_text=oracle, **kw)


def _modeled(card):
    result = parse_oracle(card)
    return result.modeled


# -- parse ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Aura Mutation", "Instant", "Destroy target enchantment. Create X 1/1 green Saproling creature tokens, where X is that enchantment's mana value."),
    ("Morbid Bloom", "Sorcery", "Exile target creature card from a graveyard, then create X 1/1 green Saproling creature tokens, where X is the exiled card's toughness."),
    ("Soul's Might", "Sorcery", "Put X +1/+1 counters on target creature, where X is that creature's power."),
    ("Great Defender", "Instant", "Target creature gets +0/+X until end of turn, where X is its mana value."),
    ("Living Armor", "Artifact", "{T}, Sacrifice this artifact: Put X +0/+1 counters on target creature, where X is that creature's mana value."),
])
def test_referent_characteristic_cards_are_modeled(name, type_line, oracle):
    assert _modeled(_card(name, type_line, oracle))


def test_a_player_target_does_not_make_its_power_the_targets():
    # "its" names the dying creature there, never the targeted player: no same-clause reading may claim it
    assert parse_effect_body("target player loses life equal to its power", reading=STANDALONE) is None


def test_a_pronoun_without_any_antecedent_stays_unclaimed():
    assert parse_effect_body("create x 1/1 white spirit creature tokens, where x is that creature's power", reading=STANDALONE) is None


def test_that_spells_mana_value_is_only_claimed_under_a_cast_trigger():
    cast = _card("Cast Probe", "Creature — Thrull",
                 "Whenever you cast a creature spell, create X 1/1 black Thrull creature tokens, where X is that spell's mana value.",
                 power=1, toughness=1)
    activated = _card("Activated Probe", "Creature — Thrull",
                      "{T}: Create X 1/1 black Thrull creature tokens, where X is that spell's mana value.",
                      power=1, toughness=1)
    assert parse_oracle(cast).modeled
    assert not parse_oracle(activated).modeled


@pytest.mark.parametrize("clause", [
    "put x +1/+1 counters on target creature, where x is the power of that creature",
    "put x +1/+1 counters on target creature, where x is that creature's power",
])
def test_of_order_reads_like_the_possessive(clause):
    specs = parse_effect_body(clause, reading=STANDALONE)
    assert specs and specs[0].type == "bind"
    assert specs[0].params["amount"]["of"] == "target"


def test_negative_x_magnitude_is_bound_negated():
    specs = parse_effect_body("each creature gets -x/-x until end of turn, where x is the number of vampires you control")
    assert specs
    pump = specs[0].params["effects"][0]["params"]["effects"][0]["params"]
    assert pump["power"] == "-$n" and pump["toughness"] == "-$n"


# -- engine --------------------------------------------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _on_battlefield(eng, card, owner="p2"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.battlefield.append(obj)
    return obj


def _in_hand(eng, card):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    eng.state.players[0].hand.append(obj)
    return obj


def _creature(name, power, toughness, mv=1):
    return _card(name, "Creature — Bear", "", cost="{1}", mv=mv, power=power, toughness=toughness)


def test_soul_might_puts_counters_equal_to_the_targets_power():
    eng = _engine()
    bear = _on_battlefield(eng, _creature("Bear", 4, 4))
    spell = _in_hand(eng, _card("Soul's Might", "Sorcery", "Put X +1/+1 counters on target creature, where X is that creature's power.", cost="{G}{G}", mv=2))
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, spell, targets=[bear])
    eng.resolve_until_stable()
    assert bear.counters.get("+1/+1") == 4


def test_great_defender_adds_toughness_equal_to_its_mana_value():
    eng = _engine()
    bear = _on_battlefield(eng, _creature("Costly Bear", 2, 2, mv=5))
    spell = _in_hand(eng, _card("Great Defender", "Instant", "Target creature gets +0/+X until end of turn, where X is its mana value.", cost="{W}", mv=1))
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"W": 1})
    eng.cast_spell(p1, spell, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (2, 7)


def test_aura_mutation_makes_tokens_equal_to_the_destroyed_enchantments_mana_value():
    eng = _engine()
    ench = _on_battlefield(eng, _card("Big Aura", "Enchantment", "", cost="{2}{W}", mv=3, is_enchantment=True))
    spell = _in_hand(eng, _card("Aura Mutation", "Instant", "Destroy target enchantment. Create X 1/1 green Saproling creature tokens, where X is that enchantment's mana value.", cost="{G}", mv=1))
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"G": 1})
    eng.cast_spell(p1, spell, targets=[ench])
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.battlefield if o.is_token and o.controller_id == "p1"]
    assert len(tokens) == 3


def test_cast_trigger_reads_the_spells_mana_value_off_the_event():
    eng = _engine()
    endrek = _card("Thrull Maker", "Creature — Human", "Whenever you cast a creature spell, create X 1/1 black Thrull creature tokens, where X is that spell's mana value.",
                   cost="{1}", mv=1, power=1, toughness=1)
    obj = GameObject(endrek, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    attach_to_object(obj, parse_oracle(endrek).specs)
    eng.state.battlefield.append(obj)
    spell = _in_hand(eng, _card("Four Drop", "Creature — Bear", "", cost="{4}", mv=4, power=2, toughness=2))
    p1 = eng.state.players[0]
    p1.mana_pool.add_many({"C": 4})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    thrulls = [o for o in eng.state.battlefield if o.is_token and o.controller_id == "p1"]
    assert len(thrulls) == 4
