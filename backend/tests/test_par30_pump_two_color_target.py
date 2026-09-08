"""PAR-30 — a colour-list creature target on the pump family.

"target `<c1>` or `<c2>` creature gets +N/+M / gains `<kw>` until end of
turn" — the Weaver cycle (Hate/Rage/Sky/Might/Spirit Weaver, Sootstoke
Kindler, Wilderness Hypnotist). `PumpEffect` gained a `colors` param
threaded into its `TargetSpec`; `TargetSpec.colors` + `_color_ok` were
already wired into `legal_targets`, just never reached from a pump.
Dedicated `_PUMP_TARGET_TWO_COLOR_RE`/handler — the shared `TARGET` macro
carries no colour slot (`_DAMAGE_TARGET_TWO_COLOR_RE`'s sibling).
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


def _creature(state, name, colors, pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2,
                        color_identity=set(colors)),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -------------------------------------------------------------------


def test_keyword_form_parses():
    assert match_clause("target black or green creature gains haste until end of turn") == [
        EffectSpec("pump", {"target_kind": "creature", "colors": ["B", "G"],
                            "keywords": ["haste"]})
    ]


def test_pt_form_parses_including_a_debuff():
    assert match_clause("target blue or red creature gets +1/+0 until end of turn") == [
        EffectSpec("pump", {"target_kind": "creature", "colors": ["U", "R"],
                            "power": 1, "toughness": 0})
    ]
    assert match_clause("target red or green creature gets -2/-0 until end of turn") == [
        EffectSpec("pump", {"target_kind": "creature", "colors": ["R", "G"],
                            "power": -2, "toughness": 0})
    ]


def test_non_flag_granted_ability_fails_closed():
    # "gains firebending 2" isn't a plain flag keyword — must not half-model
    assert match_clause(
        "target red or white creature gains firebending 2 until end of turn"
    ) is None


def test_same_colour_twice_is_rejected():
    assert match_clause(
        "target red or red creature gains haste until end of turn"
    ) is None


def test_real_weaver_cards_modeled():
    for name, text in [
        ("Rage Weaver", "{2}: Target black or green creature gains haste until end of turn."),
        ("Spirit Weaver", "{2}: Target green or blue creature gets +0/+1 until end of turn."),
        ("Wilderness Hypnotist",
         "{T}: Target red or green creature gets -2/-0 until end of turn."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Creature — Human Wizard",
                 is_creature=True, power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ---------------------------------------------------------------


def test_legal_targets_only_offers_a_matching_colour():
    eng, state = _engine()
    src = GameObject(Card(id="src", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    green = _creature(state, "Green Bear", {"G"})
    blue = _creature(state, "Blue Bear", {"U"})
    white = _creature(state, "White Bear", {"W"})
    eng.recompute_continuous_effects()

    eff = build_effects([EffectSpec("pump", {
        "target_kind": "creature", "colors": ["B", "G"], "keywords": ["haste"],
    })], src)[0]
    offered = {t["instance_id"] for t in legal_targets(state, "p1", eff.target_spec, src)}

    assert green.instance_id in offered
    assert blue.instance_id not in offered and white.instance_id not in offered


def test_resolving_pumps_the_chosen_creature():
    eng, state = _engine()
    green = _creature(state, "Green Bear", {"G"})

    build_effects([EffectSpec("pump", {
        "target_kind": "creature", "colors": ["B", "G"], "power": 3, "toughness": 0,
    })], green)[0].apply(GameContext(state, eng.rules), [green])
    eng.recompute_continuous_effects()

    assert green.power == 5  # 2 printed + 3
