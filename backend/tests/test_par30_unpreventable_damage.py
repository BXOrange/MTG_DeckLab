"""PAR-30 — RULE 615.6 "the damage can't be prevented" recognition.

Two shapes:

* a rider on one damage instance ("~ deals N damage to target `<c1>` or
  `<c2>` creature. The damage can't be prevented." — Combust) →
  `DealDamageEffect.unpreventable`, which flips `GameState.damage_
  prevention_disabled` for the span of that one `apply()` only;
* the standalone turn-scoped clause ("Damage can't be prevented this
  turn." — Flaring Pain, Impractical Joke, Unstable Footing) → the
  pre-existing `disable_damage_prevention` effect, which had no oracle-text
  route until now.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext, ReplacementRegistry
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _state():
    p1, p2 = Player(id="p1", name="Alice", life=20), Player(id="p2", name="Bob", life=20)
    return GameState(players=[p1, p2]), p1, p2


def _bf(state, name, controller="p1", colors=None):
    obj = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                          is_creature=True, power=2, toughness=2,
                          color_identity=set(colors or [])),
                     owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# --- parse -----------------------------------------------------------------


def test_damage_two_colour_unpreventable_rider_parses():
    assert match_clause(
        "~ deals 5 damage to target white or blue creature. the damage can't be prevented"
    ) == [EffectSpec("damage", {
        "amount": 5, "target_kind": "creature", "colors": ["W", "U"],
        "unpreventable": True,
    })]


def test_damage_two_colour_without_the_rider_has_no_flag():
    assert match_clause(
        "~ deals 5 damage to target white or blue creature"
    ) == [EffectSpec("damage", {
        "amount": 5, "target_kind": "creature", "colors": ["W", "U"],
    })]


def test_disable_damage_prevention_standalone_parses():
    assert match_clause("damage can't be prevented this turn") == [
        EffectSpec("disable_damage_prevention", {})
    ]


def test_combat_only_form_is_not_claimed_by_this_handler():
    # "combat damage can't be prevented" is a narrower static shape; the
    # turn-scoped all-damage effect must not swallow it.
    assert match_clause("combat damage can't be prevented this turn") is None


# --- end-to-end ----------------------------------------------------------------


def test_combust_modeled():
    c = Card(id="cbt", name="Combust", type_line="Instant", is_instant=True,
             oracle_text=("This spell can't be countered.\n"
                          "Combust deals 5 damage to target white or blue creature. "
                          "The damage can't be prevented."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_flaring_pain_modeled():
    c = Card(id="flp", name="Flaring Pain", type_line="Instant", is_instant=True,
             oracle_text="Damage can't be prevented this turn.\nFlashback {R}")
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute: the unpreventable flag ignores a shield, then restores state ----


def test_unpreventable_damage_ignores_a_standing_shield():
    state, p1, p2 = _state()
    bear = _bf(state, "Shielded Bear", controller="p2", colors=["U"])
    shield = ReplacementRegistry.create("prevent_damage", {"to": "self", "amount": "all"})
    shield.source = bear
    bear.replacement_effects.append(shield)
    engine = RulesEngine(state)
    src = GameObject(Card(id="cbt", name="Combust", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("damage", {
        "amount": 5, "target_kind": "creature", "colors": ["W", "U"],
        "unpreventable": True,
    })], src)[0].apply(GameContext(state, engine), [bear])

    assert bear.damage_marked == 5
    # RULE 615.6 flag must not leak past this one effect.
    assert state.damage_prevention_disabled is False


def test_plain_damage_of_the_same_shape_is_still_prevented():
    state, p1, p2 = _state()
    bear = _bf(state, "Shielded Bear", controller="p2", colors=["U"])
    shield = ReplacementRegistry.create("prevent_damage", {"to": "self", "amount": "all"})
    shield.source = bear
    bear.replacement_effects.append(shield)
    engine = RulesEngine(state)
    src = GameObject(Card(id="brn", name="Burn", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("damage", {
        "amount": 5, "target_kind": "creature", "colors": ["W", "U"],
    })], src)[0].apply(GameContext(state, engine), [bear])

    assert bear.damage_marked == 0
