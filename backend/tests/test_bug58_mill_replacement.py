"""BUG-58: milling goes through graveyard replacement effects.

RULE 701.17a: a milled card is put into the graveyard, so RULE 614.1 replacements (Rest in Peace, Leyline of the Void)
exile it instead. RULE 701.17c: it is still a milled card in exile, so "milled this way" picks find it there and "whenever
you mill" triggers fire; RULE 603.6c: "put into your graveyard from your library" triggers do not."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession

_DB = CardDatabase(DB_PATH)
MILL_PAIR = 2  # cards milled by the plain tests
GIGAMOLE_MILL = 3  # Ravenous Gigamole's "mill three cards"
FILLER_DEPTH = 5  # library cards under the milled ones, so a mill never empties it


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _on_battlefield(state, name, controller="p1"):
    obj = GameObject(_DB.get_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _stack(player, names):
    """Put the named real cards on top of ``player``'s library; the last listed is the top card."""
    for _ in range(FILLER_DEPTH):
        player.library.append(GameObject(_DB.get_card("Forest"), owner_id=player.id, zone=Zone.LIBRARY))
    objs = [GameObject(_DB.get_card(n), owner_id=player.id, zone=Zone.LIBRARY) for n in names]
    player.library.extend(objs)
    return objs


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id, card_id=obj.card.id, object=obj.name,
        instance_id=obj.instance_id, object_types=sorted(obj.type_words),
    ))
    engine.resolve_until_stable()


def _record(engine, *types):
    seen = []
    engine.state.subscribe(lambda e: seen.append(e) if e.type in types else None)
    return seen


def test_no_replacement_keeps_today_behaviour():
    engine, state, p1, _ = _engine()
    cards = _stack(p1, ["Grizzly Bears", "Island"])
    seen = _record(engine, EventType.MILLED_CARD)
    engine.rules.mill(p1, MILL_PAIR)
    assert all(c.zone == Zone.GRAVEYARD and c in p1.graveyard for c in cards)
    assert not p1.exile
    assert len(seen) == MILL_PAIR
    assert all(c.milled_exile_incarnation is None for c in cards)


def test_rest_in_peace_exiles_a_self_mill():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    cards = _stack(p1, ["Grizzly Bears", "Island"])
    engine.rules.mill(p1, MILL_PAIR)  # RULE 614.1
    assert all(c.zone == Zone.EXILE and c in p1.exile for c in cards)
    assert not p1.graveyard
    assert all(c.milled_exile_incarnation == c.zone_incarnation for c in cards)


def test_rest_in_peace_exiles_an_opponents_milled_cards():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Rest in Peace", controller="p1")
    engine.recompute_continuous_effects()
    cards = _stack(p2, ["Grizzly Bears", "Island"])
    engine.rules.mill(p2, MILL_PAIR)
    assert all(c in p2.exile for c in cards) and not p2.graveyard


def test_leyline_of_the_void_only_exiles_opponents_cards():
    engine, state, p1, p2 = _engine()
    _on_battlefield(state, "Leyline of the Void", controller="p1")
    engine.recompute_continuous_effects()
    own = _stack(p1, ["Grizzly Bears", "Island"])
    theirs = _stack(p2, ["Grizzly Bears", "Island"])
    engine.rules.mill(p1, MILL_PAIR)
    engine.rules.mill(p2, MILL_PAIR)
    assert all(c in p1.graveyard for c in own) and not p1.exile
    assert all(c in p2.exile for c in theirs) and not p2.graveyard


def test_land_graveyard_trigger_skips_exiled_cards_but_not_graveyard_ones():
    engine, state, p1, _ = _engine()
    shredder = _on_battlefield(state, "Hedge Shredder")  # "one or more land cards are put into your graveyard from your library"
    rip = _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    (island,) = _stack(p1, ["Island"])
    engine.rules.mill(p1, 1)
    engine.resolve_until_stable()
    assert island.zone == Zone.EXILE  # replaced, so the trigger never fired
    assert shredder.zone == Zone.BATTLEFIELD and island not in state.battlefield
    engine.rules.destroy(rip)
    engine.recompute_continuous_effects()
    (forest,) = _stack(p1, ["Forest"])
    engine.rules.mill(p1, 1)
    engine.resolve_until_stable()
    assert forest in state.battlefield  # RULE 603.6c control: with no replacement it still triggers


def test_mill_events_still_fire_and_graveyard_arrivals_do_not():
    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _stack(p1, ["Grizzly Bears", "Island"])
    milled_event = _record(engine, EventType.MILL)
    batch = _record(engine, EventType.CARDS_MILLED)
    arrivals = _record(engine, EventType.MILLED_CARD)
    nonland = _record(engine, EventType.MILL_CARD)
    engine.rules.mill(p1, MILL_PAIR)
    assert len(milled_event) == 1 and milled_event[0]["count"] == MILL_PAIR  # "whenever you mill" (RULE 701.17)
    assert [c["to_zone"] for c in batch[0]["cards"]] == ["exile"] * MILL_PAIR
    assert not arrivals  # nothing was put into a graveyard
    assert len(nonland) == 1  # the milled Grizzly Bears is still a milled nonland card


def test_cards_put_into_graveyard_history_ignores_exiled_milled_cards():
    from mtg_analyzer.models.game.turn_history import creature_card_to_graveyard

    engine, state, p1, _ = _engine()
    rip = _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    _stack(p1, ["Grizzly Bears"])
    engine.rules.mill(p1, 1)
    assert "p1" not in creature_card_to_graveyard(state.event_log)
    engine.rules.destroy(rip)
    engine.recompute_continuous_effects()
    _stack(p1, ["Grizzly Bears"])
    engine.rules.mill(p1, 1)
    assert "p1" in creature_card_to_graveyard(state.event_log)


def _gigamole_setup(rip=True):
    engine, state, p1, _ = _engine()
    if rip:
        _on_battlefield(state, "Rest in Peace", controller="p2")
        engine.recompute_continuous_effects()
    # Ravenous Gigamole: "mill three cards. You may put a creature card from among the cards milled this way into your hand"
    land, bear, other_land = _stack(p1, ["Island", "Grizzly Bears", "Forest"])
    mole = _on_battlefield(state, "Ravenous Gigamole")
    _enter(engine, mole)
    return engine, state, p1, mole, (land, bear, other_land)


def test_gigamole_pick_still_offers_a_milled_creature_that_went_to_exile():
    engine, state, p1, mole, (_, bear, _) = _gigamole_setup()
    assert bear.zone == Zone.EXILE  # RULE 614.1
    offered = {o["id"] for o in state.pending_choice["options"] if o["id"] != "decline"}
    assert offered == {str(bear.instance_id)}  # RULE 701.17c, per the Gigamole ruling
    engine.resolve_pending_choice(str(bear.instance_id))
    engine.resolve_until_stable()
    assert bear in p1.hand and bear not in p1.exile
    assert mole.counters.get("+1/+1", 0) == 0


def test_gigamole_declining_under_rest_in_peace_still_grows_it():
    engine, state, p1, mole, (_, bear, _) = _gigamole_setup()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert bear.zone == Zone.EXILE and mole.counters.get("+1/+1", 0) == 1


def test_gigamole_pick_without_replacement_is_unchanged():
    engine, state, p1, mole, (_, bear, _) = _gigamole_setup(rip=False)
    assert bear.zone == Zone.GRAVEYARD
    engine.resolve_pending_choice(str(bear.instance_id))
    engine.resolve_until_stable()
    assert bear in p1.hand


def test_pick_forgets_an_exiled_milled_card_that_moved_on():
    engine, state, p1, mole, (_, bear, _) = _gigamole_setup()
    state.pending_choice = None
    state.deferred_effects.clear()
    engine.rules.return_from_graveyard(bear, "hand")  # leaves that exile visit (RULE 400.7)
    engine.rules.exile(bear)  # a new exile visit that was not milled
    assert bear.milled_exile_incarnation != bear.zone_incarnation


def test_gigamole_pick_through_game_session_and_rewind():
    engine, state, p1, mole, (_, bear, _) = _gigamole_setup()
    session = GameSession(engine)
    pick = {"type": "choose", "option_id": str(bear.instance_id)}

    def offered_ids():
        return {a["option_id"] for a in session.legal_actions() if a.get("type") == "choose"}

    assert str(bear.instance_id) in offered_ids()
    session.apply_action(pick)
    assert bear in p1.hand
    session.rewind(1)  # undo must restore the exile visit and its milled marker
    restored = session.engine.state.find_object(bear.instance_id)
    assert restored.zone == Zone.EXILE
    assert restored.milled_exile_incarnation == restored.zone_incarnation
    assert str(bear.instance_id) in offered_ids()


def test_zone_return_batch_takes_a_milled_card_from_exile_onto_the_battlefield():
    from mtg_analyzer.game.effects.battlefield_batches import GRAVEYARD_OR_EXILE, start_zone_return_batch

    engine, state, p1, _ = _engine()
    _on_battlefield(state, "Rest in Peace")
    engine.recompute_continuous_effects()
    bear, = _stack(p1, ["Grizzly Bears"])
    engine.rules.mill(p1, 1)
    assert bear.zone == Zone.EXILE
    start_zone_return_batch(engine.rules, [(bear.instance_id, bear.zone_incarnation)], GRAVEYARD_OR_EXILE, "p1",
                            source=bear)
    engine.resolve_until_stable()
    assert bear in state.battlefield and bear not in p1.exile
