"""PAR-286 milestone 3: "whenever that creature <event> this turn" after a clause that chose the creature.

RULE 603.7a / 603.7c: the spell or ability creates a turn-long triggered ability whose subject is the object an
earlier clause chose. The head already existed for "dies / leaves the battlefield"; this widens it to attacks (the
monarch), becomes blocked and deals combat damage to a player (or planeswalker). Every behaviour test drives the real
engine event on the real card and shows near misses that must not fire: another creature, the next turn, and the
chosen creature after it changed zones (RULE 400.7).
"""

from __future__ import annotations

import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import answer, card, cast, filler, game, step

#: Hunter's Insight draws "that many" cards: the combat damage the chosen creature deals.
DAMAGE = 3
#: Barreling Attack's "+1/+1 for each creature blocking it" with two blockers.
BLOCKER_COUNT = 2
#: What Okoye's trigger grants the creature that attacked the monarch.
OKOYE_GRANT = {"double_strike", "trample"}


def _segment(text):
    return segment_line(text, allow_spell_effect=True, provenance=ParserProvenance())


@pytest.mark.parametrize("name", ["Okoye, Mighty and Adored", "Barreling Attack", "Hunter's Insight"])
def test_cards_are_modeled(name):
    card_ = CardDatabase(DB_PATH).get_card(name)
    assert card_ is not None
    assert parse_oracle(card_).coverage == MODELED


def test_head_needs_a_creature_chosen_by_an_earlier_clause():
    chosen = "choose target creature you control. whenever that creature deals combat damage to a player this turn, draw a card."
    assert _segment(chosen).claimed
    # near misses: nothing chose "that creature"; an event outside the family stays unclaimed
    assert not _segment("whenever that creature deals combat damage to a player this turn, draw a card.").claimed
    assert not _segment("choose target creature you control. whenever that creature taps this turn, draw a card.").claimed


def _hunters_insight(engine):
    mine = filler(engine, "Chosen", type_line="Creature", power=DAMAGE, toughness=DAMAGE)
    other = filler(engine, "Other", type_line="Creature", power=DAMAGE, toughness=DAMAGE)
    spell = card(engine, "Hunter's Insight", zone=Zone.HAND)
    cast(engine, spell, targets=[mine])
    return mine, other


def _hand(engine, pid="p1"):
    return len(engine.state.player_by_id(pid).hand)


def _hit(engine, source, amount=DAMAGE, combat=True, target="p2"):
    engine.rules.deal_damage(engine.state.player_by_id(target), amount, source=source, combat=combat)
    engine.resolve_until_stable()


def test_hunters_insight_draws_that_many_only_for_the_chosen_creature():
    engine = game()
    mine, other = _hunters_insight(engine)
    before = _hand(engine)
    _hit(engine, other)                       # near miss: a different creature
    assert _hand(engine) == before
    _hit(engine, mine, combat=False)          # near miss: not combat damage
    assert _hand(engine) == before
    _hit(engine, mine)
    assert _hand(engine) == before + DAMAGE
    _hit(engine, mine)                        # "whenever": it fires again within the turn
    assert _hand(engine) == before + 2 * DAMAGE


def test_hunters_insight_ends_with_the_turn():
    engine = game()
    mine, _ = _hunters_insight(engine)
    engine.state.internal_turn.number += 1
    before = _hand(engine)
    _hit(engine, mine)
    assert _hand(engine) == before


def test_hunters_insight_ignores_the_creature_after_it_changed_zones():
    engine = game()
    mine, _ = _hunters_insight(engine)
    engine.rules.destroy(mine)                # RULE 400.7: a new object returns, not the chosen one
    engine.resolve_until_stable()
    engine.rules.return_from_graveyard(mine, "battlefield", controller_id="p1")
    engine.resolve_until_stable()
    before = _hand(engine)
    _hit(engine, mine)
    assert _hand(engine) == before


def test_hunters_insight_trigger_survives_clone():
    engine = game()
    mine, _ = _hunters_insight(engine)
    clone = copy.deepcopy(engine.state)
    assert len(clone.turn_scoped_triggers) == len(engine.state.turn_scoped_triggers) == 1
    cloned = clone.turn_scoped_triggers[0]
    original = engine.state.turn_scoped_triggers[0]
    assert cloned is not original
    assert cloned.ability.trigger_event == original.ability.trigger_event
    # the RULE 400.7 link (which object, which visit) rides along with the clone
    assert original.ends_when_object_moves is True
    assert (cloned.ends_when_object_moves, cloned.bound_object_id, cloned.bound_incarnation) == (
        True, mine.instance_id, mine.zone_incarnation)


def _declare_attack(engine, attackers, kind="player", player="p2"):
    p1 = engine.state.player_by_id("p1")
    engine.state.current_phase = "combat"
    engine.state.current_step = "declare_attackers"
    spec = next(d for d in engine.legal_defenders_for(p1) if d["kind"] == kind)
    engine.declare_attackers(p1, [{"attacker": a, "defender": spec} for a in attackers])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _okoye_combat(engine):
    okoye = card(engine, "Okoye, Mighty and Adored")
    target = filler(engine, "Target", type_line="Creature", power=2, toughness=2)
    other = filler(engine, "Other", type_line="Creature", power=2, toughness=2)
    step(engine, "begin_combat")
    answer(engine, pick=lambda c: next(
        (str(o["id"]) for o in c["options"] if str(o.get("label")).startswith("Target")), None))
    engine.resolve_until_stable()
    return okoye, target, other


def test_okoye_grants_double_strike_and_trample_when_the_countered_creature_attacks_the_monarch():
    engine = game()
    engine.state.monarch_id = "p2"
    _, target, other = _okoye_combat(engine)
    assert target.counters.get("+1/+1") == 1
    _declare_attack(engine, [target, other])
    assert set(target.temp_keywords) == OKOYE_GRANT
    # near miss: the other creature attacked the monarch too, but was not the one that got the counter
    assert not set(other.temp_keywords) & OKOYE_GRANT


def test_okoye_grants_nothing_when_the_defender_is_not_the_monarch():
    engine = game()
    engine.state.monarch_id = "p1"
    _, target, _ = _okoye_combat(engine)
    _declare_attack(engine, [target])
    assert not set(target.temp_keywords) & OKOYE_GRANT


def test_okoye_trigger_does_not_outlast_the_turn():
    engine = game()
    engine.state.monarch_id = "p2"
    _, target, _ = _okoye_combat(engine)
    engine.state.internal_turn.number += 1
    _declare_attack(engine, [target])
    assert not set(target.temp_keywords) & OKOYE_GRANT


def _barreling(engine):
    mine = filler(engine, "Runner", type_line="Creature", power=3, toughness=3)
    other = filler(engine, "Other", type_line="Creature", power=3, toughness=3)
    blockers = [filler(engine, f"Wall{i}", type_line="Creature", player="p2", power=0, toughness=4)
                for i in range(BLOCKER_COUNT)]
    cast(engine, card(engine, "Barreling Attack", zone=Zone.HAND), targets=[mine])
    return mine, other, blockers


def _block(engine, attackers, blockers_by_attacker):
    _declare_attack(engine, attackers)
    engine.state.current_step = "declare_blockers"
    engine.declare_blockers(engine.state.player_by_id("p2"), [
        {"blocker": b, "attacker": a} for a, bs in blockers_by_attacker.items() for b in bs])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def test_barreling_attack_pumps_the_chosen_creature_per_blocker():
    engine = game()
    mine, other, blockers = _barreling(engine)
    assert "trample" in {k.lower() for k in mine.granted_keywords}
    base = (mine.power, mine.toughness)
    _block(engine, [mine, other], {mine: blockers, other: []})
    assert (mine.power, mine.toughness) == (base[0] + BLOCKER_COUNT, base[1] + BLOCKER_COUNT)
    assert other.power == base[0]


def test_barreling_attack_ignores_a_different_blocked_creature():
    engine = game()
    mine, other, blockers = _barreling(engine)
    base = mine.power
    _block(engine, [mine, other], {mine: [], other: blockers})
    assert mine.power == base and other.power == base
