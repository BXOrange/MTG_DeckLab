"""MEC-52 — a RULE 603.4 intervening-if on a delayed triggered ability.

`CreateDelayedTriggerEffect` / `DelayedTrigger` gained a whitelisted
``condition`` dict re-checked by `GameEngine._fire_delayed_triggers` when the
delayed ability would go on the stack; if it doesn't hold, the ability simply
doesn't trigger.

Also closes **Sauron, the Necromancer** end-to-end:
- `_COPY_PERMANENT_PREVIOUS_RE` / the exile->copy connector accept a
  "tapped and attacking" prefix, and `_COPY_EXCEPT_PT_RE` a trailing
  "with <keyword>" ("a 3/3 black Wraith with menace" -> `extra_temp_keywords`);
- new when-first `_delayed_sac_exile_when_first` handler ("At the beginning of
  the next end step, sacrifice/exile <it>[ unless ~ is your Ring-bearer]").
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import (
    ExileSpecificEffect, GameContext, _apply_effects_partitioned,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import DelayedTrigger
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import match_clause, parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state


# --- parser: Sauron -------------------------------------------------------


def _sauron_card() -> Card:
    return Card(
        id="Sauron", name="Sauron, the Necromancer",
        type_line="Legendary Creature — Avatar Horror",
        is_creature=True, is_legendary=True, power=4, toughness=4,
        mana_cost_string="{3}{B}{B}", converted_mana_cost=5, keywords=["Menace"],
        oracle_text=(
            "Menace\n"
            "Whenever Sauron attacks, exile target creature card from your "
            "graveyard. Create a tapped and attacking token that's a copy of "
            "that card, except it's a 3/3 black Wraith with menace. At the "
            "beginning of the next end step, exile that token unless Sauron is "
            "your Ring-bearer."
        ),
    )


def test_sauron_is_modeled_with_the_right_spec_shape():
    res = parse_oracle(_sauron_card())
    assert res.modeled, res.unclaimed
    trig = next(s for s in res.specs if s.ability_kind == "triggered")
    assert [e.type for e in trig.effects] == [
        "exile", "copy_permanent", "create_delayed_trigger",
    ]
    copy = trig.effects[1].params
    assert copy["referent"] == "previous"
    assert copy["tapped"] is True and copy["attacking"] is True
    assert copy["set_power"] == 3 and copy["set_toughness"] == 3
    assert copy["set_colors"] == ["B"]
    assert copy["add_subtypes"] == ["Wraith"]
    assert copy["extra_temp_keywords"] == ["menace"]
    dt = trig.effects[2].params
    assert dt["step"] == "end" and dt["scope"] == "any"
    assert dt["effects"] == [{"type": "exile_specific", "params": {}}]
    assert dt["condition"] == {"is_ring_bearer": False}


# --- parser: the when-first delayed handler -----------------------------


def test_when_first_delayed_sacrifice_parses_in_a_connector_chain():
    specs = parse_effect_body(
        "draw a card. at the beginning of the next end step, sacrifice it."
    )
    assert specs is not None
    dt = next(s for s in specs if s.type == "create_delayed_trigger")
    assert dt.params["step"] == "end" and dt.params["scope"] == "any"
    assert dt.params["capture"] == "previous_or_self"
    assert dt.params["effects"] == [{"type": "sacrifice_specific", "params": {}}]
    assert "condition" not in dt.params  # no "unless" rider


def test_when_first_unless_ring_bearer_rider_adds_the_condition():
    specs = parse_effect_body(
        "draw a card. at the beginning of the next end step, exile it unless "
        "~ is your ring-bearer."
    )
    dt = next(s for s in specs if s.type == "create_delayed_trigger")
    assert dt.params["effects"] == [{"type": "exile_specific", "params": {}}]
    assert dt.params["condition"] == {"is_ring_bearer": False}


def test_when_first_fail_closed_on_unrelated_end_step_clause():
    assert match_clause(
        "at the beginning of the next end step, draw a card"
    ) is None


# --- engine: the condition gate ---------------------------------------


def _armed(eng, condition):
    src = GameObject(
        Card(id="X", name="X", type_line="Creature — Wraith", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    token = GameObject(
        Card(id="T", name="Token", type_line="Creature — Wraith", is_creature=True,
             power=3, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    token.controller_id = "p1"
    token.is_token = True
    eng.state.add_to_battlefield(token)
    inner = ExileSpecificEffect([token], source=src)
    eng.state.delayed_triggers.append(
        DelayedTrigger(controller_id="p1", step="end", effects=[inner],
                       scope="any", condition=condition)
    )
    return src, token


def test_condition_none_fires_normally():
    eng, st = _engine()
    src, token = _armed(eng, None)
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert token.zone == Zone.EXILE
    assert st.delayed_triggers == []


def test_unless_ring_bearer_does_not_fire_while_source_is_ring_bearer():
    eng, st = _engine()
    src, token = _armed(eng, {"is_ring_bearer": False})
    st.player_by_id("p1").ring_bearer_id = src.instance_id
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert token.zone == Zone.BATTLEFIELD, "Sauron is the Ring-bearer — token stays"
    assert st.delayed_triggers == [], "the one-shot delayed trigger is still consumed"


def test_unless_ring_bearer_fires_when_source_is_not_ring_bearer():
    eng, st = _engine()
    src, token = _armed(eng, {"is_ring_bearer": False})
    # no ring-bearer set
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert token.zone == Zone.EXILE


# --- execute: Sauron's whole trigger ---------------------------------


def test_sauron_end_to_end_makes_the_token_and_exiles_it_at_end_step():
    eng, st = _engine()
    st.current_phase = "combat"
    st.current_step = "declare_attackers"
    grave = GameObject(
        Card(id="Bear", name="Grizzly Bear", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
        owner_id="p1", zone=Zone.GRAVEYARD,
    )
    st.players[0].graveyard.append(grave)
    src = GameObject(_sauron_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)

    trig = next(s for s in parse_oracle(src.card).specs if s.ability_kind == "triggered")
    effects = build_effects(
        [EffectSpec(e.type, dict(e.params)) for e in trig.effects], src
    )
    _apply_effects_partitioned(
        effects, GameContext(st, eng.rules), [grave], None, source=src,
    )
    eng.recompute_continuous_effects()

    token = next(o for o in st.battlefield if o.is_token)
    assert token.card.name == "Grizzly Bear"
    assert (token.power, token.toughness) == (3, 3)
    assert token.tapped and token.attacking
    assert "menace" in token.granted_keywords or "menace" in token.temp_keywords
    assert grave.zone == Zone.EXILE
    assert len(st.delayed_triggers) == 1
    assert st.delayed_triggers[0].condition == {"is_ring_bearer": False}

    # end step, Sauron is not the Ring-bearer -> the token is exiled
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert token.zone == Zone.EXILE
