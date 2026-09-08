"""MEC-43 round 3, "small, self-contained" batch (2026-08-25) — Vilis,
Broker of Blood and Volatile Stormdrake, both flagged in BACKLOG.md as
near-free reuses of existing shapes.

Vilis needed only oracle-text recognition: `LIFE_LOST` already exists as
the single choke point for every cause of life loss (`RulesEngine.
lose_life`, including combat/noncombat damage), so "whenever you lose
life, draw that many cards" just needed a `_PLAYER_TRIGGER_CONDITIONS`
entry (mirroring the existing `LIFE_GAINED` one) plus a new `DrawCardEffect.
count_from_trigger_event` param (mirroring `ImpulsiveDrawEffect`/
`CreateTokenEffect`'s own identical field). The same grammar addition
incidentally closed two more cache-wide cards for free (Gonti's
Machinations, Vengeful Warchief), both riding the pre-existing "for the
first time each turn" suffix strip.

Volatile Stormdrake needed a genuine new composite effect
(`ExchangeControlThenEnergySacrificeEffect`): RULE 608.2b's "if you do"
here gates on whether the RULE 701.10 exchange (`ExchangeControlEffect`'s
own shape, already shipped for Gilded Drake) actually happened — a
condition `_apply_effects_partitioned` has no channel to signal between
separate effect instances, so it's bundled into one effect the same way
Temur Sabertooth/Akiri's own "action, if you do, consequence" cards
already are. Building it surfaced a real, general, previously-dormant
bug: the shared pay-or-lose-it machinery (`_can_pay_player_cost`/
`_pay_player_cost`, shared by ward/`sacrifice_unless_pay`/
`counter_unless_pays`) had never learned about `ActivationCost.pay_energy`
at all, so an energy-costed "unless" clause would have always been free
to pay and never actually deducted anything.

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


# ---------------------------------------------------------------------------
# Vilis, Broker of Blood — the new LIFE_LOST player-trigger condition
# ---------------------------------------------------------------------------


def test_vilis_draws_cards_equal_to_life_lost():
    eng = make_engine([creature(f"Filler{i}") for i in range(10)], hand=0)
    p1 = eng.state.player_by_id("p1")
    vilis = GameObject(_named("Vilis, Broker of Blood"), owner_id="p1", zone=Zone.BATTLEFIELD)
    vilis.summoning_sick = False
    bind_from_catalogue(vilis)
    eng.state.add_to_battlefield(vilis)
    before = len(p1.hand)

    eng.rules.lose_life(p1, 3, cause="effect")
    eng.resolve_until_stable()

    assert len(p1.hand) == before + 3


def test_vilis_draws_cards_when_life_is_lost_to_combat_damage():
    # "(Damage causes loss of life.)" -- `deal_damage` routes player damage
    # through the same `lose_life` choke point, so this needs no separate
    # trigger-condition case of its own.
    eng = make_engine([creature(f"Filler{i}") for i in range(10)], hand=0)
    p1 = eng.state.player_by_id("p1")
    vilis = GameObject(_named("Vilis, Broker of Blood"), owner_id="p1", zone=Zone.BATTLEFIELD)
    vilis.summoning_sick = False
    bind_from_catalogue(vilis)
    eng.state.add_to_battlefield(vilis)
    before = len(p1.hand)

    eng.rules.deal_damage(p1, 2)
    eng.resolve_until_stable()

    assert len(p1.hand) == before + 2


def test_vilis_does_not_trigger_on_an_opponents_life_loss():
    eng = make_engine([creature(f"Filler{i}") for i in range(10)], [creature("Bystander")], hand=0)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    vilis = GameObject(_named("Vilis, Broker of Blood"), owner_id="p1", zone=Zone.BATTLEFIELD)
    vilis.summoning_sick = False
    bind_from_catalogue(vilis)
    eng.state.add_to_battlefield(vilis)
    before = len(p1.hand)

    eng.rules.lose_life(p2, 5, cause="effect")
    eng.resolve_until_stable()

    assert len(p1.hand) == before


# ---------------------------------------------------------------------------
# Volatile Stormdrake — the new ExchangeControlThenEnergySacrificeEffect
# ---------------------------------------------------------------------------


def _board_stormdrake_and_target(eng):
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    stormdrake = GameObject(_named("Volatile Stormdrake"), owner_id="p1", zone=Zone.BATTLEFIELD)
    stormdrake.summoning_sick = False
    bind_from_catalogue(stormdrake)
    eng.state.add_to_battlefield(stormdrake)
    target = GameObject(creature("Opposing Beast", cost="{2}{G}"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(target)
    return p1, p2, stormdrake, target


def _fire_stormdrake_etb(eng, stormdrake, target):
    from mtg_analyzer.game.effects.core import GameContext

    context = GameContext(eng.state, eng.rules)
    ability = stormdrake.triggered_abilities[0]
    effect = ability.effects[0]
    effect.apply(context, targets=[target])


def test_volatile_stormdrake_exchange_grants_energy_and_offers_sacrifice_unless_pay():
    eng = make_engine([creature("Filler")], [creature("Filler2")], hand=0)
    p1, p2, stormdrake, target = _board_stormdrake_and_target(eng)

    _fire_stormdrake_etb(eng, stormdrake, target)

    # The exchange itself (RULE 701.10).
    assert stormdrake.controller_id == "p2"
    assert target.controller_id == "p1"
    # "If you do, you get {E}{E}{E}{E}."
    assert p1.counters.get("energy", 0) == 4
    # "...sacrifice that creature unless you pay {E} equal to its mana
    # value" -- Opposing Beast costs {2}{G}, mana value 3.
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "sacrifice_unless_pay"
    assert choice["player_id"] == "p1"


def test_volatile_stormdrake_declining_sacrifices_the_exchanged_creature():
    eng = make_engine([creature("Filler")], [creature("Filler2")], hand=0)
    p1, p2, stormdrake, target = _board_stormdrake_and_target(eng)
    _fire_stormdrake_etb(eng, stormdrake, target)

    eng.rules.resolve_sacrifice_unless_pay_choice("decline")

    assert target not in eng.state.battlefield
    assert any(o is target for o in p2.graveyard)  # RULE 701.16c: to its owner's graveyard
    assert p1.counters.get("energy", 0) == 4  # the energy from "if you do" isn't spent


def test_volatile_stormdrake_paying_energy_keeps_the_exchanged_creature():
    eng = make_engine([creature("Filler")], [creature("Filler2")], hand=0)
    p1, p2, stormdrake, target = _board_stormdrake_and_target(eng)
    _fire_stormdrake_etb(eng, stormdrake, target)
    assert p1.counters.get("energy", 0) == 4

    eng.rules.resolve_sacrifice_unless_pay_choice("pay")

    assert target in eng.state.battlefield
    assert target.controller_id == "p1"
    assert p1.counters.get("energy", 0) == 1  # 4 - 3 (Opposing Beast's mana value)


def test_volatile_stormdrake_no_exchange_against_your_own_creature():
    eng = make_engine([creature("Filler")], [creature("Filler2")], hand=0)
    p1 = eng.state.player_by_id("p1")
    stormdrake = GameObject(_named("Volatile Stormdrake"), owner_id="p1", zone=Zone.BATTLEFIELD)
    stormdrake.summoning_sick = False
    bind_from_catalogue(stormdrake)
    eng.state.add_to_battlefield(stormdrake)
    own_creature = GameObject(creature("Own Beast"), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(own_creature)

    _fire_stormdrake_etb(eng, stormdrake, own_creature)

    assert stormdrake.controller_id == "p1"
    assert own_creature.controller_id == "p1"
    assert p1.counters.get("energy", 0) == 0
    assert eng.state.pending_choice is None
