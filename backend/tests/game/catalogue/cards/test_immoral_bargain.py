"""Immoral Bargain resolves its additional-cost sacrifice and scaling effect."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ib_card():
    return Card(id="ib", name="Immoral Bargain", type_line="Sorcery", is_sorcery=True,
                oracle_text=("As an additional cost to cast this spell, sacrifice X "
                             "creatures. Destroy X target nonland permanents."))


def test_registered_and_binds():
    assert is_registered("Immoral Bargain")
    spec = _REGISTRY["immoral bargain"]()[0]
    spec.validate()
    assert spec.effects[0].type == "immoral_bargain"
    src = GameObject(_ib_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ib_card())


def test_destroy_choose_action_removes_the_pick():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    victim = GameObject(Card(id="v", name="Bear", type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.add_to_battlefield(victim)
    src = GameObject(_ib_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._request_choose_objects(
        eng.state.player_by_id("p1"), [victim], "destroy", count=1, source=src)
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield
    assert any(o.card.name == "Bear" for o in eng.state.player_by_id("p2").graveyard)


def test_destroy_tail_scales_with_graveyard_delta():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    src = GameObject(_ib_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    for i in range(2):
        p1.add_to_zone(GameObject(Card(id=f"s{i}", name="Sacked", type_line="Creature",
                                       is_creature=True), owner_id="p1", zone=Zone.GRAVEYARD),
                       Zone.GRAVEYARD)
    targets = []
    for i in range(3):
        o = GameObject(Card(id=f"t{i}", name=f"Perm{i}", type_line="Enchantment"),
                       owner_id="p2", zone=Zone.BATTLEFIELD)
        o.controller_id = "p2"
        eng.state.add_to_battlefield(o)
        targets.append(o)

    eng.rules._apply_effect_specs(
        [{"type": "immoral_bargain_destroy", "params": {"player_id": "p1", "before": 0}}], src)
    # X == 2 -> a two-pick destroy chooser
    eng.resolve_pending_choice(str(targets[0].instance_id))
    eng.resolve_pending_choice(str(targets[1].instance_id))
    eng.resolve_until_stable()
    survivors = [o for o in eng.state.battlefield if o.card.name.startswith("Perm")]
    assert len(survivors) == 1
