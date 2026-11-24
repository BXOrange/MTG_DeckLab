"""PAR-284 milestone 21: amounts shared across packages (RULE 903.8 commander tax, 702.179 speed, 506.2 attackers, 701.22 scry).

"your highest commander tax among your commanders" (`highest_commander_tax`), "your speed" (`your_speed`), "for each
creature attacking you" (`creatures_attacking_you`) and "the number of cards looked at while scrying this way" (the
`SCRY` event's ``count``) are named amounts the engine already tracked.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.continuous import COMMANDER_TAX_PER_CAST, count_selector
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par284_counters_removed_cost import _board
from tests.test_par284_history_amounts import _spell
from tests.test_par284_this_way_windows import _card, _engine

CARDS = [
    ("Tax Bolt", "Instant", "Tax Bolt deals damage to any target equal to your highest commander tax among your commanders."),
    ("Tax Draw", "Sorcery", "Draw cards equal to your highest commander tax among your commanders."),
    ("Tax Keeper", "Creature — Bear", "Tax Keeper gets +X/+X, where X is your highest commander tax among your commanders."),
    ("Speed Demon", "Creature — Demon", "Start your engines!\nAt the beginning of your end step, you draw X cards and lose X life, where X is your speed."),
    ("Blessed Reversal", "Instant", "You gain 3 life for each creature attacking you."),
    ("Celeb", "Creature — Elf", "Whenever you scry, Celeb gets +1/+1 until end of turn for each card looked at while scrying this way."),
]


@pytest.mark.parametrize("name, type_line, oracle", CARDS)
def test_shared_amount_cards_are_modeled(name, type_line, oracle):
    card = _card(name, type_line, oracle, is_instant=type_line == "Instant", is_sorcery=type_line == "Sorcery",
                 is_creature="Creature" in type_line, power=1 if "Creature" in type_line else None,
                 toughness=1 if "Creature" in type_line else None)
    assert parse_oracle(card).modeled


@pytest.mark.parametrize("oracle", [
    "Draw cards equal to your highest commander tax among your opponents' commanders.",
    "Draw cards equal to your speed plus the speed of target opponent.",
    "You gain 3 life for each creature attacking target opponent.",
])
def test_neighbouring_phrases_stay_unclaimed(oracle):
    assert not parse_oracle(_card("Probe", "Sorcery", oracle, is_sorcery=True)).modeled


def test_highest_commander_tax_is_the_greatest_cast_tally_times_two():
    eng = _engine()
    p1 = eng.state.players[0]
    assert count_selector(eng.state, "p1", "highest_commander_tax") == 0  # no commander cast yet: no tax
    p1.commander_casts = {101: 1, 102: 3}
    assert count_selector(eng.state, "p1", "highest_commander_tax") == 3 * COMMANDER_TAX_PER_CAST


def test_tax_bolt_deals_the_highest_tax_to_the_target():
    eng = _engine()
    p1, p2 = eng.state.players
    p1.commander_casts = {101: 2}
    _spell(eng, "Tax Bolt", CARDS[0][2], targets=[p2])
    assert p2.life == 20 - 4


def test_speed_is_read_from_the_player():
    eng = _engine()
    eng.state.players[0].speed = 3
    assert count_selector(eng.state, "p1", "your_speed") == 3
    assert count_selector(eng.state, "p2", "your_speed") == 0


def test_speed_demon_draws_and_loses_by_speed_at_the_end_step():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(5):
        p1.library.append(GameObject(_card(f"L{i}", "Land"), owner_id="p1", zone=Zone.LIBRARY))
    p1.speed = 2
    _board(eng, "Speed Demon", "Creature — Demon", CARDS[3][2], {})
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    assert len(p1.hand) == 2 and p1.life == 18


def test_blessed_reversal_counts_only_creatures_attacking_the_caster():
    eng = _engine()
    p1, p2 = eng.state.players
    for i in range(3):
        _board(eng, f"Raider{i}", "Creature — Bear", "", {}, owner="p2")
    attackers = [o for o in eng.state.battlefield if o.controller_id == "p2"]
    for attacker in attackers:
        attacker.attacking = True
    attackers[0].combat_defender = {"kind": "player", "id": "p1"}
    attackers[1].combat_defender = {"kind": "player", "id": "p1"}
    attackers[2].combat_defender = {"kind": "planeswalker", "id": 99}  # attacking a planeswalker is not attacking you
    _spell(eng, "Blessed Reversal", CARDS[4][2])
    assert p1.life == 20 + 6


def test_celeborn_pumps_by_the_cards_looked_at():
    eng = _engine()
    p1 = eng.state.players[0]
    for i in range(4):
        p1.library.append(GameObject(_card(f"L{i}", "Land"), owner_id="p1", zone=Zone.LIBRARY))
    elf = _board(eng, "Celeb", "Creature — Elf", CARDS[5][2], {}, power=1, toughness=1)
    eng.rules.scry(p1, 3, source=elf)
    eng.resolve_until_stable()
    while eng.state.pending_choice is not None:
        eng.rules.resolve_choice("decline")  # keep the cards where they are: both scry phases
        eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (elf.power, elf.toughness) == (1 + 3, 1 + 3)
