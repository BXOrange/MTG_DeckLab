"""Secrets of Strixhaven — playability batch, wave 91 (PAR-60).

Serra Paragon — reuse of `graveyard_cast_permission` (Lurrus-shaped: MV cap
+ once/turn + ``exile_if_would_be_put_into_graveyard``). Documented
simplification: the land-play alternative and the "gain 2 life" tail are
dropped.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _serra_card():
    return Card(id="sp", name="Serra Paragon", type_line="Creature — Angel",
                is_creature=True, power=3, toughness=4,
                oracle_text=("Flying\nOnce during each of your turns, you may play a land "
                             "from your graveyard or cast a permanent spell with mana "
                             "value 3 or less from your graveyard. If you do, it gains "
                             "\"When this permanent is put into a graveyard from the "
                             "battlefield, exile it and you gain 2 life.\""))


def test_registered_and_binds():
    assert is_registered("Serra Paragon")
    spec = _REGISTRY["serra paragon"]()[0]
    spec.validate()
    assert spec.effects[0].type == "graveyard_cast_permission"
    assert spec.effects[0].params["max_mana_value"] == 3
    assert spec.effects[0].params["exile_if_would_be_put_into_graveyard"] is True
    src = GameObject(_serra_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_serra_card())


def test_allows_casting_a_cheap_permanent_from_graveyard():
    from mtg_analyzer.game.graveyard_cast import may_cast_spell_from_graveyard

    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    serra = GameObject(_serra_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    serra.controller_id = "p1"
    eng.state.add_to_battlefield(serra)
    bind_from_catalogue(serra)
    eng.recompute_continuous_effects()

    p1 = eng.state.player_by_id("p1")
    cheap = Card(id="c", name="Cheap Rock", type_line="Artifact", converted_mana_cost=2)
    expensive = Card(id="e", name="Big Rock", type_line="Artifact", converted_mana_cost=5)
    p1.add_to_zone(GameObject(cheap, owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)
    p1.add_to_zone(GameObject(expensive, owner_id="p1", zone=Zone.GRAVEYARD), Zone.GRAVEYARD)

    assert may_cast_spell_from_graveyard(p1, eng.state, cheap)
    assert not may_cast_spell_from_graveyard(p1, eng.state, expensive)
