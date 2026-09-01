"""PAR-30 — "return it to the battlefield [tapped] under its owner's/your
control[ with a +1/+1 counter on it]" (RULE 400.7 self-recursion).

New `_RETURN_SELF_TO_BATTLEFIELD_RE` handler reaches the pre-existing
`ReturnSelfToBattlefieldEffect` (which gained `under_your_control` and
`extra_counters`) from two real shapes: a DIES-trigger continuation
granted via `_quoted_ability_grant_effects` (Feign Death / Undying Malice
— "target creature gains 'when ~ dies, return it to the battlefield
tapped under its owner's control with a +1/+1 counter on it.'"), and a
plain "exile ~, then return it to the battlefield under its owner's
control" blink chain (Flicker of Fate / Aethergeode Miner).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse -------------------------------------------------------------------


def test_bare_form_parses():
    assert match_clause("return it to the battlefield under its owner's control") == [
        EffectSpec("return_self_to_battlefield", {"tapped": False})
    ]


def test_tapped_form_parses():
    assert match_clause("return it to the battlefield tapped under its owner's control") == [
        EffectSpec("return_self_to_battlefield", {"tapped": True})
    ]


def test_your_control_form_parses():
    assert match_clause("return ~ to the battlefield under your control") == [
        EffectSpec("return_self_to_battlefield", {"tapped": False, "under_your_control": True})
    ]


def test_counter_tail_parses():
    assert match_clause(
        "return it to the battlefield tapped under its owner's control with a +1/+1 counter on it"
    ) == [EffectSpec("return_self_to_battlefield",
                     {"tapped": True, "extra_counters": {"kind": "+1/+1", "count": 1}})]


def test_mismatched_counter_kind_fails_closed():
    assert match_clause(
        "return it to the battlefield under its owner's control with a +1/+2 counter on it"
    ) is None


def test_feign_death_modeled():
    c = Card(id="fd", name="Feign Death", type_line="Instant", is_instant=True,
             keywords=[], oracle_text=(
                 "Until end of turn, target creature gains \"When this creature "
                 "dies, return it to the battlefield tapped under its owner's "
                 "control with a +1/+1 counter on it.\""))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_flicker_of_fate_modeled():
    c = Card(id="fof", name="Flicker of Fate", type_line="Instant", is_instant=True,
             oracle_text=("Exile target creature or enchantment, then return it "
                          "to the battlefield under its owner's control."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -----------------------------------------------------------------


def test_exile_then_return_self_blinks_the_permanent():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Flicker of Fate", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    target = GameObject(Card(id="t", name="Bear", type_line="Creature — Bear",
                             is_creature=True, power=2, toughness=2),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    target.controller_id = "p1"
    state.add_to_battlefield(target)

    effects = build_effects(
        [EffectSpec("exile", {"target_kind": None}), EffectSpec("return_self_to_battlefield", {"tapped": False})],
        target,
    )
    ctx = GameContext(state, eng.rules)
    for eff in effects:
        eff.apply(ctx, [target])

    assert target in state.battlefield
    assert target not in state.player_by_id("p1").exile


def test_granted_dies_trigger_returns_tapped_with_a_counter():
    eng, state = _engine()
    bear = GameObject(Card(id="b", name="Bear", type_line="Creature — Bear",
                           is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.controller_id = "p1"
    bind_from_catalogue(bear)
    state.add_to_battlefield(bear)

    build_effects([EffectSpec("grant_until", {
        "static": {"type": "grant_triggered_ability", "params": {
            "trigger_event": "DIES",
            "grant_effects": [{"type": "return_self_to_battlefield",
                               "params": {"tapped": True,
                                          "extra_counters": {"kind": "+1/+1", "count": 1}}}],
        }},
        "duration": "end_of_turn",
        "target_kind": "creature",
    })], bear)[0].apply(GameContext(state, eng.rules), [bear])
    eng.recompute_continuous_effects()

    eng.rules.destroy(bear)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()

    assert bear in state.battlefield
    assert bear.tapped is True
    assert bear.counters.get("+1/+1", 0) == 1
