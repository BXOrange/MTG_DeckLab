"""BUG-84: "reveal cards from the top of your library until you reveal a nonland card. ~ gets +X/+0 ..., where X is that
card's mana value. Put the revealed cards on the bottom of your library in any order." (Goblin Machinist) is the
player's own ordering of the pile (RULE 401.4), not a random shuffle; "in a random order" stays random. `reveal_until`
reuses the PAR-292 M11 bottom-ordering choice, and the amount body still reads the revealed hit (RULE 701.20)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

from tests.test_cascade_discover import events_of
from tests.test_par284_inspection_referents import _card, _engine, _stack_library

BODY = ("Reveal cards from the top of your library until you reveal a nonland card. This creature gets +X/+0 until end "
        "of turn, where X is that card's mana value. Put the revealed cards on the bottom of your library in {order} order.")
LIBRARY = [("Forest", "Basic Land — Forest", 0), ("Hit", "Sorcery", 4), ("Deep", "Land", 0)]


def _machinist(eng, order):
    card = _card("Goblin Machinist", "Creature — Goblin", "When this creature enters, " + BODY.format(order=order)[0].lower()
                 + BODY.format(order=order)[1:], cost="{2}{R}", mv=3, power=0, toughness=5)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"R": 1, "C": 2})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    return obj


def _answer_in_order(eng, names):
    for name in names:
        choice = eng.state.pending_choice
        if choice is None:
            break
        option = next(o for o in choice["options"] if o.get("label") == name)
        eng.rules.resolve_choice(option["instance_id"])
        eng.resolve_until_stable()


def _power(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power


def test_parse_any_is_ordered_and_random_stays_random():
    def rest(order):
        card = _card("Probe", "Creature — Goblin", "When this creature enters, " + BODY.format(order=order).replace("Reveal", "reveal", 1),
                     power=0, toughness=5)
        return next(e for s in parse_oracle(card).specs for e in s.effects if e.type == "reveal_until").params["rest_destination"]
    assert rest("any") == "library_bottom_order"
    assert rest("a random") == "library_bottom_random"


def test_player_orders_the_pile_and_the_bind_reads_the_hit():
    eng = _engine()
    p1 = _stack_library(eng, "p1", LIBRARY)
    seen = events_of(eng)
    obj = _machinist(eng, "any")
    assert eng.state.pending_choice is not None and eng.state.pending_choice["kind"] == "library_bottom"
    _answer_in_order(eng, ["Hit", "Forest"])
    assert eng.state.pending_choice is None
    # only the two revealed cards are ordered (topmost of the pile first); Deep was never revealed
    assert [o.name for o in reversed(p1.library[:2])] == ["Hit", "Forest"]
    assert p1.library[-1].name == "Deep"
    assert all(o.zone == Zone.LIBRARY for o in p1.library) and not p1.exile
    assert _power(eng, obj) == 4
    assert not [e for e in seen if e.type == EventType.EXILE]  # BUG-81: a reveal never exiles


def test_pending_order_choice_survives_a_clone():
    eng = _engine()
    _stack_library(eng, "p1", LIBRARY)
    _machinist(eng, "any")
    restored = GameEngine(eng.state.clone())
    assert restored.state.pending_choice["kind"] == "library_bottom"
    _answer_in_order(restored, ["Forest", "Hit"])
    assert [o.name for o in reversed(restored.state.players[0].library[:2])] == ["Forest", "Hit"]
    rebuilt = next(o for o in restored.state.battlefield if o.name == "Goblin Machinist")
    assert _power(restored, rebuilt) == 4  # the body resumed after the answer and still read the hit


def test_a_single_revealed_card_needs_no_choice():
    eng = _engine()
    p1 = _stack_library(eng, "p1", [("Hit", "Sorcery", 3), ("Deep", "Land", 0)])
    obj = _machinist(eng, "any")
    assert eng.state.pending_choice is None
    assert _power(eng, obj) == 3
    assert p1.library[0].name == "Hit"  # the lone revealed card went to the bottom


def test_random_spelling_opens_no_choice():
    eng = _engine()
    _stack_library(eng, "p1", LIBRARY)
    obj = _machinist(eng, "a random")
    assert eng.state.pending_choice is None
    assert _power(eng, obj) == 4
