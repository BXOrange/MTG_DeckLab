"""PAR-30 — threaten-effect antecedent widening.

`_gain_control_eot` now accepts "another target …", a bare "target artifact",
and a "with power N or less/greater" filter; plus a new whole-clause
"for each opponent, gain control of up to 1 target creature that player
controls …" handler over a multi-target `GainControlUntilEndOfTurnEffect`
(its `apply` iterates every chosen target now, not just the first).
"""

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
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


# --- v199: richer-than-bare-haste restatement tails --------------------------
# `_GAIN_CONTROL_HASTE_TAIL_RE` now recurses whatever the "it gains … haste …
# until end of turn" sentence says beyond bare haste through
# `parse_effect_body(previous_subject=True)` → `pump` onto the just-controlled
# creature.


def test_rich_tail_extra_keyword_after_haste():
    specs = parse_effect_body(
        "gain control of target creature you don't control until end of turn. "
        "untap it. it gains haste and myriad until end of turn."
    )
    assert specs is not None
    pump = next(s for s in specs if s.type == "pump")
    assert pump.params["previous_subject"] is True
    assert set(pump.params["keywords"]) == {"haste", "myriad"}


def test_rich_tail_extra_keyword_before_haste():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap it. "
        "it gains trample and haste until end of turn."
    )
    assert specs is not None
    pump = next(s for s in specs if s.type == "pump")
    assert set(pump.params["keywords"]) == {"trample", "haste"}


def test_bare_haste_tail_still_absorbed_not_a_pump():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "it gains haste until end of turn."
    )
    assert specs is not None
    assert [s.type for s in specs] == ["gain_control_until_eot"]


def test_rich_tail_unmodellable_keyword_fails_closed():
    # "quandrix affinity" isn't a keyword — the whole clause must stay unclaimed
    assert parse_effect_body(
        "gain control of target creature until end of turn. untap it. "
        "it gains quandrix affinity and haste until end of turn."
    ) is None


def test_end_to_end_firbolg_and_traitorous_blood_modeled():
    for name, tl, text in [
        ("Firbolg Flutist", "Creature — Faerie Bard",
         "When Firbolg Flutist enters, gain control of target creature you "
         "don't control until end of turn. Untap it. It gains haste and myriad "
         "until end of turn."),
        ("Traitorous Blood", "Sorcery",
         "Gain control of target creature until end of turn. Untap it. It gains "
         "trample and haste until end of turn."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                 power=2 if "Creature" in tl else None,
                 toughness=2 if "Creature" in tl else None, keywords=[])
        assert parse_oracle(c).modeled is True, name


def test_execute_rich_tail_grants_extra_keyword_until_eot():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    victim = GameObject(
        Card(id="V", name="V", type_line="Creature — Ox", is_creature=True,
             power=3, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p2"
    st.add_to_battlefield(victim)
    src = GameObject(
        Card(id="TB", name="Traitorous Blood", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap it. "
        "it gains trample and haste until end of turn."
    )
    effects = build_effects(specs, source=src)
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [victim], None, source=src
    )
    eng.recompute_continuous_effects()
    assert victim.controller_id == "p1"
    granted = {k.lower() for k in victim.granted_keywords}
    assert "haste" in granted
    assert "trample" in granted


# --- v200: leading "until end of turn, it …" rich restatements --------------


def test_rich_prev_grant_quoted_ability():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        'until end of turn, it gains haste and "whenever ~ deals combat damage '
        'to a player or battle, create a treasure token."'
    )
    assert specs is not None
    gu = next(s for s in specs if s.type == "grant_until")
    assert gu.params["previous_subject"] is True
    assert gu.params["static"]["type"] == "grant_triggered_ability"
    assert "affects" not in gu.params["static"]["params"]


def test_rich_prev_grant_becomes_subtype():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "until end of turn, it becomes a villain in addition to its other types "
        "and gains haste."
    )
    assert specs is not None
    gu = next(s for s in specs if s.type == "grant_until")
    assert gu.params["static"]["type"] == "type_change"
    assert gu.params["static"]["params"]["add_subtypes"] == ["Villain"]


def test_rich_prev_grant_base_pt_plus_keywords():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "until end of turn, it has base power and toughness 10/10 and gains "
        "trample, annihilator 2, and haste."
    )
    assert specs is not None
    gu = next(s for s in specs if s.type == "grant_until")
    assert gu.params["static"]["type"] == "pt_set"
    assert gu.params["static"]["params"] == {"power": 10, "toughness": 10}
    pump = next(s for s in specs if s.type == "pump")
    assert pump.params["keywords"] == ["trample"]  # haste dropped (already granted)
    assert pump.params["parametric_keywords"] == [{"name": "annihilator", "n": 2}]


def test_end_to_end_furnace_reins_and_lokis_scepter_modeled():
    for name, tl, text in [
        ("Furnace Reins", "Sorcery",
         'Gain control of target creature until end of turn. Untap that '
         'creature. Until end of turn, it gains haste and "Whenever this '
         'creature deals combat damage to a player or battle, create a '
         'Treasure token."'),
        ("Loki's Scepter", "Artifact",
         "When Loki's Scepter enters, gain control of target creature until "
         "end of turn. Untap that creature. Until end of turn, it becomes a "
         "Villain in addition to its other types and gains haste.\n"
         "{T}: Add one mana of any color."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_sorcery="Sorcery" in tl, keywords=[])
        assert parse_oracle(c).modeled is True, name


def test_execute_rich_prev_grant_becomes_subtype_and_base_pt():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state
    victim = GameObject(
        Card(id="V", name="V", type_line="Creature — Ox", is_creature=True,
             power=3, toughness=3),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p2"
    st.add_to_battlefield(victim)
    src = GameObject(
        Card(id="FL", name="Flayer", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "until end of turn, it has base power and toughness 10/10 and gains "
        "trample, and haste."
    )
    effects = build_effects(specs, source=src)
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [victim], None, source=src
    )
    eng.recompute_continuous_effects()
    assert victim.controller_id == "p1"
    assert (victim.power, victim.toughness) == (10, 10)
    assert "trample" in {k.lower() for k in victim.granted_keywords}


# --- v200: opponent-scoped mass threaten ----------------------------------


def test_mass_all_artifacts_your_opponents_control():
    specs = parse_effect_body(
        "gain control of all artifacts your opponents control until end of turn. "
        "untap them. they gain haste until end of turn."
    )
    assert specs is not None
    assert _gc_spec(specs).params == {"selector": "opponents_artifacts"}


def test_mass_all_creatures_target_opponent_controls():
    specs = parse_effect_body(
        "gain control of all creatures target opponent controls until end of turn. "
        "untap those creatures. they gain haste until end of turn."
    )
    assert specs is not None
    p = _gc_spec(specs).params
    assert p["target_kind"] == "opponent"
    assert p["mass_of_target_player"] == "creature"


def test_mass_permanents_word_fails_closed():
    # "all permanents your opponents control" — no `opponents_permanents`
    # mass selector, so the whole clause must stay unclaimed
    assert parse_effect_body(
        "gain control of all permanents your opponents control until end of turn. "
        "untap them. they gain haste until end of turn."
    ) is None


def test_execute_mass_your_opponents_artifacts():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    st = eng.state

    def put(pid, name, tl):
        o = GameObject(
            Card(id=name, name=name, type_line=tl, is_creature="Creature" in tl,
                 power=2 if "Creature" in tl else None,
                 toughness=2 if "Creature" in tl else None),
            owner_id=pid, zone=Zone.BATTLEFIELD,
        )
        o.controller_id = pid
        st.add_to_battlefield(o)
        return o

    a2 = put("p2", "A2", "Artifact")
    a3 = put("p3", "A3", "Artifact")
    c2 = put("p2", "C2", "Creature — Bear")
    src = GameObject(
        Card(id="BT", name="Broadcast Takeover", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "gain control of all artifacts your opponents control until end of turn. "
        "untap them. they gain haste until end of turn."
    )
    _apply_effects_partitioned(
        build_effects(specs, source=src), GameContext(st, eng.rules), [], None, source=src
    )
    eng.recompute_continuous_effects()
    assert a2.controller_id == "p1"
    assert a3.controller_id == "p1"
    assert c2.controller_id == "p2"  # creatures untouched


def test_execute_mass_target_opponent_creatures_only():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )
    st = eng.state

    def bear(pid, name):
        o = GameObject(
            Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                 power=2, toughness=2),
            owner_id=pid, zone=Zone.BATTLEFIELD,
        )
        o.controller_id = pid
        st.add_to_battlefield(o)
        return o

    c2, c3 = bear("p2", "C2"), bear("p3", "C3")
    src = GameObject(
        Card(id="CA", name="Call for Aid", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "gain control of all creatures target opponent controls until end of turn. "
        "untap those creatures. they gain haste until end of turn."
    )
    _apply_effects_partitioned(
        build_effects(specs, source=src), GameContext(st, eng.rules),
        [st.player_by_id("p2")], None, source=src,
    )
    eng.recompute_continuous_effects()
    assert c2.controller_id == "p1"
    assert c3.controller_id == "p3"  # a different opponent's creatures untouched
    assert "haste" in {k.lower() for k in c2.granted_keywords}


# --- v201: card-specific conditional after-tails --------------------------


def test_goatnap_subtype_conditional_tail_parse():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "it gains haste until end of turn. if that creature is a goat, it also "
        "gets +3/+0 until end of turn."
    )
    assert specs is not None
    pump = next(s for s in specs if s.type == "pump")
    assert pump.params == {"power": 3, "toughness": 0, "previous_subject": True}
    assert pump.condition == {"previous_target_has_subtype": "goat"}


def test_awaken_equipped_conditional_tail_parse():
    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "it gains haste until end of turn. if it's equipped, you may destroy all "
        "equipment attached to that creature."
    )
    assert specs is not None
    dst = next(s for s in specs if s.type == "destroy")
    assert dst.params == {"selector": "equipment_attached_to_previous"}
    assert dst.condition == {"previous_target_is_equipped": True}


def test_end_to_end_goatnap_awaken_modeled():
    for name, text in [
        ("Goatnap", "Gain control of target creature until end of turn. Untap "
         "that creature. It gains haste until end of turn. If that creature is "
         "a Goat, it also gets +3/+0 until end of turn."),
        ("Awaken the Sleeper", "Gain control of target creature until end of "
         "turn. Untap that creature. It gains haste until end of turn. If it's "
         "equipped, you may destroy all Equipment attached to that creature."),
    ]:
        c = Card(id=name[:6], name=name, type_line="Sorcery", is_sorcery=True,
                 oracle_text=text)
        assert parse_oracle(c).modeled is True, name


def test_execute_goatnap_conditional_pump_only_when_goat():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0,
    )
    st = eng.state

    def creat(name, subtypes):
        o = GameObject(
            Card(id=name, name=name, type_line="Creature — " + subtypes,
                 is_creature=True, power=2, toughness=2),
            owner_id="p2", zone=Zone.BATTLEFIELD,
        )
        o.controller_id = "p2"
        st.add_to_battlefield(o)
        return o

    goat = creat("G", "Goat")
    ox = creat("O", "Ox")
    src = GameObject(
        Card(id="GN", name="Goatnap", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "gain control of target creature until end of turn. untap that creature. "
        "it gains haste until end of turn. if that creature is a goat, it also "
        "gets +3/+0 until end of turn."
    )
    # on the Goat: +3/+0 applies
    _apply_effects_partitioned(
        build_effects(specs, source=src), GameContext(st, eng.rules), [goat], None, source=src
    )
    eng.recompute_continuous_effects()
    assert (goat.power, goat.toughness) == (5, 2)
    # on the Ox: control + haste, but no pump
    _apply_effects_partitioned(
        build_effects(specs, source=src), GameContext(st, eng.rules), [ox], None, source=src
    )
    eng.recompute_continuous_effects()
    assert ox.controller_id == "p1"
    assert (ox.power, ox.toughness) == (2, 2)
