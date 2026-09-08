"""Scriv, the Obligator creates and attaches Aura tokens."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _scriv_card():
    return Card(id="sc", name="Scriv, the Obligator",
                type_line="Legendary Creature — Inkling Bird", is_creature=True,
                power=2, toughness=3,
                oracle_text=("Flying, deathtouch\nWhenever Scriv enters or attacks, "
                             "create a white Aura enchantment token named Contract "
                             "attached to target creature an opponent controls. The "
                             "token has enchant creature and \"Whenever enchanted "
                             "creature attacks, it gets +2/+0 until end of turn if it's "
                             "attacking one of your opponents. Otherwise, its controller "
                             "loses 2 life.\""))


def test_registered_and_binds():
    assert is_registered("Scriv, the Obligator")
    assert is_registered("Contract")
    specs = _REGISTRY["scriv, the obligator"]()
    assert len(specs) == 2
    assert {s.trigger["event"] for s in specs} == {"ENTERS_BATTLEFIELD", "ATTACKS"}
    for s in specs:
        s.validate()
    contract = _REGISTRY["contract"]()[0]
    contract.validate()
    assert contract.effects[0].params["selector"] == "attached_permanent_controller"


def test_specs_for_real_card():
    assert specs_for(_scriv_card())


def test_scriv_attack_makes_a_contract_on_an_opponents_creature_that_drains():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    scriv = GameObject(_scriv_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    scriv.controller_id = "p1"
    scriv.summoning_sick = False
    eng.state.add_to_battlefield(scriv)
    bind_from_catalogue(scriv)

    foe = GameObject(Card(id="f", name="Foe", type_line="Creature — Ox",
                          is_creature=True, power=3, toughness=3),
                     owner_id="p2", zone=Zone.BATTLEFIELD)
    foe.controller_id = "p2"
    eng.state.add_to_battlefield(foe)
    eng.recompute_continuous_effects()

    # fire Scriv's ATTACKS trigger
    eng.state.fire_event(GameEvent(EventType.ATTACKS, attacker="Scriv, the Obligator",
                                   player_id="p1", instance_id=scriv.instance_id))
    eng.resolve_until_stable()
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "trigger_target":
        eng.resolve_pending_choice(str(foe.instance_id))
        eng.resolve_until_stable()

    contracts = [o for o in eng.state.battlefield if o.card.name == "Contract"]
    assert len(contracts) == 1
    assert contracts[0].attached_to == foe.instance_id

    # now the enchanted creature (foe) attacks -> its controller (p2) loses 2
    p2 = eng.state.player_by_id("p2")
    life_before = p2.life
    eng.state.fire_event(GameEvent(EventType.ATTACKS, attacker="Foe",
                                   player_id="p2", instance_id=foe.instance_id))
    eng.resolve_until_stable()
    assert p2.life == life_before - 2
