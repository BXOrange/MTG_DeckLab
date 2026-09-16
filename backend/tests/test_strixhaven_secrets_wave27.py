"""Secrets of Strixhaven — playability batch, wave 27 (PAR-60).

The "~ becomes prepared" trigger cluster (STX Learn/Prepared DFCs), hand-authored
in `game/card_registry/commander_cards.py`. New engine primitives: binder
predicates ``spell_mana_value_at_least`` and ``attackers_at_least``;
`static_conditions` kinds ``graveyard_card_type_count_at_least`` and
``any_player_cards_in_hand_at_most``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import static_conditions
from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

WAVE27 = ["Eiganjo Dynastorian", "Dirgur Focusmage", "Lorehold Archivist",
          "Naktamun Lorespinner", "Inspired Skypainter", "Firemane Commando"]


@pytest.mark.parametrize("name", WAVE27)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    return eng, p1, p2


def test_graveyard_card_type_count_condition():
    eng, p1, p2 = _eng()
    cond = {"kind": "graveyard_card_type_count_at_least",
            "types": ["artifact", "creature"], "amount": 3}
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    for i, tl in enumerate(["Artifact", "Creature — Bear", "Artifact Creature — Golem"]):
        p1.graveyard.append(GameObject(card=Card(id=f"g{i}", name=f"C{i}", type_line=tl),
                                       owner_id=p1.id, zone=Zone.GRAVEYARD))
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True
    # an instant in the graveyard does not count toward artifact/creature
    p1.graveyard.append(GameObject(card=Card(id="gi", name="Bolt", type_line="Instant"),
                                   owner_id=p1.id, zone=Zone.GRAVEYARD))
    cond4 = dict(cond, amount=4)
    assert static_conditions.condition_holds(cond4, eng.state, None, p1.id) is False


def test_any_player_cards_in_hand_at_most_condition():
    eng, p1, p2 = _eng()
    cond = {"kind": "any_player_cards_in_hand_at_most", "amount": 1}
    p1.hand.extend(GameObject(card=Card(id=f"h{i}", name="x", type_line="Instant"),
                              owner_id=p1.id, zone=Zone.HAND) for i in range(3))
    p2.hand.extend(GameObject(card=Card(id=f"k{i}", name="y", type_line="Instant"),
                              owner_id=p2.id, zone=Zone.HAND) for i in range(3))
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    p2.hand.clear()
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True


def test_attackers_at_least_predicate_fires_become_prepared():
    from mtg_analyzer.models.game.events import EventType
    eng, p1, p2 = _eng()
    src = GameObject(card=Card(id="ed", name="Eiganjo Dynastorian",
                              type_line="Creature — Fox Advisor", is_creature=True),
                     owner_id=p1.id, zone=Zone.BATTLEFIELD)
    src.controller_id = p1.id
    eng.state.add_to_battlefield(src)
    ability = bind_ability(_REGISTRY["eiganjo dynastorian"]()[0], src)
    ev1 = {"attacking_player_id": p1.id, "count": 1}
    ev2 = {"attacking_player_id": p1.id, "count": 2}
    assert ability.condition(ev1, eng.rules.context) is False
    assert ability.condition(ev2, eng.rules.context) is True
