"""PAR-276: put a card from hand onto the battlefield with riders (RULE 603.7, 603.12).

Erica Ortegas, Plucky Pilot (a land, then a land of yours returns at the next end step) and U.S.S. Farragut, Bold
Explorer (a creature with haste, bottomed at the next end step, then a draw). Real cached cards on a real engine.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, game, on_battlefield, stock_library


def _in_hand(player, name, type_line, **kw) -> GameObject:
    obj = GameObject(Card(id=name, name=name, type_line=type_line, **kw), owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


def _land_in_play(engine, name) -> GameObject:
    obj = GameObject(Card(id=name, name=name, type_line="Land", is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    engine.state.add_to_battlefield(obj)
    return obj


def _settle(engine, answers=("do", "decline")):
    """Resolve the stack, answering every open choice: the trigger's 'do'/'decline' with ``answers[0]``, any card pick
    with the first offered card."""
    engine.resolve_until_stable()
    for _ in range(10):
        choice = engine.state.pending_choice
        if choice is None:
            return
        ids = [o["id"] for o in choice["options"]]
        engine.resolve_pending_choice(answers[0] if answers[0] in ids else next(i for i in ids if i != "decline"))
        engine.resolve_until_stable()
    raise AssertionError("choices never settled")


def test_erica_puts_a_land_in_and_returns_a_land_at_the_next_end_step():
    engine, p1, p2 = game(via_steps=True)
    erica = on_battlefield(engine, "p1", "Erica Ortegas, Plucky Pilot")
    old = _land_in_play(engine, "Old Forest")
    land = _in_hand(p1, "Hand Forest", "Land", is_land=True)
    engine.rules.set_tapped(erica, True)
    _settle(engine)
    assert land.zone == Zone.BATTLEFIELD
    advance_to(engine, "end")
    _settle(engine)
    # Exactly one land of the controller's went back to its owner's hand at the end step.
    assert sum(o.zone == Zone.HAND for o in (land, old)) == 1


def test_erica_declining_leaves_the_land_in_hand_and_schedules_nothing():
    engine, p1, p2 = game(via_steps=True)
    erica = on_battlefield(engine, "p1", "Erica Ortegas, Plucky Pilot")
    land = _in_hand(p1, "Hand Forest", "Land", is_land=True)
    engine.rules.set_tapped(erica, True)
    _settle(engine, answers=("decline",))
    assert land.zone == Zone.HAND and not engine.state.delayed_triggers


def test_farragut_puts_a_creature_in_with_haste_then_bottoms_it_and_draws():
    engine, p1, p2 = game(via_steps=True)
    on_battlefield(engine, "p1", "U.S.S. Farragut, Bold Explorer")
    bear = _in_hand(p1, "Hand Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    stock_library(engine, "p1", 3)
    top = p1.library[-1]
    p1.hand.append(land := GameObject(Card(id="L", name="Fresh Land", type_line="Land", is_land=True),
                                      owner_id="p1", zone=Zone.HAND))
    engine.play_land(p1, land)
    _settle(engine)
    assert bear.zone == Zone.BATTLEFIELD
    advance_to(engine, "end")
    _settle(engine)
    assert bear.zone == Zone.LIBRARY and p1.library[0] is bear
    assert top in p1.hand


def test_farragut_declining_puts_nothing_in_and_draws_nothing():
    engine, p1, p2 = game(via_steps=True)
    on_battlefield(engine, "p1", "U.S.S. Farragut, Bold Explorer")
    bear = _in_hand(p1, "Hand Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    stock_library(engine, "p1", 3)
    hand_before = len(p1.hand)
    p1.hand.append(land := GameObject(Card(id="L", name="Fresh Land", type_line="Land", is_land=True),
                                      owner_id="p1", zone=Zone.HAND))
    engine.play_land(p1, land)
    _settle(engine, answers=("decline",))
    advance_to(engine, "end")
    _settle(engine, answers=("decline",))
    assert bear.zone == Zone.HAND and len(p1.hand) == hand_before
