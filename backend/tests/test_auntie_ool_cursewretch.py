"""Blight Curse batch C4 — Auntie Ool, Cursewretch (the deck's commander;
hand-authored, `ability_catalogue/entries_017.py`).

- **Ward—Blight 2** folds in from the RULE 702 keyword catalogue (the cost
  "Blight 2" is already understood by `game/costs.parse_activation_cost`).
- The trigger: "Whenever one or more -1/-1 counters are put on a creature,
  draw a card **if you control that creature**. If you don't control it,
  its controller loses 1 life." — the Flourishing Defenses `EventType.
  COUNTER` shape with a two-way `ConditionalEffect` on the firing event's
  ``recipient_controller_id`` (new ``counter_recipient_is_you`` key) and a
  `LoseLifeEffect` ``selector="counter_recipient_controller"``.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

AUNTIE_OOL = Card(
    id="AOOL", name="Auntie Ool, Cursewretch",
    type_line="Legendary Creature — Goblin Warlock", is_creature=True, power=2, toughness=3,
    keywords=["Ward"],
    oracle_text="Ward—Blight 2. (To blight 2, a player puts two -1/-1 counters on a "
                "creature they control.)\nWhenever one or more -1/-1 counters are put on a "
                "creature, draw a card if you control that creature. If you don't control "
                "it, its controller loses 1 life.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(eng, name, pid):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear", is_creature=True,
                        power=3, toughness=3), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def _setup():
    eng = _engine()
    p1 = eng.state.players[0]
    ao = GameObject(AUNTIE_OOL, owner_id="p1", zone=Zone.BATTLEFIELD)
    ao.controller_id = "p1"
    eng.state.add_to_battlefield(ao)
    bind_from_catalogue(ao)
    for i in range(6):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains", is_land=True),
                                     owner_id="p1", zone=Zone.LIBRARY))
    eng.begin_turn()
    return eng, ao


def test_ward_blight_2_folds_in():
    kws = [s for s in specs_for(AUNTIE_OOL) if s.ability_kind == "keyword"]
    assert any((s.keyword or {}).get("name") == "ward"
               and (s.keyword or {}).get("cost") == "Blight 2" for s in kws)


def test_draw_when_the_counters_land_on_your_own_creature():
    eng, ao = _setup()
    p1, p2 = eng.state.players
    mine = _creature(eng, "Mine", "p1")
    h0, life0 = len(p1.hand), p2.life

    eng.rules.add_counters(mine, 1, "-1/-1", source=ao)
    eng.resolve_until_stable()

    assert len(p1.hand) == h0 + 1
    assert p2.life == life0  # no life loss branch


def test_opponents_controller_loses_one_life_when_it_is_their_creature():
    eng, ao = _setup()
    p1, p2 = eng.state.players
    theirs = _creature(eng, "Theirs", "p2")
    h0, life0 = len(p1.hand), p2.life

    # "one or more" — two counters still cost exactly 1 life, once.
    eng.rules.add_counters(theirs, 2, "-1/-1", source=ao)
    eng.resolve_until_stable()

    assert p2.life == life0 - 1
    assert len(p1.hand) == h0  # no draw branch
