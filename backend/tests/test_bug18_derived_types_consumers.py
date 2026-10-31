"""BUG-18: battlefield type checks use the layer-4 derived types (RULE 613.1d / 205.3).

Real cards through the real layer pass: a creature made an artifact is an artifact for targets, counts,
costs and mass selectors; a permanent that lost a type is not; Blood Moon's Mountains answer "Mountain" /
"Island" checks. Cards in other zones keep their own characteristics."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.condition_query import free_cast_condition_holds
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.engine.activation_mixin import ActivationMixin
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment")


def _real(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state


def _put(state, card, pid="p1") -> GameObject:
    obj = GameObject(card, owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _bear() -> Card:
    return Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _ids(state, kind):
    return {t["instance_id"] for t in legal_targets(state, "p1", TargetSpec(kind=kind))}


def _attach(eng, aura: Card, host: GameObject) -> GameObject:
    obj = _put(eng.state, aura)
    obj.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    return obj


def test_liquimetal_coating_makes_a_creature_a_real_artifact_target_count_cost_and_wipe_victim():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    coating = _put(state, _real("Liquimetal Coating"))
    bear = _put(state, _bear())
    assert bear.instance_id not in _ids(state, "artifact")
    eng.activate_ability(p1, coating, 0, targets=[bear])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert bear.is_artifact and "artifact" in bear.type_words
    assert bear.instance_id in _ids(state, "artifact")  # Shatter-style "destroy target artifact"
    assert continuous.count_selector(state, "p1", "artifacts_you_control") == 2
    assert continuous.matches_permanent_word(bear, "artifact")
    assert ActivationMixin._matches_sacrifice_type(bear, "artifact", state=state)
    build_effects(match_clause("destroy all artifacts"), coating)[0].apply(GameContext(state, eng.rules), None)
    assert bear not in state.battlefield and coating not in state.battlefield


def test_swift_reconfiguration_turns_a_creature_into_an_artifact_and_strips_enchantment():
    eng, state = _engine()
    bear = _put(state, _bear())
    spirit = _put(state, Card(id="sp", name="Spirit", type_line="Enchantment Creature — Spirit",
                              is_creature=True, power=1, toughness=1))
    assert spirit.instance_id in _ids(state, "enchantment")
    _attach(eng, _real("Swift Reconfiguration"), bear)
    _attach(eng, _real("Swift Reconfiguration"), spirit)
    assert bear.is_artifact and not bear.is_creature
    assert bear.instance_id in _ids(state, "artifact")
    assert spirit.is_artifact and not spirit.is_enchantment  # RULE 613.1d: "loses all other card types"
    assert spirit.instance_id in _ids(state, "artifact")
    ench = {i for i in _ids(state, "enchantment")}
    assert spirit.instance_id not in ench
    assert continuous.count_selector(state, "p1", "enchantments_you_control") == 2  # the two Auras only


def test_blood_moon_makes_a_nonbasic_land_a_mountain_and_not_an_island():
    eng, state = _engine()
    fountain = _put(state, _real("Hallowed Fountain"))
    assert fountain.instance_id not in _ids(state, "mountain")
    assert free_cast_condition_holds({"control_land_type": "island"}, fountain, state)
    _put(state, _real("Blood Moon"), "p2")
    eng.recompute_continuous_effects()
    assert fountain.has_subtype("Mountain") and not fountain.has_subtype("Island")
    assert fountain.instance_id in _ids(state, "mountain")
    assert not free_cast_condition_holds({"control_land_type": "island"}, fountain, state)
    assert free_cast_condition_holds({"control_land_type": "mountain"}, fountain, state)
    assert not fountain.has_supertype("basic")


def test_other_zones_keep_card_characteristics():
    eng, state = _engine()
    rock = GameObject(Card(id="rock", name="Rock", type_line="Artifact"), owner_id="p1", zone=Zone.GRAVEYARD)
    state.player_by_id("p1").graveyard.append(rock)
    assert rock.is_artifact and continuous.has_card_type(rock, "artifact")
    assert rock.instance_id in {t["instance_id"] for t in legal_targets(
        state, "p1", TargetSpec(kind="graveyard_artifact"))}
    fountain = GameObject(_real("Hallowed Fountain"), owner_id="p1", zone=Zone.HAND)
    assert fountain.has_subtype("Island") and not fountain.has_subtype("Mountain")
