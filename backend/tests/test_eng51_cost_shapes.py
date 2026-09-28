"""ENG-51 — the activation-cost shapes ENG-49's audit left unread.

ENG-49 made an unread cost fragment fail the ability closed; this widens the
shared grammar (`parser/oracle/catalogue/cost_text.py`) and the engine's cost
payment so the common shapes are charged instead: qualified and "another"
sacrifices, counters removed from another permanent or of any kind, exert,
mill, "discard another card named ~", typed graveyard exiles, qualified
tap-others, "or"-alternative costs, returning N lands, half your life, a -1/-1
counter as Blight 1, "tap enchanted creature". Mana abilities now fail closed
on a leftover too, Station "N+ |" tiers gate on charge counters, and
Springjack Pasture's "Sacrifice X Goats: Add X mana" announces X.

Reference: mtg_analyzer/parser/oracle/catalogue/cost_text.py,
mtg_analyzer/game/costs.py, mtg_analyzer/game/continuous.py
(`matches_permanent_word`), mtg_analyzer/game/engine/activation_mixin.py,
mtg_analyzer/game/mana_abilities.py, RULE 602.1/701.43/702.184.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import PAY_LIFE_HALF_UP, parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _segment_line_unsplit
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def engine():
    filler = _card("Grizzly Bears")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 10), ("p2", "Bob", [filler] * 10)],
        starting_hand=0,
    )
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng, eng.state.player_by_id("p1")


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def to_hand(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id(controller).hand.append(obj)
    return obj


def to_graveyard(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(controller).graveyard.append(obj)
    return obj


@pytest.mark.parametrize("name", [
    "Ayara, First of Locthwain", "Eater of Hope", "Bolrac-Clan Crusher", "Brambleback Brute",
    "Hopeful Initiate", "Fervent Paincaster", "Deranged Assistant", "Tome Shredder",
    "Relic of Legends", "Hatchet Bully", "Pearl Shard", "Springjack Pasture", "Adaptive Gemguard",
    "Flamewright", "Necratog", "Cadaverous Bloom", "Betrothed of Fire", "Gnarlbark Elm",
])
def test_cost_shapes_are_modeled(name):
    assert parse_oracle(_card(name)).coverage == "MODELED"


# ---------------------------------------------------------------------------
# Permanent phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text, word", [
    ("{1}{R}, Sacrifice a Goblin creature", "goblin_creature"),
    ("{T}, Sacrifice another black creature", "other_black_creature"),
    ("{2}, Sacrifice a nontoken permanent", "nontoken_permanent"),
    ("{T}, Sacrifice a creature with defender", "defender_creature"),
    ("{T}, Sacrifice a noncreature artifact", "noncreature_artifact"),
])
def test_qualified_sacrifice_words(text, word):
    cost = parse_activation_cost(text)
    assert cost.unrecognized is None
    assert cost.sacrifice == word


def test_permanent_word_matcher():
    eng, _ = engine()
    bear = battlefield(eng, "Grizzly Bears")
    forest = battlefield(eng, "Forest")
    eng.recompute_continuous_effects()
    assert continuous.matches_permanent_word(bear, "green_creature")
    assert not continuous.matches_permanent_word(bear, "black_creature")
    assert continuous.matches_permanent_word(forest, "basic_land")
    assert continuous.matches_permanent_word(forest, "noncreature_permanent")
    assert continuous.matches_permanent_word(bear, "artifact_or_creature")
    assert not continuous.matches_permanent_word(forest, "artifact_or_creature")


def test_another_creature_never_sacrifices_the_source():
    eng, p1 = engine()
    ayara = battlefield(eng, "Ayara, First of Locthwain")
    ability = next(a for a in ayara.activated_abilities if a.cost.sacrifice)
    assert eng._sacrifice_candidate(p1, ayara, ability.cost.sacrifice) is None
    other = battlefield(eng, "Vampire Nighthawk")
    assert eng._sacrifice_candidate(p1, ayara, ability.cost.sacrifice) is other


def test_two_other_creatures_excludes_the_source():
    eng, p1 = engine()
    eater = battlefield(eng, "Eater of Hope")
    battlefield(eng, "Grizzly Bears")
    ability = next(a for a in eater.activated_abilities if a.cost.sacrifice_count)
    p1.mana_pool.add("B", 3)
    assert not eng._can_pay_activation_cost(p1, eater, ability.cost, x=0)
    battlefield(eng, "Grizzly Bears")
    assert eng._can_pay_activation_cost(p1, eater, ability.cost, x=0)


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def test_counter_from_a_creature_you_control():
    """Bolrac-Clan Crusher: the +1/+1 counter comes off *some* creature."""
    eng, p1 = engine()
    crusher = battlefield(eng, "Bolrac-Clan Crusher")
    bear = battlefield(eng, "Grizzly Bears")
    ability = crusher.activated_abilities[0]
    assert not eng._can_pay_activation_cost(p1, crusher, ability.cost, x=0)
    bear.add_counters("+1/+1", 1)
    assert eng._can_pay_activation_cost(p1, crusher, ability.cost, x=0)
    eng._pay_activation_cost(p1, crusher, ability.cost, x=0)
    assert bear.counters.get("+1/+1", 0) == 0


def test_a_counter_of_any_kind_from_the_source():
    eng, p1 = engine()
    brute = battlefield(eng, "Brambleback Brute")
    ability = brute.activated_abilities[0]
    p1.mana_pool.add("R", 2)
    assert not eng._can_pay_activation_cost(p1, brute, ability.cost, x=0)
    brute.add_counters("stun", 1)
    eng._pay_activation_cost(p1, brute, ability.cost, x=0)
    assert brute.counters.get("stun", 0) == 0


def test_counters_from_among_creatures_spread_over_several():
    eng, p1 = engine()
    initiate = battlefield(eng, "Hopeful Initiate")
    a, b = battlefield(eng, "Grizzly Bears"), battlefield(eng, "Grizzly Bears")
    a.add_counters("+1/+1", 1)
    b.add_counters("+1/+1", 1)
    ability = next(ab for ab in initiate.activated_abilities if ab.cost.remove_counters)
    assert ability.cost.remove_counters_among
    plan = eng._counter_removal_plan(p1, initiate, ability.cost, x=0)
    assert plan is not None and sum(n for _, _, n in plan) == 2


# ---------------------------------------------------------------------------
# Other components
# ---------------------------------------------------------------------------


def test_exert_as_a_cost_skips_the_next_untap():
    eng, p1 = engine()
    paincaster = battlefield(eng, "Fervent Paincaster")
    ability = next(a for a in paincaster.activated_abilities if a.cost.exert_self)
    eng._pay_activation_cost(p1, paincaster, ability.cost, x=0)
    assert paincaster.skip_next_untap and paincaster.exerted_this_turn


def test_mill_cost_mana_ability_mills_and_stays_out_of_auto_tap():
    from mtg_analyzer.game.mana_potential import _auto_tappable_candidates

    eng, p1 = engine()
    assistant = battlefield(eng, "Deranged Assistant")
    library = len(p1.library)
    eng.tap_for_mana(p1, assistant)
    assert len(p1.library) == library - 1
    assert all(c.obj is not assistant for c in _auto_tappable_candidates(eng, p1))


def test_either_type_graveyard_exile():
    eng, p1 = engine()
    shredder = battlefield(eng, "Tome Shredder")
    ability = next(a for a in shredder.activated_abilities if a.cost.exile_from_graveyard)
    to_graveyard(eng, "Grizzly Bears")
    assert not eng._can_pay_activation_cost(p1, shredder, ability.cost, x=0)
    bolt = to_graveyard(eng, "Lightning Bolt")
    eng._pay_activation_cost(p1, shredder, ability.cost, x=0)
    assert bolt not in p1.graveyard


def test_legendary_tap_others_mana_ability():
    eng, p1 = engine()
    relic = battlefield(eng, "Relic of Legends")
    battlefield(eng, "Grizzly Bears")
    tap_legend = [a for a in mana_abilities_for(relic) if a.cost.tap_others]
    assert tap_legend
    assert not eng._can_pay_activation_cost(p1, relic, tap_legend[0].cost, x=0, is_mana_ability=True)
    battlefield(eng, "Isamaru, Hound of Konda")
    assert eng._can_pay_activation_cost(p1, relic, tap_legend[0].cost, x=0, is_mana_ability=True)


def test_half_life_rounded_up():
    eng, p1 = engine()
    cost = parse_activation_cost("Pay half your life, rounded up")
    assert cost.pay_life == PAY_LIFE_HALF_UP
    p1.life = 7
    source = battlefield(eng, "Grizzly Bears")
    eng._pay_activation_cost(p1, source, cost, x=0)
    assert p1.life == 3


def test_minus_counter_on_a_creature_is_blight_one():
    assert parse_activation_cost("{2}{R}, {T}, Put a -1/-1 counter on a creature you control").blight == 1


def test_discard_another_card_named_source():
    eng, p1 = engine()
    cost = parse_activation_cost("Discard another card named ~")
    source = battlefield(eng, "Grizzly Bears")
    to_hand(eng, "Lightning Bolt")
    assert not eng._can_pay_activation_cost(p1, source, cost, x=0)
    twin = to_hand(eng, "Grizzly Bears")
    eng._pay_activation_cost(p1, source, cost, x=0)
    assert twin.zone == Zone.GRAVEYARD


def test_alternative_costs_become_two_abilities():
    provenance = ParserProvenance(version="t", source="test", confidence=1.0)
    seg = _segment_line_unsplit(
        "{3}, {t} or {u}, {t}: draw a card.", allow_spell_effect=False, provenance=provenance,
    )
    assert seg.claimed
    costs = [spec.cost["text"] for spec in [seg.spec, *seg.extra_specs]]
    assert costs == ["{3}, {t}", "{u}, {t}"]


# ---------------------------------------------------------------------------
# Mana abilities
# ---------------------------------------------------------------------------


def test_mana_ability_with_an_unread_cost_is_refused():
    """Soldevi Adnate's "black or artifact creature" is still unread — the
    mana ability is dropped rather than made free."""
    assert parse_mana_abilities(_card("Soldevi Adnate")) == []


def test_mana_ability_reads_the_source_by_name():
    [ability] = parse_mana_abilities(_card("Black Tulip"))
    assert ability.cost.exile_self and ability.cost.unrecognized is None


def test_station_tier_mana_ability_needs_charge_counters():
    eng, _ = engine()
    evendo = battlefield(eng, "Evendo, Waking Haven")
    assert len(mana_abilities_for(evendo)) == 1
    evendo.add_counters("charge", 12)
    assert len(mana_abilities_for(evendo)) == 2


def test_springjack_pasture_adds_x_mana_and_x_life():
    eng, p1 = engine()
    pasture = battlefield(eng, "Springjack Pasture")
    goat = Card(id="goat", name="Goat", type_line="Token Creature — Goat",
                is_creature=True, power=0, toughness=1)
    goats = eng.rules.create_token(p1.id, goat, count=3)
    index = next(i for i, a in enumerate(mana_abilities_for(pasture)) if a.x_scaled)
    life = p1.life

    offer = next(
        a for a in eng.legal_actions(p1)
        if a.get("type") == "tap_for_mana" and a["instance_id"] == pasture.instance_id
        and a["ability_index"] == index
    )
    assert offer["has_x"] and offer["max_x"] == 3

    produced = eng.tap_for_mana(p1, pasture, option_index=4, ability_index=index, x=2)
    assert sum(produced.values()) == 2
    assert p1.life == life + 2
    assert sum(g.zone == Zone.GRAVEYARD for g in goats) == 2
