"""Bug report, 2026-09-04: Sam, Loyal Attendant never created its Food
token at the beginning of combat, and Ardenn, Intrepid Archaeologist's own
"at the beginning of combat" trigger never fired either. Both catalogue
entries filtered a `STEP_BEGIN` event on ``{"step": "combat"}`` — but
`game/phases.py`'s real step name is ``"begin_combat"`` (RULE 507), which
`GameEngine._step_body`/`turn_loop_mixin.py` stamps onto the event's own
``step`` field — so the filter could never match at all, silently.

Reference: `game/ability_catalogue/entries_006.py` (Sam), `entries_007.py`
(Ardenn), `game/phases.py`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _sam(state, controller="p1"):
    card = Card(
        id="Sam, Loyal Attendant", name="Sam, Loyal Attendant",
        type_line="Legendary Creature — Halfling Scout", is_creature=True, power=1, toughness=1,
        oracle_text=(
            "Partner with Frodo, Adventurous Hobbit\nAt the beginning of combat on your "
            "turn, create a Food token.\nActivated abilities of Foods you control cost "
            "{1} less to activate."
        ),
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _ardenn(state, controller="p1"):
    card = Card(
        id="Ardenn, Intrepid Archaeologist", name="Ardenn, Intrepid Archaeologist",
        type_line="Legendary Creature — Human Rogue", is_creature=True, power=1, toughness=3,
        oracle_text=(
            "At the beginning of combat on your turn, you may attach any number of "
            "Auras and Equipment you control to target permanent or player.\nPartner "
            "(You can have two commanders if both have partner.)"
        ),
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_sam_creates_a_food_token_at_the_beginning_of_combat():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _sam(eng.state, controller=p1.id)

    eng.state.current_step = "begin_combat"
    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.resolve_until_stable()

    assert any(o.name == "Food" for o in eng.state.battlefield)


def test_sam_does_not_fire_on_the_opponents_combat():
    eng = _engine()
    eng.begin_turn()  # p1's turn
    eng.begin_turn()  # p2's turn
    assert eng.state.active_player.id == "p2"
    p1 = eng.state.player_by_id("p1")
    _sam(eng.state, controller=p1.id)

    eng.state.current_step = "begin_combat"
    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0


def test_ardenn_trigger_places_at_the_beginning_of_combat():
    eng = _engine()
    eng.begin_turn()
    p1 = eng.state.active_player
    _ardenn(eng.state, controller=p1.id)

    eng.state.current_step = "begin_combat"
    from mtg_analyzer.models.events import EventType, GameEvent
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", phase="combat"))
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1


