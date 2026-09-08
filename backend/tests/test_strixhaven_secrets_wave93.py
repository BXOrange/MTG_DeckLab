"""Secrets of Strixhaven — playability batch, wave 93 (PAR-60).

Rousing Refrain — reuse of `AddManaEffect` (``target_kind="opponent"`` +
``amount_from_target_hand_size``). Documented simplification: the
mana-persistence clause and the self-exile-with-time-counters are dropped;
Suspend folds in from the keyword catalogue.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _rr_card():
    return Card(id="rr", name="Rousing Refrain", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Add {R} for each card in target opponent's hand. Until end "
                             "of turn, you don't lose this mana as steps and phases end. "
                             "Exile Rousing Refrain with three time counters on it.\n"
                             "Suspend 3—{1}{R}"))


def test_registered_and_binds():
    assert is_registered("Rousing Refrain")
    spec = _REGISTRY["rousing refrain"]()[0]
    spec.validate()
    assert spec.effects[0].type == "add_mana"
    assert spec.effects[0].params["amount_from_target_hand_size"] is True
    src = GameObject(_rr_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_rr_card())


def test_adds_red_mana_per_card_in_target_opponents_hand():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    for i in range(4):
        p2.add_to_zone(GameObject(Card(id=f"h{i}", name=f"h{i}", type_line="Sorcery",
                                       is_sorcery=True), owner_id="p2", zone=Zone.HAND),
                       Zone.HAND)
    src = GameObject(_rr_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eng.rules._apply_effect_specs(
        [{"type": "add_mana", "params": {"color": "R", "target_kind": "opponent",
                                         "amount_from_target_hand_size": True}}],
        src, targets=[p2],
    )
    eng.resolve_until_stable()
    assert p1.mana_pool.pool.get("R", 0) == 4
