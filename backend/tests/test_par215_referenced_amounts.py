"""PAR-215: "equal to its / that card's mana value / power / toughness" measure the right object.

Parse tests pin the referent each phrase binds to; execution tests resolve real cards against the real engine
and check the number (a MODELED verdict alone has shipped wrong-but-claimed amounts before).
"""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import answer, card, cast, filler, game, stack_library, step


def _parse(text, type_line="Instant"):
    from mtg_analyzer.models.cards.card import Card
    c = Card(id="x", name="Probe Card", type_line=type_line, oracle_text=text, is_instant="Instant" in type_line,
             is_creature="Creature" in type_line)
    return parse_oracle(c)


def _flat(result):
    return [e for s in result.specs for e in s.to_dict()["effects"]]


def _amount_of(effects):
    bind = next(e for e in effects if e["type"] == "bind")
    return bind["params"]["amount"]


@pytest.mark.parametrize("text,of,characteristic", [
    ("Return target card from your graveyard to your hand. You gain life equal to that card's mana value.",
     "previous_target", "mana_value"),
    ("Return target creature card from your graveyard to your hand. Probe Card deals damage equal to that card's "
     "power to target creature.", "previous_target", "power"),
    ("Scry 3, then reveal the top card of your library. You gain life equal to that card's mana value.",
     "revealed", "mana_value"),
    ("Exile the top card of your library. Probe Card deals damage to you equal to that card's mana value.",
     "created", "mana_value"),
    ("Counter target spell. You lose life equal to that spell's mana value.", "previous_subject", "mana_value"),
])
def test_referent_bound_to_the_object_the_earlier_clause_picked(text, of, characteristic):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    amount = _amount_of(_flat(result))
    assert amount["of"] == of and amount["characteristic"] == characteristic


def test_reveal_and_take_leaves_the_card_nameable():
    result = _parse("At the beginning of your upkeep, reveal the top card of your library and put that card into "
                    "your hand. You lose life equal to its mana value.", "Enchantment")
    assert result.modeled, result.unclaimed
    effects = _flat(result)
    assert [e["type"] for e in effects] == ["reveal_top", "put_revealed_card", "bind"]
    assert _amount_of(effects)["of"] == "revealed"


@pytest.mark.parametrize("text", [
    # "that spell" in a trigger is the cast spell, not the token the clause before made
    "Whenever you cast an instant spell, create a 0/0 green Fractal creature token. Put X +1/+1 counters on it, "
    "where X is that spell's mana value.",
    # no earlier clause picked a card: "that card" has no antecedent
    "You gain life equal to that card's mana value.",
    # a token is no card
    "Create a 1/1 white Spirit creature token. You gain life equal to that card's power.",
])
def test_unanchored_pronouns_stay_unclaimed(text):
    assert not _parse(text).modeled


def test_dark_confidant_loses_life_equal_to_the_revealed_cards_mana_value():
    eng = game(library=0)
    top = filler(eng, "Top", type_line="Artifact", mv=4, zone=Zone.LIBRARY)
    filler(eng, "Under", mv=1, zone=Zone.LIBRARY)
    stack_library(eng, "p1", *[o for o in eng.state.player_by_id("p1").library if o is not top], top)
    card(eng, "Dark Confidant")
    step(eng, "upkeep")
    answer(eng)
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert top in p1.hand and p1.life == 20 - 4


def test_reanimate_costs_life_equal_to_the_returned_cards_mana_value():
    eng = game(library=0)
    victim = filler(eng, "Big Dead", mv=6, power=5, toughness=5, zone=Zone.GRAVEYARD)
    spell = card(eng, "Reanimate", zone=Zone.HAND)
    cast(eng, spell, targets=[victim])
    answer(eng)
    assert victim.zone == Zone.BATTLEFIELD
    assert eng.state.player_by_id("p1").life == 20 - 6


def test_lie_in_wait_deals_damage_equal_to_the_returned_cards_power():
    eng = game(library=0)
    dead = filler(eng, "Dead Giant", mv=5, power=6, toughness=6, zone=Zone.GRAVEYARD)
    victim = filler(eng, "Victim", power=1, toughness=9, player="p2")
    spell = card(eng, "Lie in Wait", zone=Zone.HAND)
    cast(eng, spell, targets=[dead, victim])
    answer(eng)
    assert dead.zone == Zone.HAND and victim.damage_marked == 6


def test_healing_technique_gains_life_equal_to_the_returned_cards_mana_value():
    eng = game(library=0)
    dead = filler(eng, "Dead Spell", type_line="Sorcery", mv=3, zone=Zone.GRAVEYARD)
    spell = card(eng, "Healing Technique", zone=Zone.HAND)
    cast(eng, spell, targets=[dead])
    answer(eng)
    assert dead.zone == Zone.HAND and eng.state.player_by_id("p1").life == 23


def test_sifter_wurm_gains_life_equal_to_the_revealed_cards_mana_value():
    from tests.support.deck_batch import put_on_battlefield
    eng = game(library=0)
    top = filler(eng, "Top", type_line="Artifact", mv=3, zone=Zone.LIBRARY)
    stack_library(eng, "p1", top)
    put_on_battlefield(eng, "Sifter Wurm")
    answer(eng)
    eng.resolve_until_stable()
    assert top.zone == Zone.LIBRARY and eng.state.player_by_id("p1").life == 23


def test_bind_the_monster_damages_its_controller_by_the_enchanted_creatures_power():
    eng = game(library=0)
    victim = filler(eng, "Victim", power=4, toughness=4, player="p2")
    aura = card(eng, "Bind the Monster", zone=Zone.HAND)
    cast(eng, aura, targets=[victim])
    answer(eng)
    eng.resolve_until_stable()
    assert victim.tapped and eng.state.player_by_id("p1").life == 20 - 4


@pytest.mark.parametrize("text,key,value", [
    ("Counter target spell with mana value 4 or greater.", "min_mana_value", 4),
    ("Counter target spell with mana value 2 or less.", "max_mana_value", 2),
])
def test_counter_mana_value_bound_parses_as_a_floor_or_ceiling(text, key, value):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    effects = _flat(result)
    assert [(e["type"], e["params"]) for e in effects] == [("counter", {key: value})]


def test_counter_bound_is_not_an_exact_value_and_x_bound_is_refused():
    assert _flat(_parse("Counter target spell with mana value 3."))[0]["params"] == {"mana_value": 3}
    assert not _parse("Counter target spell with mana value x or less.").modeled


def test_counter_only_offers_spells_inside_the_mana_value_bound():
    from mtg_analyzer.game.targeting import _spell_matches_filter
    eng = game(library=0)
    small = filler(eng, "Small", type_line="Sorcery", mv=2, player="p2", zone=Zone.HAND)
    big = filler(eng, "Big", type_line="Sorcery", mv=5, player="p2", zone=Zone.HAND)
    floor = {"min_mana_value": 4}
    assert _spell_matches_filter(big, floor) and not _spell_matches_filter(small, floor)
    ceiling = {"max_mana_value": 2}
    assert _spell_matches_filter(small, ceiling) and not _spell_matches_filter(big, ceiling)


def test_dominate_takes_a_creature_within_the_announced_x():
    eng = game(library=0)
    cheap = filler(eng, "Cheap", mv=2, power=2, toughness=2, player="p2")
    dear = filler(eng, "Dear", mv=5, power=5, toughness=5, player="p2")
    spell = card(eng, "Dominate", zone=Zone.HAND)
    from mtg_analyzer.game.targeting import legal_targets
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    effect = build_effects(parse_effect_body("gain control of target creature with mana value x or less"), spell)[0]
    assert effect.target_spec.max_mana_value == "x"
    cast(eng, spell, targets=[cheap], x=2)
    answer(eng)
    assert cheap.controller_id == "p1" and dear.controller_id == "p2"


def test_draining_whelk_counts_the_countered_spells_mana_value():
    eng = game(library=0)
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    victim = filler(eng, "Big Spell", type_line="Instant", mv=4, player="p2", zone=Zone.HAND)
    from tests.support.deck_batch import main_phase, RICH
    main_phase(eng)
    p2.mana_pool.add_many(RICH)
    eng.cast_spell(p2, victim)
    whelk = card(eng, "Draining Whelk", zone=Zone.HAND)
    p1.mana_pool.add_many(RICH)
    eng.cast_spell(p1, whelk, targets=[victim])
    eng.resolve_until_stable()
    answer(eng)
    assert victim.zone == Zone.GRAVEYARD
    assert whelk.counters.get("+1/+1", 0) == 4


def test_an_inner_gate_survives_the_outer_intervening_if():
    result = _parse("When Probe Card enters, if it was kicked, tap target artifact. If that artifact is an Equipment, "
                    "untap it.", "Creature")
    if not result.modeled:  # the shape is only a regression probe for the condition fold
        pytest.skip("shape not claimed")
    gates = [e.get("condition") for e in _flat(result)]
    assert all(g is not None for g in gates)


def test_attach_it_to_self_is_not_the_source_attaching_to_a_permanent():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    assert match_clause("attach it to ~") is None
    assert not _parse("Whenever Probe Card attacks, gain control of target artifact with mana value 2 or less. "
                      "If that artifact is an Equipment, attach it to Probe Card.", "Creature").modeled
