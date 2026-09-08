"""Inkshield prevents combat damage and creates Inkling tokens."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ink_card():
    return Card(id="ink", name="Inkshield", type_line="Instant", is_instant=True,
                oracle_text=("Prevent all combat damage that would be dealt to you "
                             "this turn. For each 1 damage prevented this way, create "
                             "a 2/1 white and black Inkling creature token with flying."))


def test_registered_and_binds():
    assert is_registered("Inkshield")
    spec = _REGISTRY["inkshield"]()[0]
    spec.validate()
    assert spec.effects[0].type == "prevent_damage_shield"
    src = GameObject(_ink_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ink_card())


def test_prevents_combat_damage_and_tokenizes_but_lets_noncombat_through():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    src = GameObject(_ink_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    attacker = GameObject(Card(id="atk", name="Ogre", type_line="Creature — Ogre",
                               is_creature=True, power=5, toughness=5),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
    attacker.controller_id = "p2"
    eng.state.add_to_battlefield(attacker)

    eng.rules._apply_effect_specs(
        [{"type": "prevent_damage_shield", "params": {
            "amount": "all", "combat_only": True,
            "rider": {"kind": "create_tokens_scaled", "recipient": "you",
                      "token": {"token_name": "Inkling", "power": 2, "toughness": 1,
                                "colors": ["W", "B"], "subtypes": ["Inkling"],
                                "keywords": ["flying"]}},
        }}], src,
    )

    eng.rules.deal_damage(p1, 5, source=attacker, combat=True)
    assert p1.life == 20
    inklings = [o for o in eng.state.battlefield if o.card.name == "Inkling"]
    assert len(inklings) == 5

    # non-combat damage still gets through
    eng.rules.deal_damage(p1, 3, source=attacker, combat=False)
    assert p1.life == 17
    assert len([o for o in eng.state.battlefield if o.card.name == "Inkling"]) == 5
