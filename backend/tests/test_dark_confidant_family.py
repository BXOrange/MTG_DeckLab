"""MEC-12 (cEDH staples 2) — Dark Confidant's "reveal top, put into hand,
lose life equal to its mana value" upkeep trigger.

New primitive: `RevealTopThenTakeAndLoseLifeEffect` — deliberately not
`DrawCardEffect`/`RulesEngine.draw` at all (RULE 121.4: moving a card to
hand without the printed word "draw" isn't a draw, so it must never trip a
draw-replacement/"whenever you draw" trigger or count toward cards drawn
this turn).

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.state.current_step = "upkeep"
    return engine, state, p1, p2


def _library_card(name, cmc, cost="{1}{G}"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=cmc, is_creature=True, power=2, toughness=2,
    )


def _step(step):
    return GameEvent(EventType.STEP_BEGIN, step=step)


def test_dark_confidant_reveals_takes_and_loses_life_equal_to_mana_value():
    engine, state, p1, _ = _engine()
    top_card_obj = GameObject(_library_card("Bear", 4), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(top_card_obj)

    confidant = GameObject(_named("Dark Confidant"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(confidant)
    state.add_to_battlefield(confidant)

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert top_card_obj in p1.hand
    assert top_card_obj.zone == Zone.HAND
    assert top_card_obj not in p1.library
    assert p1.life == 20 - 4


def test_dark_confidant_does_not_count_as_a_draw():
    engine, state, p1, _ = _engine()
    p1.library.append(GameObject(_library_card("Bear", 3), owner_id="p1", zone=Zone.LIBRARY))

    confidant = GameObject(_named("Dark Confidant"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(confidant)
    state.add_to_battlefield(confidant)

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    # RULE 121.4: not a draw at all — never tallied in cards_drawn_this_turn.
    assert state.cards_drawn_this_turn.get("p1", 0) == 0


def test_dark_confidant_only_triggers_on_its_controllers_upkeep():
    engine, state, p1, p2 = _engine()
    p1.library.append(GameObject(_library_card("Bear", 3), owner_id="p1", zone=Zone.LIBRARY))
    state.active_player_index = 1  # p2's upkeep, not the Confidant controller's

    confidant = GameObject(_named("Dark Confidant"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(confidant)
    state.add_to_battlefield(confidant)

    state.fire_event(_step("upkeep"))
    engine.resolve_until_stable()

    assert p1.hand == []
    assert len(p1.library) == 1
