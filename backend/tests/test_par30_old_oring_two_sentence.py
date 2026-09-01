"""PAR-30 — old two-sentence Oblivion Ring templating.

Modern O-Ring folds the return into one clause ("exile X until ~ leaves the
battlefield."); the older cycle prints two separate triggers:

    When ~ enters, exile another target nonland permanent.
    When ~ leaves the battlefield, return the exiled card to the
    battlefield under its owner's control.

`handlers._return_exiled_card` claims the second line (→ `return_linked_
exile`); `handlers._exile` now also accepts an "exile **another** target …"
ETB body; and `gate.parse_oracle` stamps `remember=True` onto the companion
exile so `GameObject.linked_exile_id` is populated for the return to read.

Driftgloom Coyote's own O-Ring after-tail — "if that creature had power N or
less, put a +1/+1 counter on ~." — rides `ConditionalEffect`'s new
`previous_target_power_at_most` key.
"""

from __future__ import annotations

from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import Zone
from mtg_analyzer.game.effect_binder import bind_from_catalogue

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


_ORING_TEXT = (
    "When ~ enters, exile another target nonland permanent.\n"
    "When ~ leaves the battlefield, return the exiled card to the "
    "battlefield under its owner's control."
)


def _card(name, text, tl="Enchantment"):
    return Card(
        id=name[:6], name=name, type_line=tl, oracle_text=text.replace("~", name),
        is_creature="Creature" in tl,
        power=2 if "Creature" in tl else None,
        toughness=2 if "Creature" in tl else None,
    )


def test_return_exiled_card_line_claimed():
    specs = parse_effect_body(
        "return the exiled card to the battlefield under its owner's control"
    )
    assert specs is not None
    assert [s.type for s in specs] == ["return_linked_exile"]


def test_return_exiled_cards_plural_claimed():
    specs = parse_effect_body(
        "return the exiled cards to the battlefield under their owners' control"
    )
    assert specs is not None
    assert [s.type for s in specs] == ["return_linked_exile"]


def test_exile_another_target_claimed():
    specs = parse_effect_body("exile another target creature")
    assert specs is not None
    assert specs[0].type == "exile"
    assert specs[0].params["target_kind"] == "creature"


def test_gate_links_the_two_sentences():
    r = parse_oracle(_card("Oblivion Ring", _ORING_TEXT))
    assert r.modeled is True
    etb = next(s for s in r.specs if (s.trigger or {}).get("event") == "ENTERS_BATTLEFIELD")
    ltb = next(s for s in r.specs if (s.trigger or {}).get("event") == "LEAVES_BATTLEFIELD")
    assert etb.effects[0].type == "exile"
    assert etb.effects[0].params["remember"] is True
    assert ltb.effects[0].type == "return_linked_exile"


def test_real_cards_modeled():
    for name, tl in [
        ("Journey to Nowhere", "Enchantment"),
        ("Faceless Butcher", "Creature — Nightmare Horror"),
        ("Fiend Hunter", "Creature — Human Cleric"),
        ("Slithery Stalker", "Creature — Nightmare Beast"),
    ]:
        text = _ORING_TEXT
        if "Butcher" in name or "Hunter" in name:
            text = (
                "When ~ enters, exile another target creature.\n"
                "When ~ leaves the battlefield, return the exiled card to the "
                "battlefield under its owner's control."
            )
        assert parse_oracle(_card(name, text, tl)).modeled is True, name


def test_driftgloom_coyote_after_tail_modeled():
    r = parse_oracle(_card(
        "Driftgloom Coyote",
        "When ~ enters, exile target creature an opponent controls until ~ "
        "leaves the battlefield. If that creature had power 2 or less, put a "
        "+1/+1 counter on ~.",
        "Creature — Elemental Hound",
    ))
    assert r.modeled is True
    etb = next(s for s in r.specs if (s.trigger or {}).get("event") == "ENTERS_BATTLEFIELD")
    types = [e.type for e in etb.effects]
    assert "exile" in types and "add_counters" in types
    counter = next(e for e in etb.effects if e.type == "add_counters")
    assert counter.condition == {"previous_target_power_at_most": 2}


def test_execute_old_oring_round_trip():
    oring = _card("Old Ring", _ORING_TEXT)
    eng = make_engine([oring], [creature("Bear", cost="{2}{G}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 3, "B": 3})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", cost="{2}{G}"), controller="p2")
    bind_from_catalogue(bear)

    ring = p1.hand[0]
    bind_from_catalogue(ring)
    eng.cast_spell(p1, ring)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert bear.zone == Zone.EXILE
    assert ring.linked_exile_id == bear.instance_id

    eng.rules.put_into_graveyard(ring)
    eng.resolve_until_stable()

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.controller_id == "p2"
