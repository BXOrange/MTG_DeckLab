"""PAR-284 (d): counts taken as another player -- "for each X they control" / "in their graveyard" (RULE 608.2h).

Also the subject-player gap under it: "target player loses N life for each creature you control" used to be read as a
per-creature `for_each` with no player bound (gate-refused); it is one effect on the announced player, scaled (RULE 115.1).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _cast, _creature, _engine


def _modeled(oracle, type_line="Sorcery"):
    return parse_oracle(_card("Probe", type_line, oracle, is_sorcery=type_line == "Sorcery",
                              is_creature=type_line.startswith("Creature")))


@pytest.mark.parametrize("oracle, type_line", [
    ("Target player loses 1 life for each creature you control.", "Sorcery"),
    ("Target opponent loses 1 life for each tapped artifact they control.", "Sorcery"),
    ("Target opponent loses 2 life for each creature card in their graveyard.", "Sorcery"),
    ("Each opponent loses 1 life for each creature they control.", "Sorcery"),
    ("Each player loses 1 life for each creature they control.", "Sorcery"),
    ("Whenever ~ deals combat damage to a player, that player loses 1 life for each artifact they control.",
     "Creature — Bear"),
])
def test_relative_player_counts_are_modeled(oracle, type_line):
    result = _modeled(oracle, type_line)
    assert result.modeled, result.unclaimed


def test_they_without_a_player_in_the_body_waits_for_a_damage_head():
    # Hoard Hauler (PAR-284 milestone 23): the body names no player, so "they" is the head's damaged player. The body
    # alone carries a marker only a damage-to-a-player head satisfies; the gate refuses it anywhere else.
    [bound] = parse_effect_body("create a treasure token for each artifact they control.")
    assert bound.params["amount"]["of"] == "damaged_player" and bound.params["event_player_events"] == ["DAMAGE"]
    assert not _modeled("Create a Treasure token for each artifact they control.").modeled
    assert not _modeled("Whenever ~ deals combat damage to a creature, create a Treasure token for each artifact they control.",
                        "Creature — Bear").modeled
    assert _modeled("Whenever ~ deals combat damage to a player, create a Treasure token for each artifact they control.",
                    "Creature — Bear").modeled


def test_target_player_count_is_one_bound_effect_not_a_loop():
    specs = parse_effect_body("target player loses 1 life for each creature you control.")
    assert [s.type for s in specs] == ["bind"]
    assert specs[0].params["effects"][0]["params"]["target_kind"] == "player"


def test_that_player_they_control_reads_as_the_event_players_permanents():
    specs = _modeled("Whenever ~ deals combat damage to a player, that player loses 1 life for each artifact they control.",
                     "Creature — Bear").specs
    over = specs[0].effects[0].params["over"]["selector"]
    assert over["controller_ref"] == "trigger_player" and over["filter"] == {"card_type": "artifact"}


def _life(eng):
    return [p.life for p in eng.state.players]


def test_target_player_loses_life_for_their_own_tapped_artifacts():
    eng = _engine()
    for i, tapped in enumerate((True, True, False)):
        art = GameObject(_card(f"Art{i}", "Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
        art.controller_id = "p2"
        art.tapped = tapped
        eng.state.battlefield.append(art)
    mine = GameObject(_card("Mine", "Artifact"), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine.controller_id = "p1"
    mine.tapped = True
    eng.state.battlefield.append(mine)
    p1, p2 = eng.state.players
    card = _card("Burden", "Sorcery", "Target player loses 1 life for each tapped artifact they control.", is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(card).specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj, targets=[p2])
    eng.resolve_until_stable()
    assert _life(eng) == [20, 18]  # the two tapped artifacts of the target, not mine and not the untapped one


def test_target_opponent_loses_life_for_creature_cards_in_their_graveyard():
    eng = _engine()
    p1, p2 = eng.state.players
    for i in range(3):
        p2.graveyard.append(GameObject(_card(f"G{i}", "Creature — Bear", is_creature=True), owner_id="p2", zone=Zone.GRAVEYARD))
    p1.graveyard.append(GameObject(_card("Mine", "Creature — Bear", is_creature=True), owner_id="p1", zone=Zone.GRAVEYARD))
    card = _card("Death", "Sorcery", "Target opponent loses 2 life for each creature card in their graveyard.", is_sorcery=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(card).specs)
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj, targets=[p2])
    eng.resolve_until_stable()
    assert _life(eng) == [20, 14]


def test_each_player_loses_life_for_their_own_creatures():
    eng = _engine()
    _creature(eng, "A1", "p1", 1)
    for i in range(3):
        _creature(eng, f"B{i}", "p2", 1)
    _cast(eng, "Each player loses 1 life for each creature they control.")
    assert _life(eng) == [19, 17]


def test_each_opponent_loses_life_for_their_creatures_on_enter():
    eng = _engine()
    for i in range(2):
        _creature(eng, f"B{i}", "p2", 1)
    _creature(eng, "A1", "p1", 1)
    card = _card("Phalanx", "Creature — Horror", "When this creature enters, each opponent loses 1 life for each creature they control.",
                 is_creature=True, power=2, toughness=4)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert _life(eng) == [20, 18]


def test_emissary_of_despair_drains_for_the_damaged_players_artifacts():
    from tests.test_par208_defending_player_discard import _attack, _setup
    eng, emissary, p2 = _setup("Emissary of Despair")
    assert parse_oracle(emissary.card).modeled
    for i in range(2):
        art = GameObject(_card(f"Rock{i}", "Artifact"), owner_id=p2.id, zone=Zone.BATTLEFIELD)
        art.controller_id = p2.id
        eng.state.battlefield.append(art)
    life = p2.life
    _attack(eng, emissary)
    eng.state.current_step = "combat_damage"
    eng._step_combat_damage()  # RULE 510: damage is dealt, then the trigger resolves
    eng.resolve_until_stable()
    # combat damage from the 3-power attacker plus 1 life per artifact the damaged player controls
    assert p2.life == life - emissary.power - 2
