"""PAR-231 -- the `<n> or more` quantity-threshold trigger heads (attack and block relations).

RULE 508.3a / 508.1b: "N or more creatures attack a player" counts the attackers aimed at one defender.
RULE 509.3c / 509.3d: "blocks / becomes blocked by N or more creatures" is one trigger per declaration.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_attack_batch_head import (
    _attack, _attackers, _combat, _drawn, _stocked,
)
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _put

CREATURE = {"card_type": "creature"}


@pytest.mark.parametrize(
    "cond, condition, spec",
    [
        ("2 or more creatures you control attack a player", {"subject": "you"},
         {"filter": CREATURE, "min": 2, "at_defender": "player"}),
        ("3 or more dragons you control attack an opponent", {"subject": "you"},
         {"filter": {"subtype": "dragon"}, "min": 3, "at_defender": "player"}),
        ("2 or more creatures your opponents control attack", {"subject": "player", "scope": "not_you"},
         {"filter": CREATURE, "min": 2}),
        ("you attack a player with 1 or more creatures with power 4 or greater", {"subject": "you"},
         {"filter": {"card_type": "creature", "min_power": 4}, "min": 1, "at_defender": "player"}),
        ("an opponent attacks a planeswalker you control with 2 or more creatures",
         {"subject": "player", "scope": "not_you"},
         {"filter": CREATURE, "min": 2, "at_defender": "controller_planeswalker"}),
    ],
)
def test_quantity_attack_grammar(cond, condition, spec):
    head = parse_object_trigger_head(cond)
    # A named defender reads the per-defender group event (one trigger for each qualifying defender).
    assert head is not None and head.event == ("ATTACKERS_AT_DEFENDER" if "at_defender" in spec else "ATTACKERS_DECLARED")
    assert head.condition == condition
    assert head.trigger["attackers_declared"] == spec


@pytest.mark.parametrize(
    "cond",
    [
        "2 or more frobnicators you control attack a player",
        "2 or more creatures you control attack a battle",
        "2 or more creatures attack a player",  # no controller scope: not this head's grammar
    ],
)
def test_quantity_attack_fails_closed(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or "at_defender" not in head.trigger.get("attackers_declared", {})


@pytest.mark.parametrize(
    "cond, events, trigger",
    [
        ("~ blocks 2 or more creatures", "BLOCKS", {"related_min": 2}),
        ("~ blocks 2 or more black creatures", "BLOCKS",
         {"related_min": 2, "related_filter": {"color": "B", "card_type": "creature"}}),
        ("~ blocks or becomes blocked by 2 or more orcs", ["BLOCKS", "BECOMES_BLOCKED"],
         {"related_min": 2, "related_filter": {"subtype": "orc"}}),
        ("equipped creature becomes blocked by 2 or more colorless creatures", "BECOMES_BLOCKED", None),
    ],
)
def test_quantity_block_grammar(cond, events, trigger):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == events
    if trigger is not None:
        assert head.trigger == trigger
    else:
        assert head.trigger["related_min"] == 2


def test_quantity_block_fails_closed():
    assert parse_object_trigger_head("~ blocks 2 or more frobnicators") is None


@pytest.mark.parametrize(
    "name",
    ["Horn of the Mark", "Landroval, Horizon Witness", "Bitter Work", "Lairwatch Giant", "Amphibious Kavu",
     "Dwarven Soldier", "Hedron Blade", "Oath of Kaya", "Rashka the Slayer", "Rigo, Streetwise Mentor",
     "Serra Inquisitors"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

HORN = "Whenever two or more creatures you control attack a player, draw a card."
OATH = "Whenever an opponent attacks a planeswalker you control with one or more creatures, you gain 2 life."


def _three_players():
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.models.game.game_state import GameState
    from mtg_analyzer.models.game.player import Player

    state = GameState(players=[Player(id=i, name=i, life=20) for i in ("p1", "p2", "p3")])
    return GameEngine(state), state


def _swing(engine, state, assignments, attacking="p1"):
    """``assignments``: (attacker, defender spec) pairs; declares them all, then fires the attack events."""
    state.current_step = "declare_attackers"
    state.active_player_index = [p.id for p in state.players].index(attacking)
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": d} for a, d in assignments])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def _walker(state, owner, name="Walker"):
    card = Card(id=name, name=name, type_line="Legendary Planeswalker", loyalty="4")
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.counters["loyalty"] = 4
    state.add_to_battlefield(obj)
    return obj


def _player_spec(pid):
    return {"kind": "player", "id": pid, "label": pid}


def _horn_draws(assign):
    engine, state = _three_players()
    p1 = state.player_by_id("p1")
    for i in range(8):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"), owner_id="p1",
                                     zone=Zone.LIBRARY))
    _put(state, HORN, name="Horn", types="Artifact")
    walker = _walker(state, "p2")
    creatures = _attackers(state, [(n, "Creature — Bear", ()) for n in "ABCD"])
    pairs = assign(creatures, walker)
    for creature, _ in pairs:
        creature.summoning_sick = False
    before = len(p1.hand)
    _swing(engine, state, pairs)
    return len(p1.hand) - before


def test_horn_triggers_once_for_each_player_attacked_with_two_creatures():
    # RULE 508.1b / 603.2: two creatures at p2 and two at p3 are two qualifying defenders.
    drawn = _horn_draws(lambda c, w: [(c[0], _player_spec("p2")), (c[1], _player_spec("p2")),
                                      (c[2], _player_spec("p3")), (c[3], _player_spec("p3"))])
    assert drawn == 2


def test_horn_does_not_trigger_for_creatures_split_between_players():
    assert _horn_draws(lambda c, w: [(c[0], _player_spec("p2")), (c[1], _player_spec("p3"))]) == 0


def test_horn_ignores_attackers_aimed_at_the_players_planeswalker():
    def assign(c, w):
        return [(c[0], _player_spec("p2")), (c[1], {"kind": "planeswalker", "instance_id": w.instance_id,
                                                      "label": "Walker"})]

    assert _horn_draws(assign) == 0


def test_horn_with_two_creatures_on_one_player_triggers_once():
    assert _horn_draws(lambda c, w: [(c[0], _player_spec("p2")), (c[1], _player_spec("p2")),
                                     (c[2], _player_spec("p2"))]) == 1


def test_oath_triggers_once_for_each_attacked_planeswalker_you_control():
    engine, state = _three_players()
    _put(state, OATH, name="Oath", types="Enchantment", owner="p1")
    first, second = _walker(state, "p1", "W1"), _walker(state, "p1", "W2")
    a, b, c = _attackers(state, [(n, "Creature — Bear", ()) for n in "ABC"], owner="p2")
    for creature in (a, b, c):
        creature.summoning_sick = False
    before = state.player_by_id("p1").life
    _swing(engine, state, [
        (a, {"kind": "planeswalker", "instance_id": first.instance_id, "label": "W1"}),
        (b, {"kind": "planeswalker", "instance_id": first.instance_id, "label": "W1"}),
        (c, {"kind": "planeswalker", "instance_id": second.instance_id, "label": "W2"}),
    ], attacking="p2")
    assert state.player_by_id("p1").life - before == 4  # two planeswalkers, two triggers


def test_oath_ignores_attacks_on_the_player_and_on_other_planeswalkers():
    engine, state = _three_players()
    _put(state, OATH, name="Oath", types="Enchantment", owner="p1")
    other = _walker(state, "p3", "Theirs")
    a, b = _attackers(state, [(n, "Creature — Bear", ()) for n in "AB"], owner="p2")
    a.summoning_sick = b.summoning_sick = False
    before = state.player_by_id("p1").life
    _swing(engine, state, [
        (a, _player_spec("p1")),
        (b, {"kind": "planeswalker", "instance_id": other.instance_id, "label": "Theirs"}),
    ], attacking="p2")
    assert state.player_by_id("p1").life == before


GIANT = (
    "~ can block an additional creature each combat.\n"
    "Whenever ~ blocks two or more creatures, draw a card."
)


def _giant(state):
    giant = _put(state, GIANT, name="Giant", types="Creature — Giant", owner="p2")
    giant.summoning_sick = False
    giant.controller_id = "p2"
    return giant


def test_blocks_two_or_more_fires_once_for_two_blocked_creatures():
    engine, state = _stocked()
    attackers = _attackers(state, [("A", "Creature — Bear", ()), ("B", "Creature — Bear", ())])
    giant = _giant(state)
    p2 = state.player_by_id("p2")
    p2.library.extend(
        __import__("mtg_analyzer.models.game.game_object", fromlist=["GameObject"]).GameObject(
            __import__("mtg_analyzer.models.cards.card", fromlist=["Card"]).Card(
                id=f"M{i}", name=f"M{i}", type_line="Land"), owner_id="p2",
            zone=__import__("mtg_analyzer.models.game.game_object", fromlist=["Zone"]).Zone.LIBRARY)
        for i in range(4)
    )
    before = len(p2.hand)
    _combat(state, engine, attackers, [(giant, attackers[0]), (giant, attackers[1])])
    assert len(p2.hand) - before == 1  # one trigger, not one per blocked creature


def test_blocking_a_single_creature_does_not_fire_the_threshold():
    engine, state = _stocked()
    attackers = _attackers(state, [("A", "Creature — Bear", ()), ("B", "Creature — Bear", ())])
    giant = _giant(state)
    p2 = state.player_by_id("p2")
    before = len(p2.hand)
    _combat(state, engine, attackers, [(giant, attackers[0])])
    assert len(p2.hand) == before


def test_bitter_work_draws_once_per_player_attacked_with_a_big_creature():
    # Ruling 2025-10-02: one card per player attacked, however many power-4+ creatures hit that player.
    engine, state = _three_players()
    p1 = state.player_by_id("p1")
    for i in range(8):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"), owner_id="p1",
                                     zone=Zone.LIBRARY))
    _put(state, "Whenever you attack a player with 1 or more creatures with power 4 or greater, draw a card.",
         name="Bitter", types="Enchantment")
    big = []
    for name in "ABC":
        creature = GameObject(Card(id=name, name=name, type_line="Creature — Giant", is_creature=True, power=4,
                                   toughness=4), owner_id="p1", zone=Zone.BATTLEFIELD)
        creature.controller_id = "p1"
        creature.summoning_sick = False
        state.add_to_battlefield(creature)
        big.append(creature)
    before = len(p1.hand)
    _swing(engine, state, [(big[0], _player_spec("p2")), (big[1], _player_spec("p2")), (big[2], _player_spec("p3"))])
    assert len(p1.hand) - before == 2
