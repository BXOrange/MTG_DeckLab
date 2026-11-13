"""PAR-267: "Tap N untapped <type> you control" as an activation cost (Captain Jean-Luc Picard, Collation Trimatrix).

RULE 602.2b / 601.2h: the controller picks the permanents and taps each as the cost is paid. RULE 302.6 only restricts the
{T} cost of a creature's *own* ability, so summoning-sick creatures may be tapped to pay another ability's cost.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import game, on_battlefield, stock_library

PICARD = "Captain Jean-Luc Picard"
TRIMATRIX = "Collation Trimatrix"
SPACECRAFT = "Infinite Guideline Station"
OFFICER_COUNT = 7  # printed cost
ARTIFACT_CREATURE_COUNT = 3  # printed cost
CHARGE_COUNTERS = 7  # printed entry counters


def _offers(engine, player, source):
    return [a for a in engine.legal_actions(player)
            if a["type"] == "activate_ability" and a["instance_id"] == source.instance_id]


def _resolve(engine):
    while engine.state.stack:
        engine.rules.resolve_top_of_stack()


def _officers(engine, n):
    """``n`` plain Officer creatures (summoning sick: RULE 302.6 must not stop them paying another ability's cost)."""
    made = []
    for i in range(n):
        obj = GameObject(Card(id=f"Officer{i}", name=f"Officer {i}", type_line="Creature — Human Officer",
                              is_creature=True, power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.controller_id = "p1"
        obj.summoning_sick = True
        engine.state.add_to_battlefield(obj)
        made.append(obj)
    engine.recompute_continuous_effects()
    return made


@pytest.mark.parametrize("name", [PICARD, TRIMATRIX])
def test_cards_parse_modeled(name):
    assert parse_oracle(get_cached_card(name)).coverage == "MODELED"


def test_cost_grammar_two_word_type():
    cost = parse_activation_cost("Tap three untapped artifact creatures you control")
    assert cost.tap_others == (ARTIFACT_CREATURE_COUNT, "artifact_creature") and cost.unrecognized is None


def test_trimatrix_needs_three_untapped_artifact_creatures():
    engine, p1, _ = game()
    stock_library(engine, "p1", 5)
    tri = on_battlefield(engine, "p1", TRIMATRIX)
    on_battlefield(engine, "p1", "Grizzly Bears")  # a creature but not an artifact
    assert _offers(engine, p1, tri) == []
    a = on_battlefield(engine, "p1", TRIMATRIX)
    b = on_battlefield(engine, "p1", TRIMATRIX)
    offers = _offers(engine, p1, tri)
    assert offers
    # Summoning sickness does not stop tapping for a cost (RULE 302.6): the source and a fresh copy are both sick.
    tri.summoning_sick = True
    b.summoning_sick = True
    hand, life = len(p1.hand), p1.life
    engine.activate_ability(p1, tri, 0, tap_choices=[tri.instance_id, a.instance_id, b.instance_id])
    assert tri.tapped and a.tapped and b.tapped
    _resolve(engine)
    assert len(p1.hand) == hand + 1 and p1.life == life - 1


def test_trimatrix_rejects_a_non_matching_pick_without_side_effects():
    engine, p1, _ = game()
    stock_library(engine, "p1", 5)
    tri = on_battlefield(engine, "p1", TRIMATRIX)
    a = on_battlefield(engine, "p1", TRIMATRIX)
    on_battlefield(engine, "p1", TRIMATRIX)
    bear = on_battlefield(engine, "p1", "Grizzly Bears")
    with pytest.raises(Exception):
        engine.activate_ability(p1, tri, 0, tap_choices=[tri.instance_id, a.instance_id, bear.instance_id])
    assert not (tri.tapped or a.tapped or bear.tapped)
    assert not engine.state.stack


def test_trimatrix_skips_tapped_artifact_creatures():
    engine, p1, _ = game()
    tri = on_battlefield(engine, "p1", TRIMATRIX)
    a = on_battlefield(engine, "p1", TRIMATRIX)
    on_battlefield(engine, "p1", TRIMATRIX)
    engine.rules.set_tapped(a, True)
    assert _offers(engine, p1, tri) == []


def test_picard_search_puts_spacecraft_with_seven_charge_counters():
    engine, p1, _ = game()
    stock_library(engine, "p1", 3)
    craft = GameObject(get_cached_card(SPACECRAFT), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(craft)
    picard = on_battlefield(engine, "p1", PICARD)
    pool = [picard, *_officers(engine, OFFICER_COUNT)]  # Picard is an Officer too: 8 candidates, 7 needed
    assert _offers(engine, p1, picard)
    picks = pool[:OFFICER_COUNT]
    engine.activate_ability(p1, picard, 0, tap_choices=[o.instance_id for o in picks])
    assert all(o.tapped for o in picks) and not pool[OFFICER_COUNT].tapped
    _resolve(engine)
    if engine.state.pending_choice:
        engine.rules.resolve_choice(str(craft.instance_id))
    assert craft in engine.state.battlefield
    assert craft.counters.get("charge") == CHARGE_COUNTERS


def test_picard_not_offered_with_six_officers():
    engine, p1, _ = game()
    picard = on_battlefield(engine, "p1", PICARD)
    _officers(engine, OFFICER_COUNT - 2)  # Picard + 5 = 6
    assert _offers(engine, p1, picard) == []
