"""PAR-30 — the O-Ring / Banisher Priest / Fiend Hunter family: modern
one-sentence "exile <TARGET> [an opponent controls] until ~ leaves the
battlefield" templating.

`handlers._exile_until_leaves` emits an `ExileEffect(remember=True)` with a
new `until_source_leaves` param; `segmenter.segment_line` reads that param
and synthesizes the companion `LEAVES_BATTLEFIELD` -> `return_linked_exile`
ability that a single-body parse can't. Both the exile machinery and
`ReturnLinkedExileEffect` are pre-existing (MEC-21 / MEC-30 / Skyclave
Apparition).
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import ParserProvenance
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue

from tests.test_game_engine import creature, make_engine, obj_on_battlefield

_PROV = ParserProvenance(version="test", source="rule:oracle", confidence=1.0)


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_segment_emits_exile_plus_companion_ltb():
    seg = segment_line(
        "when ~ enters, exile target creature an opponent controls "
        "until ~ leaves the battlefield.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.claimed
    assert seg.spec.effects[0].type == "exile"
    assert seg.spec.effects[0].params["remember"] is True
    assert seg.spec.effects[0].params["until_source_leaves"] is True
    assert seg.spec.effects[0].params["target_kind"] == "creature_you_dont_control"
    assert len(seg.extra_specs) == 1
    ltb = seg.extra_specs[0]
    assert ltb.effects[0].type == "return_linked_exile"
    assert ltb.trigger["event"] == "LEAVES_BATTLEFIELD"


def test_segment_nonland_permanent_and_optional_you_may():
    seg = segment_line(
        "when ~ enters, you may exile target nonland permanent an opponent "
        "controls until ~ leaves the battlefield.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.spec.effects[0].params["target_kind"] == "nonland_permanent_you_dont_control"
    assert seg.spec.optional is True
    assert len(seg.extra_specs) == 1


def test_no_companion_without_the_until_clause():
    seg = segment_line(
        "when ~ enters, exile target creature an opponent controls.",
        allow_spell_effect=False, provenance=_PROV,
    )
    assert seg.extra_specs == []


def test_real_cards_modeled():
    for name in ("Banisher Priest", "Banishing Light", "Cast Out", "Fairgrounds Warden"):
        c = _named(name)
        assert c is not None, name
        assert parse_oracle(c).modeled is True, name


def test_execute_exile_on_etb_then_return_when_it_leaves():
    eng = make_engine([_named("Banisher Priest")], [creature("Bear", cost="{2}{G}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 3, "B": 1})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", cost="{2}{G}"), controller="p2")
    bind_from_catalogue(bear)

    priest = p1.hand[0]
    bind_from_catalogue(priest)
    eng.cast_spell(p1, priest)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert bear.zone == Zone.EXILE
    assert priest.linked_exile_id == bear.instance_id

    eng.rules.put_into_graveyard(priest)
    eng.resolve_until_stable()

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.controller_id == "p2"
