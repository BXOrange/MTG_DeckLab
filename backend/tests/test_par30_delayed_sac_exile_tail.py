"""PAR-30 — the "[Then] sacrifice/exile <it/that token/them> at the beginning
of [the/your] next end step." trailing clause.

RULE 603.7 delayed trigger over `create_delayed_trigger`, with a new
`capture="previous_or_self"` that bakes in whatever this same resolution's
earlier clause chose (RULE 115 target -> `previous_targets`) or created
(RULE 608.2 -> `created_objects`), falling back to the ability's own source
for a bare self-subject "sacrifice it" (Brackwater Elemental).
"""

from mtg_analyzer.parser.oracle.segmenter import match_clause, parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine


def test_clause_sacrifice_it_parses_to_delayed_trigger():
    specs = match_clause("sacrifice it at the beginning of the next end step")
    assert specs is not None
    s = specs[0]
    assert s.type == "create_delayed_trigger"
    assert s.params["step"] == "end"
    assert s.params["scope"] == "any"
    assert s.params["capture"] == "previous_or_self"
    assert s.params["effects"] == [{"type": "sacrifice_specific", "params": {}}]


def test_clause_exile_them_uses_exile_specific():
    specs = match_clause("exile them at the beginning of your next end step")
    assert specs is not None
    assert specs[0].params["effects"] == [{"type": "exile_specific", "params": {}}]


def test_clause_then_prefix_and_that_token():
    specs = match_clause("then exile that token at the beginning of the next end step")
    assert specs is not None
    assert specs[0].type == "create_delayed_trigger"


def test_fail_closed_on_unrelated_end_step_clause():
    assert match_clause("draw a card at the beginning of the next end step") is None


def test_end_to_end_tidal_wave_modeled():
    card = Card(
        id="TidWv", name="Tidal Wave", type_line="Sorcery", is_sorcery=True,
        oracle_text=(
            "Create a 5/5 blue Wall creature token with defender. "
            "Sacrifice it at the beginning of the next end step."
        ),
    )
    assert parse_oracle(card).modeled is True


def test_end_to_end_brackwater_elemental_self_subject_modeled():
    card = Card(
        id="BrkEl", name="Brackwater Elemental", type_line="Creature — Elemental",
        is_creature=True, power=5, toughness=4,
        oracle_text="When Brackwater Elemental attacks or blocks, sacrifice it "
                    "at the beginning of the next end step.",
    )
    assert parse_oracle(card).modeled is True


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def test_execute_created_token_is_baked_into_the_delayed_sacrifice():
    eng, st = _engine()
    src = GameObject(
        Card(id="S", name="Src", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(
        "create a 5/5 blue wall creature token with defender. "
        "sacrifice it at the beginning of the next end step."
    )
    effects = build_effects(specs, source=src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)

    token = next(o for o in st.battlefield if o.card.name == "Wall")
    assert len(st.delayed_triggers) == 1
    inner = st.delayed_triggers[0].effects[0]
    assert type(inner).__name__ == "SacrificeSpecificEffect"
    assert inner.objects == [token]


def test_execute_self_fallback_when_no_referent():
    eng, st = _engine()
    src = GameObject(
        Card(id="BW", name="Brackwater Elemental", type_line="Creature — Elemental",
             is_creature=True, power=5, toughness=4),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body("sacrifice it at the beginning of the next end step")
    effects = build_effects(specs, source=src)
    _apply_effects_partitioned(effects, GameContext(st, eng.rules), [], None, source=src)

    inner = st.delayed_triggers[0].effects[0]
    assert inner.objects == [src]
