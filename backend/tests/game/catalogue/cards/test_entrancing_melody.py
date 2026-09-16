"""Entrancing Melody gains control of a creature."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def test_entrancing_melody_registered_and_binds():
    assert is_registered("Entrancing Melody")
    spec = _REGISTRY["entrancing melody"]()[0]
    spec.validate()
    eff = spec.effects[0]
    assert eff.type == "gain_control_until_eot"
    assert eff.params["duration"] == "permanent"
    assert eff.params["untap"] is False
    assert eff.params["max_mana_value"] == "x"
    src = GameObject(card=Card(id="em", name="Entrancing Melody", type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_permanent_control_change_survives_cleanup():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    victim = GameObject(card=Card(id="v", name="Bear", type_line="Creature — Bear",
                                 is_creature=True, power=2, toughness=2,
                                 mana_cost_string="{1}{G}"),
                        owner_id=p2.id, zone=Zone.BATTLEFIELD)
    victim.controller_id = p2.id
    victim.tapped = True
    eng.state.add_to_battlefield(victim)

    src = GameObject(card=Card(id="em", name="Entrancing Melody", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    src.x_paid = 2
    ability = bind_ability(_REGISTRY["entrancing melody"]()[0], src)
    for e in (ability if isinstance(ability, list) else [ability]):
        e.source = src
        e.apply(eng.rules.context, targets=[victim])
    eng.resolve_until_stable()

    assert victim.controller_id == p1.id
    assert victim.tapped is True  # no untap
    assert victim.control_change_until_eot is None  # permanent, not EOT
    if hasattr(eng.rules, "_step_cleanup"):
        eng.rules._step_cleanup()
    assert victim.controller_id == p1.id  # still ours after cleanup
