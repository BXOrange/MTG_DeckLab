"""Secrets of Strixhaven — playability batch, wave 92 (PAR-60).

Pearl-Ear, Imperial Advisor — reuse of `cost_reduction` (``spell_type`` +
``per`` count_selector) for "affinity for Auras" + Kor Spiritdancer's own
"whenever you cast an Aura spell" group trigger. Documented simplification:
the draw's "targets a modified permanent you control" narrowing is dropped.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _pearl_card():
    return Card(id="pe", name="Pearl-Ear, Imperial Advisor",
                type_line="Legendary Creature — Fox Advisor", is_creature=True,
                power=3, toughness=4,
                oracle_text=("Lifelink\nEnchantment spells you cast have affinity for "
                             "Auras. (They cost {1} less to cast for each Aura you "
                             "control.)\nWhenever you cast an Aura spell that targets a "
                             "modified permanent you control, draw a card."))


def test_registered_and_binds():
    assert is_registered("Pearl-Ear, Imperial Advisor")
    specs = _REGISTRY["pearl-ear, imperial advisor"]()
    assert len(specs) == 2
    static, trig = specs
    assert static.effects[0].type == "cost_reduction"
    assert static.effects[0].params["spell_type"] == "enchantment"
    assert static.effects[0].params["per"] == "auras_you_control"
    assert trig.trigger["event"] == "SPELL_CAST"
    assert trig.trigger["condition"]["subtypes"] == ["aura"]
    src = GameObject(_pearl_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_pearl_card())
