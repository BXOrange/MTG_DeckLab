"""PAR-313: "defending player" conditions (RULE 506.2 / 508.5).

(a) An attack trigger's intervening "if defending player ..." is the shared condition vocabulary read for the player
the attacker attacks (`as_defending_player` / `defending_player_has_more`), never for "an opponent".
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.static_conditions import condition_holds
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _three_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(name, oracle, types="Creature — Rat", power=1, toughness=1, keywords=()):
    return Card(id=name, name=name, type_line=types, oracle_text=oracle, is_creature=True, power=power,
                toughness=toughness, keywords=list(keywords))


def _attack(eng, state, attacker, defender_id):
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": defender_id}}])
    eng.resolve_until_stable()


# -- parser -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase,inner", [
    ("defending player is poisoned", {"kind": "poison_at_least", "amount": 1}),
    ("defending player has 2 or fewer cards in hand", {"kind": "cards_in_hand_at_most", "amount": 2}),
    ("defending player has 5 or more life", {"kind": "life_at_least", "amount": 5}),
    ("defending player is the monarch", {"kind": "is_monarch"}),
])
def test_defending_player_phrases_wrap_the_you_reading(phrase, inner):
    assert static_condition(phrase) == {"kind": "as_defending_player", "condition": inner}


def test_defending_player_controls_reads_the_shared_count():
    cond = static_condition("defending player controls no walls")
    assert cond["kind"] == "as_defending_player"
    assert cond["condition"]["kind"] == "control_count" and cond["condition"]["max"] == 0


@pytest.mark.parametrize("phrase,selector", [
    ("defending player has more cards in hand than you", "cards_in_your_hand"),
    ("defending player controls more lands than you", {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}}),
])
def test_defending_player_comparisons_with_the_controller(phrase, selector):
    assert static_condition(phrase) == {"kind": "defending_player_has_more", "selector": selector}


@pytest.mark.parametrize("phrase", [
    "defending player has fewer cards in hand than you",
    "defending player controls an enchanting tale",
    "defending player owes a debt",
])
def test_unknown_defending_player_phrases_stay_unclaimed(phrase):
    assert static_condition(phrase) is None


# -- engine -----------------------------------------------------------------------------------------------------------


def test_the_condition_follows_the_attacked_player_not_any_opponent():
    eng, state = _three_player()
    rats = _put(state, _creature("Septic Rats", "Whenever ~ attacks, if defending player is poisoned, it gets +1/+1 until end of turn.", keywords=["Infect"]))
    state.player_by_id("p3").poison = 2  # p2 is clean; "an opponent is poisoned" would be true
    cond = static_condition("defending player is poisoned")
    _attack(eng, state, rats, "p2")
    assert condition_holds(cond, state, rats, "p1") is False
    assert rats.power == 1
    rats2 = _put(state, _creature("Septic Rats", "Whenever ~ attacks, if defending player is poisoned, it gets +1/+1 until end of turn.", keywords=["Infect"]))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": rats2, "defender": {"kind": "player", "id": "p3"}}])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert condition_holds(cond, state, rats2, "p1") is True
    assert rats2.power == 2 and rats.power == 1


def test_no_known_defending_player_fails_closed_for_both_polarities():
    eng, state = _three_player()
    rats = _put(state, _creature("Idle", ""))
    cond = static_condition("defending player controls no walls")
    assert condition_holds(cond, state, rats, "p1") is False
    assert condition_holds(static_condition("defending player is poisoned"), state, None, "p1") is False
    assert condition_holds({"kind": "as_defending_player", "condition": {"fnord": 1}}, state, rats, "p1") is False


def test_attacking_a_planeswalker_reads_its_controller():
    eng, state = _three_player()
    rats = _put(state, _creature("Idle", ""))
    walker = _put(state, Card(id="pw", name="Walker", type_line="Legendary Planeswalker — Test", loyalty=3), "p3")
    state.player_by_id("p3").poison = 1
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": rats, "defender": {"kind": "planeswalker", "instance_id": walker.instance_id}}])
    assert condition_holds(static_condition("defending player is poisoned"), state, rats, "p1") is True


def test_hand_size_comparison_uses_the_defender():
    eng, state = _three_player()
    rats = _put(state, _creature("Idle", ""))
    p1, p2, p3 = (state.player_by_id(i) for i in ("p1", "p2", "p3"))
    for _ in range(3):
        p3.hand.append(GameObject(Card(id="c", name="c", type_line="Instant"), owner_id="p3", zone=Zone.HAND))
    cond = static_condition("defending player has more cards in hand than you")
    _attack(eng, state, rats, "p2")
    assert condition_holds(cond, state, rats, "p1") is False  # p3 has more, p2 does not
    rats.combat_defender = {"kind": "player", "id": "p3"}
    assert condition_holds(cond, state, rats, "p1") is True


# -- real cards -------------------------------------------------------------------------------------------------------


def _real(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


@pytest.mark.parametrize("name", ["Septic Rats", "Reaper of Night // Harvest Fear", "Fear of the Dark", "Siege Dragon",
                                  "Spectral Bears", "Spectral Force", "Aerial Surveyor"])
def test_real_attack_trigger_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_real_septic_rats_pumps_only_against_a_poisoned_defender():
    eng, state = _three_player()
    state.player_by_id("p3").poison = 1
    rats = _put(state, _real("Septic Rats"))
    other = _put(state, _real("Septic Rats"))
    _attack(eng, state, rats, "p2")
    _attack(eng, state, other, "p3")
    eng.recompute_continuous_effects()
    assert (rats.power, other.power) == (2, 3)


def test_real_siege_dragon_damages_only_the_defenders_creatures_when_it_has_no_walls():
    eng, state = _three_player()
    dragon = _put(state, _real("Siege Dragon"))
    bear2 = _put(state, _creature("Bear", "", "Creature — Bear", 2, 3), "p2")
    bear3 = _put(state, _creature("Bear", "", "Creature — Bear", 2, 3), "p3")
    _attack(eng, state, dragon, "p2")
    assert (bear2.damage_marked, bear3.damage_marked) == (2, 0)


def test_real_siege_dragon_holds_fire_when_the_defender_controls_a_wall():
    eng, state = _three_player()
    dragon = _put(state, _real("Siege Dragon"))
    _put(state, _creature("Wall", "", "Creature — Wall", 0, 4), "p2")
    bear2 = _put(state, _creature("Bear", "", "Creature — Bear", 2, 3), "p2")
    bear3 = _put(state, _creature("Bear", "", "Creature — Bear", 2, 3), "p3")
    _attack(eng, state, dragon, "p2")
    assert (bear2.damage_marked, bear3.damage_marked) == (0, 0)
    _attack(eng, state, _put(state, _real("Siege Dragon")), "p3")
    assert bear3.damage_marked == 2


def test_real_fear_of_the_dark_gains_evasion_per_defender():
    eng, state = _three_player()
    _put(state, _creature("Glimmer", "", "Creature — Glimmer", 1, 1), "p2")
    fear = _put(state, _real("Fear of the Dark"))
    other = _put(state, _real("Fear of the Dark"))
    _attack(eng, state, fear, "p2")
    _attack(eng, state, other, "p3")
    eng.recompute_continuous_effects()
    assert "menace" not in {k.lower() for k in fear.granted_keywords}
    assert "menace" in {k.lower() for k in other.granted_keywords}


# -- (b) conditional unblockability -----------------------------------------------------------------------------------


def _blocks(eng, state, defender_id, attacker):
    blocker = _put(state, _creature("Wall", "", "Creature — Wall", 0, 4), defender_id)
    state.current_step = "declare_blockers"
    eng.recompute_continuous_effects()
    return eng.can_block(state.player_by_id(defender_id), blocker, attacker)


def test_real_beebles_are_unblockable_only_for_the_artifact_defender():
    eng, state = _three_player()
    _put(state, Card(id="a", name="Rock", type_line="Artifact"), "p2")
    gnat = _put(state, _real("Bouncing Beebles"))
    gnat2 = _put(state, _real("Bouncing Beebles"))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [
        {"attacker": gnat, "defender": {"kind": "player", "id": "p2"}},
        {"attacker": gnat2, "defender": {"kind": "player", "id": "p3"}},
    ])
    assert _blocks(eng, state, "p2", gnat) is False
    assert _blocks(eng, state, "p3", gnat2) is True


def test_beebles_become_blockable_when_the_defenders_artifact_leaves():
    eng, state = _three_player()
    rock = _put(state, Card(id="a", name="Rock", type_line="Artifact"), "p2")
    gnat = _put(state, _real("Bouncing Beebles"))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": gnat, "defender": {"kind": "player", "id": "p2"}}])
    assert _blocks(eng, state, "p2", gnat) is False
    eng.rules.destroy(rock)
    assert _blocks(eng, state, "p2", gnat) is True


def test_real_arctic_foxes_keep_the_power_gate_only_against_a_snow_land_defender():
    eng, state = _three_player()
    _put(state, Card(id="s", name="Snowy", type_line="Snow Land"), "p2")
    foxes = _put(state, _real("Arctic Foxes"))
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": foxes, "defender": {"kind": "player", "id": "p2"}}])
    fat = _put(state, _creature("Fat", "", "Creature — Ox", 3, 3), "p2")
    small = _put(state, _creature("Small", "", "Creature — Ox", 1, 3), "p2")
    state.current_step = "declare_blockers"
    eng.recompute_continuous_effects()
    p2 = state.player_by_id("p2")
    assert eng.can_block(p2, fat, foxes) is False
    assert eng.can_block(p2, small, foxes) is True


def test_real_activated_defending_condition_names_any_attacked_player():
    eng, state = _three_player()
    _put(state, Card(id="s", name="Snowy", type_line="Snow Land"), "p3")
    sleigh = _put(state, _real("Arcum's Sleigh"))
    guard = static_condition("defending player controls a snow land")
    wide = dict(guard, combat_wide=True)
    attacker = _put(state, _creature("Idle", ""))
    assert condition_holds(wide, state, sleigh, "p1") is False  # nobody is attacked yet
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])
    assert condition_holds(wide, state, sleigh, "p1") is False  # p2 has no snow land
    attacker.combat_defender = {"kind": "player", "id": "p3"}
    assert condition_holds(wide, state, sleigh, "p1") is True


def test_real_feed_the_infection_hits_only_opponents_with_enough_poison():
    eng, state = _three_player()
    state.player_by_id("p2").poison = 3
    state.player_by_id("p3").poison = 2
    spell = GameObject(_real("Feed the Infection"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id("p1").hand.append(spell)
    eng.begin_turn()
    state.current_step = "main1"
    state.player_by_id("p1").mana_pool.add("B", 8)
    eng.cast_spell(state.player_by_id("p1"), spell)
    eng.resolve_until_stable()
    assert [state.player_by_id(i).life for i in ("p1", "p2", "p3")] == [20 - 3, 20 - 3, 20]


def test_the_most_creatures_or_tied_follows_the_defender():
    eng, state = _three_player()
    horror = _put(state, _real("Hooded Horror"))
    for _ in range(3):
        _put(state, _creature("Bear", "", "Creature — Bear", 2, 2), "p2")
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": horror, "defender": {"kind": "player", "id": "p3"}}])
    assert _blocks(eng, state, "p3", horror) is True  # p3 (one creature after the blocker joins) trails p2's three
    horror.combat_defender = {"kind": "player", "id": "p2"}
    assert _blocks(eng, state, "p2", horror) is False  # p2 controls the most creatures
    p3_extra = [_put(state, _creature("Bear", "", "Creature — Bear", 2, 2), "p3") for _ in range(2)]
    horror.combat_defender = {"kind": "player", "id": "p3"}
    assert p3_extra and _blocks(eng, state, "p3", horror) is False  # three each: tied for the most


def test_a_rad_counter_on_the_defender_makes_nightkin_ambusher_unblockable():
    eng, state = _three_player()
    ambusher = _put(state, _real("Nightkin Ambusher"))
    state.player_by_id("p3").counters["rad"] = 1
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": ambusher, "defender": {"kind": "player", "id": "p2"}}])
    assert _blocks(eng, state, "p2", ambusher) is True
    ambusher.combat_defender = {"kind": "player", "id": "p3"}
    assert _blocks(eng, state, "p3", ambusher) is False
