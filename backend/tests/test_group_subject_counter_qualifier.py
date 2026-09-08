"""RULE 603.1 group-subject trigger conditions gained two qualifiers for the
Blight Curse batch (`parser/oracle/segmenter.py`'s `_GROUP_SUBJECT_RE`,
`_trigger_condition`; `game/binding/core.py`'s `_build_group_ok`):

* **"an opponent controls"** — the mirror of "you control", mapped to the
  existing ``controller="not_you"`` scope (Necroskitter, Malakir Cullblade,
  Yahenni, Glissa, Gideon's Avenger, …).
* **"with a -1/-1 counter on it" / "with a +1/+1 counter on it" / the
  kindless "with a counter on it"** — read off the DIES event's snapshotted
  ``counters`` (RULE 400.7), live-board fallback for verbs that keep the
  object around (Skyclave Shadowcat, Gladehart Cavalry, …).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _trigger_condition


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# --- condition parse -----------------------------------------------------------


def test_opponent_controls_maps_to_not_you():
    cond = _trigger_condition("a creature an opponent controls dies")
    assert cond == {"subject": "group", "type": "creature", "controller": "not_you", "other": False}


def test_you_control_with_minus_counter():
    cond = _trigger_condition("a creature you control with a -1/-1 counter on it dies")
    assert cond["controller"] == "you"
    assert cond["has_counter_kind"] == "-1/-1"


def test_opponent_controls_with_plus_counter():
    cond = _trigger_condition("a creature an opponent controls with a +1/+1 counter on it dies")
    assert cond["controller"] == "not_you"
    assert cond["has_counter_kind"] == "+1/+1"


def test_kindless_counter_qualifier():
    cond = _trigger_condition("a creature you control with a counter on it dies")
    assert cond["has_counter"] is True
    assert "has_counter_kind" not in cond


def test_no_counter_qualifier_leaves_condition_plain():
    cond = _trigger_condition("a creature you control dies")
    assert "has_counter" not in cond and "has_counter_kind" not in cond


# --- real cards --------------------------------------------------------------


def test_real_cards_now_modeled():
    for name, tl, text in [
        ("Skyclave Shadowcat", "Creature — Cat",
         "Whenever a creature you control with a +1/+1 counter on it dies, draw a card."),
        ("Gladehart Cavalry", "Creature — Elk Knight",
         "Whenever a creature you control with a +1/+1 counter on it dies, you gain 2 life."),
        ("Malakir Cullblade", "Creature — Zombie Warrior",
         "Whenever a creature an opponent controls dies, put a +1/+1 counter on Malakir Cullblade."),
    ]:
        c = Card(id=name[:4], name=name, type_line=tl, is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ---------------------------------------------------------------


def _put_creature(eng, name, controller, counters=None):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Rat",
                        is_creature=True, power=1, toughness=1),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    for k, n in (counters or {}).items():
        o.counters[k] = n
    eng.state.add_to_battlefield(o)
    return o


def test_counter_qualified_dies_trigger_only_fires_with_the_counter():
    eng = _engine()
    p1 = eng.state.players[0]
    watcher = GameObject(
        Card(id="SC", name="Skyclave Shadowcat", type_line="Creature — Cat",
             is_creature=True, power=2, toughness=2,
             oracle_text="Whenever a creature you control with a +1/+1 counter on it dies, "
                         "draw a card."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    watcher.controller_id = "p1"
    eng.state.add_to_battlefield(watcher)
    bind_from_catalogue(watcher)

    # p1 library so a draw is observable
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains", is_land=True),
                                     owner_id="p1", zone=Zone.LIBRARY))
    start_hand = len(p1.hand)

    bare = _put_creature(eng, "Bare Rat", "p1")
    marked = _put_creature(eng, "Marked Rat", "p1", counters={"+1/+1": 1})

    eng.rules.destroy(bare)
    eng.resolve_until_stable()
    assert len(p1.hand) == start_hand, "no counter → no trigger"

    eng.rules.destroy(marked)
    eng.resolve_until_stable()
    assert len(p1.hand) == start_hand + 1, "had a +1/+1 counter → drew"


def test_opponent_controls_dies_trigger_ignores_own_creatures():
    eng = _engine()
    watcher = GameObject(
        Card(id="MC", name="Malakir Cullblade", type_line="Creature — Zombie",
             is_creature=True, power=1, toughness=1,
             oracle_text="Whenever a creature an opponent controls dies, put a +1/+1 counter "
                         "on Malakir Cullblade."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    watcher.controller_id = "p1"
    eng.state.add_to_battlefield(watcher)
    bind_from_catalogue(watcher)

    own = _put_creature(eng, "My Rat", "p1")
    eng.rules.destroy(own)
    eng.resolve_until_stable()
    assert watcher.counters.get("+1/+1", 0) == 0, "own creature dying must not trigger"

    theirs = _put_creature(eng, "Their Rat", "p2")
    eng.rules.destroy(theirs)
    eng.resolve_until_stable()
    assert watcher.counters.get("+1/+1", 0) == 1
