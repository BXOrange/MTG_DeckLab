"""Batch 5 (docs/implementation-state/BACKLOG.md):
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
  existed (`game/effects/core.py`), it just had no oracle-text handler at all.
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

from mtg_analyzer.game.effects.core import BlinkEffect, DestroyEffect, ExileEffect, GainLifeEffect, GameContext
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


def test_proliferate_twice_is_recognized():
    # Contagion Engine/Agent Frank Horrigan/Ezuri, Stalker of Spheres-shaped.
    (spec,) = parse_effect_body("proliferate twice.")
    assert spec == EffectSpec("proliferate", {"times": 2})


def test_proliferate_n_times_is_recognized():
    # War of the Spark Saga chapter-shaped ("proliferate three times.",
    # already digit-folded by normalize.py before reaching this grammar).
    (spec,) = parse_effect_body("proliferate 3 times.")
    assert spec == EffectSpec("proliferate", {"times": 3})


def test_proliferate_x_times_stays_unclaimed():
    # A different shape (Expansion Algorithm's spell-announced-X, Tromell's
    # dynamic count-selector) — `ProliferateEffect` has no "x"/count-selector
    # support yet, so this stays fail-closed rather than guessing.
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

    from mtg_analyzer.game.effects.core import EffectRegistry

    EffectRegistry.create("proliferate", {}).apply(ctx)

    assert creature.counters["+1/+1"] == 3
    assert creature.counters["stun"] == 2


def test_proliferate_twice_effect_adds_two_counters_of_each_existing_kind():
    engine, state, p1, p2 = _rules()
    creature = _bf(state, _creature("Poison Toad"))
    creature.counters["+1/+1"] = 2
    creature.counters["stun"] = 1
    ctx = GameContext(state, engine)

    from mtg_analyzer.game.effects.core import EffectRegistry

    EffectRegistry.create("proliferate", {"times": 2}).apply(ctx)

    assert creature.counters["+1/+1"] == 4
    assert creature.counters["stun"] == 3


def test_contagion_engine_shaped_proliferate_twice_end_to_end():
    card = _card("Twin Charge Vessel", "{4}, {T}: Proliferate twice.", type_line="Artifact")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


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

    from mtg_analyzer.game.effects.core import LoseLifeEffect

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


def test_compound_filter_power_and_flying_is_recognized():
    (spec,) = parse_effect_body("destroy target creature with power 4 or greater and flying")
    assert spec.type == "destroy"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"min_power": 4, "keyword": "flying"},
    }


def test_compound_filter_toughness_and_keyword_is_recognized_for_exile():
    (spec,) = parse_effect_body(
        "exile target creature with toughness 2 or less and with vigilance"
    )
    assert spec.type == "exile"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"max_toughness": 2, "keyword": "vigilance"},
    }


def test_compound_filter_end_to_end_is_modeled():
    card = _card(
        "Skybreak Judgment",
        "Destroy target creature with power 4 or greater and flying.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


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


def test_compound_creature_filter_offers_only_targets_matching_both_clauses():
    engine, state, p1, p2 = _rules()
    big_flyer = _bf(state, _creature("Griffin", power=4, toughness=4))
    big_flyer.intrinsic_keywords = {"flying"}
    big_ground = _bf(state, _creature("Ox", power=4, toughness=4))
    small_flyer = _bf(state, _creature("Sparrow", power=1, toughness=1))
    small_flyer.intrinsic_keywords = {"flying"}

    spec = targeting.TargetSpec(
        kind="creature", creature_filter={"min_power": 4, "keyword": "flying"}
    )
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {big_flyer.instance_id}


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


# -- "destroy target non<color/artifact> creature" (Doom Blade-shaped) -------


def test_destroy_target_nonblack_creature_is_recognized():
    (spec,) = parse_effect_body("destroy target nonblack creature")
    assert spec.type == "destroy"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"without_color": "B"},
    }


def test_destroy_target_nonartifact_creature_is_recognized():
    (spec,) = parse_effect_body("destroy target nonartifact creature")
    assert spec.type == "destroy"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"without_card_type": "artifact"},
    }


def test_destroy_target_nonartifact_nonblack_creature_composes_filters():
    (spec,) = parse_effect_body("destroy target nonartifact, nonblack creature")
    assert spec.type == "destroy"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"without_card_type": "artifact", "without_color": "B"},
    }


def test_destroy_target_nonblack_creature_cant_be_regenerated_tail_is_recognized():
    (spec,) = parse_effect_body(
        "destroy target nonblack creature. it can't be regenerated"
    )
    assert spec.type == "destroy"
    assert spec.params == {
        "target_kind": "creature",
        "creature_filter": {"without_color": "B"},
        "can_be_regenerated": False,
    }


def test_doom_blade_is_fully_modeled():
    card = _card("Doom Blade", "Destroy target nonblack creature.")
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_without_color_filter_excludes_matching_creatures():
    engine, state, p1, p2 = _rules()
    black_card = Card(id="Zombie", name="Zombie", type_line="Creature — Zombie",
                       is_creature=True, power=2, toughness=2, color_identity={"B"})
    black = _bf(state, black_card)
    green_card = Card(id="Elf", name="Elf", type_line="Creature — Elf",
                       is_creature=True, power=1, toughness=1, color_identity={"G"})
    green = _bf(state, green_card)

    spec = targeting.TargetSpec(kind="creature", creature_filter={"without_color": "B"})
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {green.instance_id}


def test_without_card_type_filter_excludes_matching_creatures():
    engine, state, p1, p2 = _rules()
    artifact_creature = Card(id="Golem", name="Golem", type_line="Artifact Creature — Golem",
                              is_creature=True, power=2, toughness=2)
    art = _bf(state, artifact_creature)
    plain = _bf(state, _creature("Bear", power=2, toughness=2))

    spec = targeting.TargetSpec(kind="creature", creature_filter={"without_card_type": "artifact"})
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {plain.instance_id}


def test_compound_negative_filter_excludes_artifact_and_black_creatures():
    engine, state, p1, p2 = _rules()
    artifact = _bf(state, Card(id="Golem", name="Golem", type_line="Artifact Creature — Golem",
                               is_creature=True, power=2, toughness=2))
    black = _bf(state, Card(id="Zombie", name="Zombie", type_line="Creature — Zombie",
                            is_creature=True, power=2, toughness=2, color_identity={"B"}))
    plain = _bf(state, _creature("Bear", power=2, toughness=2))

    spec = targeting.TargetSpec(
        kind="creature",
        creature_filter={"without_card_type": "artifact", "without_color": "B"},
    )
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {plain.instance_id}
    assert artifact.instance_id not in {t["instance_id"] for t in legal}
    assert black.instance_id not in {t["instance_id"] for t in legal}


def test_doom_blade_end_to_end_destroys_the_chosen_creature():
    engine, state, p1, p2 = _rules()
    black_card = Card(id="Zombie", name="Zombie", type_line="Creature — Zombie",
                       is_creature=True, power=2, toughness=2, color_identity={"B"})
    black = _bf(state, black_card, controller="p2")
    ctx = GameContext(state, engine)

    # A chosen legal target is destroyed regardless of the filter that
    # offered it — `legal_targets` (tested above) is what keeps a black
    # creature from ever being offered to Doom Blade in the first place.
    DestroyEffect(target_kind="creature", creature_filter={"without_color": "B"}).apply(
        ctx, targets=[black]
    )
    assert black not in state.battlefield


# -- "target non-<subtype> creature" (Restoration Angel-shaped) --------------


def test_without_subtype_filter_excludes_matching_creatures():
    engine, state, p1, p2 = _rules()
    angel = Card(id="Angel Buddy", name="Angel Buddy", type_line="Creature — Angel",
                 is_creature=True, power=3, toughness=3)
    angel_obj = _bf(state, angel)
    other = Card(id="Human Buddy", name="Human Buddy", type_line="Creature — Human",
                 is_creature=True, power=1, toughness=1)
    other_obj = _bf(state, other)

    spec = targeting.TargetSpec(
        kind="creature_you_control", creature_filter={"without_subtype": "Angel"}
    )
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {other_obj.instance_id}


def test_restoration_angel_is_fully_modeled():
    card = _card(
        "Restoration Angel",
        "Flash\nFlying\nWhen this creature enters, you may exile target "
        "non-Angel creature you control, then return that card to the "
        "battlefield under your control.",
        type_line="Creature",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_restoration_angel_blinks_a_nonangel_creature_under_the_casters_control():
    engine, state, p1, p2 = _rules()
    angel = Card(id="Restoration Angel", name="Restoration Angel",
                 type_line="Creature — Angel", is_creature=True, power=3, toughness=4)
    angel_obj = _bf(state, angel, controller="p1")
    stolen = Card(id="Stolen Bear", name="Stolen Bear", type_line="Creature — Bear",
                  is_creature=True, power=2, toughness=2)
    bear = _bf(state, stolen, controller="p1")
    bear.owner_id = "p2"  # p1 controls an opponent's stolen creature
    ctx = GameContext(state, engine)

    BlinkEffect(
        source=angel_obj, target_kind="creature_you_control",
        creature_filter={"without_subtype": "Angel"}, under_your_control=True,
    ).apply(ctx, targets=[bear])

    # The blinked object is a fresh instance now on the battlefield, still
    # under p1 (the caster) even though it's owned by p2.
    refreshed = [o for o in state.battlefield if o.name == "Stolen Bear"][0]
    assert refreshed.controller_id == "p1"
    assert refreshed.owner_id == "p2"
