"""MEC-68 — per-ability, per-turn exhausted triggered modes."""

from mtg_analyzer.game.effects import GainLifeEffect, TriggeredAbility
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _modal_ability(source):
    return TriggeredAbility(
        trigger_event=EventType.SPELL_CAST,
        effects=[], source=source, controller_id="p1", modes_exhaust_per_turn=True,
        modes=[
            {"description": "Erster Modus", "effects": [GainLifeEffect(1, source=source)]},
            {"description": "Zweiter Modus", "effects": [GainLifeEffect(2, source=source)]},
        ],
    )


def _fire(engine):
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1"))
    engine.resolve_until_stable()


def test_exhausted_trigger_modes_are_scoped_to_the_ability_and_turn():
    engine = make_engine([creature(name="Mode Bear")], hand=0)
    state = engine.state
    source = GameObject(creature(name="Mode Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    ability = _modal_ability(source)
    source.triggered_abilities.append(ability)

    engine.begin_turn()
    _fire(engine)
    assert [o["id"] for o in state.pending_choice["options"]] == ["0", "1"]
    engine.resolve_pending_choice("0")
    engine.resolve_until_stable()

    _fire(engine)
    assert [o["id"] for o in state.pending_choice["options"]] == ["1"]
    engine.resolve_pending_choice("1")
    engine.resolve_until_stable()

    # No legal mode remains: the third trigger creates no modal chooser.
    _fire(engine)
    assert state.pending_choice is None

    engine.begin_turn()
    _fire(engine)
    assert [o["id"] for o in state.pending_choice["options"]] == ["0", "1"]


def test_modes_of_different_abilities_on_one_permanent_do_not_collide():
    engine = make_engine([creature(name="Mode Bear")], hand=0)
    state = engine.state
    source = GameObject(creature(name="Mode Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    state.add_to_battlefield(source)
    first, second = _modal_ability(source), _modal_ability(source)
    source.triggered_abilities.extend([first, second])

    engine.begin_turn()
    _fire(engine)
    engine.resolve_pending_choice("0")
    engine.resolve_until_stable()
    # The second queued trigger is now choosing independently, including 0.
    assert state.pending_choice is not None
    assert [o["id"] for o in state.pending_choice["options"]] == ["0", "1"]
