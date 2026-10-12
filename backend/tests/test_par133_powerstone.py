"""PAR-133: Powerstone tokens ("create a [tapped] Powerstone token") — the curated token (`data/tokens.json` +
`handlers._NAMED_TOKEN_WORDS`) and its RULE 605.3a spend ban ("This mana can't be spent to cast a nonartifact spell"):
legal for artifact spells and for any ability, never for a nonartifact spell.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect, EffectRegistry, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import NONARTIFACT_CAST_BAN_KIND, _parse_restriction, parse_mana_abilities
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.token_database import default_token_database

POWERSTONE_TEXT = "{T}: Add {C}. This mana can't be spent to cast a nonartifact spell."


def _card(name, type_line, oracle="", cost="{1}", **flags):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string=cost,
                converted_mana_cost=1, is_creature="Creature" in type_line, is_sorcery="Sorcery" in type_line,
                is_instant="Instant" in type_line, power=1 if "Creature" in type_line else None,
                toughness=1 if "Creature" in type_line else None, **flags)


def _engine_with_powerstone(hand_cards):
    eng = GameEngine.new_game([("p1", "Alice", list(hand_cards)), ("p2", "Bob", [])],
                              starting_life=20, starting_hand=len(hand_cards))
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    maker = GameObject(_card("Maker", "Creature — Bear"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(maker)
    effect = EffectRegistry.create("create_token", {"count": 1, "token_name": "Powerstone"})
    effect.source = maker
    effect.apply(GameContext(eng.state, eng.rules), [])
    stone = next(o for o in eng.state.battlefield if o.name == "Powerstone")
    stone.tapped = False
    stone.summoning_sick = False
    return eng, p1, stone


def test_the_curated_token_has_its_restricted_mana_ability():
    token = default_token_database().get_token("Powerstone")
    assert token is not None and token.is_artifact
    [ability] = parse_mana_abilities(token)
    assert ability.options == [{"C": 1}]
    assert ability.restriction["kind"] == NONARTIFACT_CAST_BAN_KIND
    assert ability.restriction["allow_ability"]


@pytest.mark.parametrize("text", [
    "Add {C}. This mana can't be spent to cast a nonartifact spell.",
    "Add {C}. This mana can't be spent to cast nonartifact spells.",
])
def test_the_ban_clause_parses(text):
    assert _parse_restriction(text)["kind"] == NONARTIFACT_CAST_BAN_KIND


def test_an_unrelated_clause_is_not_the_ban():
    assert _parse_restriction("Add {C}. This mana can't be spent to cast a legendary spell.") is None


def test_powerstone_mana_cannot_cast_a_nonartifact_spell():
    eng, p1, stone = _engine_with_powerstone([_card("Bolt", "Instant", cost="{1}")])
    eng.tap_for_mana(p1, stone)
    assert p1.mana_pool.total() == 1
    bolt = p1.hand[0]
    assert not eng.can_cast(p1, bolt)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, bolt)


def test_powerstone_mana_can_cast_an_artifact_spell():
    eng, p1, stone = _engine_with_powerstone([_card("Rock", "Artifact", cost="{1}")])
    eng.tap_for_mana(p1, stone)
    rock = p1.hand[0]
    assert eng.can_cast(p1, rock)
    eng.cast_spell(p1, rock)
    assert p1.mana_pool.total() == 0


def test_powerstone_mana_can_pay_for_an_activated_ability():
    eng, p1, stone = _engine_with_powerstone([])
    eng.tap_for_mana(p1, stone)
    bear = GameObject(_card("Bear", "Creature — Bear"), owner_id="p1", controller_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)
    ability = ActivatedAbility(effects=[DrawCardEffect(1, player=p1)],
                               cost=parse_activation_cost("{1}: Draw a card."), source=bear)
    bear.activated_abilities.append(ability)
    assert eng.can_activate(p1, bear, ability)
    eng.activate_ability(p1, bear)
    assert p1.mana_pool.total() == 0


# --- real cards -------------------------------------------------------------


@pytest.mark.parametrize("name, text", [
    ("Powerstone Engineer", "When this creature enters, create a Powerstone token."),
    ("Splitting the Powerstone", "Create 2 tapped Powerstone tokens."),
    ("Repair and Recharge-like", "Create a tapped Powerstone token."),
])
def test_cards_with_the_token_are_modeled(name, text):
    assert parse_oracle(_card(name, "Sorcery", text)).modeled


def test_a_tapped_powerstone_enters_tapped_in_a_live_engine():
    eng, p1, _stone = _engine_with_powerstone([])
    effect = EffectRegistry.create("create_token", {"count": 2, "token_name": "Powerstone", "tapped": True})
    effect.source = next(o for o in eng.state.battlefield if o.name == "Maker")
    effect.apply(GameContext(eng.state, eng.rules), [])
    stones = [o for o in eng.state.battlefield if o.name == "Powerstone"]
    assert len(stones) == 3
    assert sum(1 for o in stones if o.tapped) == 2
