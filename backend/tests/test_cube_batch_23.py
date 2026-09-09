"""cEDH staples cube — batch 23: the granted-protection primitive (RULE 702.16).

New core capability: `GameObject.temp_protections` (a set of qualities — a
WUBRG colour letter or "colorless") that `combat.is_protected_from` reads
alongside printed text, cleared at cleanup (RULE 514.2). The `grant_protection`
effect opens an interactive "color of your choice" pick
(`RulesEngine.grant_protection_choice` / `_resume_grant_protection_color`).

Registers Mother of Runes and Giver of Runes (the latter with the "colorless"
option; its "another" restriction is a documented drop).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GrantProtectionEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _creature(name, owner="p1", colors=None, colorless=False) -> GameObject:
    card = Card(id=name, name=name, type_line="Creature — Human",
                is_creature=True, power=2, toughness=2,
                color_identity=set(colors or []))
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    return obj


# ---------------------------------------------------------------------------
# 1. is_protected_from reads temp_protections
# ---------------------------------------------------------------------------


def test_temp_protection_blocks_a_matching_colored_source():
    defender = _creature("Def")
    red_source = _creature("Bolt-y", colors=["R"])
    assert not combat.is_protected_from(defender, red_source)
    defender.temp_protections.add("R")
    assert combat.is_protected_from(defender, red_source)


def test_temp_protection_does_not_block_a_different_color():
    defender = _creature("Def")
    blue_source = _creature("Bluey", colors=["U"])
    defender.temp_protections.add("R")
    assert not combat.is_protected_from(defender, blue_source)


def test_colorless_protection_blocks_only_colorless_sources():
    defender = _creature("Def")
    defender.temp_protections.add("colorless")
    colorless_src = _creature("Eldrazi", colors=[])
    red_src = _creature("Goblin", colors=["R"])
    assert combat.is_protected_from(defender, colorless_src)
    assert not combat.is_protected_from(defender, red_src)


# ---------------------------------------------------------------------------
# 2. The grant_protection effect + interactive choice
# ---------------------------------------------------------------------------


def test_grant_protection_effect_opens_a_color_choice_and_applies_it():
    eng = _engine()
    creature = _creature("Ally", owner="p1")
    eng.state.add_to_battlefield(creature)
    src = _creature("Mom", owner="p1")
    eng.state.add_to_battlefield(src)

    eff = GrantProtectionEffect(target_kind="creature_you_control")
    eff.source = src
    eff.apply(eng.rules.context, [creature])

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "grant_protection_color"
    assert choice["target_id"] == creature.instance_id
    # Colour ids present; no "colorless" for Mother-style (allow_colorless=False).
    ids = {o["id"] for o in choice["options"]}
    assert "R" in ids and "colorless" not in ids

    eng.rules.resolve_choice("R")
    assert eng.state.pending_choice is None
    assert "R" in creature.temp_protections


def test_giver_offers_a_colorless_option():
    eng = _engine()
    creature = _creature("Ally", owner="p1")
    eng.state.add_to_battlefield(creature)
    src = _creature("Giver", owner="p1")
    eng.state.add_to_battlefield(src)

    eff = GrantProtectionEffect(target_kind="creature_you_control", allow_colorless=True)
    eff.source = src
    eff.apply(eng.rules.context, [creature])
    assert "colorless" in {o["id"] for o in eng.state.pending_choice["options"]}


def test_temp_protection_clears_at_cleanup():
    eng = _engine()
    creature = _creature("Ally", owner="p1")
    creature.temp_protections.add("R")
    eng.state.add_to_battlefield(creature)
    eng._step_cleanup()
    assert creature.temp_protections == set()


# ---------------------------------------------------------------------------
# 3. Registration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Mother of Runes", "Giver of Runes"])
def test_registered_with_a_grant_protection_activated_ability(name):
    assert name.strip().lower() in ac._REGISTRY
    specs = ac._REGISTRY[name.strip().lower()]()
    assert any(
        s.ability_kind == "activated" and any(e.type == "grant_protection" for e in s.effects)
        for s in specs
    )


def test_mother_of_runes_binds_the_activated_ability():
    obj = GameObject(
        Card(id="mom", name="Mother of Runes", type_line="Creature — Human Cleric",
             is_creature=True, power=1, toughness=1,
             oracle_text="{T}: Target creature you control gains protection from "
                         "the color of your choice until end of turn."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bind_from_catalogue(obj)
    assert obj.activated_abilities, "Mother of Runes should bind a {T} activated ability"
