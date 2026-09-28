"""PAR-30 — Katara, Seeking Revenge's two remaining clauses (PARSER_VERSION 158).

- "~ gets +P/+T for each `<subtype>` card in your graveyard" → a self
  `anthem` scaled by `continuous.count_selector`'s new
  `<subtype>_cards_in_your_graveyard` prefix (a live type-line scan). Also
  reached Knight of the Reliquary ("land card"), Liliana's Elite /
  Fiend Artisan ("creature card"), Salvage Slasher ("artifact card"), …
- "`<effect>` unless `<its>` additional cost was paid" → the negative,
  suffix form of v155's `additional_cost_paid` `EffectSpec.condition`,
  checked after the connector split so it binds only to its own clause.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _gy(state, name, type_line, owner="p1", **flags):
    obj = GameObject(Card(id=name[:8], name=name, type_line=type_line, **flags),
                     owner_id=owner, zone=Zone.GRAVEYARD)
    state.player_by_id(owner).graveyard.append(obj)
    return obj


# --- parse ---------------------------------------------------------------------


def test_for_each_subtype_anthem_parses():
    assert static_effect_specs(
        "~ gets +1/+1 for each lesson card in your graveyard"
    ) == [
        EffectSpec("anthem", {
            "affects": "self", "power": 1, "toughness": 1,
            "power_count": "lesson_cards_in_your_graveyard",
            "toughness_count": "lesson_cards_in_your_graveyard",
        })
    ]
    # asymmetric P/T (Salvage Slasher) and a main-type word (land)
    assert static_effect_specs(
        "~ gets +1/+0 for each artifact card in your graveyard"
    )[0].params["power_count"] == "artifact_cards_in_your_graveyard"
    assert static_effect_specs(
        "~ gets +1/+1 for each land card in your graveyard"
    )[0].params["toughness_count"] == "land_cards_in_your_graveyard"
    # PAR-120: a positive "and" type list counts either card type.
    assert static_effect_specs(
        "~ gets +1/+0 for each instant and sorcery card in your graveyard"
    )[0].params["power_count"] == {
        "zone": "graveyard", "of": "you",
        "filter": {"card_type_any": ["instant", "sorcery"]},
    }


def test_unless_additional_cost_paid_suffix_binds_to_its_own_clause():
    specs = parse_effect_body(
        "draw a card, then discard a card unless her additional cost was paid"
    )
    assert specs == [
        EffectSpec("draw", {"count": 1}),  # unconditional
        EffectSpec("discard", {"count": 1}, condition={"kind": "not", "condition": {"kind": "flag", "flag": "additional_cost_paid"}}),
    ]
    # bare single clause
    assert parse_effect_body(
        "discard a card unless its additional cost was paid"
    ) == [EffectSpec("discard", {"count": 1}, condition={"kind": "not", "condition": {"kind": "flag", "flag": "additional_cost_paid"}})]


def test_katara_seeking_revenge_modeled():
    c = Card(
        id="ksr", name="Katara, Seeking Revenge",
        type_line="Legendary Creature — Human Warrior", is_creature=True,
        power=2, toughness=2, mana_cost_string="{1}{U}{B}",
        oracle_text=(
            "As an additional cost to cast this spell, you may waterbend {2}.\n"
            "When Katara, Seeking Revenge enters, draw a card, then discard a "
            "card unless her additional cost was paid.\n"
            "Katara, Seeking Revenge gets +1/+1 for each Lesson card in your "
            "graveyard."),
    )
    res = parse_oracle(c)
    assert res.modeled, res.unclaimed


# --- execute ------------------------------------------------------------------


def test_count_selector_scans_graveyard_type_lines():
    eng, state = _engine()
    _gy(state, "Forest", "Basic Land — Forest", is_land=True)
    _gy(state, "Island", "Basic Land — Island", is_land=True)
    _gy(state, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    _gy(state, "Lesson One", "Sorcery — Lesson", is_sorcery=True)

    # count_selector(state, controller_id, selector)
    assert continuous.count_selector(state, "p1", "land_cards_in_your_graveyard") == 2
    assert continuous.count_selector(state, "p1", "lesson_cards_in_your_graveyard") == 1
    # opponent's graveyard doesn't count
    _gy(state, "Plains", "Basic Land — Plains", owner="p2", is_land=True)
    assert continuous.count_selector(state, "p1", "land_cards_in_your_graveyard") == 2
    # unknown word → 0, never a crash
    assert continuous.count_selector(state, "p1", "wombat_cards_in_your_graveyard") == 0


def test_for_each_subtype_anthem_scales_live():
    eng, state = _engine()
    c = Card(id="ksr", name="Katara", type_line="Creature — Warrior", is_creature=True,
             power=2, toughness=2,
             oracle_text="Katara gets +1/+1 for each Lesson card in your graveyard.")
    obj = GameObject(c, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (2, 2)

    _gy(state, "L1", "Instant — Lesson", is_instant=True)
    _gy(state, "L2", "Sorcery — Lesson", is_sorcery=True)
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (4, 4)

    state.player_by_id("p1").graveyard.clear()
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (2, 2)
