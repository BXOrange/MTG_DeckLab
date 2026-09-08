"""Eriette of the Charmed Apple restricts enchanted creatures and drains opponents."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _bf(eng, name, controller, **kw):
    obj = GameObject(card=Card(id=name[:3] + str(id(name) % 97), name=name, **kw),
                     owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    eng.state.add_to_battlefield(obj)
    return obj


def test_eriette_registered_and_binds():
    assert is_registered("Eriette of the Charmed Apple")
    specs = _REGISTRY["eriette of the charmed apple"]()
    assert len(specs) == 2
    src = GameObject(card=Card(id="e", name="Eriette of the Charmed Apple",
                              type_line="Legendary Creature — Human Warlock",
                              is_creature=True, power=2, toughness=4),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)
    static_spec = specs[0]
    assert static_spec.ability_kind == "static"
    eff = static_spec.effects[0]
    assert eff.type == "cant_attack_defender"
    assert eff.params["attacker_filter"] == {"enchanted_by_controller_aura": True}


def test_aura_enchanted_creature_cant_attack_eriettes_controller():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    eri = _bf(eng, "Eriette of the Charmed Apple", p1.id,
              type_line="Legendary Creature — Human Warlock",
              is_creature=True, power=2, toughness=4)
    bind_from_catalogue(eri)
    bear = _bf(eng, "Grizzly Bears", p2.id, type_line="Creature — Bear",
               is_creature=True, power=2, toughness=2)
    bear.summoning_sick = False
    aura = _bf(eng, "Pacifism", p1.id, type_line="Enchantment — Aura")
    aura.attached_to = bear.instance_id
    eng.recompute_continuous_effects()

    # p1 controls the Aura on p2's Bears -> Bears can't attack p1.
    assert eng._can_attack(p2, bear, p1) is False
    # A second opponent with no Eriette is still a legal target.
    # (offer-time, defender unknown) stays permissive:
    assert eng._can_attack(p2, bear, None) is True

    # If the Aura is controlled by someone other than Eriette's controller,
    # the bar lifts.
    aura.controller_id = p2.id
    eng.recompute_continuous_effects()
    assert eng._can_attack(p2, bear, p1) is True


def test_unenchanted_creature_attacks_eriette_freely():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    eri = _bf(eng, "Eriette of the Charmed Apple", p1.id,
              type_line="Legendary Creature — Human Warlock",
              is_creature=True, power=2, toughness=4)
    bind_from_catalogue(eri)
    ogre = _bf(eng, "Gray Ogre", p2.id, type_line="Creature — Ogre",
               is_creature=True, power=2, toughness=2)
    ogre.summoning_sick = False
    eng.recompute_continuous_effects()
    assert eng._can_attack(p2, ogre, p1) is True
