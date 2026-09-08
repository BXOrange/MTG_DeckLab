"""Dance with Calamity exiles cards within a mana-value limit."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _dc_card():
    return Card(id="dc", name="Dance with Calamity", type_line="Sorcery", is_sorcery=True,
                oracle_text=("Shuffle your library. As many times as you choose, you may "
                             "exile the top card of your library. If the total mana "
                             "value of the cards exiled this way is 13 or less, you may "
                             "cast any number of spells from among those cards without "
                             "paying their mana costs."))


def test_registered_and_binds():
    assert is_registered("Dance with Calamity")
    spec = _REGISTRY["dance with calamity"]()[0]
    spec.validate()
    assert spec.effects[0].type == "dance_with_calamity"
    src = GameObject(_dc_card(), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_dc_card())


def test_exiles_up_to_budget_and_grants_free_casts():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    p1 = eng.state.player_by_id("p1")
    # library top-first: MV 5, MV 5, MV 4 (total 14 > 13 -> stop before the 4)
    for name, mv in [("Third", 4), ("Second", 5), ("First", 5)]:
        p1.add_to_zone(GameObject(Card(id=name, name=name, type_line="Sorcery",
                                       is_sorcery=True, converted_mana_cost=mv),
                                  owner_id="p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    src = GameObject(_dc_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "dance_with_calamity", "params": {}}], src)
    eng.resolve_until_stable()

    # library was shuffled, so which cards get exiled depends on the shuffle,
    # but the greedy loop never lets the exiled total mana value exceed 13
    exiled_mv = sum(int(o.card.converted_mana_cost or 0) for o in p1.exile)
    assert 1 <= len(p1.exile) <= 3
    assert exiled_mv <= 13
    assert len(p1.exile) + len(p1.library) == 3
    for o in p1.exile:
        assert o.instance_id in eng.state.free_cast_instance_ids
        assert o.instance_id in eng.state.temp_play_permissions
