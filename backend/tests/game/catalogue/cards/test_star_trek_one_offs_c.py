"""Star Trek (TRK/TRC) one-off cards, batch C: real cached cards on a real engine."""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, attack, cast, game, on_battlefield, stock_library, vanilla


def _card_in_graveyard(player, name="Grave Land"):
    obj = GameObject(Card(id=name, name=name, type_line="Land", is_land=True), owner_id=player.id, zone=Zone.GRAVEYARD)
    player.graveyard.append(obj)
    return obj


def test_vash_draws_once_per_turn_when_cards_leave_the_graveyard():
    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Vash, Freelance Archaeologist")
    stock_library(engine, "p1", 5)
    first, second = _card_in_graveyard(p1, "One"), _card_in_graveyard(p1, "Two")
    engine.rules.exile(first)
    engine.resolve_until_stable()
    assert len(p1.hand) == 1
    engine.rules.exile(second)  # RULE 603.2: "only once each turn"
    engine.resolve_until_stable()
    assert len(p1.hand) == 1


def test_vash_ignores_the_opponents_graveyard():
    engine, p1, p2 = game()
    on_battlefield(engine, "p1", "Vash, Freelance Archaeologist")
    stock_library(engine, "p1", 3)
    theirs = _card_in_graveyard(p2)
    engine.rules.exile(theirs)
    engine.resolve_until_stable()
    assert not p1.hand


def test_hologram_stalker_returns_a_card_and_makes_one_illusion_per_turn():
    engine, p1, p2 = game("Hologram Stalker")
    _card_in_graveyard(p1)
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    illusions = [o for o in engine.state.battlefield if o.name == "Illusion"]
    assert len(illusions) == 1
    assert (illusions[0].power, illusions[0].toughness) == (3, 3) and illusions[0].card.is_artifact
    assert any(o.name == "Grave Land" for o in p1.hand)


def test_targ_wrangler_sacrifices_a_nonland_permanent_only_after_attacking():
    engine, p1, p2 = game(via_steps=True)
    wrangler = on_battlefield(engine, "p1", "Targ Wrangler")
    fodder = vanilla(engine, "p1", "Fodder")
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert wrangler in engine.state.battlefield and fodder in engine.state.battlefield  # did not attack

    engine, p1, p2 = game(via_steps=True)
    wrangler = on_battlefield(engine, "p1", "Targ Wrangler")
    fodder = vanilla(engine, "p1", "Fodder")
    attack(engine, p1, wrangler)
    advance_to(engine, "end")
    if engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    survivors = {o for o in engine.state.battlefield if o in (wrangler, fodder)}
    assert len(survivors) == 1  # exactly one nonland permanent went


def test_miles_obrien_draws_at_end_step_only_if_a_permanent_was_bounced_this_turn():
    engine, p1, p2 = game("Miles O'Brien, Transporter Ops", via_steps=True)
    stock_library(engine, "p1", 4)
    bounced = vanilla(engine, "p1", "Bounce Me")
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert bounced not in engine.state.battlefield and any(o.name == "Bounce Me" for o in p1.hand)
    hand = len(p1.hand)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 1


def test_miles_obrien_does_not_draw_when_nothing_was_returned():
    engine, p1, p2 = game("Miles O'Brien, Transporter Ops", via_steps=True)
    stock_library(engine, "p1", 4)
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        engine.resolve_pending_choice("decline") if any(
            o["id"] == "decline" for o in engine.state.pending_choice["options"]) else None
    engine.resolve_until_stable()
    hand = len(p1.hand)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand


def test_guinan_counters_new_creatures_and_draws_when_two_or_more_got_one():
    engine, p1, p2 = game()
    guinan = on_battlefield(engine, "p1", "Guinan, Ancient Advisor")
    old = vanilla(engine, "p1", "Old")
    old.turn_entered = None  # entered on an earlier turn
    new_a, new_b = vanilla(engine, "p1", "New A"), vanilla(engine, "p1", "New B")
    stock_library(engine, "p1", 3)
    p1.mana_pool.add_many({"C": 1})
    engine.activate_ability(p1, guinan)
    engine.resolve_until_stable()
    assert new_a.counters.get("+1/+1") == 1 and new_b.counters.get("+1/+1") == 1
    assert old.counters.get("+1/+1", 0) == 0
    assert len(p1.hand) == 1

