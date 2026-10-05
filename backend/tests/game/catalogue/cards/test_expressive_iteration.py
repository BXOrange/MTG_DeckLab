"""Expressive Iteration selects, exiles, and grants a temporary play window."""

from __future__ import annotations

from mtg_analyzer.game.card_registry import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ei_card():
    return Card(id="ei", name="Expressive Iteration", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Look at the top three cards of your library. Put one of "
                             "them into your hand, put one of them on the bottom of your "
                             "library, and exile one of them. You may play the exiled "
                             "card this turn."))


def test_registered_and_binds():
    assert is_registered("Expressive Iteration")
    spec = _REGISTRY["expressive iteration"]()[0]
    spec.validate()
    assert spec.effects[0].type == "expressive_iteration"
    src = GameObject(_ei_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_ei_card())


def test_one_to_hand_one_exiled_playable_one_to_bottom():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    names = ["Bottom5", "Bottom4", "Bottom3", "TOP_C", "TOP_B", "TOP_A"]
    for n in names:
        p1.add_to_zone(GameObject(Card(id=n, name=n, type_line="Sorcery", is_sorcery=True),
                                  owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    # top of library (list end) = TOP_A, then TOP_B, TOP_C
    # a battlefield object as the effect source so the chooser's then_specs
    # can recover it by instance id (a real EI spell sits on the stack)
    src = GameObject(Card(id="ei", name="Expressive Iteration Source",
                          type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "expressive_iteration", "params": {}}], src)
    # pick 1: put TOP_A into hand
    assert eng.state.pending_choice["kind"] == "choose_objects"
    a_id = next(o.instance_id for o in p1.library if o.card.name == "TOP_A")
    eng.resolve_pending_choice(str(a_id))
    # pick 2: exile TOP_B (playable this turn); TOP_C -> bottom
    assert eng.state.pending_choice["kind"] == "choose_objects"
    b_id = next(o.instance_id for o in p1.library if o.card.name == "TOP_B")
    eng.resolve_pending_choice(str(b_id))
    eng.resolve_until_stable()

    assert any(o.card.name == "TOP_A" for o in p1.hand)
    exiled = [o for o in p1.exile if o.card.name == "TOP_B"]
    assert len(exiled) == 1
    assert exiled[0].instance_id in eng.state.temp_play_permissions
    # TOP_C went to the bottom (index 0)
    assert p1.library[0].card.name == "TOP_C"
