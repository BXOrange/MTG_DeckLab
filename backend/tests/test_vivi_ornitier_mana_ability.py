"""Vivi Ornitier's mana ability (bug report, 2026-09-04): "{0}: Add X mana
in any combination of {U} and/or {R}, where X is Vivi Ornitier's power.
Activate only during your turn and only once each turn." — three
pre-existing gaps in `game/mana_abilities.py`/`GameEngine.tap_for_mana`:

1. "any combination of `<printed symbols>`" (a *restricted* colour subset)
   wasn't recognised at all — only the generic "any combination of
   colours" (every WUBRG colour) was, so this fell through to a fixed,
   unscaled ``{U: 1, R: 1}`` option ignoring both the colour restriction
   and the power-based ``X``.
2. "Activate only during your turn and only once each turn." (RULE
   602.5d), printed as a trailing sentence rather than part of the
   ``<cost>:`` prefix, was never parsed or enforced for a mana ability at
   all (`ActivationCost.once_per_turn` is new; `only_during_your_turn`
   already existed for the stack-based activated-ability path but was
   never checked from `tap_for_mana`'s no-stack one).
3. The colour-split UI (`gameBoardView.js`'s `colorSplitHtml`) offered all
   five WUBRG colours regardless of what the ability actually restricted
   to — now derived from `ability.options` (already colour-restricted)
   instead of a hardcoded list; not exercised here (backend-only test
   file), see the frontend fix itself.

Also covers the parser grammar this needed generally (not Vivi-specific):
a restricted symbol subset with 2 or 3 printed colours, and a "where X is
<name>'s power"/"the number of <subject> you control" subject on a
combination ability — verified against the real cache's storage-land/
tri-land/sac-cost/planeswalker family sharing the same "any combination of
`{X}` and/or `{Y}`" template (`test_mana_combination.py` covers the
pre-existing "any combination of colours" shape this builds on).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities


def _vivi_card(**kw):
    return Card(
        id="Vivi Ornitier", name="Vivi Ornitier", type_line="Legendary Creature — Wizard",
        is_creature=True, power=0, toughness=3, color_identity=["R", "U"],
        oracle_text=(
            "{0}: Add X mana in any combination of {U} and/or {R}, where X is Vivi "
            "Ornitier's power. Activate only during your turn and only once each turn.\n"
            "Whenever you cast a noncreature spell, put a +1/+1 counter on Vivi "
            "Ornitier and it deals 1 damage to each opponent."
        ),
        **kw,
    )


def _engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0,
    )


def _battlefield_vivi(state, controller="p1", power_counters=0):
    obj = GameObject(_vivi_card(), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if power_counters:
        obj.counters["+1/+1"] = power_counters
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_to_a_restricted_two_color_combination_ability():
    [ability] = parse_mana_abilities(_vivi_card())
    assert ability.any_combination is True
    assert ability.options == [{"U": 1}, {"R": 1}]  # restricted, not full WUBRG
    assert ability.amount_selector == {"kind": "power_of_self"}
    assert ability.cost.only_during_your_turn is True
    assert ability.cost.once_per_turn is True


def test_resolved_options_scale_by_the_permanents_own_power():
    state_free_obj = GameObject(_vivi_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    state_free_obj.counters["+1/+1"] = 3  # printed power 0 + 3 counters = 3
    [ability] = mana_abilities_for(state_free_obj)
    assert ability.options == [{"U": 3}, {"R": 3}]


def test_zero_power_produces_nothing():
    obj = GameObject(_vivi_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    [ability] = mana_abilities_for(obj)
    assert ability.options == [{"U": 0}, {"R": 0}]


# ---------------------------------------------------------------------------
# GameEngine.tap_for_mana — colour restriction + timing
# ---------------------------------------------------------------------------


def test_color_split_outside_the_printed_pair_is_rejected():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    p1 = eng.state.active_player
    assert p1.id == "p1"
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=2)

    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, vivi, color_split={"U": 1, "W": 1})  # W isn't printed


def test_color_split_within_the_printed_pair_is_accepted():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    p1 = eng.state.active_player
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=2)

    produced = eng.tap_for_mana(p1, vivi, color_split={"U": 1, "R": 1})
    assert produced == {"U": 1, "R": 1}
    assert p1.mana_pool.total() == 2


def test_second_activation_the_same_turn_is_rejected():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    p1 = eng.state.active_player
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=1)

    eng.tap_for_mana(p1, vivi, color_split={"U": 1})
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, vivi, color_split={"R": 1})


def test_activation_is_available_again_next_turn():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    p1 = eng.state.active_player
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=1)
    eng.tap_for_mana(p1, vivi, color_split={"U": 1})

    eng.begin_turn()  # p2's turn
    eng.begin_turn()  # back to p1's own next turn
    assert eng.state.active_player.id == "p1"
    eng._step_untap()  # RULE 502.1 — resets `mana_abilities_activated_this_turn`
    produced = eng.tap_for_mana(p1, vivi, color_split={"R": 1})
    assert produced == {"R": 1}


def test_cannot_activate_on_an_opponents_turn():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    if eng.state.active_player.id != "p2":
        eng.begin_turn()
    assert eng.state.active_player.id == "p2"
    p1 = eng.state.player_by_id("p1")
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=1)

    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, vivi, color_split={"U": 1})


def test_legal_actions_stops_offering_it_once_used_this_turn():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    vivi = _battlefield_vivi(eng.state, controller="p1", power_counters=1)

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "tap_for_mana"]
    assert len(offered) == 1
    assert offered[0]["any_combination"] is True

    eng.tap_for_mana(p1, vivi, color_split={"U": 1})
    offered_after = [a for a in eng.legal_actions(p1) if a.get("type") == "tap_for_mana"]
    assert offered_after == []


def test_legal_actions_does_not_offer_it_on_an_opponents_turn():
    eng = _engine("p1", "p2")
    eng.begin_turn()
    if eng.state.active_player.id != "p2":
        eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.player_by_id("p1")
    _battlefield_vivi(eng.state, controller="p1", power_counters=1)

    offered = [a for a in eng.legal_actions(p1) if a.get("type") == "tap_for_mana"]
    assert offered == []
