"""MEC-126 — "<effect> target X and each other X that shares a color with it" (Radiance).

One target is announced (RULE 601.2c); on resolution the body also applies to every other X sharing a colour
with it (RULE 105.2, 608.2). Pinned: the `shares_color_with_reference` predicate, the `target_group`
composite, the parser rows, and every Radiance card run through the real cast/resolve path, each with
negative controls (a non-sharing creature untouched, a colourless target alone, an illegal target on
resolution forms no group, RULE 608.2b).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

RADIANCE = {
    "Cleansing Beam": ("Instant", "{2}{R}", "Radiance — ~ deals 2 damage to target creature and each other creature that shares a color with it."),
    "Surge of Zeal": ("Instant", "{R}", "Radiance — Target creature and each other creature that shares a color with it gain haste until end of turn."),
    "Wojek Siren": ("Instant", "{W}", "Radiance — Target creature and each other creature that shares a color with it get +1/+1 until end of turn."),
    "Rally the Righteous": ("Instant", "{2}{W}", "Radiance — Untap target creature and each other creature that shares a color with it. Those creatures get +2/+0 until end of turn."),
    "Incite Hysteria": ("Sorcery", "{1}{R}", 'Radiance — Until end of turn, target creature and each other creature that shares a color with it gain "This creature can\'t block."'),
    "Leave No Trace": ("Instant", "{1}{W}", "Radiance — Destroy target enchantment and each other enchantment that shares a color with it."),
    "Brightflame": ("Sorcery", "{X}{R}{W}", "Radiance — ~ deals X damage to target creature and each other creature that shares a color with it. You gain life equal to the damage dealt this way."),
}


def _card(name: str) -> Card:
    type_line, cost, text = RADIANCE[name]
    return Card(
        id=name, name=name, type_line=type_line, is_instant=type_line == "Instant",
        is_sorcery=type_line == "Sorcery", mana_cost_string=cost,
        color_identity={c for c in cost if c in "WUBRG"}, oracle_text=text.replace("~", name),
        keywords=["Radiance"],  # Scryfall lists the ability word; the normalizer strips it by this signal
    )


def _engine() -> GameEngine:
    filler = [Card(id=f"f{i}", name=f"Filler {i}", type_line="Land", is_land=True) for i in range(20)]
    eng = GameEngine.new_game([("p1", "A", list(filler)), ("p2", "B", list(filler))], starting_life=20, starting_hand=0)
    eng.start()
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    return eng


def _perm(eng, name, colors, controller="p1", enchantment=False, toughness=4):
    card = Card(
        id=name, name=name,
        type_line="Enchantment" if enchantment else "Creature — Bear",
        is_creature=not enchantment,
        power=None if enchantment else 2, toughness=None if enchantment else toughness,
        color_identity=set(colors),
    )
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = True
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _cast(eng, name, target, x=0, before_resolve=None):
    obj = GameObject(_card(name), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = eng.state.player_by_id("p1")
    player.hand.append(obj)
    for colour in "WUBRGC":
        player.mana_pool.add(colour, 30)
    eng.cast_spell(player, obj, targets=[target], x=x)
    if before_resolve:
        before_resolve()
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    return obj


@pytest.fixture
def board():
    eng = _engine()
    red = _perm(eng, "Red", "R")
    redgreen = _perm(eng, "RedGreen", "RG", controller="p2")
    green = _perm(eng, "Green", "G", controller="p2")
    colorless = _perm(eng, "Golem", "", controller="p2")
    eng.recompute_continuous_effects()
    return eng, red, redgreen, green, colorless


# --- the predicate ----------------------------------------------------------


def test_shares_color_predicate(board):
    _, red, redgreen, green, colorless = board
    key = {"shares_color_with_reference": True}
    assert combat.matches_object_filter(redgreen, key, reference=red)
    assert combat.matches_object_filter(redgreen, key, reference=green)
    assert not combat.matches_object_filter(green, key, reference=red)
    assert not combat.matches_object_filter(colorless, key, reference=colorless)  # colourless shares nothing
    assert not combat.matches_object_filter(red, key)  # no reference: closed


# --- parse ------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(set(RADIANCE)))
def test_radiance_cards_are_modeled(name):
    assert parse_oracle(_card(name)).coverage == MODELED, parse_oracle(_card(name)).unclaimed


def test_clause_shape():
    specs = parse_effect_body("~ deals 2 damage to target creature and each other creature that shares a color with it.")
    assert [s.type for s in specs] == ["target_group"]
    assert specs[0].params["shares"] == "color"
    assert specs[0].params["filter"] == {"card_type": "creature"}
    assert specs[0].params["effects"] == [{"type": "damage", "params": {"amount": 2, "target_kind": "creature"}}]


def test_almost_matching_clauses_are_not_claimed():
    # a different type word on each side, and a non-colour shared quality, are not this family
    assert parse_effect_body("~ deals 2 damage to target creature and each other artifact that shares a color with it.") is None
    assert parse_effect_body("~ deals 2 damage to target creature and each other creature that shares a name with it.") is None


# --- execute ----------------------------------------------------------------


def test_cleansing_beam_hits_the_color_group_only(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Cleansing Beam", red)
    assert (red.damage_marked, redgreen.damage_marked) == (2, 2)
    assert (green.damage_marked, colorless.damage_marked) == (0, 0)  # no shared colour with Red


def test_group_is_read_through_the_targets_own_colors(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Cleansing Beam", green)  # Green shares with RedGreen; Red does not
    assert (green.damage_marked, redgreen.damage_marked, red.damage_marked) == (2, 2, 0)


def test_colorless_target_is_alone(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Cleansing Beam", colorless)
    assert colorless.damage_marked == 2
    assert (red.damage_marked, redgreen.damage_marked, green.damage_marked) == (0, 0, 0)


def test_illegal_target_forms_no_group(board):
    # RULE 608.2b: the only target is gone on resolution, so the spell does not resolve at all.
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Cleansing Beam", red, before_resolve=lambda: eng.state.remove_from_battlefield(red)
          if hasattr(eng.state, "remove_from_battlefield") else eng.rules.destroy(red))
    assert red not in eng.state.permanents()  # the control really removed the target
    assert (redgreen.damage_marked, green.damage_marked, colorless.damage_marked) == (0, 0, 0)


def test_surge_of_zeal_grants_haste_to_the_group(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Surge of Zeal", red)
    assert combat.has(red, "haste") and combat.has(redgreen, "haste")
    assert not combat.has(green, "haste") and not combat.has(colorless, "haste")


def test_wojek_siren_pumps_the_group(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Wojek Siren", red)
    assert (red.power, redgreen.power, green.power) == (3, 3, 2)


def test_rally_the_righteous_untaps_and_pumps_the_group(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Rally the Righteous", red)
    assert not red.tapped and not redgreen.tapped
    assert green.tapped and colorless.tapped
    assert (red.power, redgreen.power, green.power, colorless.power) == (4, 4, 2, 2)


def test_incite_hysteria_stops_the_group_blocking(board):
    eng, red, redgreen, green, colorless = board
    _cast(eng, "Incite Hysteria", red)
    assert combat.has(red, "cant_block") and combat.has(redgreen, "cant_block")
    assert not combat.has(green, "cant_block")


def test_leave_no_trace_destroys_the_enchantment_group():
    eng = _engine()
    white = _perm(eng, "WhiteAura", "W", enchantment=True)
    whiteblue = _perm(eng, "WBAura", "WU", controller="p2", enchantment=True)
    black = _perm(eng, "BlackAura", "B", controller="p2", enchantment=True)
    bear = _perm(eng, "WhiteBear", "W", controller="p2")
    eng.recompute_continuous_effects()
    _cast(eng, "Leave No Trace", white)
    zones = {o.card.name: o.zone for o in (white, whiteblue, black, bear)}
    assert zones["WhiteAura"] != Zone.BATTLEFIELD and zones["WBAura"] != Zone.BATTLEFIELD
    assert zones["BlackAura"] == Zone.BATTLEFIELD and zones["WhiteBear"] == Zone.BATTLEFIELD  # wrong type / colour


def test_brightflame_gains_life_equal_to_total_damage_dealt(board):
    eng, red, redgreen, green, colorless = board
    life = eng.state.player_by_id("p1").life
    _cast(eng, "Brightflame", red, x=1)
    assert (red.damage_marked, redgreen.damage_marked, green.damage_marked) == (1, 1, 0)
    assert eng.state.player_by_id("p1").life == life + 2  # damage actually dealt to the two members


def test_brightflame_counts_only_damage_actually_dealt(board):
    eng, red, redgreen, green, colorless = board
    redgreen.temp_protections.add("R")  # protection from red: the Red source's damage to it is prevented
    life = eng.state.player_by_id("p1").life
    _cast(eng, "Brightflame", red, x=1)
    assert redgreen.damage_marked == 0 and red.damage_marked == 1
    assert eng.state.player_by_id("p1").life == life + 1  # the prevented hit is not 'dealt this way'


# --- Bathe in Light (hand-authored: one colour pick for the whole group) ----


def test_bathe_in_light_one_choice_protects_the_group():
    eng = _engine()
    red = _perm(eng, "Red", "R")
    redgreen = _perm(eng, "RedGreen", "RG", controller="p2")
    green = _perm(eng, "Green", "G", controller="p2")
    eng.recompute_continuous_effects()
    card = Card(id="bil", name="Bathe in Light", type_line="Instant", is_instant=True, mana_cost_string="{W}",
                keywords=["Radiance"],
                oracle_text="Radiance — Choose a color. Target creature and each other creature that shares a color with it gain protection from the chosen color until end of turn.")
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    player = eng.state.player_by_id("p1")
    player.hand.append(obj)
    player.mana_pool.add("W", 5)
    eng.cast_spell(player, obj, targets=[red])
    eng.resolve_until_stable()
    pc = eng.state.pending_choice
    assert pc is not None and pc["kind"] == "grant_protection_color"
    eng.resolve_pending_choice("B")  # a single answer
    assert eng.state.pending_choice is None
    assert "B" in red.temp_protections and "B" in redgreen.temp_protections
    assert "B" not in green.temp_protections


# --- the two {T} Radiance creatures -------------------------------------------


def _wojek(eng, name, text):
    card = Card(
        id=name, name=name, type_line="Creature — Human Wizard", is_creature=True, power=1, toughness=1,
        color_identity={"W"}, keywords=["Radiance"], oracle_text=f"Radiance — {text}",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_wojek_embermage_pings_the_group(board):
    eng, red, redgreen, green, colorless = board
    mage = _wojek(eng, "Wojek Embermage", "{T}: This creature deals 1 damage to target creature and each other creature that shares a color with it.")
    eng.activate_ability(eng.state.player_by_id("p1"), mage, 0, targets=[red])
    eng.resolve_until_stable()
    assert (red.damage_marked, redgreen.damage_marked, green.damage_marked, colorless.damage_marked) == (1, 1, 0, 0)


def test_wojek_apothecary_shields_the_group(board):
    eng, red, redgreen, green, colorless = board
    mage = _wojek(eng, "Wojek Apothecary", "{T}: Prevent the next 1 damage that would be dealt to target creature and each other creature that shares a color with it this turn.")
    eng.activate_ability(eng.state.player_by_id("p1"), mage, 0, targets=[red])
    eng.resolve_until_stable()
    for victim in (red, redgreen, green):
        eng.rules.deal_damage(victim, 1, None)
    assert (red.damage_marked, redgreen.damage_marked, green.damage_marked) == (0, 0, 1)
