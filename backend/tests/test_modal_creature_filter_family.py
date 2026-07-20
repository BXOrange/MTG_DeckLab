"""Batch 5 (docs/implementation-state/ToDo_Backend.md):
"modal-block cleanup".

Investigation showed the ranked "choose <n> —" backlog wasn't a header-
recognition gap at all (`catalogue/modal.py` already splits/parses every
real modal block correctly) — it's an artifact of the all-or-nothing gate:
`gate.py`'s `_process_modal_block`/`_process_triggered_modal_block` mark
*every* mode body (including ones that parse fine on their own) unclaimed
whenever even one sibling mode fails, so the modal header shows up in the
ranked backlog as a proxy for "some mode in this block still has a real
gap". Sampling the genuinely-failing mode bodies (not just anything that
rode along) surfaced three real, cross-cutting gaps worth generalizing
(they also fire outside modal blocks, on ordinary non-modal cards):

* **Bare "proliferate."** (RULE 701.30) — `ProliferateEffect` already
  existed (`game/effects.py`), it just had no oracle-text handler at all.
  "proliferate twice"/"proliferate X times" stay unclaimed (fail-closed):
  `ProliferateEffect` has no repeat-count parameter yet.
* **Targeted "target player gains/loses N life."** — `LoseLifeEffect`
  already had an opt-in `target_kind` (RULE 115 target); `_lose_life`'s own
  regex accepted the "target player" phrasing but silently discarded it,
  so a targeted life-loss clause was previously bound as an *untargeted*
  "you lose N life" — a real latent bug, not just a missing feature.
  `GainLifeEffect` gained the same opt-in `target_kind` mirroring
  `LoseLifeEffect`.
* **"target creature with power/toughness/keyword quality"**
  (`targeting.TargetSpec.creature_filter`, `DestroyEffect`/`ExileEffect`
  ``creature_filter=``) — "destroy target creature with power 4 or
  greater"/"…with flying" needed a genuinely new RULE 115/601.2c narrowing
  `TargetSpec` didn't have (only `color`/`max_mana_value` existed before).
  Deliberately narrow: only ``power``/``toughness`` comparators and a
  closed keyword list recognized so far — a compound filter ("power 4 or
  greater and flying") or a non-creature noun ("target artifact or
  enchantment with...") stays unclaimed.

Each family is driven through real oracle text via `parse_oracle`/
`parse_effect_body` **and** exercised against a real `RulesEngine`/
`GameContext`, per the project's "parse-only verification has masked real
runtime bugs" lesson.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py,
mtg_analyzer/game/{effects,targeting}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effects import DestroyEffect, ExileEffect, GainLifeEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.game import targeting
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, oracle_text, type_line="Instant"):
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
    )


def _creature(name, power=2, toughness=2, oracle_text=""):
    return Card(
        id=name, name=name, type_line="Creature — Bear",
        is_creature=True, power=power, toughness=toughness, oracle_text=oracle_text,
    )


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# -- proliferate --------------------------------------------------------------


def test_bare_proliferate_is_modeled():
    assert parse_effect_body("proliferate.") == [EffectSpec("proliferate", {})]


def test_proliferate_composes_with_a_sibling_clause():
    effects = parse_effect_body("draw a card. proliferate.")
    assert effects is not None
    assert [e.type for e in effects] == ["draw", "proliferate"]


def test_proliferate_twice_stays_unclaimed():
    # Fail-closed: ProliferateEffect has no repeat-count parameter yet.
    assert parse_effect_body("proliferate twice.") is None
    assert parse_effect_body("proliferate x times.") is None


def test_card_with_bare_proliferate_ability_is_modeled():
    card = _card("Contentious Plan", "Draw a card. Proliferate.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_proliferate_effect_adds_a_counter_of_each_existing_kind():
    engine, state, p1, p2 = _rules()
    creature = _bf(state, _creature("Poison Toad"))
    creature.counters["+1/+1"] = 2
    creature.counters["stun"] = 1
    ctx = GameContext(state, engine)

    from mtg_analyzer.game.effects import EffectRegistry

    EffectRegistry.create("proliferate", {}).apply(ctx)

    assert creature.counters["+1/+1"] == 3
    assert creature.counters["stun"] == 2


# -- targeted gain/lose life ---------------------------------------------------


def test_gain_life_recognizes_you_and_targeted_forms():
    plain = parse_effect_body("you gain 4 life.")[0]
    assert plain.params == {"amount": 4}

    targeted = parse_effect_body("target player gains 4 life.")[0]
    assert targeted.params == {"amount": 4, "target_kind": "player"}


def test_targeted_gain_life_card_is_modeled():
    card = _card("Abuna's Gift", "Target player gains 5 life.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_gain_life_effect_applies_to_the_declared_target_not_the_controller():
    engine, state, p1, p2 = _rules()
    ctx = GameContext(state, engine)

    GainLifeEffect(amount=5, target_kind="player").apply(ctx, targets=[p2])

    assert p2.life == 25
    assert p1.life == 20


def test_lose_life_effect_applies_to_the_declared_target_not_the_controller():
    engine, state, p1, p2 = _rules()
    ctx = GameContext(state, engine)

    from mtg_analyzer.game.effects import LoseLifeEffect

    LoseLifeEffect(amount=3, target_kind="player").apply(ctx, targets=[p2])

    assert p2.life == 17
    assert p1.life == 20


def test_untargeted_gain_life_still_defaults_to_the_source_controller():
    engine, state, p1, p2 = _rules()
    source = _bf(state, _creature("Lifelinker"), controller="p1")
    ctx = GameContext(state, engine)

    GainLifeEffect(amount=3, source=source).apply(ctx)

    assert p1.life == 23
    assert p2.life == 20


# -- creature quality filter (destroy/exile) -----------------------------------


def test_destroy_with_power_filter_is_modeled():
    card = _card("Bar Entry", "Choose one —\n"
                  "• Destroy target creature with power 4 or greater.\n"
                  "• Destroy target creature with power 4 or less.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_destroy_with_flying_filter_is_modeled():
    card = _card("Skyfall Bolt", "Destroy target creature with flying.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_exile_with_toughness_filter_is_modeled():
    card = _card("Sunder the Sturdy", "Exile target creature with toughness 4 or greater.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_compound_filter_stays_unclaimed():
    # Fail-closed: "power 4 or greater and flying" isn't in the recognized
    # single-condition grammar.
    assert parse_effect_body("destroy target creature with power 4 or greater and flying") is None


def test_creature_filter_offers_only_matching_targets():
    engine, state, p1, p2 = _rules()
    flyer = _bf(state, _creature("Sparrow", power=1, toughness=1))
    ground = _bf(state, _creature("Ox", power=4, toughness=4))
    flyer.intrinsic_keywords = {"flying"}

    spec = targeting.TargetSpec(kind="creature", creature_filter={"keyword": "flying"})
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {flyer.instance_id}

    spec2 = targeting.TargetSpec(kind="creature", creature_filter={"min_power": 4})
    legal2 = targeting.legal_targets(state, "p1", spec2)
    assert {t["instance_id"] for t in legal2} == {ground.instance_id}


def test_destroy_effect_with_creature_filter_only_destroys_the_chosen_target():
    engine, state, p1, p2 = _rules()
    big = _bf(state, _creature("Ox", power=4, toughness=4))
    small = _bf(state, _creature("Mouse", power=1, toughness=1))
    ctx = GameContext(state, engine)

    DestroyEffect(target_kind="creature", creature_filter={"min_power": 4}).apply(ctx, targets=[big])

    assert big not in state.battlefield
    assert small in state.battlefield


def test_exile_effect_with_creature_filter_exiles_the_chosen_target():
    engine, state, p1, p2 = _rules()
    flyer = _bf(state, _creature("Sparrow", power=1, toughness=1))
    flyer.intrinsic_keywords = {"flying"}
    ctx = GameContext(state, engine)

    ExileEffect(target_kind="creature", creature_filter={"keyword": "flying"}).apply(ctx, targets=[flyer])

    assert flyer not in state.battlefield
    assert flyer in p1.exile
