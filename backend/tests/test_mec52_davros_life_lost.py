"""MEC-52 — `GameState.life_lost_this_turn` and Davros, Dalek Creator.

The mirror of `life_gained_this_turn`: bumped at `RulesEngine.lose_life`'s
single choke point (damage, life-paid costs, "loses N life" all funnel
through it), reset for *every* player each `GameEngine.begin_turn`.

Feeds two new hooks:
- `ConditionalEffect`'s `opponent_lost_life_this_turn_at_least` key ("…create
  a token … if an opponent lost 3 or more life this turn");
- `FaceVillainousChoiceEffect.subject_min_life_lost` ("each opponent **who
  lost 3 or more life this turn** faces a villainous choice — …").
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine(players=3):
    seats = [(f"p{i+1}", chr(65 + i), []) for i in range(players)]
    eng = GameEngine.new_game(seats, starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    for p in eng.state.players:  # a few cards to draw / discard
        for i in range(5):
            p.library.append(GameObject(
                Card(id=f"{p.id}L{i}", name="Filler", type_line="Land — Plains"),
                owner_id=p.id, zone=Zone.LIBRARY,
            ))
    return eng, eng.state


def _davros_card() -> Card:
    return Card(
        id="Davros", name="Davros, Dalek Creator",
        type_line="Legendary Artifact Creature — Alien Scientist",
        is_creature=True, is_legendary=True, power=3, toughness=3,
        mana_cost_string="{1}{U}{B}{R}", converted_mana_cost=4, keywords=["Menace"],
        oracle_text=(
            "Menace\n"
            "At the beginning of your end step, create a 3/3 black Dalek "
            "artifact creature token with menace if an opponent lost 3 or "
            "more life this turn. Then each opponent who lost 3 or more life "
            "this turn faces a villainous choice — You draw a card, or that "
            "player discards a card."
        ),
    )


def _src(st, pid="p1"):
    o = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


# --- GameState.life_lost_this_turn -------------------------------------


def test_lose_life_and_damage_both_bump_the_counter():
    eng, st = _engine(2)
    p2 = st.player_by_id("p2")
    eng.rules.lose_life(p2, 2)
    assert st.life_lost_this_turn["p2"] == 2
    eng.rules.deal_damage_to_player(p2, 3) if hasattr(eng.rules, "deal_damage_to_player") \
        else eng.rules.lose_life(p2, 3, cause="damage")
    assert st.life_lost_this_turn["p2"] == 5
    assert st.life_lost_this_turn["p1"] == 0


def test_begin_turn_resets_every_players_counter():
    eng, st = _engine(2)
    eng.rules.lose_life(st.player_by_id("p2"), 4)
    assert st.life_lost_this_turn["p2"] == 4
    eng.begin_turn()  # p2's turn now
    assert st.life_lost_this_turn["p2"] == 0
    assert st.life_lost_this_turn["p1"] == 0


# --- parser -----------------------------------------------------------


def test_davros_is_modeled_with_condition_and_subject_filter():
    res = parse_oracle(_davros_card())
    assert res.modeled, res.unclaimed
    trig = next(s for s in res.specs if s.ability_kind == "triggered")
    ct, villain = trig.effects
    assert ct.type == "create_token"
    assert ct.condition == {"opponent_lost_life_this_turn_at_least": 3}
    assert villain.type == "face_villainous_choice"
    assert villain.params["subject"] == "each_opponent"
    assert villain.params["subject_min_life_lost"] == 3
    assert villain.params["option_a"] == [{"type": "draw", "params": {"count": 1}}]
    assert villain.params["option_b"][0]["type"] == "discard"


def test_suffix_condition_does_not_leak_onto_a_later_then_clause():
    # "create X if an opponent lost N life this turn. then <Y>." — only the
    # first clause is gated; a bare `<Y>` must not inherit the condition.
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
    specs = parse_effect_body(
        "create a 1/1 white soldier creature token if an opponent lost 3 or "
        "more life this turn. then draw a card."
    )
    by_type = {s.type: s for s in specs}
    assert by_type["create_token"].condition == {"opponent_lost_life_this_turn_at_least": 3}
    assert by_type["draw"].condition is None


# --- execute: the condition gate ------------------------------------


def test_conditional_token_only_when_an_opponent_is_past_the_threshold():
    eng, st = _engine(2)
    src = _src(st, "p1")
    specs = [EffectSpec("create_token", {
        "power": 2, "toughness": 2, "subtypes": ["Zombie"], "colors": ["B"],
    })]
    specs[0] = EffectSpec(specs[0].type, specs[0].params,
                          condition={"opponent_lost_life_this_turn_at_least": 3})

    # nobody has lost life → no token
    effects = build_effects([EffectSpec(s.type, dict(s.params), s.condition) for s in specs], src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)
    assert not [o for o in st.battlefield if o.is_token]

    # opponent loses 3 → token now enters
    eng.rules.lose_life(st.player_by_id("p2"), 3)
    effects = build_effects([EffectSpec(s.type, dict(s.params), s.condition) for s in specs], src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)
    assert len([o for o in st.battlefield if o.is_token]) == 1


# --- execute: the filtered villainous sweep -------------------------


def test_villainous_sweep_skips_opponents_who_did_not_lose_enough_life():
    eng, st = _engine(3)
    src = _src(st, "p1")
    st.life_lost_this_turn["p2"] = 4   # past the threshold
    st.life_lost_this_turn["p3"] = 1   # not

    effects = build_effects([EffectSpec("face_villainous_choice", {
        "subject": "each_opponent",
        "subject_min_life_lost": 3,
        "option_a": [{"type": "draw", "params": {"count": 1}}],
        "option_b": [{"type": "discard", "params": {"count": 1, "target_kind": "player"}}],
    })], src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)

    # only p2 is asked
    assert st.pending_choice is not None
    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("0")   # p2 picks A → the controller (p1) draws
    eng.resolve_until_stable()
    assert st.pending_choice is None   # p3 was never asked
    assert len(st.player_by_id("p1").hand) == 1


def test_villainous_sweep_is_empty_when_no_opponent_qualifies():
    eng, st = _engine(2)
    src = _src(st, "p1")
    # p2 lost only 2
    st.life_lost_this_turn["p2"] = 2
    effects = build_effects([EffectSpec("face_villainous_choice", {
        "subject": "each_opponent", "subject_min_life_lost": 3,
        "option_a": [{"type": "draw", "params": {"count": 1}}],
        "option_b": [{"type": "discard", "params": {"count": 1, "target_kind": "player"}}],
    })], src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)
    assert st.pending_choice is None


# --- end-to-end -----------------------------------------------------


def test_davros_end_step_trigger_end_to_end():
    eng, st = _engine(2)
    src = GameObject(_davros_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    eng.rules.lose_life(st.player_by_id("p2"), 5)   # p2 is well past 3

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    effects = build_effects(
        [EffectSpec(e.type, dict(e.params), e.condition) for e in trig.effects], src
    )
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)
    eng.recompute_continuous_effects()

    assert len([o for o in st.battlefield if o.is_token]) == 1, "the Dalek token entered"
    assert st.pending_choice is not None and st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("1")   # p2 picks "that player discards a card"
    eng.resolve_until_stable()
    assert st.pending_choice is None
