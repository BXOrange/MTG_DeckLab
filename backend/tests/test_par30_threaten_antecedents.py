"""PAR-30 — threaten-effect antecedent widening.

`_gain_control_eot` now accepts "another target …", a bare "target artifact",
and a "with power N or less/greater" filter; plus a new whole-clause
"for each opponent, gain control of up to 1 target creature that player
controls …" handler over a multi-target `GainControlUntilEndOfTurnEffect`
(its `apply` iterates every chosen target now, not just the first).
"""

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine


def _gc_spec(specs):
    return next(s for s in specs if s.type == "gain_control_until_eot")


def test_another_target_creature():
    specs = parse_effect_body(
        "gain control of another target creature until end of turn. "
        "untap that creature. it gains haste until end of turn."
    )
    assert specs is not None
    assert _gc_spec(specs).params["target_kind"] == "creature"


def test_target_artifact():
    specs = parse_effect_body(
        "gain control of target artifact until end of turn. "
        "untap that artifact. it gains haste until end of turn."
    )
    assert specs is not None
    assert _gc_spec(specs).params["target_kind"] == "artifact"


def test_with_power_filter():
    specs = parse_effect_body(
        "gain control of target creature an opponent controls with power 2 or less "
        "until end of turn. untap that creature. it gains haste until end of turn."
    )
    assert specs is not None
    p = _gc_spec(specs).params
    assert p["target_kind"] == "creature_you_dont_control"
    assert p["creature_filter"] == {"max_power": 2}


def test_with_power_greater_filter():
    specs = parse_effect_body(
        "gain control of target creature with power 4 or greater until end of turn. "
        "untap that creature. it gains haste until end of turn."
    )
    assert specs is not None
    assert _gc_spec(specs).params["creature_filter"] == {"min_power": 4}


def test_per_opponent_whole_clause():
    specs = parse_effect_body(
        "for each opponent, gain control of up to 1 target creature that player "
        "controls until end of turn. untap those creatures. they gain haste "
        "until end of turn."
    )
    assert specs is not None
    p = _gc_spec(specs).params
    assert p["count_selector"] == "opponents"
    assert p["target_kind"] == "creature_you_dont_control"
    assert p["optional"] is True


def test_end_to_end_mass_mutiny_and_enthralling_victor_modeled():
    for name, tl, text, kw in [
        ("Mass Mutiny", "Sorcery",
         "For each opponent, gain control of up to one target creature that "
         "player controls until end of turn. Untap those creatures. They gain "
         "haste until end of turn.", []),
        ("Enthralling Victor", "Creature — Human Berserker",
         "When Enthralling Victor enters, gain control of target creature an "
         "opponent controls with power 2 or less until end of turn. Untap that "
         "creature. It gains haste until end of turn.", []),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                 power=2 if "Creature" in tl else None,
                 toughness=2 if "Creature" in tl else None, keywords=kw)
        assert parse_oracle(c).modeled is True, name


def test_execute_multi_target_gain_control():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    st = eng.state

    def bear(pid, name):
        o = GameObject(
            Card(id=name, name=name, type_line="Creature — Bear",
                 is_creature=True, power=2, toughness=2),
            owner_id=pid, zone=Zone.BATTLEFIELD,
        )
        o.controller_id = pid
        st.add_to_battlefield(o)
        return o

    b2, b3 = bear("p2", "B2"), bear("p3", "B3")
    src = GameObject(
        Card(id="MM", name="Mass Mutiny", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "for each opponent, gain control of up to 1 target creature that player "
        "controls until end of turn. untap those creatures. they gain haste "
        "until end of turn."
    )
    effects = build_effects(specs, source=src)
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [b2, b3], None, source=src
    )
    eng.recompute_continuous_effects()
    assert b2.controller_id == "p1"
    assert b3.controller_id == "p1"
    assert "haste" in {k.lower() for k in b2.granted_keywords}
    assert "haste" in {k.lower() for k in b3.granted_keywords}
