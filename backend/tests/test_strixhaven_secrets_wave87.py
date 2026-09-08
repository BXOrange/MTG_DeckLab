"""Secrets of Strixhaven — playability batch, wave 87 (PAR-60).

Surge to Victory — new `surge_to_victory` effect (exile target i/s card
from your graveyard, creatures you control get +X/+0 = its MV). Documented
simplification: the copy-on-combat-damage rider is dropped.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _stv_card():
    return Card(id="stv", name="Surge to Victory", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Exile target instant or sorcery card from your graveyard. "
                             "Creatures you control get +X/+0 until end of turn, where X "
                             "is that card's mana value. Whenever a creature you control "
                             "deals combat damage to a player this turn, copy the exiled "
                             "card. You may cast the copy without paying its mana cost."))


def test_registered_and_binds():
    assert is_registered("Surge to Victory")
    spec = _REGISTRY["surge to victory"]()[0]
    spec.validate()
    assert spec.effects[0].type == "surge_to_victory"
    src = GameObject(_stv_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_stv_card())


def test_exiles_the_card_and_pumps_your_team_by_its_mv():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    bolt = GameObject(Card(id="b", name="Big Spell", type_line="Sorcery", is_sorcery=True,
                           converted_mana_cost=4),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(bolt, Zone.GRAVEYARD)

    c1 = GameObject(Card(id="c1", name="C1", type_line="Creature — Bear", is_creature=True,
                         power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD)
    c1.controller_id = "p1"
    c2 = GameObject(Card(id="c2", name="C2", type_line="Creature — Ox", is_creature=True,
                         power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    c2.controller_id = "p1"
    eng.state.add_to_battlefield(c1)
    eng.state.add_to_battlefield(c2)
    src = GameObject(_stv_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    eng.recompute_continuous_effects()

    eng.rules._apply_effect_specs([{"type": "surge_to_victory", "params": {}}],
                                  src, targets=[bolt])
    eng.recompute_continuous_effects()

    assert bolt.zone == Zone.EXILE
    assert c1.power == 6   # 2 + 4
    assert c2.power == 5   # 1 + 4
