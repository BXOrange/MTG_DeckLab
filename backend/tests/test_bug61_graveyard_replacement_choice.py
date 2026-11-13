"""BUG-61: competing graveyard replacements are chosen by the affected card's controller.

RULE 616.1: when several replacement effects apply to one event, the affected object's controller (its owner off the
battlefield) chooses which applies first. Dauthi Voidwalker (exile with a void counter) and Rest in Peace / Leyline of
the Void (plain exile) both end in exile, so the move happens at once and only the void counter is left to the choice,
offered as a state-based-action prompt (like RULE 903.9a). RULE 616.1f: nothing is left to apply after the first, since
the card has already left for exile. Identical outcomes (Rest in Peace plus Leyline) never ask."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession

_DB = CardDatabase(DB_PATH)
WIPE_REST = 2  # creatures dying alongside the first in the board-wipe test
FILLER_DEPTH = 5  # library cards under a milled one, so a mill never empties it
CHOICE_KIND = "graveyard_replacement"


def _engine():
    p1 = Player(id="p1", name="Alice", life=20)
    p2 = Player(id="p2", name="Bob", life=20)
    state = GameState(players=[p1, p2])
    return GameEngine(state), state, p1, p2


def _on_battlefield(state, name, controller):
    obj = GameObject(_DB.get_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _board(*redirects):
    """Alice controls the named redirect permanents; Bob's Grizzly Bears is the creature that will die."""
    engine, state, p1, p2 = _engine()
    for name in redirects:
        _on_battlefield(state, name, "p1")
    bear = _on_battlefield(state, "Grizzly Bears", "p2")
    engine.recompute_continuous_effects()
    return engine, state, p1, p2, bear


def _kill(engine, bear):
    engine.rules.destroy(bear)
    engine.rules.check_state_based_actions()


def test_dauthi_alone_still_marks_without_asking():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker")
    _kill(engine, bear)
    assert bear in p2.exile and state.pending_choice is None
    assert state.void_counter_holder[bear.instance_id] == "p1"


def test_rest_in_peace_alone_still_exiles_plainly():
    engine, state, _, p2, bear = _board("Rest in Peace")
    _kill(engine, bear)
    assert bear in p2.exile and state.pending_choice is None
    assert bear.instance_id not in state.void_counter_holder


def test_rest_in_peace_plus_leyline_never_asks():
    engine, state, _, p2, bear = _board("Rest in Peace", "Leyline of the Void")
    _kill(engine, bear)
    assert bear in p2.exile and state.pending_choice is None  # RULE 616.1: identical outcomes
    assert bear.instance_id not in state.void_counter_holder


def test_dauthi_plus_rest_in_peace_asks_the_creatures_controller():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    _kill(engine, bear)
    pending = state.pending_choice
    assert pending["kind"] == CHOICE_KIND and pending["player_id"] == "p2"  # not the Dauthi controller
    assert bear in p2.exile  # RULE 616.1f: it has already left for exile either way


def test_choosing_the_void_counter_marks_the_card():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    _kill(engine, bear)
    engine.resolve_pending_choice([str(bear.instance_id)])
    assert state.void_counter_holder[bear.instance_id] == "p1" and state.pending_choice is None


def test_choosing_plain_exile_leaves_no_counter():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    _kill(engine, bear)
    engine.resolve_pending_choice("decline")
    assert bear in p2.exile and bear.instance_id not in state.void_counter_holder


def test_a_board_wipe_asks_once_and_the_chooser_picks_a_subset():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    others = [_on_battlefield(state, "Grizzly Bears", "p2") for _ in range(WIPE_REST)]
    engine.recompute_continuous_effects()
    for victim in [bear, *others]:
        engine.rules.destroy(victim)
    engine.rules.check_state_based_actions()
    offered = {o["id"] for o in state.pending_choice["options"] if o["id"] != "decline"}
    assert offered == {str(v.instance_id) for v in [bear, *others]}  # RULE 616.1: one prompt, a pick per card
    engine.resolve_pending_choice([str(bear.instance_id)])  # only one of the three takes the void counter
    assert state.void_counter_holder == {bear.instance_id: "p1"}
    assert all(v in p2.exile for v in [bear, *others]) and state.pending_choice is None


def test_a_token_is_not_asked():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    bear.is_token = True
    _kill(engine, bear)
    assert state.pending_choice is None  # RULE 704.5d: a token ceases to exist in exile whichever applies


def test_mill_under_dauthi_and_rest_in_peace_asks_the_owner():
    engine, state, p1, p2, _ = _board("Dauthi Voidwalker", "Rest in Peace")
    for _ in range(FILLER_DEPTH):
        p2.library.append(GameObject(_DB.get_card("Forest"), owner_id="p2", zone=Zone.LIBRARY))
    top = GameObject(_DB.get_card("Island"), owner_id="p2", zone=Zone.LIBRARY)
    p2.library.append(top)
    engine.rules.mill(p2, 1)
    engine.rules.check_state_based_actions()
    assert top in p2.exile and state.pending_choice["player_id"] == "p2"  # RULE 616.1: the owner chooses
    engine.resolve_pending_choice([str(top.instance_id)])
    assert state.void_counter_holder[top.instance_id] == "p1"


def test_session_flow_offers_both_options_and_undo_restores_the_prompt():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    session = GameSession(engine)
    engine.rules.destroy(bear)
    engine.rules.check_state_based_actions()
    options = {a["option_id"] for a in session.legal_actions() if a.get("type") == "choose"}
    assert str(bear.instance_id) in options
    selection_id = state.pending_choice["selection_id"]
    session.apply_action({"type": "choose", "selection_id": selection_id, "option_ids": [str(bear.instance_id)]})
    assert session.engine.state.void_counter_holder[bear.instance_id] == "p1"
    session.rewind(1)  # the pending prompt must survive undo/clone
    restored = session.engine.state
    assert restored.pending_choice["kind"] == CHOICE_KIND
    assert bear.instance_id not in restored.void_counter_holder


def test_bot_default_takes_the_plain_exile():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker", "Rest in Peace")
    session = GameSession(engine)
    engine.rules.destroy(bear)
    engine.rules.check_state_based_actions()
    session.apply_action({"type": "decline"})  # what a bot's generic fallback answers
    assert bear.instance_id not in session.engine.state.void_counter_holder


# --- exile classes vs the library class (Colossus-style "shuffle it into its owner's library instead") -------------

PLENTY_OF_MANA = 6  # comfortably above Nexus of Fate's cost
NEXUS_BLUE_PIPS = 2  # {5}{U}{U}
LIBRARY_BASE = 5  # cards already in the library, so a shuffled-in card is distinguishable from an empty library


def _fill_library(player):
    for _ in range(LIBRARY_BASE):
        player.library.append(GameObject(_DB.get_card("Forest"), owner_id=player.id, zone=Zone.LIBRARY))


def test_rest_in_peace_plus_legacy_weapon_destroyed_goes_to_the_library():
    engine, state, p1, p2, _ = _board("Rest in Peace")
    weapon = _on_battlefield(state, "Legacy Weapon", "p2")
    engine.recompute_continuous_effects()
    engine.rules.destroy(weapon)  # RULE 616.1: library (default, beneficial) over Rest in Peace's exile
    assert weapon in p2.library and weapon not in p2.exile and state.pending_choice is None


def test_rest_in_peace_plus_blightsteel_sacrificed_goes_to_the_library():
    engine, state, p1, p2, _ = _board("Rest in Peace")
    colossus = _on_battlefield(state, "Blightsteel Colossus", "p2")
    engine.recompute_continuous_effects()
    engine.rules.put_into_graveyard(colossus)
    assert colossus in p2.library and not p2.exile


def test_library_class_also_beats_dauthi_without_a_prompt():
    engine, state, p1, p2, _ = _board("Dauthi Voidwalker", "Rest in Peace")
    weapon = _on_battlefield(state, "Legacy Weapon", "p2")
    engine.recompute_continuous_effects()
    engine.rules.destroy(weapon)
    engine.rules.check_state_based_actions()
    assert weapon in p2.library and state.pending_choice is None and not state.void_counter_holder


def test_nexus_of_fate_resolving_under_rest_in_peace_is_shuffled_in_by_its_owner():
    engine, state, p1, p2, _ = _board("Rest in Peace")
    _fill_library(p1)
    nexus = GameObject(_DB.get_card("Nexus of Fate"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(nexus)
    p1.hand.append(nexus)
    engine.begin_turn()
    state.current_step = "main1"
    p1.mana_pool.add_many({"C": PLENTY_OF_MANA, "U": NEXUS_BLUE_PIPS})
    engine.cast_spell(p1, nexus)
    engine.resolve_until_stable()
    assert nexus in p1.library and nexus not in p1.exile and nexus not in p1.graveyard  # off the battlefield too


def test_dauthi_plus_finality_counter_asks_the_controller():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker")
    bear.add_counters("finality", 1)
    _kill(engine, bear)
    assert state.pending_choice["kind"] == CHOICE_KIND and state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice([str(bear.instance_id)])
    assert state.void_counter_holder[bear.instance_id] == "p1"


def test_dauthi_plus_yawgmoths_will_turn_redirect_asks_the_owner():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker")
    p2.graveyard_redirect_to_exile_until_turn = state.internal_turn.number
    _kill(engine, bear)
    assert state.pending_choice["kind"] == CHOICE_KIND
    engine.resolve_pending_choice("decline")
    assert bear in p2.exile and bear.instance_id not in state.void_counter_holder


def test_dauthi_plus_a_would_die_exile_replacement_asks_the_controller():
    engine, state, _, p2, _ = _board("Dauthi Voidwalker")
    shrieker = _on_battlefield(state, "Gloomshrieker", "p2")
    engine.recompute_continuous_effects()
    _kill(engine, shrieker)
    assert shrieker in p2.exile and state.pending_choice["kind"] == CHOICE_KIND


def test_dauthi_plus_finality_prompt_survives_undo():
    engine, state, _, p2, bear = _board("Dauthi Voidwalker")
    bear.add_counters("finality", 1)
    session = GameSession(engine)
    engine.rules.destroy(bear)
    engine.rules.check_state_based_actions()
    selection_id = state.pending_choice["selection_id"]
    session.apply_action({"type": "choose", "selection_id": selection_id, "option_ids": [str(bear.instance_id)]})
    session.rewind(1)
    assert session.engine.state.pending_choice["kind"] == CHOICE_KIND
