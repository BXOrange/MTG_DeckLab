"""Secrets of Strixhaven — playability batch, wave 98 (PAR-60).

Plumb the Forbidden — new `sacrifice_any_number_draw_lose_scaled` effect,
the Eventide's Shadow sacrifice-choose + graveyard-delta-tail idiom.
Documented simplification: "copy this spell for each creature sacrificed"
is modeled as its net effect (one extra draw + 1 life loss per creature).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _plumb_card():
    return Card(id="plumb", name="Plumb the Forbidden", type_line="Instant", is_instant=True,
                oracle_text=("As an additional cost to cast this spell, you may "
                             "sacrifice one or more creatures. When you do, copy this "
                             "spell for each creature sacrificed this way. You draw a "
                             "card and lose 1 life."))


def test_registered_and_binds():
    assert is_registered("Plumb the Forbidden")
    spec = _REGISTRY["plumb the forbidden"]()[0]
    spec.validate()
    assert spec.effects[0].type == "sacrifice_any_number_draw_lose_scaled"
    src = GameObject(_plumb_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_plumb_card())


def _lib(player, n):
    for i in range(n):
        player.add_to_zone(
            GameObject(Card(id=f"L{i}{id(object())}", name="filler", type_line="Sorcery",
                            is_sorcery=True), owner_id=player.id, zone=Zone.LIBRARY),
            Zone.LIBRARY,
        )


def test_base_draw_and_loss_with_no_sacrifice():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    _lib(p1, 5)
    src = GameObject(_plumb_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    eng.rules._apply_effect_specs(
        [{"type": "sacrifice_any_number_draw_lose_scaled", "params": {}}], src)
    eng.resolve_until_stable()
    assert len(p1.hand) == 1
    assert p1.life == 19


def test_scaled_tail_reads_graveyard_delta():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    _lib(p1, 5)
    src = GameObject(_plumb_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    # two creatures already in the graveyard simulate the sacrifice delta
    for i in range(2):
        p1.add_to_zone(GameObject(Card(id=f"c{i}", name="Dead", type_line="Creature",
                                       is_creature=True), owner_id="p1", zone=Zone.GRAVEYARD),
                       Zone.GRAVEYARD)
    eng.rules._apply_effect_specs(
        [{"type": "sacrifice_count_draw_lose", "params": {"player_id": "p1", "before": 0}}], src)
    eng.resolve_until_stable()
    assert len(p1.hand) == 2
    assert p1.life == 18
