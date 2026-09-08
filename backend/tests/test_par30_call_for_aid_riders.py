"""PAR-30 (Threaten / O-Ring trailing items) — Call for Aid's two
anti-abuse riders + Shackles of Treachery's granted quoted trigger.

Call for Aid: "Gain control of all creatures target opponent controls until
end of turn. Untap those creatures. They gain haste until end of turn. You
can't attack that player this turn. You can't sacrifice those creatures
this turn."
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine

_CFA = (
    "gain control of all creatures target opponent controls until end of turn. "
    "untap those creatures. they gain haste until end of turn. you can't attack "
    "that player this turn. you can't sacrifice those creatures this turn."
)


def test_call_for_aid_parses_both_riders():
    specs = parse_effect_body(_CFA)
    assert specs is not None
    gc = next(s for s in specs if s.type == "gain_control_until_eot")
    assert gc.params["mass_of_target_player"] == "creature"
    assert gc.params["mark_no_sacrifice"] is True
    assert any(s.type == "prevent_attacking_player_this_turn" for s in specs)


def test_call_for_aid_modeled():
    c = Card(id="CFA", name="Call for Aid", type_line="Sorcery", is_sorcery=True,
             oracle_text=_CFA.capitalize())
    assert parse_oracle(c).modeled is True


def test_unknown_rider_fails_closed():
    assert parse_effect_body(
        "gain control of all creatures target opponent controls until end of "
        "turn. untap those creatures. they gain haste until end of turn. you "
        "can't win the game this turn."
    ) is None


def _engine():
    return GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
        starting_life=20, starting_hand=0,
    )


def _bear(st, pid, name):
    o = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


def test_execute_riders_bar_sacrifice_and_attack_then_lapse_at_cleanup():
    eng = _engine()
    st = eng.state
    c2 = _bear(st, "p2", "C2")
    src = GameObject(
        Card(id="CA", name="Call for Aid", type_line="Sorcery", is_sorcery=True),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    specs = parse_effect_body(_CFA)
    _apply_effects_partitioned(
        build_effects(specs, source=src), GameContext(st, eng.rules),
        [st.player_by_id("p2")], None, source=src,
    )
    eng.recompute_continuous_effects()

    assert c2.controller_id == "p1"
    assert c2.cant_be_sacrificed_this_turn is True
    assert ("p1", "p2") in st.no_attack_pairs_this_turn

    # p1 can't sacrifice c2 (effect-driven sac finds no candidate)
    eng.rules.sacrifice(st.player_by_id("p1"), "creature", 1)
    eng.resolve_until_stable()
    assert c2.zone == Zone.BATTLEFIELD

    # p1 can't declare c2 as an attacker against p2, but can against p3
    assert eng._can_attack(st.player_by_id("p1"), c2, st.player_by_id("p2")) is False
    assert eng._can_attack(st.player_by_id("p1"), c2, st.player_by_id("p3")) is True

    # both riders lapse at cleanup
    eng._step_cleanup()
    assert c2.cant_be_sacrificed_this_turn is False
    assert st.no_attack_pairs_this_turn == set()


# --- Shackles of Treachery: granted quoted "deals damage" trigger ----------

_SHACKLES = (
    "gain control of target creature until end of turn. untap that creature. "
    'until end of turn, it gains haste and "whenever ~ deals damage, destroy '
    'target equipment attached to it."'
)


def test_shackles_parses_granted_quoted_damage_trigger():
    specs = parse_effect_body(_SHACKLES)
    assert specs is not None
    gu = next(s for s in specs if s.type == "grant_until")
    static = gu.params["static"]
    assert static["type"] == "grant_triggered_ability"
    assert static["params"]["trigger_event"] == "DAMAGE"
    assert "filter" not in static["params"]  # bare "deals damage" -> any damage
    dst = static["params"]["grant_effects"][0]
    assert dst["type"] == "destroy"
    assert dst["params"]["target_kind"] == "equipment_attached_to_source"


def test_shackles_modeled():
    c = Card(id="ST", name="Shackles of Treachery", type_line="Sorcery",
             is_sorcery=True, oracle_text=(
                 "Gain control of target creature until end of turn. Untap that "
                 'creature. Until end of turn, it gains haste and "Whenever this '
                 'creature deals damage, destroy target Equipment attached to it."'))
    assert parse_oracle(c).modeled is True


def test_bare_deals_damage_trigger_no_recipient_filter():
    from mtg_analyzer.parser.oracle.segmenter import segment_line
    from mtg_analyzer.parser.oracle.spec import ParserProvenance

    seg = segment_line(
        "whenever ~ deals damage, draw a card.",
        allow_spell_effect=False,
        provenance=ParserProvenance(version="t", source="rule:oracle", confidence=1.0),
    )
    assert seg.claimed
    assert seg.spec.trigger["event"] == "DAMAGE"
    assert "is_player" not in (seg.spec.trigger.get("filter") or {})
