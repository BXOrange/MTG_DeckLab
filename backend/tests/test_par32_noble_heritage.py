"""PAR-32 / MEC-62 — Noble Heritage's compound trigger + per-player
counters + protection:

    Commander creatures you own have "When this creature enters and at
    the beginning of your upkeep, each player may put two +1/+1 counters
    on a creature they control. For each opponent who does, you gain
    protection from that player until your next turn."

Hand-authored (`card_registry.special_mechanics._noble_heritage`): a
compound ENTERS_BATTLEFIELD + STEP_BEGIN/upkeep grant sharing one
`each_player_counter_then_protection` effect body
(`EachPlayerMayCounterThenProtectionEffect`). The ETB half is subject to
the same pre-existing granted-ETB-timing gap Master Chef/Candlekeep Sage
already document (a grant isn't computed onto an object until *after*
it's already on the battlefield, so it can't fire off its own entry) —
only the upkeep half is exercised here, the same way `test_par32_tavern_
brawler.py` only exercises its own granted upkeep trigger.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import card_registry


def test_noble_heritage_registered_with_compound_trigger():
    specs = card_registry.specs_for(
        Card(id="nh", name="Noble Heritage",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    grants = specs[0].effects
    assert len(grants) == 2
    events = sorted(g.params["trigger_event"] for g in grants)
    assert events == ["ENTERS_BATTLEFIELD", "STEP_BEGIN"]
    for g in grants:
        assert g.type == "grant_triggered_ability"
        assert g.params["affects"] == "commander_creatures_you_own"
        (effect,) = g.params["grant_effects"]
        assert effect["type"] == "each_player_counter_then_protection"
    upkeep = next(g for g in grants if g.params["trigger_event"] == "STEP_BEGIN")
    assert upkeep.params["filter"] == {"step": "upkeep"}
    assert upkeep.params["phase_relation"] == "you"


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


def test_upkeep_counters_both_players_and_grants_protection():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="nh", name="Noble Heritage",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                        is_creature=True, power=2, toughness=2), commander=True)
    p2_creature = _bf(st, Card(id="e", name="Enemy Bear", type_line="Creature — Bear",
                                is_creature=True, power=2, toughness=2), controller="p2")
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    p2 = st.player_by_id("p2")
    st.active_player_index = st.players.index(p1)
    st.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="BEGINNING"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()

    assert cmd.counters.get("+1/+1", 0) == 2  # p1's own creature accepted
    assert p2_creature.counters.get("+1/+1", 0) == 2  # p2 (opponent) accepted

    # p1 gained protection from p2 until p1's next turn: damage from a
    # source p2 controls is prevented …
    eng.rules.deal_damage(p1, 5, source=p2_creature)
    assert p1.life == 20
    # … but an unrelated (p1-controlled) source's damage isn't.
    eng.rules.deal_damage(p1, 3, source=cmd)
    assert p1.life == 17


def test_opponent_with_no_creature_grants_no_protection():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="nh", name="Noble Heritage",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Cmdr", type_line="Legendary Creature — Human",
                        is_creature=True, power=2, toughness=2), commander=True)
    eng.recompute_continuous_effects()

    p1 = st.player_by_id("p1")
    p2 = st.player_by_id("p2")  # no creature at all
    st.active_player_index = st.players.index(p1)
    st.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="BEGINNING"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()

    assert cmd.counters.get("+1/+1", 0) == 2
    assert not any(
        getattr(e, "protected_from_player_id", None) == "p2"
        for e in p1.player_effects
    )
