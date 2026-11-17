"""PAR-284: "counter target spell unless its controller pays {1} for each <count>" and "... pays {X}, where X is <amount>"
(RULE 118.12, 107.3a, 608.2h).

The unless-cost is one generic amount measured as the counter resolves: `bind` measures the amount and writes it into
`CounterSpellEffect.unless_pays_generic`. The countered spell's controller then answers the usual pay / decline choice.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _creature, _engine


STARTING_LIFE = 20  # `_engine`'s starting_life
LIFE_AFTER_VICTIM_RESOLVES = STARTING_LIFE + 7  # the victim's "You gain 7 life."


def _bound(oracle):
    specs = parse_effect_body(oracle)
    assert specs is not None and [s.type for s in specs] == ["bind"], specs
    return specs[0].params


def test_for_each_count_is_the_generic_unless_cost():
    params = _bound("counter target spell unless its controller pays {1} for each card in your hand.")
    assert params["amount"]["selector"] == {"zone": "hand", "of": "you"}
    assert params["effects"] == [{"type": "counter", "params": {"unless_pays_generic": "$n"}}]


@pytest.mark.parametrize("clause, amount_kind", [
    ("counter target spell unless its controller pays {x}, where x is the greatest power among creatures you control.",
     "count_selector"),
    ("counter target spell unless its controller pays {x}, where x is your devotion to blue.", "count_selector"),
    ("counter target spell unless its controller pays {x}, where x is its mana value.", "characteristic"),
    ("counter target spell unless its controller pays {1} for each card discarded this way.", "this_way_count"),
])
def test_where_x_and_for_each_amounts_bind_into_the_unless_cost(clause, amount_kind):
    params = _bound(clause)
    assert params["amount"]["kind"] == amount_kind
    assert params["effects"][0]["params"]["unless_pays_generic"] == "$n"
    assert "unless_pays" not in params["effects"][0]["params"]


def test_a_cast_x_unless_cost_and_a_tax_on_a_fixed_cost_keep_their_own_reading():
    # Mindswipe-style "{X}" is the spell's own announced X, not a measured amount.
    plain = parse_effect_body("counter target spell unless its controller pays {x}.")
    assert [(s.type, s.params) for s in plain] == [("counter", {"unless_pays": "{x}"})]
    # a fixed "{2} for each" has no one-generic unit to scale
    assert parse_effect_body("counter target spell unless its controller pays {2} for each card in your hand.") is None


def _spell_on_stack(eng, mana):
    p2 = eng.state.players[1]
    card = _card("Victim", "Instant", "You gain 7 life.", mv=3, is_instant=True)
    victim = GameObject(card, owner_id="p2", zone=Zone.HAND)
    attach_to_object(victim, parse_oracle(card).specs)
    p2.hand.append(victim)
    p2.mana_pool.add_many({"C": mana})
    eng.cast_spell(p2, victim)
    return p2, victim


def _counter(eng, oracle, victim, *, type_line="Instant"):
    card = _card("Counter Probe", type_line, oracle, is_instant=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    item = next(i for i in eng.state.stack if i.obj is victim)
    eng.rules.cast_spell(p1, obj, targets=[item])
    eng.resolve_until_stable()
    return obj


def _hand_of(eng, n):
    p1 = eng.state.players[0]
    for i in range(n):
        p1.hand.append(GameObject(_card(f"H{i}", "Instant", is_instant=True), owner_id="p1", zone=Zone.HAND))


@pytest.mark.parametrize("answer, countered", [("pay", False), ("decline", True)])
def test_oppressive_will_shape_charges_one_per_card_in_hand(answer, countered):
    eng = _engine()
    _hand_of(eng, 3)  # the counter itself leaves the hand on cast: three cards remain
    p2, victim = _spell_on_stack(eng, mana=3 + 3)  # {1} cast cost on the stub card + the tax
    _counter(eng, "Counter target spell unless its controller pays {1} for each card in your hand.", victim)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "counter_unless_pays" and "{3}" in choice["prompt"]
    paid_from = p2.mana_pool.total()
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    if countered:
        assert p2.life == STARTING_LIFE and victim.zone == Zone.GRAVEYARD  # countered: its life gain never happened
        assert p2.mana_pool.total() == paid_from
    else:
        assert p2.mana_pool.total() == paid_from - 3  # the tax was paid out of the pool
        assert p2.life == LIFE_AFTER_VICTIM_RESOLVES


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_spell_rupture_shape_reads_the_greatest_power(answer):
    eng = _engine()
    _creature(eng, "Small", "p1", 2)
    _creature(eng, "Big", "p1", 5)
    p2, victim = _spell_on_stack(eng, mana=1 + 5)
    _counter(eng, "Counter target spell unless its controller pays {X}, where X is the greatest power among creatures you control.", victim)
    choice = eng.state.pending_choice
    assert choice is not None and "{5}" in choice["prompt"]
    paid_from = p2.mana_pool.total()
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    if answer == "pay":
        assert p2.mana_pool.total() == paid_from - 5
        assert p2.life == LIFE_AFTER_VICTIM_RESOLVES
    else:
        assert p2.life == STARTING_LIFE and victim.zone == Zone.GRAVEYARD


def test_rethink_shape_reads_the_targeted_spells_mana_value():
    eng = _engine()
    p2, victim = _spell_on_stack(eng, mana=1 + 3)
    _counter(eng, "Counter target spell unless its controller pays {X}, where X is its mana value.", victim)
    choice = eng.state.pending_choice
    assert choice is not None and "{3}" in choice["prompt"]
    eng.rules.resolve_choice("decline")
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD


def test_an_unaffordable_measured_cost_counters_without_a_choice():
    eng = _engine()
    _creature(eng, "Big", "p1", 6)
    p2, victim = _spell_on_stack(eng, mana=1)  # nothing left to pay {6}
    _counter(eng, "Counter target spell unless its controller pays {X}, where X is the greatest power among creatures you control.", victim)
    assert eng.state.pending_choice is None
    assert victim.zone == Zone.GRAVEYARD


def _activate_counter(eng, oracle, victim, *, counters=0, power=3):
    """A battlefield creature with ``oracle``'s sacrifice-cost counter ability, activated at ``victim``."""
    card = _card("Sacrifice Counter", "Creature — Spirit", oracle, is_creature=True, power=power, toughness=power)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    src = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    src.summoning_sick = False
    if counters:
        src.counters["verse"] = counters
    attach_to_object(src, result.specs)
    eng.state.battlefield.append(src)
    eng.activate_ability(eng.state.players[0], src, 0, targets=[victim])
    eng.resolve_until_stable()
    return src


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_mausoleum_wanderer_shape_reads_the_sacrificed_sources_power(answer):
    # RULE 608.2h: the cost sacrificed ~, so its power is last-known information.
    eng = _engine()
    p2, victim = _spell_on_stack(eng, mana=1 + 3)
    _activate_counter(eng, "Sacrifice ~: Counter target instant or sorcery spell unless its controller pays {X}, "
                           "where X is ~'s power.", victim, power=3)
    choice = eng.state.pending_choice
    assert choice is not None and "{3}" in choice["prompt"]
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    assert p2.life == (LIFE_AFTER_VICTIM_RESOLVES if answer == "pay" else STARTING_LIFE)


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_lilting_refrain_shape_reads_the_sacrificed_sources_counters(answer):
    eng = _engine()
    p2, victim = _spell_on_stack(eng, mana=1 + 2)
    _activate_counter(eng, "Sacrifice ~: Counter target spell unless its controller pays {X}, where X is the number of "
                           "verse counters on ~.", victim, counters=2)
    choice = eng.state.pending_choice
    assert choice is not None and "{2}" in choice["prompt"]
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    assert p2.life == (LIFE_AFTER_VICTIM_RESOLVES if answer == "pay" else STARTING_LIFE)


def test_a_group_for_each_tax_is_one_measured_amount_not_a_repeated_counter():
    # Spell Syphon: the counted group phrase used to read as a per-permanent `for_each` that repeated the counter.
    params = _bound("counter target spell unless its controller pays {1} for each blue permanent you control.")
    assert params["amount"]["selector"]["filter"] == {"color": "U"}
    assert params["effects"][0]["params"] == {"unless_pays_generic": "$n"}


def test_plus_an_additional_tax_is_the_base_plus_the_scaled_count():
    spell_stutter = _bound("counter target spell unless its controller pays {2} plus an additional {1} for each faerie you control.")
    assert spell_stutter["amount"]["plus"] == 2 and "multiply" not in spell_stutter["amount"]
    rune_snag = _bound("counter target spell unless its controller pays {2} plus an additional {2} for each card named ~ "
                       "in each graveyard.")
    assert rune_snag["amount"]["plus"] == 2 and rune_snag["amount"]["multiply"] == 2
    # the party tax keeps its established named-selector row
    party = parse_effect_body("counter target noncreature spell unless its controller pays {1} plus an additional {1} "
                              "for each creature in your party.")
    assert party[0].type == "counter" and party[0].params["unless_pays_extra_selector"] == "creatures_in_your_party"


@pytest.mark.parametrize("answer", ["pay", "decline"])
def test_spell_stutter_shape_charges_the_base_plus_one_per_creature(answer):
    eng = _engine()
    for i in range(2):
        _creature(eng, f"Bear{i}", "p1", 1)
    p2, victim = _spell_on_stack(eng, mana=1 + 4)
    _counter(eng, "Counter target spell unless its controller pays {2} plus an additional {1} for each creature you control.",
             victim)
    choice = eng.state.pending_choice
    assert choice is not None and "{4}" in choice["prompt"]  # {2} + two creatures
    eng.rules.resolve_choice(answer)
    eng.resolve_until_stable()
    assert p2.life == (LIFE_AFTER_VICTIM_RESOLVES if answer == "pay" else STARTING_LIFE)
