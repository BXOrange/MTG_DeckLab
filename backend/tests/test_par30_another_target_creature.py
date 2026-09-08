"""PAR-30 — the shared ``TARGET`` macro's "another target creature you
control" row (RULE 109.5).

The two-keyword until-EOT pump ("gains trample and indestructible until end
of turn") already worked for a bare "target creature". What real ETB /
combat-trigger creatures actually print is **"another target creature you
control gains <kw> until end of turn"** — the ability's own source is
excluded. The engine's `other_creature_you_control` target kind
(`targeting.py`) already does that exclusion + "you control" scoping + its
German label; this batch just routes the printed phrase there and adds the
kind to `_pump_target`'s pumpable-kind allowlist. The no-"you control"
form ("another target creature") originally stayed UNMODELED (its
``other_creature`` kind was never engine-wired). The Blight Curse batch
(2026-09-07) added a bare ``(?:another|other) target creature`` → ``creature``
row instead: RULE 109.5's "another" adds no distinct engine kind — the plain
``creature`` pick already excludes the ability's own source (RULE 115.6),
exactly like the "another target permanent" → ``permanent`` row. It's a
documented precision loss for the rarer *two-target* shape (Consume Strength's
"Another target creature gets -2/-2" — the two targets could be re-picked as
the same creature, `distinct_from_others` isn't threaded through `pump`), the
same RULE 115 simplification this file's own N-way rows already accept.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _bear(state, name="Bear", pid="p1"):
    o = GameObject(Card(id=name[:6], name=name, type_line="Creature — Bear",
                        is_creature=True, power=2, toughness=2),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse --------------------------------------------------------------


def test_single_keyword_another_target_you_control():
    specs = match_clause(
        "another target creature you control gains deathtouch until end of turn"
    )
    assert specs is not None
    assert specs[0].type == "pump"
    assert specs[0].params == {
        "keywords": ["deathtouch"], "target_kind": "other_creature_you_control",
    }


def test_two_keyword_another_target_you_control():
    specs = match_clause(
        "another target creature you control gains haste and myriad until end of turn"
    )
    assert specs is not None
    assert specs[0].params["keywords"] == ["haste", "myriad"]
    assert specs[0].params["target_kind"] == "other_creature_you_control"


def test_no_you_control_form_maps_to_bare_creature():
    # "another target creature" (no "you control") now routes to the plain
    # engine-wired ``creature`` kind (RULE 109.5 "another" == "not the
    # source", which ``creature`` already excludes — RULE 115.6).
    specs = match_clause(
        "another target creature gains deathtouch until end of turn"
    )
    assert specs is not None
    assert specs[0].type == "pump"
    assert specs[0].params == {"keywords": ["deathtouch"], "target_kind": "creature"}


def test_real_cards_modeled():
    for name, tl, text in [
        ("Heavenly Qilin", "Creature — Unicorn Monk",
         "Flying\nWhenever Heavenly Qilin attacks, another target creature "
         "you control gains flying until end of turn."),
        ("Duke Ulder Ravengard", "Legendary Creature — Human Soldier",
         "At the beginning of combat on your turn, another target creature "
         "you control gains haste and myriad until end of turn."),
        ("Selfless Savior", "Creature — Dog",
         "Sacrifice Selfless Savior: Another target creature you control "
         "gains indestructible until end of turn."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature=True, power=2, toughness=2)
        r = parse_oracle(c)
        assert r.coverage != UNMODELED, (name, r.unclaimed)


# --- execute -----------------------------------------------------------


def test_legal_targets_excludes_the_ability_source():
    eng, state = _engine()
    src = _bear(state, "Heavenly Qilin")
    friend = _bear(state, "Ally")
    enemy = _bear(state, "Foe", pid="p2")

    spec = TargetSpec(kind="other_creature_you_control")
    ids = {t["instance_id"] for t in legal_targets(state, "p1", spec, source=src)}

    assert friend.instance_id in ids
    assert src.instance_id not in ids        # RULE 109.5 — "another"
    assert enemy.instance_id not in ids      # "you control" scoping


def test_pump_lands_on_the_other_creature_end_to_end():
    eng, state = _engine()
    src = GameObject(
        Card(id="QILIN", name="Heavenly Qilin", type_line="Creature — Unicorn Monk",
             is_creature=True, power=3, toughness=3,
             oracle_text=("Whenever Heavenly Qilin attacks, another target creature "
                          "you control gains flying until end of turn.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    state.add_to_battlefield(src)
    bind_from_catalogue(src)
    friend = _bear(state, "Ally")

    trig = src.triggered_abilities[0]
    eff = trig.effects[0]
    eng.rules.context.previous_targets = []
    eff.apply(eng.rules.context, [friend])
    eng.recompute_continuous_effects()

    assert "flying" in friend.granted_keywords or "flying" in getattr(friend, "temp_keywords", set())
