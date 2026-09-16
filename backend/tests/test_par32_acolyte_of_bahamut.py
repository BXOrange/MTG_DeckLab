"""PAR-32 / MEC-60 — Acolyte of Bahamut's granted per-turn-first cost
reduction:

    Commander creatures you own have "The first Dragon spell you cast
    each turn costs {2} less to cast."

Hand-authored (`card_registry.special_mechanics._acolyte_of_bahamut`): a
granted `cost_reduction` static (MEC-55's `grant_static_ability`
`static_specs`, already-existing `spell_subtype`/`active_if` params) gated
by a new `static_conditions` kind `first_subtype_spell_this_turn`, reading
a new `GameState.creature_type_spells_cast_this_turn` tracker populated by
`RulesEngine._track_spell_cast` off each cast object's live subtypes.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.game import card_registry


def test_acolyte_of_bahamut_registered_with_gated_cost_reduction():
    specs = card_registry.specs_for(
        Card(id="ab", name="Acolyte of Bahamut",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    (grant,) = specs[0].effects
    assert grant.type == "grant_static_ability"
    assert grant.params["affects"] == "commander_creatures_you_own"
    (inner,) = grant.params["static_specs"]
    assert inner["type"] == "cost_reduction"
    p = inner["params"]
    assert p["generic"] == 2
    assert p["spell_subtype"] == "Dragon"
    assert p["active_if"] == {"kind": "first_subtype_spell_this_turn", "subtype": "Dragon"}


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


def _dragon_spell(iid="d1"):
    return GameObject(
        Card(id=iid, name="Shivan Dragon", type_line="Creature — Dragon",
             is_creature=True, power=5, toughness=5),
        owner_id="p1", zone=Zone.STACK,
    )


def test_first_dragon_spell_this_turn_gets_the_discount():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ab", name="Acolyte of Bahamut",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    dragon = _dragon_spell()
    net, contributors = continuous.cost_reduction_for(st, p1, dragon)
    assert net == 2
    assert contributors


def test_non_dragon_spell_gets_no_discount():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ab", name="Acolyte of Bahamut",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    bear = GameObject(
        Card(id="b", name="Grizzly Bear", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.STACK,
    )
    net, _ = continuous.cost_reduction_for(st, p1, bear)
    assert net == 0


def test_second_dragon_spell_this_turn_gets_no_discount():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ab", name="Acolyte of Bahamut",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    first_dragon = _dragon_spell("d1")
    st.stack.append(StackItem(kind="spell", controller_id="p1", obj=first_dragon))
    # Simulate the first Dragon spell actually being cast this turn (the
    # real choke point every cast path funnels SPELL_CAST through).
    st.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p1", instance_id=first_dragon.instance_id,
        object_types=sorted(first_dragon.type_words),
    ))
    assert "dragon" in st.creature_type_spells_cast_this_turn.get("p1", set())

    second_dragon = _dragon_spell("d2")
    net, _ = continuous.cost_reduction_for(st, p1, second_dragon)
    assert net == 0


def test_tracker_resets_next_turn():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ab", name="Acolyte of Bahamut",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                 is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    first_dragon = _dragon_spell("d1")
    item = StackItem(kind="spell", controller_id="p1", obj=first_dragon)
    st.stack.append(item)
    st.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id="p1", instance_id=first_dragon.instance_id,
        object_types=sorted(first_dragon.type_words),
    ))
    st.stack.remove(item)

    eng.begin_turn()
    net, _ = continuous.cost_reduction_for(st, p1, _dragon_spell("d3"))
    assert net == 2
