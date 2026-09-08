"""MEC-40 — cEDH Rocco / cEDH staples remaining gaps, batch 1: Abrupt Decay
(a plain parser fix — `_destroy_mv`'s allowed-kinds tuple was missing
"nonland_permanent" despite its own docstring already naming Abrupt Decay),
Culling Ritual, Cabal Ritual, Ranger-Captain of Eos, Vexing Shusher, Tinder
Wall.

Reference: docs/implementation-state/Done_Backend.md "MEC-40" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _cast(eng, p1, mana):
    eng.begin_turn()
    eng.state.current_step = "main1"
    spell = p1.hand[0]
    bind_from_catalogue(spell)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    return spell


# ---------------------------------------------------------------------------
# Abrupt Decay — parser fix only, no catalogue entry
# ---------------------------------------------------------------------------


def test_abrupt_decay_destroys_a_cheap_nonland_permanent():
    eng = make_engine([_named("Abrupt Decay")], [_named("Abrupt Decay")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    cheap = _put(eng.state, creature("Cheap Bear", cost="{1}", power=1, toughness=1), controller="p2")
    expensive = _put(
        eng.state, creature("Big Bear", cost="{5}", power=5, toughness=5), controller="p2"
    )

    eng.begin_turn()
    eng.state.current_step = "main1"
    spell = p1.hand[0]
    bind_from_catalogue(spell)
    p1.mana_pool.add_many({"B": 1, "G": 1})
    eng.cast_spell(p1, spell, targets=[cheap])
    eng.resolve_until_stable()

    assert cheap not in eng.state.battlefield
    assert expensive in eng.state.battlefield
    assert p2 is not None


def test_abrupt_decay_cannot_target_an_expensive_permanent():
    eng = make_engine([_named("Abrupt Decay")], hand=1)
    p1 = eng.state.player_by_id("p1")
    expensive = _put(eng.state, creature("Big Bear", cost="{5}", power=5, toughness=5), controller="p1")

    eng.begin_turn()
    eng.state.current_step = "main1"
    spell = p1.hand[0]
    bind_from_catalogue(spell)
    from mtg_analyzer.game.targeting import legal_targets, TargetSpec

    legal = legal_targets(eng.state, "p1", TargetSpec(kind="nonland_permanent", max_mana_value=3), source=spell)
    assert expensive.instance_id not in {o["instance_id"] for o in legal}


# ---------------------------------------------------------------------------
# Culling Ritual
# ---------------------------------------------------------------------------


def test_culling_ritual_destroys_cheap_nonland_permanents_and_spares_lands_and_expensive():
    eng = make_engine([_named("Culling Ritual")], hand=1)
    p1 = eng.state.player_by_id("p1")
    from mtg_analyzer.models.cards.card import Card

    cheap_one = _put(eng.state, creature("Cheap One", cost="{1}", power=1, toughness=1), controller="p1")
    cheap_two = _put(eng.state, creature("Cheap Two", cost="{G}", power=1, toughness=1), controller="p1")
    expensive = _put(eng.state, creature("Big Bear", cost="{5}", power=5, toughness=5), controller="p1")
    a_land = GameObject(Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(a_land)

    _cast(eng, p1, {"B": 1, "G": 1, "C": 2})
    # `add_mana_any_color`'s pending choice for the "ANY" combination
    assert eng.state.pending_choice is not None
    assert eng.state.pending_choice["kind"] == "add_mana_any_color"
    offered = {o["id"] for o in eng.state.pending_choice["options"]}
    assert offered == {"B", "G"}
    eng.resolve_pending_choice("B")

    assert cheap_one not in eng.state.battlefield
    assert cheap_two not in eng.state.battlefield
    assert expensive in eng.state.battlefield
    assert a_land in eng.state.battlefield
    # 2 destroyed permanents -> 2 mana of the chosen color
    assert p1.mana_pool.pool.get("B", 0) == 2


def test_culling_ritual_produces_no_mana_when_nothing_destroyed():
    eng = make_engine([_named("Culling Ritual")], hand=1)
    p1 = eng.state.player_by_id("p1")
    only_expensive = _put(eng.state, creature("Big Bear", cost="{5}", power=5, toughness=5), controller="p1")

    _cast(eng, p1, {"B": 1, "G": 1, "C": 2})

    assert only_expensive in eng.state.battlefield
    assert eng.state.pending_choice is None
    assert p1.mana_pool.pool.get("B", 0) == 0
    assert p1.mana_pool.pool.get("G", 0) == 0


# ---------------------------------------------------------------------------
# Cabal Ritual
# ---------------------------------------------------------------------------


def test_cabal_ritual_adds_three_black_below_threshold():
    eng = make_engine([_named("Cabal Ritual")], hand=1)
    p1 = eng.state.player_by_id("p1")
    _cast(eng, p1, {"B": 1, "C": 1})
    assert p1.mana_pool.pool.get("B", 0) == 3


def test_cabal_ritual_adds_five_black_at_threshold():
    eng = make_engine([_named("Cabal Ritual")], hand=1)
    p1 = eng.state.player_by_id("p1")
    for i in range(7):
        p1.graveyard.append(GameObject(creature(f"Filler {i}"), owner_id="p1", zone=Zone.GRAVEYARD))
    _cast(eng, p1, {"B": 1, "C": 1})
    assert p1.mana_pool.pool.get("B", 0) == 5


# ---------------------------------------------------------------------------
# Ranger-Captain of Eos
# ---------------------------------------------------------------------------


def test_ranger_captain_etb_search_puts_cheap_creature_in_hand():
    small = creature("Small One", cost="{G}", power=1, toughness=1)
    eng = make_engine([_named("Ranger-Captain of Eos")], hand=1)
    p1 = eng.state.player_by_id("p1")
    small_obj = GameObject(small, owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(small_obj)

    obj = p1.hand[0]
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"W": 3})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    pick = next(o for o in choice["options"] if o.get("instance_id") == small_obj.instance_id)
    eng.resolve_pending_choice(pick["id"])
    eng.resolve_until_stable()
    assert any(o.card is small for o in p1.hand)


def test_ranger_captain_sacrifice_shuts_off_opponent_noncreature_casting():
    eng = make_engine([_named("Ranger-Captain of Eos")], [_named("Ranger-Captain of Eos")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    ranger = _put(eng.state, _named("Ranger-Captain of Eos"), controller="p1")

    from mtg_analyzer.models.cards.card import Card

    bolt = Card(id="Lightning Bolt", name="Lightning Bolt", type_line="Instant", is_instant=True,
                mana_cost_string="{R}", converted_mana_cost=1,
                oracle_text="~ deals 3 damage to any target.")
    bolt_obj = GameObject(bolt, owner_id="p2", zone=Zone.HAND)
    p2.hand.append(bolt_obj)
    bind_from_catalogue(bolt_obj)
    p2.mana_pool.add_many({"R": 1})

    assert eng.can_cast(p2, bolt_obj)
    eng.activate_ability(p1, ranger, ability_index=0)
    eng.resolve_until_stable()

    assert ranger not in eng.state.battlefield
    assert not eng.can_cast(p2, bolt_obj)
    # p1's own noncreature casts are untouched (scope="opponents")
    p1_bolt = GameObject(bolt, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(p1_bolt)
    bind_from_catalogue(p1_bolt)
    p1.mana_pool.add_many({"R": 1})
    assert eng.can_cast(p1, p1_bolt)


# ---------------------------------------------------------------------------
# Vexing Shusher
# ---------------------------------------------------------------------------


def test_vexing_shusher_static_makes_itself_uncounterable():
    from mtg_analyzer.game.effects.core import CantBeCounteredEffect

    eng = make_engine([_named("Vexing Shusher")], hand=1)
    obj = eng.state.player_by_id("p1").hand[0]
    bind_from_catalogue(obj)
    assert any(isinstance(e, CantBeCounteredEffect) for e in obj.static_effects)


def test_vexing_shusher_ability_marks_target_spell_uncounterable():
    eng = make_engine([_named("Vexing Shusher")], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    shusher = _put(eng.state, _named("Vexing Shusher"), controller="p1")

    from mtg_analyzer.models.cards.card import Card

    ritual = Card(id="Dark Ritual", name="Dark Ritual", type_line="Instant", is_instant=True,
                  mana_cost_string="{B}", converted_mana_cost=1, oracle_text="Add {B}{B}{B}.")
    ritual_obj = GameObject(ritual, owner_id="p2", zone=Zone.HAND)
    p2.hand.append(ritual_obj)
    bind_from_catalogue(ritual_obj)
    p2.mana_pool.add_many({"B": 1})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.cast_spell(p2, ritual_obj)

    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, shusher, ability_index=0, targets=[ritual_obj])
    eng.resolve_until_stable()

    from mtg_analyzer.game.effects.core import CantBeCounteredEffect

    assert any(isinstance(e, CantBeCounteredEffect) for e in ritual_obj.spell_effects)


# ---------------------------------------------------------------------------
# Tinder Wall
# ---------------------------------------------------------------------------


def test_tinder_wall_can_only_target_the_creature_it_is_blocking():
    eng = make_engine([_named("Tinder Wall")], [creature("Attacker", power=3, toughness=3)], hand=0)
    wall = _put(eng.state, _named("Tinder Wall"), controller="p1")
    attacker = _put(eng.state, creature("Attacker", power=3, toughness=3), controller="p2")
    bystander = _put(eng.state, creature("Bystander", power=3, toughness=3), controller="p2")
    wall.blocking = attacker.instance_id

    from mtg_analyzer.game.targeting import legal_targets, TargetSpec

    legal = legal_targets(
        eng.state, "p1", TargetSpec(kind="creature_source_is_blocking"), source=wall,
    )
    ids = {o["instance_id"] for o in legal}
    assert ids == {attacker.instance_id}
    assert bystander.instance_id not in ids


def test_tinder_wall_sacrifices_itself_to_damage_the_blocked_attacker():
    eng = make_engine([_named("Tinder Wall")], [creature("Attacker", power=3, toughness=3)], hand=0)
    p1 = eng.state.player_by_id("p1")
    wall = _put(eng.state, _named("Tinder Wall"), controller="p1")
    attacker = _put(eng.state, creature("Attacker", power=3, toughness=3), controller="p2")
    wall.blocking = attacker.instance_id
    attacker.blocked_by = [wall.instance_id]

    p1.mana_pool.add_many({"R": 1})
    eng.activate_ability(p1, wall, ability_index=0, targets=[attacker])
    eng.resolve_until_stable()

    assert wall not in eng.state.battlefield
    assert attacker.damage_marked == 2


def test_tinder_wall_sacrifices_for_red_mana():
    eng = make_engine([_named("Tinder Wall")], hand=0)
    p1 = eng.state.player_by_id("p1")
    wall = _put(eng.state, _named("Tinder Wall"), controller="p1")

    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    abilities = mana_abilities_for(wall)
    assert len(abilities) == 1
    assert abilities[0].options == [{"R": 2}]
