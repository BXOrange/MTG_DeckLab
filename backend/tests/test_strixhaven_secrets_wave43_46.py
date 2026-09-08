"""Secrets of Strixhaven — playability batch, waves 43-46 (PAR-60).

wave 43: Muddle the Ever-Changing, Rionya Fire Dancer (cast->copy).
wave 44: Rootha Mercurial Artist, Mistveil Plains.
wave 45: Fractal Harness, Ceaseless Conflict — ``permanents_destroyed_this_way``
         added to `_TOKEN_COUNT_CONTEXT_ACCUMULATORS`.
wave 46: Hydroid Krasis — ``half_x_down`` sentinel on a resolution payoff.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE = ["Muddle, the Ever-Changing", "Rionya, Fire Dancer",
        "Rootha, Mercurial Artist", "Mistveil Plains", "Fractal Harness",
        "Ceaseless Conflict", "Hydroid Krasis"]


@pytest.mark.parametrize("name", WAVE)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature", is_creature=True),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_hydroid_krasis_half_x_sentinels():
    spec = _REGISTRY["hydroid krasis"]()[0]
    vals = {e.type: e.params for e in spec.effects}
    assert vals["gain_life"]["amount"] == "half_x_down"
    assert vals["draw"]["count"] == "half_x_down"


def test_ceaseless_conflict_token_count_from_destroyed():
    spec = _REGISTRY["ceaseless conflict"]()[0]
    tok = next(e for e in spec.effects if e.type == "create_token")
    assert tok.params["count_from_context"] == "permanents_destroyed_this_way"
    from mtg_analyzer.game.effects import _TOKEN_COUNT_CONTEXT_ACCUMULATORS
    assert "permanents_destroyed_this_way" in _TOKEN_COUNT_CONTEXT_ACCUMULATORS
