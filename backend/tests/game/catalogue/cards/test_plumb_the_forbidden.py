"""Plumb the Forbidden scales card draw and life loss with sacrificed creatures."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


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


@pytest.mark.parametrize("sacrifices", [0, 1, 2])
@pytest.mark.parametrize("tokens", [False, True])
def test_cast_plumb_counts_only_selected_creatures_during_resolution(sacrifices, tokens):
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    eng.advance_step()
    eng.state.current_phase, eng.state.current_step = "main", "main1"
    p = eng.state.player_by_id("p1")
    _lib(p, 10)
    src = GameObject(Card(id="plumb-cost", name="Plumb the Forbidden", type_line="Instant",
                          is_instant=True, mana_cost_string="{1}{B}", mana_cost={"generic": 1, "B": 1}),
                     owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(src)
    p.add_to_zone(src, Zone.HAND)
    victims = []
    for i in range(2):
        obj = GameObject(Card(id=f"victim-{i}", name=f"Victim {i}", type_line="Creature",
                              is_creature=True, power=2, toughness=2), owner_id="p1", zone=Zone.BATTLEFIELD, is_token=tokens)
        eng.state.add_to_battlefield(obj)
        victims.append(obj)
    p.mana_pool.add_many({"B": 1, "C": 1})
    eng.cast_spell(p, src)
    eng.resolve_until_stable()
    assert src.zone == Zone.STACK and src not in p.graveyard
    for victim in victims[:sacrifices]:
        eng.resolve_pending_choice(str(victim.instance_id))
    if eng.state.pending_choice:
        eng.resolve_pending_choice("decline")
    assert src in p.graveyard
    assert len(p.hand) == 1 + sacrifices and p.life == 19 - sacrifices
    assert all(v.zone == Zone.BATTLEFIELD for v in victims[sacrifices:])
