"""PAR-30 (Threaten / O-Ring trailing items) — RULE 601.2i "When you cast
this spell, <effect>." recognizer.

`segmenter._CAST_THIS_SPELL_TRIGGER_RE` emits a `SPELL_CAST` trigger scoped
`{"subject": "self"}`; `effect_binder.bind_ability` already sets
`TriggeredAbility.functions_from_stack` off exactly that shape (MEC-43), so
the trigger fires while the spell is still on the stack and resolves above
it.
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue

from tests.test_game_engine import make_engine

_PROV = ParserProvenance(version="test", source="rule:oracle", confidence=1.0)


def test_segment_emits_spell_cast_self_trigger():
    seg = segment_line(
        "when you cast this spell, create a 10/10 colorless eldrazi creature token.",
        allow_spell_effect=True, provenance=_PROV,
    )
    assert seg.claimed
    assert seg.spec.ability_kind == "triggered"
    assert seg.spec.trigger == {"event": "SPELL_CAST", "condition": {"subject": "self"}}
    assert seg.spec.effects[0].type == "create_token"


def test_segment_fails_closed_on_unmodellable_body():
    seg = segment_line(
        "when you cast this spell, copy it if you control a planeswalker.",
        allow_spell_effect=True, provenance=_PROV,
    )
    assert not seg.claimed


def test_real_cards_modeled():
    for name, text in [
        ("Desolation Twin",
         "When you cast this spell, create a 10/10 colorless Eldrazi creature token."),
        ("It of the Horrid Swarm",
         "When you cast this spell, create a 3/3 colorless Eldrazi Horror "
         "creature token."),
    ]:
        c = Card(id=name[:6], name=name, type_line="Creature — Eldrazi", is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).modeled is True, name


def test_execute_trigger_fires_above_the_spell():
    twin = Card(
        id="DT", name="Desolation Twin", type_line="Creature — Eldrazi",
        is_creature=True, power=10, toughness=10, mana_cost_string="{10}",
        oracle_text="When you cast this spell, create a 10/10 colorless Eldrazi "
                    "creature token.",
    )
    eng = make_engine([twin], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 12})

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()

    tokens = [o for o in eng.state.battlefield if getattr(o, "is_token", False)]
    assert len(tokens) == 1
    assert (tokens[0].power, tokens[0].toughness) == (10, 10)
    # the spell itself also resolved
    assert any(o.name == "Desolation Twin" and not getattr(o, "is_token", False)
               for o in eng.state.battlefield)
