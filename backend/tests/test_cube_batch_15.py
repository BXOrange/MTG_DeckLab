"""cEDH staples cube — batch 15: the `EventType.SACRIFICE` primitive.

New core primitive: `RulesEngine._move_to_graveyard` now fires a distinct
`EventType.SACRIFICE` occurrence (RULE 701.17) — *in addition to*
DIES/LEAVES_BATTLEFIELD — whenever the move's cause is a sacrifice (every
`put_into_graveyard` caller). This lets "whenever a player sacrifices a
permanent" be told apart from a plain death.

Proven here on Mayhem Devil (the motivating real card) plus the event
plumbing itself: a sacrificed creature fires both DIES and SACRIFICE, a
sacrificed noncreature only SACRIFICE, and a *destroyed* (non-sacrifice)
creature fires DIES but never SACRIFICE (so Mayhem Devil doesn't over-fire).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine(p1_cards=(), p2_cards=()) -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_cards)), ("p2", "Bob", list(p2_cards))],
        starting_life=40,
        starting_hand=max(len(p1_cards), len(p2_cards)) or 0,
    )
    for player in eng.state.players:
        for obj in list(player.hand) + list(player.library):
            bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _record_events(state) -> list[str]:
    seen: list[str] = []
    state.subscribe(lambda ev: seen.append(ev.type))
    return seen


def _creature(name: str, controller: str = "p1") -> Card:
    return Card(id=name, name=name, type_line="Creature — Elf",
                is_creature=True, power=1, toughness=1)


def _artifact(name: str) -> Card:
    return Card(id=name, name=name, type_line="Artifact")


# ---------------------------------------------------------------------------
# 0. Registration + playability
# ---------------------------------------------------------------------------


def test_mayhem_devil_registered_and_playable():
    assert "mayhem devil" in ac._REGISTRY
    specs = ac.specs_for(_card("Mayhem Devil"))
    assert specs, "Mayhem Devil produced no specs"


# ---------------------------------------------------------------------------
# 1. The SACRIFICE event plumbing
# ---------------------------------------------------------------------------


def test_sacrificed_creature_fires_both_dies_and_sacrifice():
    eng = _engine()
    state = eng.state
    victim = _battlefield(state, _creature("SacVictim"), controller="p1")
    seen = _record_events(state)

    eng.rules.put_into_graveyard(victim)

    assert EventType.DIES in seen
    assert EventType.SACRIFICE in seen
    # SACRIFICE fires after DIES (a dies-trigger batches before a sac-trigger).
    assert seen.index(EventType.SACRIFICE) > seen.index(EventType.DIES)


def test_sacrificed_noncreature_fires_sacrifice_but_not_dies():
    eng = _engine()
    state = eng.state
    rock = _battlefield(state, _artifact("SacRock"), controller="p1")
    seen = _record_events(state)

    eng.rules.put_into_graveyard(rock)

    assert EventType.SACRIFICE in seen
    assert EventType.DIES not in seen


def test_destroyed_creature_fires_dies_but_not_sacrifice():
    eng = _engine()
    state = eng.state
    victim = _battlefield(state, _creature("DestroyVictim"), controller="p1")
    seen = _record_events(state)

    eng.rules.destroy(victim)

    assert EventType.DIES in seen
    assert EventType.SACRIFICE not in seen, "destruction is not a sacrifice (RULE 701.17)"


def test_effect_driven_sacrifice_fires_sacrifice():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    _battlefield(state, _creature("AnnihVictim"), controller="p1")
    seen = _record_events(state)

    eng.rules.sacrifice(p1, "creature", count=1)

    assert EventType.SACRIFICE in seen


# ---------------------------------------------------------------------------
# 2. Mayhem Devil behaviour
# ---------------------------------------------------------------------------


def test_mayhem_devil_pings_on_a_sacrifice():
    eng = _engine()
    state = eng.state
    p2 = state.player_by_id("p2")
    _battlefield(state, _card("Mayhem Devil"), controller="p1")
    victim = _battlefield(state, _creature("Fodder"), controller="p1")
    start_life = p2.life

    eng.rules.put_into_graveyard(victim)
    eng.rules.put_triggers_on_stack()

    # Mayhem Devil's 1-damage effect targets "any target": aim it at p2.
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.rules.resolve_trigger_target_choice("p2")
    eng.resolve_until_stable()

    assert p2.life == start_life - 1


def test_mayhem_devil_does_not_fire_on_a_plain_destroy():
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Mayhem Devil"), controller="p1")
    victim = _battlefield(state, _creature("DestroyedFodder"), controller="p1")

    eng.rules.destroy(victim)
    placed = eng.rules.put_triggers_on_stack()

    assert placed == 0, "a destroyed (non-sacrificed) creature must not trigger Mayhem Devil"
    assert state.pending_choice is None
