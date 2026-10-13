"""PAR-164: "deals / is dealt N or more damage" trigger heads, and "you may exile it. When you do, <effect>"
(real cached cards on the real engine).

RULE 120.3: the DAMAGE event is one source dealing to one recipient, so the threshold compares that event's amount:
two smaller hits never add up and one big hit fires once. RULE 603.12: the exile is the antecedent of a reflexive
trigger, so declining it skips the effect.
"""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, card, filler, game, stack_library

NAMES = [
    "Deus of Calamity", "Dragonborn Champion", "Innocent Bystander", "Pain Magnification",
    "Spinneret and Spiderling", "Paramecia Coloniex", "Sandbender Scavengers", "The Balrog of Moria",
]


@pytest.mark.parametrize("name", NAMES)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


def _hit(engine, target, amount, source):
    engine.rules.deal_damage(target, amount, source=source)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def _clues(engine, player="p1"):
    return [o for o in engine.state.permanents_controlled_by(player) if o.card.name == "Clue"]


def test_is_dealt_threshold_innocent_bystander():
    engine = game()
    bystander = card(engine, "Innocent Bystander")
    bystander.card.toughness = 20  # survive the hits; the trigger does not depend on dying
    src = filler(engine, "Src", player="p2", power=1, toughness=1)
    _hit(engine, bystander, 2, src)
    assert not _clues(engine)
    _hit(engine, bystander, 3, src)
    assert len(_clues(engine)) == 1


def test_threshold_is_per_event_not_cumulative_and_fires_once_for_a_big_hit():
    engine = game()
    bystander = card(engine, "Innocent Bystander")
    bystander.card.toughness = 20  # survive
    src = filler(engine, "Src", player="p2", power=1, toughness=1)
    _hit(engine, bystander, 2, src)
    _hit(engine, bystander, 2, src)
    assert not _clues(engine)
    _hit(engine, bystander, 7, src)
    assert len(_clues(engine)) == 1


def test_source_you_control_threshold_dragonborn_champion():
    engine = game()
    card(engine, "Dragonborn Champion")
    mine = filler(engine, "Mine", power=5, toughness=5)
    theirs = filler(engine, "Theirs", player="p2", power=5, toughness=5)
    stack_library(engine, "p1", filler(engine, "A", zone=Zone.LIBRARY), filler(engine, "B", zone=Zone.LIBRARY))
    p2 = engine.state.player_by_id("p2")
    hand = len(engine.state.player_by_id("p1").hand)
    _hit(engine, p2, 4, mine)          # below the threshold
    _hit(engine, p2, 6, theirs)        # opponent's source
    _hit(engine, engine.state.player_by_id("p1"), 6, theirs)
    assert len(engine.state.player_by_id("p1").hand) == hand
    _hit(engine, p2, 5, mine)          # exactly the threshold
    assert len(engine.state.player_by_id("p1").hand) == hand + 1


def test_deus_of_calamity_needs_six_to_an_opponent():
    engine = game()
    deus = card(engine, "Deus of Calamity")
    land = filler(engine, "Their Land", type_line="Land", player="p2")
    own_land = filler(engine, "My Land", type_line="Land")
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    _hit(engine, p2, 5, deus)
    assert land.zone == Zone.BATTLEFIELD
    _hit(engine, p1, 6, deus)          # not an opponent
    answer(engine)
    assert land.zone == Zone.BATTLEFIELD and own_land.zone == Zone.BATTLEFIELD
    _hit(engine, p2, 6, deus)
    answer(engine)
    assert land.zone == Zone.GRAVEYARD and own_land.zone == Zone.BATTLEFIELD


def test_pain_magnification_makes_the_damaged_opponent_discard():
    engine = game()
    card(engine, "Pain Magnification")
    src = filler(engine, "Src", power=3, toughness=3)
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    for owner in ("p1", "p2"):
        filler(engine, "H1" + owner, player=owner, zone=Zone.HAND)
        filler(engine, "H2" + owner, player=owner, zone=Zone.HAND)
    _hit(engine, p2, 2, src)
    answer(engine)
    assert len(p2.hand) == 2
    _hit(engine, p1, 3, src)           # "an opponent" is not you
    answer(engine)
    assert len(p1.hand) == 2
    _hit(engine, p2, 3, src)
    answer(engine)
    assert len(p2.hand) == 1 and len(p1.hand) == 2


def test_spinneret_and_spiderling_fires_on_any_recipient_at_four():
    engine = game()
    spider = card(engine, "Spinneret and Spiderling")
    victim = filler(engine, "Victim", player="p2", power=1, toughness=9)
    top = filler(engine, "Top", zone=Zone.LIBRARY)
    stack_library(engine, "p1", top)
    _hit(engine, victim, 3, spider)
    assert top.zone == Zone.LIBRARY
    _hit(engine, victim, 4, spider)
    answer(engine)
    assert top.zone != Zone.LIBRARY


def _dies(engine, creature):
    engine.rules.destroy(creature)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def test_reflexive_exile_accepted_puts_the_target_on_top_of_the_library():
    engine = game()
    coloniex = card(engine, "Paramecia Coloniex")
    other = filler(engine, "Other", power=1, toughness=1, zone=Zone.GRAVEYARD)
    _dies(engine, coloniex)
    answer(engine, pick=lambda c: "exile" if any(o["id"] == "exile" for o in c.get("options") or []) else None)
    assert coloniex.zone == Zone.EXILE
    assert other.zone == Zone.LIBRARY and engine.state.player_by_id("p1").library[-1] is other


def test_reflexive_exile_declined_skips_the_effect():
    engine = game()
    coloniex = card(engine, "Paramecia Coloniex")
    other = filler(engine, "Other", power=1, toughness=1, zone=Zone.GRAVEYARD)
    _dies(engine, coloniex)
    answer(engine, pick=lambda c: "decline" if any(o["id"] == "decline" for o in c.get("options") or []) else None)
    assert coloniex.zone == Zone.GRAVEYARD and other.zone == Zone.GRAVEYARD
    assert engine.state.pending_choice is None


def test_sandbender_returns_only_cards_up_to_its_power():
    engine = game()
    scav = card(engine, "Sandbender Scavengers")
    power = int(scav.power)
    cheap = filler(engine, "Cheap", power=1, toughness=1, mv=power, zone=Zone.GRAVEYARD)
    dear = filler(engine, "Dear", power=1, toughness=1, mv=power + 1, zone=Zone.GRAVEYARD)
    _dies(engine, scav)
    answer(engine, pick=lambda c: "exile" if any(o["id"] == "exile" for o in c.get("options") or []) else None)
    assert cheap.zone == Zone.BATTLEFIELD
    assert dear.zone == Zone.GRAVEYARD


def test_power_bounded_return_also_serves_a_plain_dies_trigger_gurgling_anointer():
    engine = game()
    anointer = card(engine, "Gurgling Anointer")
    power = int(anointer.power)
    cheap = filler(engine, "Cheap", power=1, toughness=1, mv=power, zone=Zone.GRAVEYARD)
    dear = filler(engine, "Dear", power=1, toughness=1, mv=power + 1, zone=Zone.GRAVEYARD)
    _dies(engine, anointer)
    answer(engine)
    assert cheap.zone == Zone.BATTLEFIELD and dear.zone == Zone.GRAVEYARD and anointer.zone == Zone.GRAVEYARD


def _sandbender_with_counters(counters, extra_mv):
    engine = game()
    scav = card(engine, "Sandbender Scavengers")
    scav.counters["+1/+1"] = counters
    engine.recompute_continuous_effects()
    base = int(scav.power) - counters
    cheap = filler(engine, "Cheap", power=1, toughness=1, mv=base + counters, zone=Zone.GRAVEYARD)
    dear = filler(engine, "Dear", power=1, toughness=1, mv=base + counters + extra_mv, zone=Zone.GRAVEYARD)
    _dies(engine, scav)
    # RULE 400.7: the card in the graveyard is a new object without its counters, whatever this engine keeps on
    # the stale object; only the last-known power (the DIES event snapshot) still knows about them.
    scav.counters.clear()
    scav._derived_power = None  # the layer stamp is stale; printed power + (no) counters remains
    assert int(scav.power) == base
    answer(engine, pick=lambda c: "exile" if any(o["id"] == "exile" for o in c.get("options") or []) else None)
    return cheap, dear


def test_sandbender_reads_last_known_power_including_counters():
    # RULE 608.2h: the exiled card has lost its counters; the bound is its power as it last existed.
    cheap, dear = _sandbender_with_counters(2, 1)
    assert cheap.zone == Zone.BATTLEFIELD  # base power + 2
    assert dear.zone == Zone.GRAVEYARD     # one more than that
