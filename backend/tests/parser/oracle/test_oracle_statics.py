"""Tests for the attached-permanent static-clause family (docs/11 §6).

Covers `parser/oracle/catalogue/static_handlers.py`'s recognition of an
Aura/Equipment/Fortification's own "equipped/enchanted creature gets +N/+N
[and has <keywords>]" / "… has <keywords>" buff — the #2 unclaimed template
in the card cache. The engine side (`affects="attached_permanent"`,
`game/continuous.py`) already fully supports this (see the hand-authored
Armadillo Cloak entry in `game/ability_catalogue.py`); only the parser-
recognition half is new here.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# -- Clause-shape recognition -------------------------------------------------


def test_equipped_creature_anthem():
    specs = static_effect_specs("Equipped creature gets +2/+2.")
    assert specs == [
        EffectSpec("anthem", {"power": 2, "toughness": 2, "affects": "attached_permanent"})
    ]


def test_enchanted_creature_anthem():
    specs = static_effect_specs("Enchanted creature gets +1/+1.")
    assert specs == [
        EffectSpec("anthem", {"power": 1, "toughness": 1, "affects": "attached_permanent"})
    ]


def test_enchanted_permanent_anthem():
    specs = static_effect_specs("Enchanted permanent gets -1/-1.")
    assert specs == [
        EffectSpec("anthem", {"power": -1, "toughness": -1, "affects": "attached_permanent"})
    ]


def test_compound_equipped_creature_anthem_and_single_keyword():
    # Rancor-style Equipment buff — a compound "gets +N/+N and has <kw>" clause.
    specs = static_effect_specs("Equipped creature gets +1/+0 and has trample.")
    assert specs == [
        EffectSpec("anthem", {"power": 1, "toughness": 0, "affects": "attached_permanent"}),
        EffectSpec("grant_keyword", {"keywords": ["trample"], "affects": "attached_permanent"}),
    ]


def test_compound_enchanted_creature_anthem_and_multiple_keywords():
    specs = static_effect_specs("Enchanted creature gets +2/+2 and has flying and vigilance.")
    assert specs == [
        EffectSpec("anthem", {"power": 2, "toughness": 2, "affects": "attached_permanent"}),
        EffectSpec("grant_keyword", {"keywords": ["flying", "vigilance"],
                                      "affects": "attached_permanent"}),
    ]


def test_keyword_only_equipped_creature_grant():
    specs = static_effect_specs("Equipped creature has flying.")
    assert specs == [
        EffectSpec("grant_keyword", {"keywords": ["flying"], "affects": "attached_permanent"})
    ]


def test_keyword_only_enchanted_creature_grant_multiple():
    specs = static_effect_specs("Enchanted creature has hexproof and lifelink.")
    assert specs == [
        EffectSpec("grant_keyword", {"keywords": ["hexproof", "lifelink"],
                                      "affects": "attached_permanent"})
    ]


def test_fortified_land_keyword_grant():
    specs = static_effect_specs("Fortified land has hexproof.")
    assert specs == [
        EffectSpec("grant_keyword", {"keywords": ["hexproof"], "affects": "attached_permanent"})
    ]


def test_enchanted_land_keyword_grant():
    specs = static_effect_specs("Enchanted land has hexproof.")
    assert specs == [
        EffectSpec("grant_keyword", {"keywords": ["hexproof"], "affects": "attached_permanent"})
    ]


# -- Fail-closed cases ---------------------------------------------------------


def test_for_each_tail_stays_unclaimed():
    # A dynamic anthem the current `anthem` EffectSpec can't express (no CDA
    # count) — the fullmatch requirement makes this fall out for free.
    assert static_effect_specs(
        "Equipped creature gets +1/+1 for each artifact you control."
    ) is None


def test_until_end_of_turn_tail_stays_unclaimed():
    # Temporary, not a static ability — must not be claimed as one.
    assert static_effect_specs("Equipped creature gets +1/+1 until end of turn.") is None


def test_unknown_nonflag_keyword_in_has_list_stays_unclaimed():
    # "ward" is a parametric (COST-shape) keyword — the grant can't express
    # its cost, so the whole clause must fail closed (mirrors the existing
    # "have <keywords>" tail's landwalk example).
    assert static_effect_specs("Equipped creature has ward.") is None


def test_compound_anthem_with_unknown_keyword_tail_stays_unclaimed():
    assert static_effect_specs("Equipped creature gets +2/+2 and has ward.") is None


def test_unsupported_subject_stays_unclaimed():
    # "equipped artifact"/"equipped land" aren't real printed shapes — the
    # closed `_ATTACHED_SUBJECTS` list must not guess at them.
    assert static_effect_specs("Equipped artifact gets +1/+1.") is None


# -- End-to-end: a synthetic Equipment card ------------------------------------


def _bear():
    return Card(id="Bear", name="Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def _equipment():
    return Card(
        id="Buffy Boots", name="Buffy Boots", type_line="Artifact — Equipment",
        oracle_text="Equipped creature gets +2/+2 and has trample.\nEquip {1}",
    )


def test_synthetic_equipment_card_is_modeled():
    result = parse_oracle(_equipment())
    assert result.coverage == MODELED
    static_specs = [s for s in result.specs if s.ability_kind == "static"]
    assert len(static_specs) == 1
    effects = static_specs[0].effects
    assert EffectSpec("anthem", {"power": 2, "toughness": 2,
                                  "affects": "attached_permanent"}) in effects
    assert EffectSpec("grant_keyword", {"keywords": ["trample"],
                                         "affects": "attached_permanent"}) in effects


def test_synthetic_equipment_card_buffs_the_equipped_creature_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "Alice", [_bear()]), ("p2", "Bob", [_bear()])],
        starting_life=20, starting_hand=0,
    )
    host = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    equipment = GameObject(_equipment(), owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(equipment)
    equipment.attached_to = host.instance_id

    result = parse_oracle(equipment.card)
    assert result.modeled
    attach_to_object(equipment, result.specs)

    continuous.recompute(eng.state)

    assert (host.power, host.toughness) == (4, 4)
    assert combat.has_trample(host)

    # Unattaching stops the buff (RULE 613 recomputes fresh every pass).
    equipment.attached_to = None
    continuous.recompute(eng.state)
    assert (host.power, host.toughness) == (2, 2)
    assert not combat.has_trample(host)
