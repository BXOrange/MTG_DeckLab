"""Blight Curse batch — the Marchesa `counter_death_return` primitive
(`RulesEngine._collect_counter_death_return_triggers`) gained four optional
marker flags for Necroskitter / The Reaper, King No More:

* ``opponent`` — the dying creature is an *opponent's*, not this
  permanent's controller's (Marchesa's default is "you control").
* ``immediate`` — resolve now, no "at the beginning of the next end step"
  delay.
* ``optional`` — "you may".
* ``once_per_turn`` — RULE 603.2 (The Reaper).

Both cards are hand-authored (`card_registry/blight_curse.py`).
"""

from __future__ import annotations

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(eng, card, pid, counters=None):
    o = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    for k, n in (counters or {}).items():
        o.counters[k] = n
    eng.state.add_to_battlefield(o)
    return o


NECROSKITTER = Card(
    id="NK", name="Necroskitter", type_line="Creature — Elemental", is_creature=True,
    power=1, toughness=1, keywords=["Wither"],
    oracle_text="Wither\nWhenever a creature an opponent controls with a -1/-1 counter "
                "on it dies, you may return that card to the battlefield under your control.",
)
REAPER = Card(
    id="TR", name="The Reaper, King No More", type_line="Legendary Artifact Creature — Scarecrow",
    is_creature=True, power=3, toughness=3,
    oracle_text="When The Reaper enters, put a -1/-1 counter on each of up to two target "
                "creatures.\nWhenever a creature an opponent controls with a -1/-1 counter "
                "on it dies, you may put that card onto the battlefield under your control. "
                "Do this only once each turn.",
)


def test_both_cards_are_authored():
    for c in (NECROSKITTER, REAPER):
        assert specs_for(c), c.name


def test_necroskitter_folds_in_wither():
    kinds = {(s.ability_kind, (s.keyword or {}).get("name")) for s in specs_for(NECROSKITTER)}
    assert ("keyword", "wither") in kinds


def _bare(name, pid):
    return Card(id=name[:6], name=name, type_line="Creature — Rat", is_creature=True,
                power=2, toughness=2)


def test_necroskitter_steals_an_opponents_countered_creature_immediately():
    eng = _engine()
    nk = _put(eng, NECROSKITTER, "p1")
    bind_from_catalogue(nk)
    eng.begin_turn()

    victim = _put(eng, _bare("Doomed", "p2"), "p2", counters={"-1/-1": 1})
    eng.rules.destroy(victim)
    eng.resolve_until_stable()

    # Immediate (not a delayed end-step return) and under p1's control.
    assert victim in eng.state.battlefield
    assert victim.controller_id == "p1"
    assert victim.owner_id == "p2"


def test_necroskitter_ignores_a_creature_with_no_minus_counter():
    eng = _engine()
    nk = _put(eng, NECROSKITTER, "p1")
    bind_from_catalogue(nk)
    eng.begin_turn()

    victim = _put(eng, _bare("Safe", "p2"), "p2")  # no counter
    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield


def test_necroskitter_ignores_your_own_dying_creature():
    eng = _engine()
    nk = _put(eng, NECROSKITTER, "p1")
    bind_from_catalogue(nk)
    eng.begin_turn()

    mine = _put(eng, _bare("Mine", "p1"), "p1", counters={"-1/-1": 1})
    eng.rules.destroy(mine)
    eng.resolve_until_stable()
    # "an opponent controls" — my own creature dying must not bring it back
    # under some other control; it just goes to the graveyard.
    assert mine not in eng.state.battlefield


def test_reaper_once_per_turn():
    eng = _engine()
    tr = _put(eng, REAPER, "p1")
    bind_from_catalogue(tr)
    eng.begin_turn()

    v1 = _put(eng, _bare("First", "p2"), "p2", counters={"-1/-1": 1})
    v2 = _put(eng, _bare("Second", "p2"), "p2", counters={"-1/-1": 1})
    eng.rules.destroy(v1)
    eng.resolve_until_stable()
    eng.rules.destroy(v2)
    eng.resolve_until_stable()

    assert v1.controller_id == "p1" and v1 in eng.state.battlefield
    # The second one this turn does NOT come back (RULE 603.2 once-per-turn).
    assert v2 not in eng.state.battlefield
