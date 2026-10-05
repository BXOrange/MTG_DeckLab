"""PAR-29 — RULE 701.68 Blight, the *cost* forms (Bloomburrow).

The standalone-verb effect ("whenever ~ attacks, blight 1") shipped at
PARSER_VERSION 111 (`effects.BlightEffect` / `RulesEngine.blight`). This
batch adds Blight as a *cost*:

* `ActivationCost.blight` — an activated-ability cost (`{T}, Blight 1:`),
  an additional cast cost (`blight N or pay {M}`), and a `pay_cost_then`
  half (`you may blight N. If you do/don't, <effect>`).
* `RulesEngine.blight(..., interactive=False)` — the synchronous,
  auto-pick (highest toughness) form payment needs.
* `_PAY_COST_THEN_OR_ELSE_RE` — "you may <cost>. If you don't, <effect>."
  into `PayCostThenEffect.else_effects` (Chaos Spewer, Gutsplitter Gang).

Also fixes a latent bug: the cost parser silently dropped "Blight N" from
a cost string, so `{cost}, Blight N:` abilities (Sting-Slinger) charged no
blight at all.

Reference: game/costs.py (`_BLIGHT_RE`, `blight` field), game/rules/
mana_counters_mixin.py (`blight` / `blight_possible`), game/engine/
{activation,casting}_mixin.py, parser/oracle/segmenter.py
(`_ADDITIONAL_COST_BLIGHT_RE`), parser/oracle/catalogue/handlers.py
(`_MAY_COST_THEN_CLAUSE`, `_pay_cost_then_or_else`).
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _additional_cost_dict


# --- parse -----------------------------------------------------------------


def test_blight_additional_cost_dict_forms():
    assert _additional_cost_dict("blight 2 or pay {1}") == {"blight": 2}
    assert _additional_cost_dict("blight 1") == {"blight": 1}
    assert _additional_cost_dict("blight 2 or pay {2}{b}") == {"blight": 2}
    assert _additional_cost_dict("blight two") is None
    assert _additional_cost_dict("blight 2, then draw a card") is None


def test_blight_cost_string_parses_and_roundtrips():
    cost = parse_activation_cost({"text": "{1}{r}, {t}, blight 1"})
    assert cost.blight == 1 and cost.taps_self and cost.mana.raw == "{1}{r}"
    assert cost.is_free is False
    assert "Blight 1" in cost.label()
    assert parse_activation_cost(cost.to_dict()).blight == 1
    assert parse_activation_cost({"blight": 3}).blight == 3


def test_blight_pay_cost_then_clause_forms():
    do = match_clause("you may blight 1. if you do, each opponent discards a card")
    assert do and do[0].type == "pay_cost_then"
    assert do[0].params["cost"] == "blight 1"
    assert do[0].params["effects"] and not do[0].params.get("else_effects")

    dont = match_clause("you may pay {2}. if you don't, blight 2")
    assert dont and dont[0].type == "pay_cost_then"
    assert dont[0].params["cost"] == "pay {2}"
    assert dont[0].params["else_effects"] == [{"type": "blight", "params": {"amount": 2}}]
    assert dont[0].params["effects"] == []


def test_real_blight_cost_cards_modeled():
    for name, type_line, kw, text in [
        ("Wild Unraveling", "Instant", {},
         "As an additional cost to cast this spell, blight 2 or pay {1}.\n"
         "Counter target spell."),
        ("Chaos Spewer", "Creature — Beast", dict(is_creature=True),
         "When this creature enters, you may pay {2}. If you don't, blight 2."),
        ("Gutsplitter Gang", "Creature — Goblin", dict(is_creature=True),
         "At the beginning of your first main phase, you may blight 2. "
         "If you don't, you lose 3 life."),
    ]:
        c = Card(id=name[:3], name=name, type_line=type_line,
                 is_instant=(type_line == "Instant"),
                 mana_cost_string="{1}{U}", oracle_text=text, **kw)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, pid, name, power, toughness):
    c = Card(id=name, name=name, type_line="Creature — Bear",
             is_creature=True, power=power, toughness=toughness)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_blight_non_interactive_picks_highest_toughness():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    frail = _creature(state, "p1", "Frail", 1, 1)
    tough = _creature(state, "p1", "Tough", 1, 5)
    eng.recompute_continuous_effects()

    eng.rules.blight(p1, 2, interactive=False)
    assert state.pending_choice is None  # never prompts
    eng.recompute_continuous_effects()
    assert tough.counters.get("-1/-1") == 2
    assert frail.counters.get("-1/-1", 0) == 0


def test_blight_possible_gate():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    assert eng.rules.blight_possible(p1) is False
    _creature(state, "p1", "C", 2, 2)
    assert eng.rules.blight_possible(p1) is True


def test_blight_as_additional_cast_cost_non_blocking():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    spell = GameObject(
        Card(id="wu", name="Wild Unraveling", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.STACK,
    )
    spell.additional_cast_cost = parse_activation_cost({"blight": 1})

    # no creature -> still payable, just no counters placed
    assert eng._can_pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)
    eng._pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)

    # one creature -> the -1/-1 counter lands, non-interactively
    c = _creature(state, "p1", "C", 3, 3)
    eng._pay_additional_cast_cost(p1, spell, spell.additional_cast_cost, x=0)
    eng.recompute_continuous_effects()
    assert c.counters.get("-1/-1") == 1


def test_blight_player_cost_gate_and_payment():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    cost = parse_activation_cost({"blight": 2})
    assert eng.rules._can_pay_player_cost(p1, cost) is False  # no creature
    big = _creature(state, "p1", "Big", 4, 6)
    _creature(state, "p1", "Small", 1, 2)
    eng.recompute_continuous_effects()
    assert eng.rules._can_pay_player_cost(p1, cost) is True
    eng.rules._pay_player_cost(p1, cost)
    eng.recompute_continuous_effects()
    assert big.counters.get("-1/-1") == 2  # highest-toughness auto-pick
