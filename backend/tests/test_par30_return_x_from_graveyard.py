"""PAR-30 (reanimator-token residue) — "return [up to] X target creature
cards from your graveyard to your hand / the battlefield".

The target count is the spell's own announced {X} (`GameObject.x_paid`),
read at target-gathering time via `TargetSpec.count_selector=
"source_x_paid"` — the same idiom March of Swirling Mist / Change of Plans
use. `ReturnFromGraveyardEffect` gained a `count_selector` param + a
matching multi-target apply branch. Death Denied, Entreat the Dead, Wake
the Dead, Shattered Crypt.
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


def _gy_creature(state, name, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Zombie",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.GRAVEYARD)
    state.player_by_id(pid).graveyard.append(o)
    return o


# --- parse -------------------------------------------------------------------


def test_return_x_to_hand_parses():
    assert match_clause(
        "return x target creature cards from your graveyard to your hand"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand",
        "count_selector": "source_x_paid", "optional": True,
    })]


def test_return_up_to_x_to_battlefield_parses():
    assert match_clause(
        "return up to x target creature cards from your graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield",
        "count_selector": "source_x_paid", "optional": True,
    })]


def test_numeric_plural_still_takes_the_multi_target_route():
    # the pre-existing N>=2 handler, untouched — a literal count, no selector
    assert match_clause(
        "return up to 2 target creature cards from your graveyard to your hand"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand",
        "count": 2, "optional": True,
    })]


def test_real_cards_modeled():
    for name, text in [
        ("Death Denied", "Return X target creature cards from your graveyard to your hand."),
        ("Entreat the Dead",
         "Return X target creature cards from your graveyard to the battlefield."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{X}{B}{B}", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ---------------------------------------------------------------


def test_apply_returns_exactly_x_targets_to_hand():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    src = GameObject(Card(id="dd", name="Death Denied", type_line="Sorcery",
                          is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    src.x_paid = 2

    c1 = _gy_creature(state, "Zombie A")
    c2 = _gy_creature(state, "Zombie B")
    c3 = _gy_creature(state, "Zombie C")

    eff = build_effects([EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand",
        "count_selector": "source_x_paid", "optional": True,
    })], src)[0]
    eff.apply(GameContext(state, eng.rules), [c1, c2])   # targeting layer offered X=2 picks

    assert c1 in p1.hand and c2 in p1.hand
    assert c3 in p1.graveyard          # the third was never chosen
    assert c1 not in p1.graveyard and c2 not in p1.graveyard


def test_full_cast_with_x_two_reanimates_two_creatures():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    spell = GameObject(Card(id="etd", name="Entreat the Dead", type_line="Sorcery",
                            is_sorcery=True, mana_cost_string="{X}{B}{B}",
                            oracle_text="Return X target creature cards from your "
                                        "graveyard to the battlefield."),
                       owner_id="p1", zone=Zone.HAND)
    spell.controller_id = "p1"
    p1.hand.append(spell)
    bind_from_catalogue(spell)

    a = _gy_creature(state, "Ghoul A")
    b = _gy_creature(state, "Ghoul B")
    p1.mana_pool.add_many({"B": 4})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, spell, targets=[a, b], x=2)
    eng.resolve_until_stable()

    assert a in state.battlefield and b in state.battlefield
    assert a.controller_id == "p1" and b.controller_id == "p1"


def test_x_zero_returns_nothing_and_still_resolves():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    src = GameObject(Card(id="dd", name="Death Denied", type_line="Sorcery",
                          is_sorcery=True), owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    src.x_paid = 0
    c1 = _gy_creature(state, "Zombie A")

    build_effects([EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand",
        "count_selector": "source_x_paid", "optional": True,
    })], src)[0].apply(GameContext(state, eng.rules), [])

    assert c1 in p1.graveyard and c1 not in p1.hand
