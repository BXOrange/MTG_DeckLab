"""Secrets of Strixhaven — playability batch, wave 75 (PAR-60).

Hateful Eidolon — new ``attached_aura_controller_ids`` snapshot on the DIES
event (recorded while the dying creature + its Auras are still on the
battlefield), read by the `draw_per_attached_aura_controller` effect; the
trigger reuses wave 48's ``enchanted_by_your_aura`` group-condition key.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _eidolon_card():
    return Card(id="he", name="Hateful Eidolon",
                type_line="Enchantment Creature — Spirit", is_creature=True,
                power=1, toughness=2,
                oracle_text=("Lifelink\nWhenever an enchanted creature dies, draw a "
                             "card for each Aura you controlled that was attached to it."))


def test_registered_and_binds():
    assert is_registered("Hateful Eidolon")
    spec = _REGISTRY["hateful eidolon"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "DIES"
    assert spec.trigger["condition"]["enchanted_by_your_aura"] is True
    assert spec.effects[0].type == "draw_per_attached_aura_controller"
    src = GameObject(_eidolon_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_eidolon_card())


def _aura(eng, controller, attached_to_id, name="Aura"):
    a = GameObject(Card(id=name, name=name, type_line="Enchantment — Aura"),
                   owner_id=controller, zone=Zone.BATTLEFIELD)
    a.controller_id = controller
    a.attached_to = attached_to_id
    eng.state.add_to_battlefield(a)
    return a


def test_draws_one_per_your_aura_on_the_dying_creature():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    for i in range(5):
        p1.add_to_zone(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains",
                                       is_land=True), owner_id="p1", zone=Zone.LIBRARY),
                       Zone.LIBRARY)

    eid = GameObject(_eidolon_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eid.controller_id = "p1"
    eid.summoning_sick = False
    eng.state.add_to_battlefield(eid)
    bind_from_catalogue(eid)

    victim = GameObject(Card(id="v", name="Victim", type_line="Creature — Ox",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.add_to_battlefield(victim)
    _aura(eng, "p1", victim.instance_id, "MyAuraA")
    _aura(eng, "p1", victim.instance_id, "MyAuraB")
    _aura(eng, "p2", victim.instance_id, "TheirAura")  # not yours -> not counted
    eng.recompute_continuous_effects()

    hand_before = len(p1.hand)
    eng.rules.destroy(victim)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_before + 2


def test_no_draw_when_you_controlled_no_aura_on_it():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        p1.add_to_zone(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Plains",
                                       is_land=True), owner_id="p1", zone=Zone.LIBRARY),
                       Zone.LIBRARY)
    eid = GameObject(_eidolon_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eid.controller_id = "p1"
    eid.summoning_sick = False
    eng.state.add_to_battlefield(eid)
    bind_from_catalogue(eid)
    victim = GameObject(Card(id="v", name="Victim", type_line="Creature — Ox",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.add_to_battlefield(victim)
    _aura(eng, "p2", victim.instance_id, "TheirAura")
    eng.recompute_continuous_effects()

    hand_before = len(p1.hand)
    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    assert len(p1.hand) == hand_before
