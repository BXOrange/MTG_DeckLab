"""PAR-287 milestone 3 (A): "that creature / that planeswalker / that player" under a damage head names the right party.

RULE 120.3: a damage event has a dealer and a recipient. Under "whenever a <dealer> deals damage to a <recipient>" a body's
"that <recipient noun>" is the recipient (read off the event's `target_id`), not the dealer the group dispatch used to
stamp; a noun both parties share is refused. Under "whenever equipped / enchanted creature deals damage to a player",
"that player" is the player the damage hit, not the host's controller. Every behaviour test runs the real card with a
same-type bystander, the dealer, and (for players) a third seat that must stay untouched.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, card, filler, game

#: A victim with this toughness survives the small hits below.
SURVIVOR_TOUGHNESS = 4
ONE_DAMAGE = 1
#: A planeswalker's starting loyalty: enough to survive a one-damage hit so the destroy is the trigger's doing.
LOYALTY = 5
#: The test hosts start with this many cards in hand and library, so a discard / mill is a visible delta.
HAND = 4
LIBRARY = 10
EQUIPPED_DAMAGE = 2

CORRECTED = ["Toxin Sliver", "Zagras, Thief of Heartbeats", "Hooded Blightfang", "Elder Mastery", "Specter's Shroud",
             "Sword of Body and Mind"]


def _planeswalker(engine, name="Walker", player="p2"):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject
    obj = GameObject(Card(id=name, name=name, type_line="Legendary Planeswalker — Test", loyalty=LOYALTY),
                     owner_id=player, zone=Zone.BATTLEFIELD)
    obj.controller_id = player
    obj.counters["loyalty"] = LOYALTY
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _hit(engine, recipient, source, combat=True, amount=ONE_DAMAGE):
    engine.rules.deal_damage(recipient, amount, source=source, combat=combat)
    engine.resolve_until_stable()
    answer(engine)
    engine.resolve_until_stable()


@pytest.mark.parametrize("name", CORRECTED)
def test_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


# --- group damage heads: "that creature" / "that planeswalker" is the recipient -------------------------------

def test_toxin_sliver_destroys_the_damaged_creature_not_the_sliver_or_a_bystander():
    engine = game()
    sliver = card(engine, "Toxin Sliver")
    other_sliver = filler(engine, "Other Sliver", type_line="Creature — Sliver", power=1, toughness=SURVIVOR_TOUGHNESS)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=SURVIVOR_TOUGHNESS)
    bystander = filler(engine, "Bystander", player="p2", power=1, toughness=SURVIVOR_TOUGHNESS)
    _hit(engine, victim, other_sliver)                       # "a Sliver" is any Sliver, not only Toxin Sliver itself
    assert victim.zone == Zone.GRAVEYARD
    assert sliver.zone == Zone.BATTLEFIELD and other_sliver.zone == Zone.BATTLEFIELD   # the dealer was the old victim
    assert bystander.zone == Zone.BATTLEFIELD


def test_toxin_sliver_near_misses_destroy_nothing():
    engine = game()
    card(engine, "Toxin Sliver")
    sliver = filler(engine, "Other Sliver", type_line="Creature — Sliver", power=1, toughness=SURVIVOR_TOUGHNESS)
    plain = filler(engine, "Plain", power=1, toughness=SURVIVOR_TOUGHNESS)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=SURVIVOR_TOUGHNESS)
    _hit(engine, victim, sliver, combat=False)               # "deals combat damage": noncombat is a near miss
    _hit(engine, victim, plain)                               # a non-Sliver dealer
    engine.rules.deal_damage(engine.state.player_by_id("p2"), ONE_DAMAGE, source=sliver, combat=True)
    engine.resolve_until_stable()                             # damage to a player, not a creature
    assert victim.zone == Zone.BATTLEFIELD and sliver.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("name", ["Zagras, Thief of Heartbeats", "Hooded Blightfang"])
def test_planeswalker_destroy_hits_the_damaged_walker_not_the_dealer_or_another_walker(name):
    engine = game()
    source = card(engine, name)                               # Blightfang has deathtouch itself; Zagras's "a creature you control"
    walker = _planeswalker(engine, "Hit Walker")
    other_walker = _planeswalker(engine, "Other Walker")
    _hit(engine, walker, source)
    assert walker.zone == Zone.GRAVEYARD
    assert other_walker.zone == Zone.BATTLEFIELD and source.zone == Zone.BATTLEFIELD


@pytest.mark.parametrize("name", ["Zagras, Thief of Heartbeats", "Hooded Blightfang"])
def test_planeswalker_destroy_near_misses(name):
    engine = game()
    source = card(engine, name)
    walker = _planeswalker(engine)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=SURVIVOR_TOUGHNESS)
    _hit(engine, victim, source)                               # damage to a creature: no planeswalker is destroyed
    # (Both sources carry deathtouch, so the victim itself dies: the point is the walker is untouched.)
    assert walker.zone == Zone.BATTLEFIELD and source.zone == Zone.BATTLEFIELD


def test_hooded_blightfang_needs_deathtouch_on_the_dealer():
    engine = game()
    card(engine, "Hooded Blightfang")
    plain = filler(engine, "Plain", power=1, toughness=SURVIVOR_TOUGHNESS)
    walker = _planeswalker(engine)
    _hit(engine, walker, plain)
    assert walker.zone == Zone.BATTLEFIELD


def test_zagras_ignores_an_opponents_creature_dealing_damage():
    engine = game()
    card(engine, "Zagras, Thief of Heartbeats")
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=SURVIVOR_TOUGHNESS)
    walker = _planeswalker(engine, player="p1")
    _hit(engine, walker, theirs)                               # "a creature you control": an opponent's creature does not count
    assert walker.zone == Zone.BATTLEFIELD


def test_a_noun_shared_by_dealer_and_recipient_is_refused():
    # "a creature ... deals damage to a creature, ... that creature" names either party: no silent guess.
    ambiguous = _synthetic(
        "Whenever a creature you control deals combat damage to a creature, put a -1/-1 counter on that creature.")
    assert ambiguous.coverage != MODELED


def test_dealer_noun_still_reads_the_dealer():
    # Liliana's Talent: the recipient is the enchanted planeswalker, "that creature" is the dealer (unchanged reading).
    talent = parse_oracle(CardDatabase(DB_PATH).get_card("Liliana's Talent"))
    assert talent.coverage == MODELED
    trig = [s for s in talent.specs if s.ability_kind == "triggered" and "deals damage" in s.raw_text][0]
    assert trig.effects[0].params["event_key"] == "__group_subject__"


def _synthetic(oracle, type_line="Creature — Spider"):
    return parse_oracle(Card(id="x", name="Syn", type_line=type_line, is_creature="Creature" in type_line,
                             power=1, toughness=1, oracle_text=oracle))


# --- attached damage heads: "that player" is the damaged player -------------------------------------------------

def _hand_library_life(engine):
    return {p.id: (p.life, len(p.hand), len(p.library)) for p in engine.state.players}


def _hosted(name, damaged="p3"):
    engine = game(players=3, library=LIBRARY)
    host = filler(engine, "Carrier", power=EQUIPPED_DAMAGE, toughness=EQUIPPED_DAMAGE)
    attachment = card(engine, name)
    attachment.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    for pid in ("p1", "p2", "p3"):
        for i in range(HAND):
            filler(engine, f"Card {pid}{i}", player=pid, zone=Zone.HAND, power=1, toughness=1)
    return engine, host


@pytest.mark.parametrize("name,discards", [("Elder Mastery", 2), ("Specter's Shroud", 1)])
@pytest.mark.parametrize("damaged,other", [("p3", "p2"), ("p2", "p3")])
def test_that_player_discards_is_the_damaged_opponent(name, discards, damaged, other):
    engine, host = _hosted(name)
    before = _hand_library_life(engine)
    _hit(engine, engine.state.player_by_id(damaged), host, amount=EQUIPPED_DAMAGE)
    after = _hand_library_life(engine)
    assert after[damaged][1] == before[damaged][1] - discards
    assert after[other][1] == before[other][1] and after["p1"][1] == before["p1"][1]   # not the other opponent, not the controller


@pytest.mark.parametrize("name", ["Elder Mastery", "Specter's Shroud"])
def test_no_discard_when_the_host_damages_a_creature(name):
    engine, host = _hosted(name)
    victim = filler(engine, "Victim", player="p3", power=1, toughness=SURVIVOR_TOUGHNESS)
    before = _hand_library_life(engine)
    _hit(engine, victim, host, amount=EQUIPPED_DAMAGE)
    assert _hand_library_life(engine) == before


def test_sword_of_body_and_mind_mills_the_damaged_player_and_makes_a_wolf_for_the_controller():
    engine, host = _hosted("Sword of Body and Mind")
    before = _hand_library_life(engine)
    _hit(engine, engine.state.player_by_id("p3"), host, amount=EQUIPPED_DAMAGE)
    after = _hand_library_life(engine)
    assert after["p3"][2] == 0                                 # milled ten
    assert after["p2"][2] == before["p2"][2] and after["p1"][2] == before["p1"][2]
    wolves = [o for o in engine.state.battlefield if o.name == "Wolf"]
    assert len(wolves) == 1 and wolves[0].controller_id == "p1"


def test_sword_of_body_and_mind_does_nothing_for_creature_damage():
    engine, host = _hosted("Sword of Body and Mind")
    victim = filler(engine, "Victim", player="p3", power=1, toughness=SURVIVOR_TOUGHNESS)
    before = _hand_library_life(engine)
    _hit(engine, victim, host, amount=EQUIPPED_DAMAGE)
    assert _hand_library_life(engine) == before
    assert not [o for o in engine.state.battlefield if o.name == "Wolf"]


def test_neko_te_life_loss_reads_the_damaged_player():
    # The card's other ability (a no-untap duration) is still unmodelled, but its life-loss line no longer claims the host's controller.
    neko = parse_oracle(CardDatabase(DB_PATH).get_card("Neko-Te"))
    life = [s for s in neko.specs if s.ability_kind == "triggered" and "loses 1 life" in s.raw_text][0]
    assert life.effects[0].params["player"] == {"of": "damaged_player"}


def test_neko_te_sentence_executes_on_the_damaged_opponent():
    oracle = "Equipped creature gets +0/+0.\nWhenever equipped creature deals damage to a player, that player loses 1 life.\nEquip {2}"
    engine = game(players=3)
    host = filler(engine, "Carrier", power=EQUIPPED_DAMAGE, toughness=EQUIPPED_DAMAGE)
    gear = filler(engine, "Gear", type_line="Artifact — Equipment", oracle_text=oracle)
    assert parse_oracle(gear.card).coverage == MODELED
    gear.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    _hit(engine, engine.state.player_by_id("p3"), host, amount=EQUIPPED_DAMAGE)
    assert [p.life for p in engine.state.players] == [20, 20, 20 - EQUIPPED_DAMAGE - 1]
