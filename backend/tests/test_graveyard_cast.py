"""Tests for the standing "cast [permanent] spells from your graveyard"
permission (Lurrus of the Dream-Den-shaped) — `game/graveyard_cast.py`, its
wiring into `GameEngine.can_cast`/`cast_spell`/`legal_actions`, the
untap-step ``once_per_turn`` reset, and the hand-authored catalogue card.
Mirrors `test_top_library.py`'s fixture/coverage shape for the closely
related "cast from the top of your library" permission.
"""

from mtg_analyzer.game import ability_catalogue
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import GraveyardCastPermissionEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.graveyard_cast import (
    active_graveyard_cast_grants,
    graveyard_cast_grant_for,
    may_cast_spell_from_graveyard,
)
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _bear(name="Bear", mv=2, mana="{1}{G}"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2, mana_cost_string=mana, converted_mana_cost=mv)


def _instant(name="Shock", mv=1, mana="{R}"):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                mana_cost_string=mana, converted_mana_cost=mv)


def _land(name="Island"):
    return Card(id=name, name=name, type_line="Basic Land — Island", is_land=True)


def _permanent_with_grant(state, controller="p1", **grant_kwargs):
    source_card = Card(id="Granter", name="Granter", type_line="Enchantment")
    obj = GameObject(source_card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    obj.static_effects.append(GraveyardCastPermissionEffect(source=obj, **grant_kwargs))
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


# ---------------------------------------------------------------------------
# UNIT: game/graveyard_cast.py
# ---------------------------------------------------------------------------


def test_no_grant_means_no_permission():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    assert active_graveyard_cast_grants(p1, state) == []
    assert not may_cast_spell_from_graveyard(p1, state, _bear())


def test_grant_allows_a_permanent_at_or_under_the_mana_value_gate():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, max_mana_value=2)
    assert may_cast_spell_from_graveyard(p1, state, _bear(mv=2))
    assert not may_cast_spell_from_graveyard(p1, state, _bear(name="Big Bear", mv=3))


def test_grant_rejects_a_land_and_a_non_permanent_spell():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, max_mana_value=2)
    assert not may_cast_spell_from_graveyard(p1, state, _land())
    assert not may_cast_spell_from_graveyard(p1, state, _instant(mv=1))


def test_permanent_only_false_allows_an_instant():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, max_mana_value=2, permanent_only=False)
    assert may_cast_spell_from_graveyard(p1, state, _instant(mv=1))


def test_multiple_grants_or_together_on_the_loosest_filter():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    _permanent_with_grant(state, max_mana_value=2)
    _permanent_with_grant(state, max_mana_value=None)
    assert may_cast_spell_from_graveyard(p1, state, _bear(name="Big Bear", mv=6))


def test_once_per_turn_grant_stops_offering_after_its_own_source_is_used():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    granter = _permanent_with_grant(state, max_mana_value=2, once_per_turn=True)
    grant = graveyard_cast_grant_for(p1, state, _bear())
    assert grant is not None
    granter.graveyard_casts_this_turn = 1
    assert graveyard_cast_grant_for(p1, state, _bear()) is None


def test_permission_ends_when_granting_permanent_leaves_battlefield():
    state = GameState(players=[Player(id="p1")])
    p1 = state.players[0]
    granter = _permanent_with_grant(state, max_mana_value=2)
    assert may_cast_spell_from_graveyard(p1, state, _bear())
    state.remove_from_battlefield(granter)
    assert not may_cast_spell_from_graveyard(p1, state, _bear())


# ---------------------------------------------------------------------------
# ENGINE: can_cast / cast_spell / legal_actions / once-per-turn reset
# ---------------------------------------------------------------------------


def test_can_cast_and_cast_a_cheap_permanent_from_the_graveyard_with_permission():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    _permanent_with_grant(eng.state, max_mana_value=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})

    assert eng.can_cast(p1, obj)
    eng.cast_spell(p1, obj, targets=[])
    assert obj.zone == Zone.STACK
    assert obj not in p1.graveyard


def test_cannot_cast_too_expensive_a_permanent_from_the_graveyard():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Big Bear", mv=6, mana="{4}{G}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    _permanent_with_grant(eng.state, max_mana_value=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 6})
    assert not eng.can_cast(p1, obj)


def test_cast_from_graveyard_pays_normal_mana_cost_not_an_alt_cost():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    _permanent_with_grant(eng.state, max_mana_value=2)
    cost = eng.effective_cast_cost(p1, obj)
    assert cost == ManaCost.parse("{1}{G}")


def test_cast_via_permission_marks_the_once_per_turn_grant_used():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    granter = _permanent_with_grant(eng.state, max_mana_value=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})

    eng.cast_spell(p1, obj, targets=[])
    assert granter.graveyard_casts_this_turn == 1

    other = GameObject(_bear("Second Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(other, Zone.GRAVEYARD)
    p1.mana_pool.add_many({"G": 1, "C": 1})
    assert not eng.can_cast(p1, other)


def test_once_per_turn_grant_resets_on_the_next_untap_step():
    eng = _engine()
    p1 = eng.state.players[0]
    granter = _permanent_with_grant(eng.state, max_mana_value=2)
    granter.graveyard_casts_this_turn = 1
    eng.begin_turn()
    eng._step_untap()
    assert granter.graveyard_casts_this_turn == 0


def test_legal_actions_offers_a_graveyard_cast_when_permitted():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    _permanent_with_grant(eng.state, max_mana_value=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    actions = eng.legal_actions(p1)
    assert any(
        a.get("type") == "cast_spell" and a.get("instance_id") == obj.instance_id
        for a in actions
    )


def test_legal_actions_omits_graveyard_cast_without_permission():
    eng = _engine()
    p1 = eng.state.players[0]
    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    actions = eng.legal_actions(p1)
    assert not any(a.get("instance_id") == obj.instance_id for a in actions)


# ---------------------------------------------------------------------------
# HAND-AUTHORED CATALOGUE: Lurrus of the Dream-Den
# ---------------------------------------------------------------------------


def test_lurrus_specs_include_graveyard_cast_permission():
    card = Card(
        id="Lurrus of the Dream-Den", name="Lurrus of the Dream-Den",
        type_line="Legendary Creature — Cat Nightmare", is_creature=True,
        power=2, toughness=3,
        oracle_text=(
            "Once during each of your turns, you may cast a permanent "
            "spell with mana value 2 or less from your graveyard."
        ),
    )
    specs = ability_catalogue.specs_for(card)
    (static,) = [s for s in specs if s.ability_kind == "static"]
    (effect,) = static.effects
    assert effect == EffectSpec("graveyard_cast_permission", {"max_mana_value": 2})


def test_lurrus_end_to_end_casts_a_cheap_permanent_from_the_graveyard():
    eng = _engine()
    p1 = eng.state.players[0]
    lurrus_card = Card(
        id="Lurrus of the Dream-Den", name="Lurrus of the Dream-Den",
        type_line="Legendary Creature — Cat Nightmare", is_creature=True,
        power=2, toughness=3,
    )
    lurrus = GameObject(lurrus_card, owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(lurrus)
    eng.state.add_to_battlefield(lurrus)

    obj = GameObject(_bear("Dead Bear", mv=2, mana="{1}{G}"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(obj, Zone.GRAVEYARD)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})

    assert eng.can_cast(p1, obj)
    eng.cast_spell(p1, obj, targets=[])
    assert obj.zone == Zone.STACK
    assert lurrus.graveyard_casts_this_turn == 1
