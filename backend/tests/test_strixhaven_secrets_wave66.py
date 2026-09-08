"""Secrets of Strixhaven — playability batch, wave 66 (PAR-60).

Altered Ego — ``EnterAsCopyReplacement`` gained ``extra_counters_from_x``
(the copy spell's own announced {X} as the extra-+1/+1 count, resolved when
the copy is made).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def test_altered_ego_registered_and_binds():
    assert is_registered("Altered Ego")
    specs = _REGISTRY["altered ego"]()
    assert len(specs) == 2
    assert specs[0].effects[0].type == "cant_be_countered"
    assert specs[1].ability_kind == "enter_replacement"
    ec = specs[1].effects[0]
    assert ec.type == "enter_as_copy"
    assert ec.params["extra_counters_from_x"] is True
    src = GameObject(card=Card(id="ae", name="Altered Ego",
                             type_line="Creature — Shapeshifter", is_creature=True,
                             power=0, toughness=0),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_enter_as_copy_effect_carries_x_flag():
    from mtg_analyzer.game.effects import EffectRegistry

    eff = EffectRegistry.create("enter_as_copy", {"target_kind": "creature",
                                                  "extra_counters_from_x": True})
    assert eff.extra_counters_from_x is True
    # default off
    eff2 = EffectRegistry.create("enter_as_copy", {"target_kind": "creature"})
    assert eff2.extra_counters_from_x is False
