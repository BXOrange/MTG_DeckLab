"""PAR-30 — the colour-list creature/permanent target extended to removal.

`_DESTROY_COLOR_ADJ_RE` widened to a "`<c1>` or `<c2>`" adjective (+ an
optional "with `<kw>`" tail) — Deathmark, Wallop; new
`_EXILE_TARGET_TWO_COLOR_RE`/handler — Celestial Purge. `DestroyEffect` /
`ExileEffect` gained a `colors` param threaded into their `TargetSpec`
(the multi-letter sibling of `DestroyEffect.color`); `TargetSpec.colors`
+ `targeting._color_ok` were already wired into `legal_targets`.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _creature(state, name, colors, pid="p1", keywords=None):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors),
                        keywords=list(keywords or [])),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -------------------------------------------------------------------


def test_destroy_two_color_parses():
    assert match_clause("destroy target green or white creature") == [
        EffectSpec("destroy", {"target_kind": "creature", "colors": ["G", "W"]})
    ]


def test_destroy_two_color_with_keyword_filter_parses():
    assert match_clause("destroy target blue or black creature with flying") == [
        EffectSpec("destroy", {"target_kind": "creature", "colors": ["U", "B"],
                               "creature_filter": {"keyword": "flying"}})
    ]


def test_single_color_destroy_still_works():
    assert match_clause("destroy target black creature") == [
        EffectSpec("destroy", {"target_kind": "creature", "color": "B"})
    ]


def test_exile_two_color_permanent_parses():
    assert match_clause("exile target black or red permanent") == [
        EffectSpec("exile", {"target_kind": "permanent", "colors": ["B", "R"]})
    ]
    assert match_clause("exile target black or red permanent you don't control") == [
        EffectSpec("exile", {"target_kind": "permanent_you_dont_control",
                             "colors": ["B", "R"]})
    ]


def test_same_colour_twice_fails_closed():
    assert match_clause("destroy target red or red creature") is None
    assert match_clause("exile target blue or blue permanent") is None


def test_real_cards_modeled():
    for name, text in [
        ("Deathmark", "Destroy target green or white creature."),
        ("Wallop", "Destroy target blue or black creature with flying."),
        ("Celestial Purge", "Exile target black or red permanent."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Instant", is_instant=True,
                 oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ---------------------------------------------------------------


def test_destroy_only_offers_a_matching_colour():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    green = _creature(state, "Green Bear", {"G"}, pid="p2")
    white = _creature(state, "White Bear", {"W"}, pid="p2")
    blue = _creature(state, "Blue Bear", {"U"}, pid="p2")
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("destroy", {
        "target_kind": "creature", "colors": ["G", "W"],
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert {green.instance_id, white.instance_id} <= offered
    assert blue.instance_id not in offered


def test_destroy_resolves_on_a_matching_creature():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    green = _creature(state, "Green Bear", {"G"}, pid="p2")

    build_effects([EffectSpec("destroy", {
        "target_kind": "creature", "colors": ["G", "W"],
    })], src)[0].apply(GameContext(state, eng.rules), [green])
    eng.rules.check_state_based_actions()

    assert green not in state.battlefield


def test_exile_two_color_removes_the_permanent():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Instant"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    red = _creature(state, "Red Bear", {"R"}, pid="p2")

    build_effects([EffectSpec("exile", {
        "target_kind": "permanent", "colors": ["B", "R"],
    })], src)[0].apply(GameContext(state, eng.rules), [red])

    assert red not in state.battlefield
    assert red.zone == Zone.EXILE
