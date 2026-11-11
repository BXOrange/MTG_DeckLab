"""ENG-57: CR 20261106 adoption sweep (122.1g battle SBA, Heartwood, Werewolf Pack Leader)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.subtype_types import ARTIFACT_SUBTYPES
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.token_database import TokenDatabase
from tests.support.card_cache import get_cached_card
from tests.support.game import creature

PACK_LEADER_TEXT = (
    "Pack tactics — Whenever this creature attacks, if you attacked with creatures with total power 6 or "
    "greater this combat, draw a card.\n"
    "{3}{G}: Until end of turn, this creature has base power and toughness 5/3, gains trample, and is a Werewolf."
)
#: A stack item's `source` is all `_sba_collect_battle_zero_defense` reads from it.
class _StackItem:
    def __init__(self, source):
        self.source = source


def _engine():
    forest = get_cached_card("Forest")
    engine = GameEngine.new_game([("p1", "A", [forest] * 5), ("p2", "B", [forest] * 5)], starting_hand=0)
    engine.advance_step()
    return engine


def _battle(engine, type_line):
    card = Card(id="b", name="Test Battle", type_line=type_line, defense=3)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    engine.state.add_to_battlefield(obj)
    obj.counters.clear()
    return obj


# --- RULE 122.1g -----------------------------------------------------------------------------------------------

def test_non_siege_battle_at_zero_defense_dies_even_as_a_pending_ability_source():
    engine = _engine()
    battle = _battle(engine, "Battle — Fortress")
    engine.state.stack.append(_StackItem(battle))
    assert [a for a in engine.rules._sba_collect_battle_zero_defense(set())]


def test_siege_at_zero_defense_keeps_the_pending_ability_exception():
    engine = _engine()
    siege = _battle(engine, "Battle — Siege")
    engine.state.stack.append(_StackItem(siege))
    assert engine.rules._sba_collect_battle_zero_defense(set()) == []
    engine.state.stack.clear()
    assert engine.rules._sba_collect_battle_zero_defense(set())


# --- RULE 111.10x / 205.3g -------------------------------------------------------------------------------------

def test_heartwood_is_an_artifact_type_with_its_predefined_token():
    assert "heartwood" in ARTIFACT_SUBTYPES
    token = next(t for t in TokenDatabase().all_tokens() if t.name == "Heartwood")
    assert token.type_line == "Token Artifact — Heartwood"
    assert token.oracle_text == "{T}: Add {R} or {G}."
    assert set(token.color_identity) == {"R", "G"}


# --- Werewolf Pack Leader (CR 20261106 Oracle) -----------------------------------------------------------------

def _pack_leader():
    return Card(id="wpl", name="Werewolf Pack Leader", type_line="Creature — Human Werewolf",
                oracle_text=PACK_LEADER_TEXT, mana_cost_string="{G}{G}", is_creature=True, power=3, toughness=3)


def test_pack_leader_is_modeled_and_the_activation_sets_werewolf_only():
    assert parse_oracle(_pack_leader()).coverage == "MODELED"
    engine = _engine()
    obj = GameObject(_pack_leader(), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    assert obj.has_subtype("Human")
    player = engine.state.player_by_id("p1")
    player.mana_pool.add("G", 4)
    engine.activate_ability(player, obj, ability_index=0)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (5, 3)
    assert "trample" in {k.lower() for k in obj.granted_keywords}
    # RULE 205.3m: "is a Werewolf" replaces the creature types, so Human is lost.
    assert obj.has_subtype("Werewolf") and not obj.has_subtype("Human")


# --- RULE 701.27e / 701.28e ------------------------------------------------------------------------------------

def test_a_permanent_never_transforms_into_an_instant_or_sorcery_face():
    card = Card(id="inv", name="Test Invasion // Test Spell", type_line="Battle — Siege", defense=4,
                back_name="Test Spell", back_type_line="Sorcery", layout="transform")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    assert obj.transform() is False and not obj.transformed and obj.card is card


# --- RULE 712.11b / 701.27j ------------------------------------------------------------------------------------

def _instant_back_dfc():
    return Card(id="d", name="Odd Front", type_line="Creature — Human", is_creature=True, power=1, toughness=1,
                layout="transform", back_name="Odd Back", back_type_line="Instant", back_oracle_text="")


def test_card_with_instant_back_face_stays_in_graveyard_when_returned_transformed():
    engine = _engine()
    p1 = engine.state.players[0]
    obj = GameObject(_instant_back_dfc(), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(obj)
    engine.rules.return_from_graveyard(obj, "battlefield", transformed=True)
    assert obj.zone == Zone.GRAVEYARD and obj in p1.graveyard and obj not in engine.state.battlefield
    engine.rules.return_from_graveyard(obj, "battlefield")  # untransformed entry is unaffected
    assert obj.zone == Zone.BATTLEFIELD and not obj.transformed
