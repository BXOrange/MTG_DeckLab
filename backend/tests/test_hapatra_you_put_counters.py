"""Blight Curse batch C4 — Hapatra, Vizier of Poisons (hand-authored,
`ability_catalogue/entries_017.py`).

Second clause: "Whenever **you** put one or more -1/-1 counters on a
creature, create a 1/1 green Snake creature token with deathtouch." — the
Flourishing Defenses `EventType.COUNTER` shape plus the new causer-scoped
``by_you`` trigger-filter key (`game/binding/core.py`): the counters'
``source_controller_id`` must be this ability's own controller.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

HAPATRA = Card(
    id="HAP", name="Hapatra, Vizier of Poisons",
    type_line="Legendary Creature — Human Cleric", is_creature=True, power=2, toughness=2,
    oracle_text="Whenever Hapatra deals combat damage to a player, you may put a -1/-1 "
                "counter on target creature.\nWhenever you put one or more -1/-1 counters "
                "on a creature, create a 1/1 green Snake creature token with deathtouch.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(eng, name, pid, **kw):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Ogre", is_creature=True,
                        power=kw.get("power", 3), toughness=kw.get("toughness", 3)),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_hapatra_is_authored_with_two_abilities():
    assert len(specs_for(HAPATRA)) == 2


def test_snake_token_on_your_own_minus_counter_placement():
    eng = _engine()
    hap = GameObject(HAPATRA, owner_id="p1", zone=Zone.BATTLEFIELD)
    hap.controller_id = "p1"
    eng.state.add_to_battlefield(hap)
    bind_from_catalogue(hap)
    victim = _put(eng, "Victim", "p1")
    eng.begin_turn()

    eng.rules.add_counters(victim, 2, "-1/-1", source=hap)  # you (p1) put them
    eng.resolve_until_stable()

    snakes = [o for o in eng.state.battlefield if o.name == "Snake"]
    assert len(snakes) == 1
    assert "deathtouch" in [k.lower() for k in snakes[0].card.keywords]


def test_no_snake_when_an_opponent_places_the_counter():
    eng = _engine()
    hap = GameObject(HAPATRA, owner_id="p1", zone=Zone.BATTLEFIELD)
    hap.controller_id = "p1"
    eng.state.add_to_battlefield(hap)
    bind_from_catalogue(hap)
    opp_src = _put(eng, "OppSrc", "p2")
    victim = _put(eng, "Victim", "p1")
    eng.begin_turn()

    eng.rules.add_counters(victim, 1, "-1/-1", source=opp_src)  # p2 put it
    eng.resolve_until_stable()

    assert not [o for o in eng.state.battlefield if o.name == "Snake"]
