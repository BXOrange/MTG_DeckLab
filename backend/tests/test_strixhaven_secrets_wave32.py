"""Secrets of Strixhaven — playability batch, wave 32 (PAR-60).

Modal "choose one [or more]" spells hand-authored in
`game/card_registry/commander_cards.py` as `modes` blocks. Engine:
`_mass_wipe_objects` ``token`` filter (Perplexing Test).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WAVE32 = ["Casualties of War", "Final Act", "Perplexing Test"]


@pytest.mark.parametrize("name", WAVE32)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Sorcery"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


@pytest.mark.parametrize("name,expected_choose,expected_modes,at_least", [
    ("Casualties of War", 1, 5, True),
    ("Final Act", 1, 5, True),
    ("Perplexing Test", 1, 2, False),
])
def test_modal_shape(name, expected_choose, expected_modes, at_least):
    spec = _REGISTRY[name.lower()]()[0]
    assert spec.modes["choose"] == expected_choose
    assert len(spec.modes["options"]) == expected_modes
    assert bool(spec.modes.get("at_least")) is at_least


def test_perplexing_test_token_filter_partitions_creatures():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player

    def mk(name, token):
        o = GameObject(card=Card(id=name, name=name, type_line="Creature — Bear",
                                 is_creature=True, power=1, toughness=1),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
        o.controller_id = p1.id
        o.is_token = token
        eng.state.add_to_battlefield(o)
        return o

    tok = mk("Tok", True)
    real = mk("Real", False)
    src = GameObject(card=Card(id="pt", name="Perplexing Test", type_line="Instant"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    mode1 = _REGISTRY["perplexing test"]()[0].modes["options"][0]
    effs = build_effects(mode1, src)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    names = {o.card.name for o in eng.state.battlefield if o.is_creature}
    assert "Tok" not in names   # token bounced
    assert "Real" in names      # nontoken stays
