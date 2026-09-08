"""Mirrorwing Dragon copies a spell once for each other creature."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem


def _mw_card():
    return Card(id="mw", name="Mirrorwing Dragon", type_line="Creature — Dragon",
                is_creature=True, power=4, toughness=5,
                oracle_text=("Flying\nWhenever a player casts an instant or sorcery spell "
                             "that targets only this creature, that player copies that "
                             "spell for each other creature they control that the spell "
                             "could target. Each copy targets a different one of those "
                             "creatures."))


def test_registered_and_binds():
    assert is_registered("Mirrorwing Dragon")
    spec = _REGISTRY["mirrorwing dragon"]()[0]
    spec.validate()
    assert spec.effects[0].type == "mirrorwing_copy"
    src = GameObject(_mw_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_mw_card())


def test_copies_the_spell_once_per_other_creature_retargeted():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    mw = GameObject(_mw_card(), owner_id="p2", zone=Zone.BATTLEFIELD)
    mw.controller_id = "p2"
    eng.state.add_to_battlefield(mw)
    others = []
    for i in range(2):
        o = GameObject(Card(id=f"c{i}", name=f"Buddy{i}", type_line="Creature — Elf",
                            is_creature=True, power=1, toughness=1),
                       owner_id="p2", zone=Zone.BATTLEFIELD)
        o.controller_id = "p2"
        eng.state.add_to_battlefield(o)
        others.append(o)

    spell_obj = GameObject(Card(id="bolt", name="Shock", type_line="Instant",
                                is_instant=True), owner_id="p2", zone=Zone.STACK)
    item = StackItem(kind="spell", controller_id="p2", effects=[], obj=spell_obj,
                     targets=[mw])
    eng.state.stack.append(item)

    src_spec = _REGISTRY["mirrorwing dragon"]()[0]
    eng.rules.context.trigger_event = {"instance_id": spell_obj.instance_id, "player_id": "p2"}
    eng.rules._apply_effect_specs([{"type": "mirrorwing_copy", "params": {}}], mw)

    copies = [it for it in eng.state.stack if getattr(it, "obj", None) is not None
              and it.obj is not spell_obj and it.obj.name == "Shock"]
    assert len(copies) == 2
    targeted = {t.instance_id for c in copies for t in c.targets}
    assert targeted == {o.instance_id for o in others}
