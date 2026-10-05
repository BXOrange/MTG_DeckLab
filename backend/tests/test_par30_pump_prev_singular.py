"""PAR-30 — the singular-pronoun previous-subject pump family.

"it [also] gets +N/+N [and gains <kw>] until end of turn" / "it [also] gains
<kw> until end of turn", where the pronoun points at the single RULE 115
target the preceding split clause chose (`GameContext.previous_targets`,
`PumpEffect.previous_subject`). Plus the connector-split loop's referent
*propagation* through a clause that itself consumed the pronoun ("untap that
creature." -> "it gains haste.").
"""

from mtg_analyzer.parser.oracle.segmenter import match_clause, parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine


def _specs(body, **kw):
    return parse_effect_body(body, **kw)


def test_singular_it_keyword_only_previous_subject():
    specs = match_clause("it gains hexproof until end of turn", previous_subject=True)
    assert specs is not None
    assert specs[0].type == "pump"
    assert specs[0].params["keywords"] == ["hexproof"]
    assert specs[0].params["previous_subject"] is True


def test_singular_that_creature_pt_and_keyword():
    specs = match_clause(
        "that creature gets +2/+0 and gains haste until end of turn",
        previous_subject=True,
    )
    assert specs is not None
    p = specs[0].params
    assert (p["power"], p["toughness"]) == (2, 0)
    assert p["keywords"] == ["haste"]
    assert p["previous_subject"] is True


def test_singular_also_qualifier():
    specs = match_clause("it also gets +3/+0 until end of turn", previous_subject=True)
    assert specs is not None
    assert (specs[0].params["power"], specs[0].params["toughness"]) == (3, 0)


def test_fail_closed_without_previous_subject():
    # The row is `previous_subject_only` — nothing to bind the pronoun to.
    assert match_clause("it gains haste until end of turn", previous_subject=False) is None


def test_connector_loop_propagates_referent_through_untap():
    # "put a +1/+1 counter on target creature you control. it gains hexproof
    #  until end of turn." — part 1 chooses the target, part 2 reads "it".
    specs = _specs(
        "put a +1/+1 counter on target creature you control. "
        "it gains hexproof until end of turn."
    )
    assert specs is not None
    assert [s.type for s in specs] == ["add_counters", "pump"]
    assert specs[1].params["previous_subject"] is True


def test_connector_loop_chains_through_a_pronoun_consuming_clause():
    # "~ deals 1 damage to target creature. that creature gains trample until
    #  end of turn." then a further "it"/"they" clause would still resolve —
    #  the middle clause consumed the pronoun and keeps the chain alive.
    specs = _specs(
        "gain control of target creature until end of turn. untap that creature. "
        "it gets +2/+0 and gains haste until end of turn."
    )
    assert specs is not None
    types = [s.type for s in specs]
    assert "gain_control_until_eot" in types
    pump = [s for s in specs if s.type == "pump"][0]
    assert (pump.params["power"], pump.params["toughness"]) == (2, 0)
    assert pump.params["previous_subject"] is True


def test_end_to_end_snakeskin_veil_modeled():
    card = Card(
        id="SnkVl", name="Snakeskin Veil", type_line="Instant", is_instant=True,
        oracle_text=(
            "Put a +1/+1 counter on target creature you control. "
            "It gains hexproof until end of turn."
        ),
    )
    assert parse_oracle(card).modeled is True


def test_execute_pump_previous_subject_pumps_the_counter_target():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    st = eng.state

    bear = GameObject(
        Card(id="B", name="Grizzly Bears", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = "p1"
    st.add_to_battlefield(bear)

    src = GameObject(
        Card(id="S", name="Src", type_line="Enchantment"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = _specs(
        "put a +1/+1 counter on target creature you control. "
        "it gains trample until end of turn."
    )
    effects = build_effects(specs, source=src)
    ctx = GameContext(st, eng.rules)
    _apply_effects_partitioned(effects, ctx, [bear], None, source=src)
    eng.recompute_continuous_effects()
    assert "trample" in {k.lower() for k in bear.granted_keywords}
    assert bear.counters.get("+1/+1") == 1
