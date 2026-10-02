"""Hand-authored cards of the saved "Counter Intelligence" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1


def _dispatch(artifacts):
    engine, p1 = _game("Dispatch")
    for i in range(artifacts):
        battlefield_object(engine, "p1", f"Trinket {i}", "Artifact")
    victim = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    p1.mana_pool.add_many({"W": 1})
    engine.cast_spell(p1, p1.hand[0], targets=[victim])
    engine.resolve_until_stable()
    return engine, victim


def test_dispatch_taps_and_with_metalcraft_exiles_the_creature():
    engine, victim = _dispatch(artifacts=3)
    assert victim.zone == Zone.EXILE

    engine, victim = _dispatch(artifacts=2)
    assert victim in engine.state.battlefield and victim.tapped  # tapped only, no metalcraft


def test_soul_guide_lantern_exiles_only_opponents_graveyards():
    engine, p1 = _game()
    p2 = engine.state.player_by_id("p2")
    lantern = battlefield_object(engine, "p1", "Soul-Guide Lantern", "Artifact")
    bind_from_catalogue(lantern)
    mine = GameObject(Card(id="m", name="Mine", type_line="Instant"), owner_id="p1", zone=Zone.GRAVEYARD)
    theirs = GameObject(Card(id="t", name="Theirs", type_line="Instant"), owner_id="p2", zone=Zone.GRAVEYARD)
    p1.graveyard.append(mine)
    p2.graveyard.append(theirs)
    ability = next(i for i, a in enumerate(lantern.activated_abilities) if a.cost.raw == "{T}, Sacrifice ~")
    engine.activate_ability(p1, lantern, ability)
    engine.resolve_until_stable()
    assert theirs.zone == Zone.EXILE and not p2.graveyard
    assert mine in p1.graveyard
    assert lantern.zone != Zone.BATTLEFIELD  # sacrificed as a cost


def test_threefold_thunderhulk_makes_gnomes_equal_to_power_on_enter_and_attack():
    engine, p1 = _game("Threefold Thunderhulk")
    hulk = p1.hand[0]
    p1.mana_pool.add_many({"C": 8})
    engine.cast_spell(p1, hulk)
    engine.resolve_until_stable()
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert hulk.zone == Zone.BATTLEFIELD and hulk.counters.get("+1/+1") == 3

    def gnomes():
        return [o for o in engine.state.battlefield if o.name == "Gnome"]

    assert len(gnomes()) == hulk.power
    before = len(gnomes())
    hulk.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": hulk, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert len(gnomes()) == before + hulk.power


def test_darksteel_reactor_wins_when_the_twentieth_charge_counter_lands():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1 = _game()
    reactor = battlefield_object(engine, "p1", "Darksteel Reactor", "Artifact")
    bind_from_catalogue(reactor)

    def upkeep():
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning", player_id="p1"))
        engine.rules.put_triggers_on_stack()
        while engine.state.pending_choice:  # "you may" — accept
            engine.resolve_pending_choice("do")
        engine.resolve_until_stable()

    reactor.counters["charge"] = 18
    upkeep()
    assert reactor.counters["charge"] == 19 and not engine.state.game_over
    upkeep()
    assert reactor.counters["charge"] == 20
    assert engine.state.game_over and engine.state.winner_id == "p1"
