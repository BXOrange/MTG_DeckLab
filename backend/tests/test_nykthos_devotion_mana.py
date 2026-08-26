"""Nykthos, Shrine to Nyx: "{2}, {T}: Choose a color. Add an amount of mana
of that color equal to your devotion to that color." — the one mana
ability in the cache where the colour *choice* and the produced *amount*
are coupled (every other `ManaAbility.color_selector` menu either has a
fixed amount per option, or a board-dependent menu with no choice
involved). Modeled as a genuine "any one color" menu whose per-option
amount is that option's own devotion (`resolve_options`'s
``"devotion_to_chosen_color"`` branch), not a shared `amount_selector`
scalar — those only scale every option by the *same* count.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for, resolve_options
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def land(name, oracle_text):
    return Card(id=name, name=name, type_line="Legendary Land", is_land=True, oracle_text=oracle_text)


def permanent(name, mana_cost_string, power=2, toughness=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string=mana_cost_string,
        converted_mana_cost=3,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


NYKTHOS_TEXT = (
    "{T}: Add {C}.\n"
    "{2}, {T}: Choose a color. Add an amount of mana of that color equal "
    "to your devotion to that color."
)


def test_nykthos_is_modeled():
    card = land("Nykthos, Shrine to Nyx", NYKTHOS_TEXT)
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_devotion_mana_menu_matches_board_devotion():
    eng = make_engine("p1", "p2")
    nykthos = put(eng.state, land("Nykthos, Shrine to Nyx", NYKTHOS_TEXT))
    put(eng.state, permanent("White Thing", "{W}{W}"))
    put(eng.state, permanent("Blue Thing", "{U}"))

    abilities = mana_abilities_for(nykthos, eng.state)
    devotion_ability = next(a for a in abilities if a.color_selector == "devotion_to_chosen_color")
    options = resolve_options(devotion_ability, nykthos, eng.state)

    assert {"W": 2} in options
    assert {"U": 1} in options
    assert not any("B" in opt or "R" in opt or "G" in opt for opt in options)


def test_zero_devotion_colors_are_not_offered():
    eng = make_engine("p1", "p2")
    nykthos = put(eng.state, land("Nykthos, Shrine to Nyx", NYKTHOS_TEXT))

    abilities = mana_abilities_for(nykthos, eng.state)
    devotion_ability = next(a for a in abilities if a.color_selector == "devotion_to_chosen_color")
    options = resolve_options(devotion_ability, nykthos, eng.state)

    assert options == []


def test_only_the_controllers_own_devotion_counts():
    eng = make_engine("p1", "p2")
    nykthos = put(eng.state, land("Nykthos, Shrine to Nyx", NYKTHOS_TEXT), controller="p1")
    put(eng.state, permanent("Opponent's Thing", "{R}{R}"), controller="p2")

    abilities = mana_abilities_for(nykthos, eng.state)
    devotion_ability = next(a for a in abilities if a.color_selector == "devotion_to_chosen_color")
    options = resolve_options(devotion_ability, nykthos, eng.state)

    assert options == []
