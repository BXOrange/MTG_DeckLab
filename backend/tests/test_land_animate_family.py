"""MEC-12 (cEDH staples 2) — the land-animate family: Kamahl, Heart of
Krosa's "target land you control becomes a 1/1 … creature … It's still a
land." and Ashaya, Soul of the Wild's reverse-direction "nontoken creatures
you control are Forest lands in addition to their other types."

New primitives: chaining two `grant_until` `EffectSpec`s onto the same
resolve-time target via `GrantUntilEffect.previous_subject` (Kamahl); the
`pt_cda` static's first real card (Ashaya's characteristic-defining P/T);
`continuous.affected_objects`'s new ``"nontoken_creatures_you_control"``
scope; and a real, general bug fix — `GameObject.is_land` had never folded
in a layer-4 `add_types` grant the way `is_creature` already does, so no
card could ever make something a land via a static before this.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game import mana_abilities
from mtg_analyzer.game.effect_binder import bind_from_catalogue

from tests.test_game_engine import land, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_kamahl_animates_a_land_until_end_of_turn():
    eng = make_engine([_named("Kamahl, Heart of Krosa")], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})

    kamahl = obj_on_battlefield(eng.state, eng, _named("Kamahl, Heart of Krosa"), controller="p1")
    bind_from_catalogue(kamahl)
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    eng.recompute_continuous_effects()
    assert forest.is_creature is False

    eng.activate_ability(p1, kamahl, ability_index=0, targets=[forest])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert forest.is_creature is True
    assert forest.is_land is True  # "It's still a land."
    assert forest.power == 1
    assert forest.toughness == 1
    assert forest.granted_keywords >= {"vigilance", "indestructible", "haste"}


def test_kamahl_animation_ends_at_cleanup():
    eng = make_engine([_named("Kamahl, Heart of Krosa")], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 1})

    kamahl = obj_on_battlefield(eng.state, eng, _named("Kamahl, Heart of Krosa"), controller="p1")
    bind_from_catalogue(kamahl)
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")

    eng.activate_ability(p1, kamahl, ability_index=0, targets=[forest])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert forest.is_creature is True

    from mtg_analyzer.game import durations
    durations.sweep(eng.state, "cleanup")
    eng.recompute_continuous_effects()
    assert forest.is_creature is False
    assert forest.is_land is True


def test_ashaya_power_toughness_equal_lands_controlled():
    eng = make_engine([_named("Ashaya, Soul of the Wild")], [], hand=0)
    ashaya = obj_on_battlefield(eng.state, eng, _named("Ashaya, Soul of the Wild"), controller="p1")
    bind_from_catalogue(ashaya)
    obj_on_battlefield(eng.state, eng, land(), controller="p1")
    obj_on_battlefield(eng.state, eng, land("Island", "Island"), controller="p1")

    eng.recompute_continuous_effects()

    # 2 real lands + Ashaya herself, since her own second ability makes her
    # (a nontoken creature she controls) a Forest land too — a real,
    # documented ruling on this card, not a test-authoring slip.
    assert ashaya.power == 3
    assert ashaya.toughness == 3


def test_ashaya_makes_nontoken_creatures_you_control_forest_lands():
    eng = make_engine([_named("Ashaya, Soul of the Wild")], [], hand=0)
    ashaya = obj_on_battlefield(eng.state, eng, _named("Ashaya, Soul of the Wild"), controller="p1")
    bind_from_catalogue(ashaya)
    from tests.test_game_engine import creature

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", cost="{1}{G}"), controller="p1")
    eng.recompute_continuous_effects()

    assert bear.is_land is True
    assert bear.is_creature is True  # still a creature too
    options = mana_abilities.mana_abilities_for(bear, eng.state)
    assert any(a.options == [{"G": 1}] for a in options)


def test_ashaya_does_not_affect_token_creatures():
    from mtg_analyzer.models.card import Card
    from mtg_analyzer.models.game_object import GameObject, Zone

    eng = make_engine([_named("Ashaya, Soul of the Wild")], [], hand=0)
    ashaya = obj_on_battlefield(eng.state, eng, _named("Ashaya, Soul of the Wild"), controller="p1")
    bind_from_catalogue(ashaya)

    token_card = Card(
        id="Bear Token", name="Bear Token", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
    )
    token = GameObject(token_card, owner_id="p1", zone=Zone.BATTLEFIELD, is_token=True)
    eng.state.add_to_battlefield(token)
    eng.recompute_continuous_effects()

    assert token.is_land is False
