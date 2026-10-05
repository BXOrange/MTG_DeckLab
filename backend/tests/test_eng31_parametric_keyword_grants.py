"""ENG-31 — parametric keyword *grants*.

A grant of a keyword that carries a number — "target creature gains
firebending N until end of turn" (Fire Nation Palace), "creatures you
control gain firebending N …" (Sozin's Comet), a token "with firebending N"
(Fire Nation Attacks) — had no representation: `pump`/`grant_keyword`/
`create_token` all carried a flat ``keywords: [str]`` list.

Now `{name, n}` entries ride alongside that flat list in a new
``parametric_keywords`` param; `continuous._apply_layer_6_ability` stamps
them onto `GameObject._granted_parametric_keywords` /
`temp_parametric_keywords`, and `effect_binder.
parametric_keyword_triggered_abilities` re-synthesizes the keyword's RULE
702-text triggered ability (firebending's self-only ``ATTACKS`` add-{R}×N
mana ability) off the *granted* N every recompute.

Reference: game/effects/core.py (`PumpEffect`/`CreateTokenEffect`
``parametric_keywords``), game/continuous.py (`_apply_layer_6_ability`),
game/binding/core.py (`parametric_keyword_triggered_abilities`),
parser/oracle/catalogue/handlers.py (`_split_keywords_with_parametric`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -------------------------------------------------------------------


def test_pump_parametric_keyword_clause_parses():
    assert match_clause(
        "target creature you control gains firebending 4 until end of turn"
    ) == [EffectSpec("pump", {
        "parametric_keywords": [{"name": "firebending", "n": 4}],
        "target_kind": "creature_you_control",
    })]


def test_group_pump_parametric_keyword_clause_parses():
    # PAR-120: "creatures you control" now resolves to a structured
    # selector, not the retired `_GROUP_SELECTORS` string.
    assert match_clause(
        "creatures you control gain firebending 1 until end of turn"
    ) == [EffectSpec("pump", {
        "parametric_keywords": [{"name": "firebending", "n": 1}],
        "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
    })]


def test_token_with_parametric_keyword_clause_parses():
    assert match_clause(
        "create 2 2/2 red soldier creature tokens with firebending 1"
    ) == [EffectSpec("create_token", {
        "count": 2, "power": 2, "toughness": 2, "colors": ["R"],
        "subtypes": ["Soldier"], "keywords": [], "token_name": "Soldier",
        "parametric_keywords": [{"name": "firebending", "n": 1}],
    })]


def test_non_grantable_numbered_keyword_stays_fail_closed():
    # renown is NUMBER-shaped but not a grantable parametric keyword.
    assert match_clause(
        "target creature gains renown 2 until end of turn"
    ) is None


def test_real_firebending_grant_cards_modeled():
    for name, text in [
        ("Fire Nation Palace",
         "{1}{R}, {T}: Target creature you control gains firebending 4 until "
         "end of turn."),
        ("Fire Nation Attacks",
         "Create two 2/2 red Soldier creature tokens with firebending 1."),
        ("Sozin's Comet",
         "Creatures you control gain firebending 1 until end of turn."),
    ]:
        c = Card(id=name[:4], name=name, type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{2}{R}", oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


def test_self_parametric_grant_clause_parses():
    # PAR-30 (PARSER_VERSION 157): "~ has firebending N" — the self-scoped
    # static grant, ENG-31's group/pump/token siblings' missing fourth form.
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
    assert static_effect_specs("~ has firebending 2") == [
        EffectSpec("grant_keyword", {
            "affects": "self",
            "parametric_keywords": [{"name": "firebending", "n": 2}],
        })
    ]
    # a plain flag self-grant is unchanged (regression guard)
    assert static_effect_specs("~ has flying") == [
        EffectSpec("grant_keyword", {"affects": "self", "keywords": ["flying"]})
    ]
    # a non-grantable numbered keyword still fails closed
    assert static_effect_specs("~ has renown 2") is None


def test_fire_nation_cadets_modeled():
    c = Card(id="fnc", name="Fire Nation Cadets", type_line="Creature — Human Soldier",
             is_creature=True, power=2, toughness=1, mana_cost_string="{1}{R}",
             oracle_text=(
                 "This creature has firebending 2 as long as there's a Lesson "
                 "card in your graveyard.\n{2}: This creature gets +1/+0 until "
                 "end of turn."))
    res = parse_oracle(c)
    assert res.modeled, res.unclaimed
    grant = [s for s in res.effect_specs if s.ability_kind == "static"][0].effects[0]
    assert grant.params["parametric_keywords"] == [{"name": "firebending", "n": 2}]
    assert grant.params["active_if"] == {"kind": "subtype_in_graveyard", "subtype": "lesson"}


# --- execute ---------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _bear(state, pid, name="Bear"):
    c = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def _has_firebending_mana_ability(obj) -> int:
    """The R count of a synthesized firebending ATTACKS mana ability on
    ``obj``, or 0 if none."""
    for ta in obj.granted_triggered_abilities:
        if ta.trigger_event == EventType.ATTACKS and getattr(ta, "mana_ability", False):
            return sum(len(getattr(e, "colors", [])) for e in ta.effects)
    return 0


def test_static_grant_synthesizes_firebending_and_drops_with_source():
    eng, state = _engine()
    bear = _bear(state, "p1")

    ench = GameObject(Card(id="e", name="Fire Lord", type_line="Enchantment"),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    ench.controller_id = "p1"
    state.add_to_battlefield(ench)
    ench.static_effects.extend(build_effects([EffectSpec("grant_keyword", {
        "affects": "creatures_you_control",
        "parametric_keywords": [{"name": "firebending", "n": 2}],
    })], ench))

    eng.recompute_continuous_effects()
    assert bear.parametric_keyword_value("firebending") == 2
    assert _has_firebending_mana_ability(bear) == 2  # add {R}{R} on attack

    # source leaves → grant re-derives to nothing next pass (RULE 613.6)
    state.battlefield.remove(ench)
    eng.recompute_continuous_effects()
    assert bear.parametric_keyword_value("firebending") is None
    assert _has_firebending_mana_ability(bear) == 0


def test_until_eot_grant_clears_at_cleanup():
    eng, state = _engine()
    bear = _bear(state, "p1")
    src = GameObject(Card(id="s", name="Spell", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eff = build_effects([EffectSpec("pump", {
        "target_kind": "creature",
        "parametric_keywords": [{"name": "firebending", "n": 3}],
    })], src)[0]
    eff.apply(eng.rules.context, [bear])
    eng.recompute_continuous_effects()
    assert bear.parametric_keyword_value("firebending") == 3
    assert _has_firebending_mana_ability(bear) == 3

    for _ in range(20):  # a full turn cycle past the next cleanup step
        eng.advance_step()
    eng.recompute_continuous_effects()
    assert bear.temp_parametric_keywords == {}
    assert bear.parametric_keyword_value("firebending") is None
    assert _has_firebending_mana_ability(bear) == 0


def test_token_created_with_parametric_keyword():
    eng, state = _engine()
    src = GameObject(Card(id="s", name="Fire Nation Attacks", type_line="Sorcery",
                          is_sorcery=True, oracle_text=""),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    build_effects([EffectSpec("create_token", {
        "count": 2, "power": 2, "toughness": 2, "colors": ["R"],
        "subtypes": ["Soldier"], "keywords": [],
        "parametric_keywords": [{"name": "firebending", "n": 1}],
    })], src)[0].apply(eng.rules.context, None)

    toks = [o for o in state.battlefield if o.card.is_token]
    assert len(toks) == 2
    for t in toks:
        assert t.parametric_keywords.get("firebending") == {"n": 1}
        assert _has_firebending_mana_ability_intrinsic(t) == 1


def _has_firebending_mana_ability_intrinsic(obj) -> int:
    for ta in obj.triggered_abilities:
        if ta.trigger_event == EventType.ATTACKS and getattr(ta, "mana_ability", False):
            return sum(len(getattr(e, "colors", [])) for e in ta.effects)
    return 0


def test_end_to_end_fire_nation_palace_grants_on_activation():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    bear = _bear(state, "p1")
    land = GameObject(
        Card(id="FNP", name="Fire Nation Palace", type_line="Land", is_land=True,
             oracle_text="{1}{R}, {T}: Target creature you control gains "
                         "firebending 4 until end of turn."),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    land.controller_id = "p1"
    state.add_to_battlefield(land)
    bind_from_catalogue(land)
    assert land.activated_abilities, "the firebending-grant ability should bind"

    for eff in land.activated_abilities[0].effects:
        eff.apply(eng.rules.context, [bear])
    eng.recompute_continuous_effects()
    assert bear.parametric_keyword_value("firebending") == 4
    assert _has_firebending_mana_ability(bear) == 4
