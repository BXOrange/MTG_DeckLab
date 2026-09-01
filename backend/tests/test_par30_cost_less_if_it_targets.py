"""PAR-30-adjacent — "This spell costs {N} less to cast if it targets a
`<criteria>`." (RULE 601.2f — Ajani's Response / Knockout Blow / Depower
cycle).

`cost_reduction` gained a `reduce_if_targets` param (a criteria dict);
`continuous.self_cost_reduction_for` takes the caster's chosen targets and
applies the discount only when one matches (`_obj_matches_target_criteria`
→ `combat.matches_object_filter`, which grew a `tapped` key).
`_adjust_cost` / `effective_cast_cost` thread `targets` through.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs as match_static_line
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


# --- parse -------------------------------------------------------------------


def test_targets_tapped_creature_parses_to_reduce_if_targets():
    specs = match_static_line("this spell costs {2} less to cast if it targets a tapped creature")
    assert specs == [__import__("mtg_analyzer.parser.oracle.spec", fromlist=["EffectSpec"]).EffectSpec(
        "cost_reduction",
        {"affects": "self", "generic": 2, "reduce_if_targets": {"card_type": "creature", "tapped": True}},
    )]


def test_targets_red_creature_parses_to_colour_criteria():
    specs = match_static_line("this spell costs {2} less to cast if it targets a red creature")
    assert specs[0].params["reduce_if_targets"] == {"card_type": "creature", "color": "R"}


def test_targets_attacking_creature_parses():
    specs = match_static_line("this spell costs {1} less to cast if it targets an attacking creature")
    assert specs[0].params["reduce_if_targets"] == {"card_type": "creature", "attacking": True}


def test_unrecognised_target_shape_falls_through_to_board_condition():
    # "a creature card with mana value 3 or less" isn't a permanent criteria
    # this vocabulary knows → the board-condition path takes over and (also
    # not recognising it) fails closed.
    specs = match_static_line(
        "this spell costs {3} less to cast if it targets a creature card with mana value 3 or less"
    )
    assert specs is None


def test_ajanis_response_modeled():
    c = Card(id="ar", name="Ajani's Response", type_line="Instant", is_instant=True,
             oracle_text=("This spell costs {3} less to cast if it targets a "
                          "tapped creature.\nDestroy target creature."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute ---------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _spell_in_hand(state):
    card = Card(id="ar", name="Ajani's Response", type_line="Instant", is_instant=True,
                mana_cost_string="{3}{W}", oracle_text=(
                    "This spell costs {2} less to cast if it targets a tapped "
                    "creature.\nDestroy target creature."))
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    state.player_by_id("p1").hand.append(obj)
    return obj


def _creature(state, name, tapped, pid="p2"):
    o = GameObject(Card(id=name, name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    o.tapped = tapped
    state.add_to_battlefield(o)
    return o


def test_discount_applies_only_when_a_tapped_creature_is_targeted():
    eng, state = _engine()
    spell = _spell_in_hand(state)
    tapped = _creature(state, "Tapped Bear", tapped=True)
    untapped = _creature(state, "Untapped Bear", tapped=False)

    no_targets = eng.effective_cast_cost(state.player_by_id("p1"), spell)
    hit = eng.effective_cast_cost(state.player_by_id("p1"), spell, targets=[tapped])
    miss = eng.effective_cast_cost(state.player_by_id("p1"), spell, targets=[untapped])

    # {3}{W} = mana value 4
    assert no_targets.converted_mana_cost == 2   # offer-time: best case (discount assumed)
    assert hit.converted_mana_cost == 2          # {1}{W} — {2} off, target is tapped
    assert miss.converted_mana_cost == 4         # full price, target isn't tapped


def test_self_cost_reduction_for_reads_the_targets_directly():
    eng, state = _engine()
    spell = _spell_in_hand(state)
    tapped = _creature(state, "Tapped Bear", tapped=True)
    untapped = _creature(state, "Untapped Bear", tapped=False)

    hit, _ = continuous.self_cost_reduction_for(spell, state, caster_id="p1", targets=[tapped])
    miss, _ = continuous.self_cost_reduction_for(spell, state, caster_id="p1", targets=[untapped])
    probe, _ = continuous.self_cost_reduction_for(spell, state, caster_id="p1")

    assert hit == 2
    assert miss == 0
    assert probe == 2  # targets=None → best case
