"""Secrets of Strixhaven — playability batch, wave 42 (PAR-60).

"Whenever you discard a card, exile it from your graveyard, then you may
play it this turn" — hand-authored in `game/ability_catalogue/entries_019.py`.
Engine: `ExileTriggeringDiscardMayPlayThisTurnEffect`
("exile_triggering_discard_may_play_this_turn").
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE42 = ["Containment Construct", "Conspiracy Theorist"]


@pytest.mark.parametrize("name", WAVE42)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Artifact Creature",
                              is_creature=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_containment_construct_exiles_discard_and_grants_play_window():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    cc = GameObject(card=Card(id="cc", name="Containment Construct",
                             type_line="Artifact Creature — Construct", is_creature=True),
                    owner_id=p1.id, zone=Zone.BATTLEFIELD)
    cc.controller_id = p1.id
    eng.state.add_to_battlefield(cc)
    bind_from_catalogue(cc)

    bolt = GameObject(card=Card(id="bolt", name="Bolt", type_line="Instant"),
                      owner_id=p1.id, zone=Zone.HAND)
    bolt.controller_id = p1.id
    p1.hand.append(bolt)
    eng.rules.discard(p1, 1)
    eng.resolve_until_stable()

    assert bolt.zone == Zone.EXILE
    assert bolt.instance_id in eng.state.temp_play_permissions
