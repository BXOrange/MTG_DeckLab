"""PAR-32 / MEC-58 — Tavern Brawler's two-clause granted trigger:

    Commander creatures you own have "At the beginning of your upkeep,
    exile the top card of your library. This creature gets +X/+0 until
    end of turn, where X is that card's mana value. You may play that
    card this turn."

Hand-authored (`card_registry.special_mechanics._tavern_brawler`): a
`grant_triggered_ability` (STEP_BEGIN/upkeep) whose `grant_effects` chain
two existing primitives — `impulsive_draw` (now also seeding
`GameContext.created_objects` with the exiled card) and `pump`'s new
`amount_from_created_object_mana_value` flag, which reads that seeded
card's mana value.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import card_registry


def test_tavern_brawler_registered_with_both_clauses():
    specs = card_registry.specs_for(
        Card(id="tb", name="Tavern Brawler",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    (grant,) = specs[0].effects
    assert grant.type == "grant_triggered_ability"
    assert grant.params["affects"] == "commander_creatures_you_own"
    assert grant.params["trigger_event"] == "STEP_BEGIN"
    assert grant.params["filter"] == {"step": "upkeep"}
    kinds = [e["type"] for e in grant.params["grant_effects"]]
    assert kinds == ["impulsive_draw", "pump"]
    assert grant.params["grant_effects"][1]["params"]["amount_from_created_object_mana_value"] is True


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _bf(st, card, controller="p1", commander=False):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.is_commander = commander
    st.add_to_battlefield(o)
    return o


def test_upkeep_trigger_exiles_top_card_and_pumps_by_its_mana_value():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="tb", name="Tavern Brawler",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                        is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    threedrop = GameObject(
        Card(id="pyre", name="Fire Elemental", type_line="Creature — Elemental",
             is_creature=True, power=3, toughness=3, mana_cost_string="{2}{R}",
             converted_mana_cost=3),
        owner_id="p1", zone=Zone.LIBRARY,
    )
    p1.library.append(threedrop)

    st.active_player_index = st.players.index(p1)
    st.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="BEGINNING"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()

    assert threedrop in p1.exile
    assert threedrop not in p1.library
    assert threedrop.instance_id in st.temp_play_permissions
    eng.recompute_continuous_effects()
    assert cmd.power == 2 + 3  # +X/+0, X = 3 (Fire Elemental's mana value)
    assert cmd.toughness == 2  # untouched


def test_upkeep_trigger_with_empty_library_pumps_nothing():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="tb", name="Tavern Brawler",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                        is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    st.active_player_index = st.players.index(p1)
    st.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="BEGINNING"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()

    eng.recompute_continuous_effects()
    assert cmd.power == 2
    assert cmd.toughness == 2
