"""PAR-287 milestone 2: "that creature" / "that player" under a damage head names the damaged object.

Under "whenever ~ / equipped creature deals (combat) damage to a creature" the one object a body's "that creature" can
name is the creature the damage event hit (RULE 120.3, read off the event's `target_id` and stamped as the referent
with its zone visit, RULE 400.7 / 608.2h). Every behaviour test drives real damage on the real card against a same-type
bystander that must stay untouched, plus the near misses (damage to a player, non-combat damage under a combat head)
and the damaged creature dying before the trigger resolves.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, filler, game

NEWLY_COVERED = ["Mercurial Kite", "Queen of Ice // Rage of Winter", "Obelisk Spider", "Sword of Kaldra", "Walker of Secret Ways"]

#: A creature with this much toughness survives the small hits below.
SURVIVOR_TOUGHNESS = 4
#: One point of damage: enough to fire the trigger, never lethal to a survivor.
ONE_DAMAGE = 1
#: Lethal damage for a 1-toughness victim.
LETHAL = 1


def _victim_and_bystander(engine, toughness=SURVIVOR_TOUGHNESS):
    victim = filler(engine, "Victim", player="p2", power=1, toughness=toughness)
    bystander = filler(engine, "Bystander", player="p2", power=1, toughness=toughness)
    return victim, bystander


def _hit(engine, victim, source, combat=True, amount=ONE_DAMAGE):
    engine.rules.deal_damage(victim, amount, source=source, combat=combat)
    engine.resolve_until_stable()


def _untap_step_of(engine, player_id):
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == player_id)
    engine._step_untap()


@pytest.mark.parametrize("name", NEWLY_COVERED)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


@pytest.mark.parametrize("name", ["Mercurial Kite", "Queen of Ice // Rage of Winter"])
def test_tap_and_freeze_hits_only_the_damaged_creature(name):
    engine = game()
    dealer = card(engine, name)
    victim, bystander = _victim_and_bystander(engine)
    _hit(engine, victim, dealer)
    assert victim.tapped and victim.skip_next_untap
    assert not bystander.tapped and not bystander.skip_next_untap   # same type, same controller: untouched
    assert not dealer.tapped and not dealer.skip_next_untap          # the dealer is not "that creature"


@pytest.mark.parametrize("name", ["Mercurial Kite", "Queen of Ice // Rage of Winter"])
def test_freeze_lasts_exactly_one_untap_step(name):
    engine = game()
    dealer = card(engine, name)
    victim, bystander = _victim_and_bystander(engine)
    bystander.tapped = True                                          # an untouched tapped creature untaps normally
    _hit(engine, victim, dealer)
    _untap_step_of(engine, "p2")                                    # first untap step: kept tapped
    assert victim.tapped and not victim.skip_next_untap
    assert not bystander.tapped
    _untap_step_of(engine, "p2")                                    # second untap step: the effect is over
    assert not victim.tapped


@pytest.mark.parametrize("name", ["Mercurial Kite", "Queen of Ice // Rage of Winter"])
def test_damage_to_a_player_or_noncombat_damage_does_nothing(name):
    engine = game()
    dealer = card(engine, name)
    victim, bystander = _victim_and_bystander(engine)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), ONE_DAMAGE, source=dealer, combat=True)
    engine.resolve_until_stable()
    assert not victim.tapped and not bystander.tapped
    _hit(engine, victim, dealer, combat=False)                       # "deals combat damage": noncombat is a near miss
    assert not victim.tapped and not victim.skip_next_untap


@pytest.mark.parametrize("name", ["Mercurial Kite", "Queen of Ice // Rage of Winter"])
def test_damaged_creature_that_died_is_not_frozen_or_tapped(name):
    engine = game()
    dealer = card(engine, name)
    victim, bystander = _victim_and_bystander(engine, toughness=LETHAL)
    _hit(engine, victim, dealer)
    assert victim.zone == Zone.GRAVEYARD                              # state-based death precedes the trigger's resolution
    assert not victim.tapped and not victim.skip_next_untap           # RULE 400.7: the new object is not "that creature"
    assert bystander.zone == Zone.BATTLEFIELD and not bystander.tapped and not bystander.skip_next_untap


def test_obelisk_spider_puts_the_counter_on_the_damaged_creature_and_drains():
    engine = game()
    spider = card(engine, "Obelisk Spider")
    victim, bystander = _victim_and_bystander(engine)
    _hit(engine, victim, spider)
    assert victim.counters.get("-1/-1") == 1
    assert not bystander.counters.get("-1/-1") and not spider.counters.get("-1/-1")
    assert engine.state.player_by_id("p2").life == 19 and engine.state.player_by_id("p1").life == 21  # its second ability


def test_obelisk_spider_player_damage_and_dead_victim_put_no_counter():
    engine = game()
    spider = card(engine, "Obelisk Spider")
    victim, bystander = _victim_and_bystander(engine, toughness=LETHAL)
    engine.rules.deal_damage(engine.state.player_by_id("p2"), ONE_DAMAGE, source=spider, combat=True)
    engine.resolve_until_stable()
    assert not victim.counters.get("-1/-1") and not bystander.counters.get("-1/-1")
    _hit(engine, victim, spider)
    assert victim.zone == Zone.GRAVEYARD and not victim.counters.get("-1/-1")
    assert not bystander.counters.get("-1/-1") and not spider.counters.get("-1/-1")
    # Only the one point of player damage cost p2 life; no counter was put, so there was no drain either way.
    assert engine.state.player_by_id("p2").life == 20 - ONE_DAMAGE and engine.state.player_by_id("p1").life == 20


def _equipped(engine):
    sword = card(engine, "Sword of Kaldra")
    carrier = filler(engine, "Carrier", power=1, toughness=SURVIVOR_TOUGHNESS)
    sword.attached_to = carrier.instance_id
    engine.recompute_continuous_effects()
    return sword, carrier


def test_sword_of_kaldra_exiles_the_damaged_creature_not_the_carrier_or_a_bystander():
    engine = game()
    _, carrier = _equipped(engine)
    victim, bystander = _victim_and_bystander(engine)
    _hit(engine, victim, carrier, combat=False)                       # "deals damage": noncombat counts too
    assert victim.zone == Zone.EXILE
    assert carrier.zone == Zone.BATTLEFIELD and bystander.zone == Zone.BATTLEFIELD


def test_sword_of_kaldra_ignores_damage_from_an_unequipped_creature_and_to_a_player():
    engine = game()
    _, carrier = _equipped(engine)
    victim, bystander = _victim_and_bystander(engine)
    other = filler(engine, "Other", power=1, toughness=SURVIVOR_TOUGHNESS)
    _hit(engine, victim, other)
    assert victim.zone == Zone.BATTLEFIELD
    engine.rules.deal_damage(engine.state.player_by_id("p2"), ONE_DAMAGE, source=carrier, combat=True)
    engine.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD and bystander.zone == Zone.BATTLEFIELD


def test_walker_of_secret_ways_looks_at_the_damaged_players_hand_only():
    engine = game(players=3)
    walker = card(engine, "Walker of Secret Ways")
    seen = []
    original = engine.rules.look_at_hand
    engine.rules.look_at_hand = lambda looker, owner, source=None, **kw: (seen.append((looker.id, owner.id)), original(looker, owner, source=source, **kw))[1]
    engine.rules.deal_damage(engine.state.player_by_id("p3"), ONE_DAMAGE, source=walker, combat=True)
    engine.resolve_until_stable()
    assert seen == [("p1", "p3")]                                      # the damaged player, not the other opponent
    seen.clear()
    victim, _ = _victim_and_bystander(engine)
    _hit(engine, victim, walker)                                       # damage to a creature: no hand is looked at
    assert seen == []


def _synthetic(oracle):
    from mtg_analyzer.models.cards.card import Card
    return parse_oracle(Card(id="x", name="Syn", type_line="Creature — Spider", is_creature=True, power=1, toughness=1,
                             oracle_text=oracle))


def test_body_naming_the_source_stays_unclaimed():
    # "~" in the body makes its pronouns ambiguous, so the recipient reading is not applied.
    mixed = _synthetic("Whenever ~ deals combat damage to a creature, tap that creature and ~ gains flying until end of turn.")
    assert mixed.coverage != MODELED
