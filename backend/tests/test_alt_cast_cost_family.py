"""Tests for MEC-15 — RULE 118.9 "You may pay `<cost>` rather than pay this
spell's mana cost." (the "pitch"/Force-of-Will family: Force of Will,
Force of Negation, Force of Vigor, Daze).

All four were already hand-authored (`game/ability_catalogue.py`) at their
real printed mana cost, with the alternative cost itself dropped as a
documented "confirmed-unbuilt mechanism" — this batch builds it: a
structured `AbilitySpec.alt_cost` (mirrors `additional_cost`'s "fixed
template, not open cost text" shape), `GameObject.alt_cast_cost`/
`alt_cast_condition` (`game/effect_binder.py`), `GameEngine.can_cast`/
`cast_spell`'s new `alt_cost=True` branch (parallel to the existing
`free=True` RULE 601.2f path), and the real UI wiring that free-cast
casting itself never got: `_offer_cast`/`_cast_action`
(`game/engine/legal_actions_mixin.py`) now offer a free/alt-cost cast as
its own `cast_spell` action, and `GameSession._dispatch_cast_spell` round-
trips it.

Reference: mtg_analyzer/game/costs.py (`ActivationCost.
exile_hand_card_color`/`return_to_hand`), game/condition_query.py
(`free_cast_condition_holds`'s ``not_your_turn``/``your_turn``),
game/engine/casting_mixin.py, game/engine/legal_actions_mixin.py,
game/ability_catalogue.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import condition_query
from mtg_analyzer.game.costs import ActivationCost
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
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


def two_player_engine():
    filler = _card("Lightning Bolt")
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler] * 5), ("p2", "Bob", [filler] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def to_hand(eng, name, controller="p1"):
    obj = GameObject(_card(name), owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id(controller).hand.append(obj)
    return obj


def push_enemy_spell(eng, controller="p2"):
    """A bare spell on the stack, a legal counter target for the family."""
    from mtg_analyzer.models.game_state import StackItem

    obj = GameObject(_card("Lightning Bolt"), owner_id=controller, zone=Zone.STACK)
    item = StackItem(
        kind="spell", controller_id=controller, obj=obj, description=obj.name, effects=[],
    )
    eng.state.stack.append(item)
    return obj


# ---------------------------------------------------------------------------
# game/costs.py — the new ActivationCost fields
# ---------------------------------------------------------------------------


def test_exile_hand_card_color_is_not_free_and_labeled():
    cost = ActivationCost(exile_hand_card_color="U")
    assert cost.is_free is False
    assert "Exile a U card from your hand" in cost.label()


def test_return_to_hand_still_labeled_for_a_spell_alt_cost():
    cost = ActivationCost(return_to_hand="island")
    assert cost.is_free is False
    assert "Return a Island you control" in cost.label()


# ---------------------------------------------------------------------------
# game/condition_query.py — the shared not_your_turn/your_turn vocabulary
# ---------------------------------------------------------------------------


def test_not_your_turn_condition_holds_off_the_live_active_player():
    eng, p1, p2 = two_player_engine()
    obj = GameObject(_card("Lightning Bolt"), owner_id="p1", zone=Zone.HAND)
    eng.state.active_player_index = 0  # p1's own turn
    assert condition_query.free_cast_condition_holds(
        {"not_your_turn": True}, obj, eng.state
    ) is False
    eng.state.active_player_index = 1  # p2's turn — not p1's
    assert condition_query.free_cast_condition_holds(
        {"not_your_turn": True}, obj, eng.state
    ) is True


# ---------------------------------------------------------------------------
# Force of Will — pay 1 life + exile a blue card, unconditional
# ---------------------------------------------------------------------------


def test_force_of_will_alt_cost_unaffordable_by_mana_but_payable_by_alt_cost():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    to_hand(eng, "Brainstorm", "p1")  # the blue card to exile
    p1.life = 20
    assert eng.can_cast(p1, fow) is False  # no mana at all
    assert eng.can_cast(p1, fow, alt_cost=True) is True


def test_force_of_will_alt_cost_illegal_without_a_blue_card_in_hand():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    p1.life = 20
    assert eng.can_cast(p1, fow, alt_cost=True) is False


def test_force_of_will_alt_cost_illegal_at_zero_life():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    to_hand(eng, "Brainstorm", "p1")
    p1.life = 0
    assert eng.can_cast(p1, fow, alt_cost=True) is False


def test_force_of_will_alt_cost_pays_life_and_exiles_the_blue_card_then_counters():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    blue = to_hand(eng, "Brainstorm", "p1")
    p1.life = 20
    victim = push_enemy_spell(eng, "p2")
    eng.cast_spell(p1, fow, targets=[victim], alt_cost=True)
    assert p1.life == 19
    assert blue not in p1.hand
    assert blue in p1.exile
    assert fow not in p1.hand
    eng.resolve_until_stable()
    assert eng.state.stack == []  # both Force of Will and its target resolved off


# ---------------------------------------------------------------------------
# Force of Negation / Force of Vigor — the shared "if it's not your turn" gate
# ---------------------------------------------------------------------------


def test_force_of_negation_alt_cost_only_legal_off_your_own_turn():
    eng, p1, p2 = two_player_engine()
    negation = to_hand(eng, "Force of Negation", "p1")
    to_hand(eng, "Brainstorm", "p1")
    eng.state.active_player_index = 0  # p1's own turn
    assert eng.can_cast(p1, negation, alt_cost=True) is False
    eng.state.active_player_index = 1  # p2's turn
    assert eng.can_cast(p1, negation, alt_cost=True) is True


def test_force_of_vigor_alt_cost_exiles_a_green_card_not_a_blue_one():
    eng, p1, p2 = two_player_engine()
    vigor = to_hand(eng, "Force of Vigor", "p1")
    to_hand(eng, "Brainstorm", "p1")  # blue, doesn't qualify
    eng.state.active_player_index = 1  # off p1's own turn
    assert eng.can_cast(p1, vigor, alt_cost=True) is False
    green = to_hand(eng, "Llanowar Elves", "p1")  # green, qualifies
    assert eng.can_cast(p1, vigor, alt_cost=True) is True
    eng.cast_spell(p1, vigor, alt_cost=True)
    assert green in p1.exile


# ---------------------------------------------------------------------------
# Daze — return an Island you control, unconditional
# ---------------------------------------------------------------------------


def test_daze_alt_cost_needs_an_island_you_control():
    eng, p1, p2 = two_player_engine()
    daze = to_hand(eng, "Daze", "p1")
    assert eng.can_cast(p1, daze, alt_cost=True) is False
    battlefield(eng, "Island", "p1")
    assert eng.can_cast(p1, daze, alt_cost=True) is True


def test_daze_alt_cost_bounces_the_island_and_counters_unless_paid():
    eng, p1, p2 = two_player_engine()
    daze = to_hand(eng, "Daze", "p1")
    island = battlefield(eng, "Island", "p1")
    victim = push_enemy_spell(eng, "p2")
    eng.cast_spell(p1, daze, targets=[victim], alt_cost=True)
    assert island not in eng.state.battlefield
    assert island in p1.hand


# ---------------------------------------------------------------------------
# legal_actions / _offer_cast — the real UI wiring gap this batch closes
# ---------------------------------------------------------------------------


def test_legal_actions_offers_only_alt_cost_with_no_mana_in_the_pool():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    to_hand(eng, "Brainstorm", "p1")
    p1.life = 20
    push_enemy_spell(eng, "p2")
    offers = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "cast_spell" and a.get("instance_id") == fow.instance_id
    ]
    assert len(offers) == 1
    assert offers[0].get("alt_cost") is True
    assert "alt_cost_label" in offers[0]


def test_legal_actions_offers_both_plain_and_alt_cost_when_both_are_payable():
    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    to_hand(eng, "Brainstorm", "p1")
    p1.life = 20
    p1.mana_pool.add("U", 5)
    push_enemy_spell(eng, "p2")
    offers = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "cast_spell" and a.get("instance_id") == fow.instance_id
    ]
    assert len(offers) == 2
    assert {bool(o.get("alt_cost")) for o in offers} == {True, False}


# ---------------------------------------------------------------------------
# MEC-12 ninth pass (2026-08-11) — the same alt_cost shape, now reachable
# from oracle text directly (`segmenter._ALT_COST_EXILE_HAND_COLOR_RE`)
# instead of one-at-a-time hand-authoring: Snapback (blue), Pyrokinesis
# (red), Unmask (black).
# ---------------------------------------------------------------------------


def test_snapback_pyrokinesis_unmask_are_parser_modeled_not_hand_authored():
    from mtg_analyzer.game.ability_catalogue import is_registered

    for name in ("Snapback", "Pyrokinesis", "Unmask"):
        assert not is_registered(name), name  # reached generically, not one-off
        assert parse_oracle(_card(name)).modeled, name


def test_snapback_alt_cost_needs_a_blue_card_in_hand():
    eng, p1, p2 = two_player_engine()
    snapback = to_hand(eng, "Snapback", "p1")
    assert eng.can_cast(p1, snapback, alt_cost=True) is False
    to_hand(eng, "Brainstorm", "p1")  # blue, qualifies
    assert eng.can_cast(p1, snapback, alt_cost=True) is True


def test_pyrokinesis_alt_cost_needs_a_red_card_not_a_blue_one():
    eng, p1, p2 = two_player_engine()
    pyro = to_hand(eng, "Pyrokinesis", "p1")
    to_hand(eng, "Brainstorm", "p1")  # blue, doesn't qualify
    assert eng.can_cast(p1, pyro, alt_cost=True) is False
    to_hand(eng, "Lightning Bolt", "p1")  # red, qualifies
    assert eng.can_cast(p1, pyro, alt_cost=True) is True


def test_unmask_alt_cost_needs_a_black_card_in_hand():
    eng, p1, p2 = two_player_engine()
    eng.state.current_step = "main1"  # Unmask is a sorcery — needs sorcery-speed timing
    unmask = to_hand(eng, "Unmask", "p1")
    assert eng.can_cast(p1, unmask, alt_cost=True) is False
    to_hand(eng, "Dark Confidant", "p1")  # black, qualifies
    assert eng.can_cast(p1, unmask, alt_cost=True) is True


def test_dispatch_cast_spell_rountrips_the_alt_cost_flag():
    from mtg_analyzer.services.game_session import GameSession

    eng, p1, p2 = two_player_engine()
    fow = to_hand(eng, "Force of Will", "p1")
    blue = to_hand(eng, "Brainstorm", "p1")
    p1.life = 20
    victim = push_enemy_spell(eng, "p2")
    session = GameSession.__new__(GameSession)
    session.engine = eng
    session._dispatch_cast_spell(
        {
            "type": "cast_spell", "instance_id": fow.instance_id, "alt_cost": True,
            "targets": [{"instance_id": victim.instance_id}],
        },
        p1,
    )
    assert p1.life == 19
    assert blue in p1.exile
