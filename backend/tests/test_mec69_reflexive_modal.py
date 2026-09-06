"""MEC-69 / PAR-58 — modal reflexive continuations (RULE 603.11)."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase

from tests.test_game_engine import make_engine


def _card(name):
    return CardDatabase(DB_PATH).get_card(name)


def test_voltstorm_modal_payoff_is_a_fresh_trigger_with_its_own_mode_choice():
    engine = make_engine([], hand=0)
    state = engine.state
    player = state.player_by_id("p1")
    angel = GameObject(_card("Voltstorm Angel"), owner_id="p1", zone=Zone.BATTLEFIELD)
    angel.summoning_sick = False
    state.add_to_battlefield(angel)
    bind_from_catalogue(angel)
    player.counters["energy"] = 2
    engine.begin_turn()

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    engine.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"

    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    assert player.counters.get("energy", 0) == 0
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "trigger_mode"

    # The modal effect is not part of the just-paid trigger's resolution;
    # it is selected and placed as its own stack object.
    engine.resolve_pending_choice("0")
    engine.resolve_until_stable()
    assert "vigilance" in angel.temp_keywords
    assert "lifelink" in angel.temp_keywords


def test_voltstorm_angel_declined_payment_creates_no_modal_trigger():
    engine = make_engine([], hand=0)
    state = engine.state
    player = state.player_by_id("p1")
    angel = GameObject(_card("Voltstorm Angel"), owner_id="p1", zone=Zone.BATTLEFIELD)
    angel.summoning_sick = False
    state.add_to_battlefield(angel)
    bind_from_catalogue(angel)
    player.counters["energy"] = 2
    engine.begin_turn()

    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    engine.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "pay_cost_then"

    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()

    assert state.pending_choice is None
    assert not angel.temp_keywords
