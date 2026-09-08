"""PAR-30 — colour-list target on a graveyard-card exile + "it gains <kw>
until your next turn" on a previous-clause subject.

Two adjacent grammar points that together close Offspring's Revenge (and,
as a bycatch, Bond of Revival):

* `_EXILE_FROM_GRAVEYARD_RE` gained an optional `(?P<colors>…)` group →
  `exile` spec's `colors` → `TargetSpec.colors`, now also honoured in
  `targeting.legal_targets`' graveyard-card branch (`_color_ok`, the call
  every battlefield branch already had). `_color_word_list` is the
  N-colour generalization of `_two_color_letters`.
* `grant_until_previous` — "It gains haste until your next turn." with the
  "it" bound to whatever the preceding clause created/targeted
  (`previous_subject: True`, `EffectHandler.previous_subject_only`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
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


def _gy_creature(state, name, colors, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors)),
                   owner_id=pid, zone=Zone.GRAVEYARD)
    state.player_by_id(pid).graveyard.append(o)
    return o


# --- parse: colour-list graveyard exile --------------------------------------


def test_three_colour_graveyard_exile_parses():
    assert match_clause(
        "exile target red, white, or black creature card from your graveyard"
    ) == [EffectSpec("exile", {"target_kind": "graveyard_creature",
                              "colors": ["R", "W", "B"]})]


def test_two_colour_graveyard_exile_parses():
    assert match_clause(
        "exile target white or blue card from your graveyard"
    ) == [EffectSpec("exile", {"target_kind": "graveyard_card",
                              "colors": ["W", "U"]})]


def test_plain_graveyard_exile_still_has_no_colour_key():
    assert match_clause(
        "exile target creature card from your graveyard"
    ) == [EffectSpec("exile", {"target_kind": "graveyard_creature"})]


def test_repeated_colour_fails_closed():
    assert match_clause(
        "exile target red, red, or black creature card from your graveyard"
    ) is None


# --- parse: grant_until_previous -------------------------------------------------


def test_it_gains_haste_until_your_next_turn_parses():
    assert match_clause(
        "it gains haste until your next turn", previous_subject=True
    ) == [
        EffectSpec("grant_until", {
            "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
            "duration": "your_next_turn",
            "previous_subject": True,
            "target_kind": None,
        })
    ]


def test_it_gains_haste_until_end_of_combat_parses():
    assert match_clause(
        "then it gains trample until end of combat", previous_subject=True
    ) == [
        EffectSpec("grant_until", {
            "static": {"type": "grant_keyword", "params": {"keywords": ["trample"]}},
            "duration": "end_of_combat",
            "previous_subject": True,
            "target_kind": None,
        })
    ]


def test_a_bare_it_still_claims_nothing_without_the_previous_subject_reading():
    assert match_clause("it gains haste until your next turn") is None


def test_it_gains_nonsense_fails_closed():
    assert match_clause(
        "it gains wobbliness until your next turn", previous_subject=True
    ) is None


# --- end-to-end: real cards --------------------------------------------------


def test_offsprings_revenge_modeled():
    c = Card(
        id="ofr", name="Offspring's Revenge",
        type_line="Enchantment", oracle_text=(
            "At the beginning of combat on your turn, exile target red, white, "
            "or black creature card from your graveyard. Create a token that's "
            "a copy of that card, except it's 1/1. It gains haste until your "
            "next turn."
        ),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


def test_bond_of_revival_modeled():
    c = Card(
        id="bor", name="Bond of Revival", type_line="Sorcery", is_sorcery=True,
        oracle_text=(
            "Return target creature card from your graveyard to the "
            "battlefield. It gains haste until your next turn."
        ),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute: colour narrowing on the graveyard branch ------------------------


def test_graveyard_exile_only_offers_a_matching_colour():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    red = _gy_creature(state, "Red Ghoul", {"R"})
    black = _gy_creature(state, "Black Ghoul", {"B"})
    green = _gy_creature(state, "Green Ghoul", {"G"})
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("exile", {
        "target_kind": "graveyard_creature", "colors": ["R", "W", "B"],
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert {red.instance_id, black.instance_id} <= offered
    assert green.instance_id not in offered


# --- execute: grant_until_previous actually grants haste ----------------------


def test_grant_until_previous_gives_the_prior_subject_haste():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    token = GameObject(Card(id="tk", name="Copy", type_line="Creature — Bear",
                            is_creature=True, power=1, toughness=1),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    token.controller_id = "p1"
    state.add_to_battlefield(token)

    ctx = GameContext(state, eng.rules)
    ctx.previous_targets = [token]
    build_effects([EffectSpec("grant_until", {
        "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
        "duration": "your_next_turn",
        "previous_subject": True,
        "target_kind": None,
    })], src)[0].apply(ctx, None)
    eng.recompute_continuous_effects()

    assert "haste" in token.granted_keywords
