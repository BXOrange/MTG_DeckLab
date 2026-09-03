"""Tests for a parser bug fix: Mox Amber, Exotic Orchard, Fellwar Stone (and
kin) all print a *qualified* "add one mana of any color" clause — the menu
is board-dependent, not a fixed five colors — but the bare substring check
in `_parse_clause`'s `_ANY_COLOR_PHRASES` matched "any color" regardless of
the qualifying clause, so all three silently behaved like an unconditional
5-color mana rock (never checking whether the qualifying permanent/land was
even on the battlefield).

Two new `ManaAbility.color_selector` kinds close this, both genuine menus
(the payer still picks one colour) built fresh off the live board every
call, same shape as the existing `"imprinted_card_colors"`:

* ``"colors_of_legendary_creatures_planeswalkers_you_control"`` /
  ``"colors_of_legendary_permanents_you_control"`` (Mox Amber / Plaza of
  Heroes's own second mana ability) — `_LEGENDARY_AMONG_RE`.
* ``"colors_lands_you_control_could_produce"`` /
  ``"colors_lands_opponents_control_could_produce"`` (Exotic Orchard/
  Fellwar Stone/Quirion Explorer/Sylvok Explorer — opponent-scoped;
  Harvester Druid — self-scoped) — `_LAND_COULD_PRODUCE_RE`, resolved via
  `_colors_a_land_could_produce`, which reads each qualifying land's own
  live mana abilities rather than its printed colour identity, and guards
  against two mutually-reflecting lands recursing into each other forever
  (`_LAND_REFLECTION_SELECTORS`).

Reference: mtg_analyzer/game/mana_abilities.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import mana_abilities
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def filler(name="Filler"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string="{0}",
        converted_mana_cost=0, is_instant=True,
    )


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler("F1")] * 5), ("p2", "Bob", [filler("F2")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def basic(name):
    color = {"Island": "U", "Mountain": "R", "Forest": "G", "Plains": "W", "Swamp": "B"}[name]
    return Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True), color


# ---------------------------------------------------------------------------
# Mox Amber — legendary creatures/planeswalkers you control
# ---------------------------------------------------------------------------


def test_mox_amber_produces_nothing_with_no_legendary_permanent():
    eng, p1, p2 = two_player_engine()
    mox = battlefield(eng, _card("Mox Amber"))
    [ability] = mana_abilities.mana_abilities_for(mox, state=eng.state)
    assert ability.color_selector == "colors_of_legendary_creatures_planeswalkers_you_control"
    assert mana_abilities.resolve_options(ability, mox, eng.state) == []
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, mox)


def test_mox_amber_offers_a_menu_of_its_legendary_creatures_colors():
    eng, p1, p2 = two_player_engine()
    mox = battlefield(eng, _card("Mox Amber"))
    battlefield(eng, _card("Niv-Mizzet Reborn"))  # WUBRG legendary creature
    [ability] = mana_abilities.mana_abilities_for(mox, state=eng.state)
    options = mana_abilities.resolve_options(ability, mox, eng.state)
    assert {frozenset(o.items()) for o in options} == {
        frozenset({(c, 1)}) for c in "WUBRG"
    }
    produced = eng.tap_for_mana(p1, mox, option_index=0)
    assert list(produced.keys())[0] in "WUBRG"


def test_mox_amber_ignores_a_legendary_permanent_that_isnt_a_creature_or_planeswalker():
    eng, p1, p2 = two_player_engine()
    mox = battlefield(eng, _card("Mox Amber"))
    # A legendary artifact is a legendary permanent, but not a creature or
    # planeswalker — Mox Amber's own scope excludes it (unlike Plaza of
    # Heroes' broader "legendary permanents" wording, tested below).
    battlefield(eng, _card("Bolas's Citadel"))
    [ability] = mana_abilities.mana_abilities_for(mox, state=eng.state)
    assert mana_abilities.resolve_options(ability, mox, eng.state) == []


def test_mox_amber_ignores_an_opponents_legendary_creature():
    eng, p1, p2 = two_player_engine()
    mox = battlefield(eng, _card("Mox Amber"))
    battlefield(eng, _card("Niv-Mizzet Reborn"), controller="p2")
    [ability] = mana_abilities.mana_abilities_for(mox, state=eng.state)
    assert mana_abilities.resolve_options(ability, mox, eng.state) == []


def test_plaza_of_heroes_broader_scope_counts_a_legendary_artifact():
    eng, p1, p2 = two_player_engine()
    plaza = battlefield(eng, _card("Plaza of Heroes"))
    # Bolas's Citadel: legendary, black, but neither a creature nor a
    # planeswalker — Plaza of Heroes' "legendary permanents" wording counts
    # it where Mox Amber's narrower one wouldn't (see the test above).
    battlefield(eng, _card("Bolas's Citadel"))
    abilities = mana_abilities.mana_abilities_for(plaza, state=eng.state)
    reflecting = [a for a in abilities if a.color_selector == "colors_of_legendary_permanents_you_control"]
    assert len(reflecting) == 1
    options = mana_abilities.resolve_options(reflecting[0], plaza, eng.state)
    assert options == [{"B": 1}]


# ---------------------------------------------------------------------------
# Exotic Orchard / Fellwar Stone / Harvester Druid — a land could produce
# ---------------------------------------------------------------------------


def test_exotic_orchard_produces_nothing_with_no_opponent_lands():
    eng, p1, p2 = two_player_engine()
    orchard = battlefield(eng, _card("Exotic Orchard"))
    [ability] = mana_abilities.mana_abilities_for(orchard, state=eng.state)
    assert ability.color_selector == "colors_lands_opponents_control_could_produce"
    assert mana_abilities.resolve_options(ability, orchard, eng.state) == []


def test_exotic_orchard_reads_only_opponent_lands():
    eng, p1, p2 = two_player_engine()
    orchard = battlefield(eng, _card("Exotic Orchard"))
    island, _ = basic("Island")
    mountain, _ = basic("Mountain")
    forest, _ = basic("Forest")
    battlefield(eng, island, controller="p2")
    battlefield(eng, mountain, controller="p2")
    battlefield(eng, forest, controller="p1")  # this player's own — must not count
    [ability] = mana_abilities.mana_abilities_for(orchard, state=eng.state)
    options = mana_abilities.resolve_options(ability, orchard, eng.state)
    assert {frozenset(o.items()) for o in options} == {
        frozenset({("U", 1)}), frozenset({("R", 1)}),
    }
    produced = eng.tap_for_mana(p1, orchard, option_index=0)
    assert produced in ({"U": 1}, {"R": 1})


def test_fellwar_stone_same_shape_as_exotic_orchard():
    eng, p1, p2 = two_player_engine()
    fellwar = battlefield(eng, _card("Fellwar Stone"))
    island, _ = basic("Island")
    battlefield(eng, island, controller="p2")
    [ability] = mana_abilities.mana_abilities_for(fellwar, state=eng.state)
    assert ability.color_selector == "colors_lands_opponents_control_could_produce"
    assert mana_abilities.resolve_options(ability, fellwar, eng.state) == [{"U": 1}]


def test_harvester_druid_is_self_scoped_not_opponent_scoped():
    eng, p1, p2 = two_player_engine()
    druid = battlefield(eng, _card("Harvester Druid"))
    island, _ = basic("Island")
    battlefield(eng, island, controller="p1")  # own land
    opp_forest, _ = basic("Forest")
    battlefield(eng, opp_forest, controller="p2")  # must not count
    abilities = mana_abilities.mana_abilities_for(druid, state=eng.state)
    reflecting = [a for a in abilities if a.color_selector == "colors_lands_you_control_could_produce"]
    assert len(reflecting) == 1
    assert mana_abilities.resolve_options(reflecting[0], druid, eng.state) == [{"U": 1}]


def test_mutually_reflecting_lands_do_not_recurse_forever():
    eng, p1, p2 = two_player_engine()
    mine = battlefield(eng, _card("Exotic Orchard"), controller="p1")
    battlefield(eng, _card("Exotic Orchard"), controller="p2")
    [ability] = mana_abilities.mana_abilities_for(mine, state=eng.state)
    # Neither land can answer "what could the other produce" by asking the
    # same question back — the recursion guard treats that as "nothing"
    # rather than looping; the important assertion is that this returns at
    # all.
    assert mana_abilities.resolve_options(ability, mine, eng.state) == []


def test_with_no_state_produces_nothing_rather_than_guessing():
    mox_card = _card("Mox Amber")
    obj = GameObject(mox_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ability = mana_abilities.parse_mana_abilities(mox_card)[0]
    assert mana_abilities.resolve_options(ability, obj, state=None) == []


# ---------------------------------------------------------------------------
# Arcane Signet / Command Tower / Commander's Sphere / Path of Ancestry —
# "any color in your commander's color identity" (RULE 903.4), the same
# bug/fix shape: the bare "any color" substring made these unconditional
# 5-colour rocks, ignoring the identity filter entirely.
# ---------------------------------------------------------------------------


def _commander_on_battlefield(eng, identity, controller="p1"):
    card = Card(
        id=f"cmdr-{''.join(sorted(identity)) or 'C'}",
        name="Test Commander",
        type_line="Legendary Creature — Avatar",
        color_identity=set(identity),
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD, is_commander=True)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_arcane_signet_parses_to_a_commander_identity_selector_not_five_colours():
    ability = mana_abilities.parse_mana_abilities(_card("Arcane Signet"))[0]
    assert ability.color_selector == "colors_in_commanders_color_identity"
    assert ability.options == []  # no fixed menu — built off the board


def test_arcane_signet_offers_only_the_commanders_identity_colours():
    eng, p1, p2 = two_player_engine()
    _commander_on_battlefield(eng, {"W", "U", "B"})
    signet = battlefield(eng, _card("Arcane Signet"))
    [ability] = mana_abilities.mana_abilities_for(signet, state=eng.state)
    assert mana_abilities.resolve_options(ability, signet, eng.state) == [
        {"B": 1}, {"U": 1}, {"W": 1},
    ]


def test_arcane_signet_mono_colour_commander_offers_exactly_one_colour():
    eng, p1, p2 = two_player_engine()
    _commander_on_battlefield(eng, {"B"})
    signet = battlefield(eng, _card("Arcane Signet"))
    [ability] = mana_abilities.mana_abilities_for(signet, state=eng.state)
    assert mana_abilities.resolve_options(ability, signet, eng.state) == [{"B": 1}]


def test_arcane_signet_ignores_an_opponents_commander():
    eng, p1, p2 = two_player_engine()
    _commander_on_battlefield(eng, {"R", "G"}, controller="p2")
    signet = battlefield(eng, _card("Arcane Signet"), controller="p1")
    [ability] = mana_abilities.mana_abilities_for(signet, state=eng.state)
    assert mana_abilities.resolve_options(ability, signet, eng.state) == []


def test_arcane_signet_counts_a_commander_still_in_the_command_zone():
    eng, p1, p2 = two_player_engine()
    card = Card(
        id="cmdr-UG", name="Test Commander",
        type_line="Legendary Creature — Avatar", color_identity={"U", "G"},
    )
    cmdr = GameObject(card, owner_id="p1", zone=Zone.COMMAND, is_commander=True)
    p1.zones[Zone.COMMAND].append(cmdr)
    signet = battlefield(eng, _card("Arcane Signet"))
    [ability] = mana_abilities.mana_abilities_for(signet, state=eng.state)
    assert mana_abilities.resolve_options(ability, signet, eng.state) == [{"G": 1}, {"U": 1}]


def test_arcane_signet_produces_nothing_with_no_commander_at_all():
    eng, p1, p2 = two_player_engine()
    signet = battlefield(eng, _card("Arcane Signet"))
    [ability] = mana_abilities.mana_abilities_for(signet, state=eng.state)
    assert mana_abilities.resolve_options(ability, signet, eng.state) == []


def test_command_tower_and_path_of_ancestry_share_the_shape():
    for name in ("Command Tower", "Commander's Sphere", "Path of Ancestry"):
        abilities = mana_abilities.parse_mana_abilities(_card(name))
        identity_abilities = [
            a for a in abilities
            if a.color_selector == "colors_in_commanders_color_identity"
        ]
        assert len(identity_abilities) == 1, name


def test_arcane_signet_tap_for_mana_produces_an_identity_colour():
    eng, p1, p2 = two_player_engine()
    _commander_on_battlefield(eng, {"B"})
    signet = battlefield(eng, _card("Arcane Signet"))
    produced = eng.tap_for_mana(p1, signet, option_index=0)
    assert produced == {"B": 1}


def test_arcane_signet_legal_actions_offer_only_identity_colours():
    eng, p1, p2 = two_player_engine()
    _commander_on_battlefield(eng, {"W", "B"})
    signet = battlefield(eng, _card("Arcane Signet"))
    taps = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "tap_for_mana" and a.get("instance_id") == signet.instance_id
    ]
    assert len(taps) == 1
    produced_colours = {c for opt in taps[0]["options"] for c in opt["mana"]}
    assert produced_colours == {"W", "B"}
