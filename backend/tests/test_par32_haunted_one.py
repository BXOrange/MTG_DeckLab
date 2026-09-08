"""PAR-32 / MEC-59 — Haunted One's granted becomes-tapped tribal pump:

    Commander creatures you own have "Whenever this creature becomes
    tapped, it and other creatures you control that share a creature
    type with it each get +2/+0 and gain undying until end of turn."

Hand-authored (`ability_catalogue.entries_016._haunted_one`): a granted
`TAPPED` trigger (already grantable-shaped, self-subject) whose
`grant_effects` pump uses the new `PumpEffect` selector
`self_and_shared_creature_type_you_control` — self plus every other
creature the same controller controls sharing at least one printed
creature subtype, computed off the source's own live subtypes.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue


def test_haunted_one_registered_with_tapped_trigger_and_selector():
    specs = ability_catalogue.specs_for(
        Card(id="ho", name="Haunted One",
             type_line="Legendary Enchantment — Background"))
    assert specs is not None and len(specs) == 1
    (grant,) = specs[0].effects
    assert grant.type == "grant_triggered_ability"
    assert grant.params["affects"] == "commander_creatures_you_own"
    assert grant.params["trigger_event"] == "TAPPED"
    (pump,) = grant.params["grant_effects"]
    assert pump["type"] == "pump"
    assert pump["params"]["selector"] == "self_and_shared_creature_type_you_control"
    assert pump["params"]["power"] == 2 and pump["params"]["toughness"] == 0
    assert pump["params"]["keywords"] == ["undying"]


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )


def _bf(st, card, controller="p1", commander=False):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.summoning_sick = False
    o.is_commander = commander
    st.add_to_battlefield(o)
    return o


def test_becomes_tapped_pumps_self_and_shared_type_creatures():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ho", name="Haunted One",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Skeleton Knight",
                        type_line="Legendary Creature — Skeleton Knight",
                        is_creature=True, power=2, toughness=2), commander=True)
    kin = _bf(st, Card(id="s", name="Skeleton Peon",
                        type_line="Creature — Skeleton",
                        is_creature=True, power=1, toughness=1))
    stranger = _bf(st, Card(id="b", name="Grizzly Bear",
                             type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(cmd, True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert cmd.power == 4 and cmd.toughness == 2
    assert kin.power == 3 and kin.toughness == 1
    assert stranger.power == 2 and stranger.toughness == 2  # no shared type
    assert "undying" in cmd.granted_keywords
    assert "undying" in kin.granted_keywords
    assert "undying" not in stranger.granted_keywords


def test_opponents_creature_of_the_same_type_is_untouched():
    eng = _engine()
    st = eng.state
    granter = _bf(st, Card(
        id="ho", name="Haunted One",
        type_line="Legendary Enchantment — Background"))
    bind_from_catalogue(granter)
    cmd = _bf(st, Card(id="k", name="Skeleton Knight",
                        type_line="Legendary Creature — Skeleton Knight",
                        is_creature=True, power=2, toughness=2), commander=True)
    enemy_kin = _bf(st, Card(id="es", name="Enemy Skeleton",
                              type_line="Creature — Skeleton",
                              is_creature=True, power=1, toughness=1),
                     controller="p2")
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(cmd, True)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert cmd.power == 4
    assert enemy_kin.power == 1 and enemy_kin.toughness == 1
