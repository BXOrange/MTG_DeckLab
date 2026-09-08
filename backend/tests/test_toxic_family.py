"""RULE 702.164 Toxic N — additive poison counters on top of ordinary combat
damage to a player (unlike Infect, RULE 702.90, which *replaces* damage with
-1/-1 counters and poison instead of life loss).

Reference: game/combat.py (has_toxic/toxic_value), game/rules/damage_death_mixin.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)  # populates parametric_keywords["toxic"] off the card's own oracle text
    state.add_to_battlefield(obj)
    return obj


def test_toxic_combat_damage_deals_life_loss_and_poison():
    engine, state, p1, p2 = _rules()
    attacker = _bf(
        state,
        Card(id="Toxic Bear", name="Toxic Bear", type_line="Creature", is_creature=True,
             power=3, toughness=3, keywords=["Toxic"],
             oracle_text="Toxic 2 (Players dealt combat damage by this creature also get 2 poison counters.)"),
        controller="p1",
    )
    engine.deal_damage(p2, 3, source=attacker, combat=True)
    assert p2.life == 17  # ordinary damage still applies — additive, not a substitution
    assert p2.poison == 2


def test_toxic_non_combat_damage_gives_no_poison():
    # RULE 702.164c: toxic's poison only applies to *combat* damage.
    engine, state, p1, p2 = _rules()
    source = _bf(
        state,
        Card(id="Toxic Bolt Source", name="Toxic Bolt Source", type_line="Creature",
             is_creature=True, power=1, toughness=1, keywords=["Toxic"],
             oracle_text="Toxic 2 (Players dealt combat damage by this creature also get 2 poison counters.)"),
        controller="p1",
    )
    engine.deal_damage(p2, 3, source=source, combat=False)
    assert p2.life == 17
    assert p2.poison == 0


def test_non_toxic_combat_damage_gives_no_poison():
    engine, state, p1, p2 = _rules()
    attacker = _bf(
        state,
        Card(id="Plain Bear", name="Plain Bear", type_line="Creature", is_creature=True,
             power=3, toughness=3),
        controller="p1",
    )
    engine.deal_damage(p2, 3, source=attacker, combat=True)
    assert p2.life == 17
    assert p2.poison == 0


def test_toxic_stacks_across_multiple_hits():
    engine, state, p1, p2 = _rules()
    attacker = _bf(
        state,
        Card(id="Toxic Bear", name="Toxic Bear", type_line="Creature", is_creature=True,
             power=1, toughness=1, keywords=["Toxic"],
             oracle_text="Toxic 1 (Players dealt combat damage by this creature also get 1 poison counter.)"),
        controller="p1",
    )
    engine.deal_damage(p2, 1, source=attacker, combat=True)
    engine.deal_damage(p2, 1, source=attacker, combat=True)
    assert p2.poison == 2
