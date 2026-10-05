"""PAR-107…114 residue batches, part 5 — "During turns other than yours, `<static>`" (RULE 613.6): the `not_your_turn`
mirror of the existing "During your turn, …" gate (Mesa Lynx, Glory of Warfare, Vibrating Sphere, Oak Street
Innkeeper), plus the gated self-animation of Warden of the Wall and Midnight Mangler ("~ is a 2/3 Gargoyle artifact
creature with flying" — a layer-4 `type_change` with the base P/T, and a keyword grant).

Reference: parser/oracle/catalogue/static_handlers.py (`_DURING_YOUR_TURN_LEADING_RE`, `_self_animation_specs`).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line, text, power=None, toughness=None):
    creature = "Creature" in type_line
    card = Card(
        id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature,
        power=power if creature else None, toughness=toughness if creature else None,
    )
    if not creature:
        card.power, card.toughness = power, toughness  # a Vehicle's printed stats
    return card


def _board(card, controller="p1"):
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return eng, obj


def _on_turn_of(eng, index):
    eng.state.active_player_index = index
    eng.recompute_continuous_effects()


def test_self_pump_applies_only_off_turn():
    eng, lynx = _board(_card("Mesa Lynx", "Creature — Cat", "During turns other than yours, ~ gets +0/+2.", 3, 3))
    assert parse_oracle(lynx.card).modeled
    _on_turn_of(eng, 0)
    assert (lynx.power, lynx.toughness) == (3, 3)
    _on_turn_of(eng, 1)
    assert (lynx.power, lynx.toughness) == (3, 5)


def test_group_anthem_applies_only_off_turn():
    eng, glory = _board(_card("Glory of Warfare", "Enchantment",
                              "During your turn, creatures you control get +2/+0.\n"
                              "During turns other than yours, creatures you control get +0/+2."))
    bear = GameObject(_card("Bear", "Creature — Bear", "", 2, 2), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.controller_id = "p1"
    eng.state.add_to_battlefield(bear)
    _on_turn_of(eng, 0)
    assert (bear.power, bear.toughness) == (4, 2)
    _on_turn_of(eng, 1)
    assert (bear.power, bear.toughness) == (2, 4)


def test_tapped_creatures_gain_hexproof_off_turn_only():
    eng, inn = _board(_card("Oak Street Innkeeper", "Creature — Elf", "During turns other than yours, tapped creatures "
                                                                     "you control have hexproof.", 3, 3))
    inn.tapped = True
    _on_turn_of(eng, 0)
    assert "hexproof" not in inn.granted_keywords
    _on_turn_of(eng, 1)
    assert "hexproof" in inn.granted_keywords
    inn.tapped = False
    eng.recompute_continuous_effects()
    assert "hexproof" not in inn.granted_keywords


def test_warden_of_the_wall_is_a_flying_gargoyle_creature_off_turn():
    text = ("This artifact enters tapped.\n{T}: Add {C}.\n"
            "During turns other than yours, this artifact is a 2/3 Gargoyle artifact creature with flying.")
    eng, warden = _board(_card("Warden of the Wall", "Artifact", text))
    assert parse_oracle(warden.card).modeled
    _on_turn_of(eng, 0)
    assert not warden.is_creature
    _on_turn_of(eng, 1)
    assert warden.is_creature and (warden.power, warden.toughness) == (2, 3)
    assert "flying" in warden.granted_keywords and continuous.has_subtype(warden, "Gargoyle")


def test_midnight_mangler_keeps_its_printed_stats_when_it_becomes_a_creature():
    eng, mangler = _board(_card("Midnight Mangler", "Artifact — Vehicle",
                                "During turns other than yours, this Vehicle is an artifact creature.\nCrew 2", 4, 4))
    assert parse_oracle(mangler.card).modeled
    _on_turn_of(eng, 0)
    assert not mangler.is_creature
    _on_turn_of(eng, 1)
    assert mangler.is_creature and (mangler.power, mangler.toughness) == (4, 4)


def test_an_ungated_self_animation_is_not_claimed():
    card = _card("Probe", "Artifact", "~ is a 2/3 Gargoyle artifact creature with flying.")
    assert not parse_oracle(card).modeled
