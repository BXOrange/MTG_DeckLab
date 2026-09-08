"""Secrets of Strixhaven — playability batch, wave 106 (PAR-60).

Advanced Reconstruction — hand-authored as a full Class. Level 1: new
`advanced_reconstruction_l1` effect (mill + random graveyard exile +
play-this-turn). Level 2: the batched ``CARDS_LEFT_GRAVEYARD`` trigger ->
2 damage to each opponent. Level 3: `cost_reduction` with the new
``not_from_hand`` param (documented simplification: command-zone commander
casts aren't covered).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _ar_card():
    return Card(id="ar", name="Advanced Reconstruction", type_line="Enchantment — Class",
                oracle_text=("(Gain the next level as a sorcery to add its ability.)\n"
                             "At the beginning of your first main phase, mill a card, then "
                             "exile a card from your graveyard at random. You may play the "
                             "exiled card this turn.\n{1}{R}: Level 2\nWhenever one or more "
                             "cards leave your graveyard, this Class deals 2 damage to "
                             "each opponent.\n{1}{R}: Level 3\nSpells you cast from "
                             "anywhere other than your hand cost {2} less to cast."))


def test_registered_and_binds():
    assert is_registered("Advanced Reconstruction")
    specs = _REGISTRY["advanced reconstruction"]()
    assert [s.effects[0].type for s in specs] == [
        "advanced_reconstruction_l1", "class_level", "damage", "class_level",
        "cost_reduction",
    ]
    src = GameObject(_ar_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_ar_card())


def test_l1_mills_and_impulse_exiles_from_graveyard():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    for i in range(3):
        p1.add_to_zone(GameObject(Card(id=f"L{i}", name=f"Lib{i}", type_line="Sorcery",
                                       is_sorcery=True), owner_id="p1", zone=Zone.LIBRARY),
                       Zone.LIBRARY)
    src = GameObject(_ar_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "advanced_reconstruction_l1", "params": {}}], src)
    eng.resolve_until_stable()
    assert len(p1.exile) == 1
    assert p1.exile[0].instance_id in eng.state.temp_play_permissions


def test_l3_cost_reduction_only_off_hand():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    static = EffectRegistry.create("cost_reduction", {
        "affects": "your_spells", "generic": 2, "not_from_hand": True,
    })
    holder = GameObject(_ar_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    holder.controller_id = "p1"
    static.source = holder
    holder.static_effects.append(static)
    eng.state.add_to_battlefield(holder)

    from_hand = GameObject(Card(id="h", name="HandSpell", type_line="Sorcery",
                                is_sorcery=True), owner_id="p1", zone=Zone.STACK)
    from_gy = GameObject(Card(id="g", name="Flashed", type_line="Sorcery", is_sorcery=True),
                         owner_id="p1", zone=Zone.STACK)
    from_gy.cast_via_flashback = True

    assert continuous.cost_reduction_for(eng.state, p1, obj=from_hand)[0] == 0
    assert continuous.cost_reduction_for(eng.state, p1, obj=from_gy)[0] == 2
