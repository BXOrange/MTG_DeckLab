"""PAR-43 — single-characteristic CDA: "~'s power is equal to the number of
`<X>`." (RULE 604.3 — Ironroot Warlord / Kolaghan Forerunners / Suki,
Kyoshi Warrior — a printed toughness with a live-count power).

`static_handlers._PT_CDA_SINGLE_RE` emits a `pt_cda` spec with only
`power_count` (or `toughness_count`) set — `continuous.recompute`'s 7a
`pt_cda` pass already applies the two independently, so no engine change.
Same `_pt_cda_selector` resolution as the "power **and** toughness" form
(PAR-120, PARSER_VERSION 466: the shared `count_phrase` grammar first,
`_PT_CDA_SELECTORS`' one remaining special case — RULE 700.8's party
count — as fallback).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.support.game import creature, make_engine, obj_on_battlefield


# --- parse -----------------------------------------------------------------


_CREATURES_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}
_LANDS_YOU_CONTROL = {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}}


def test_power_only_cda_parses():
    assert static_effect_specs("~'s power is equal to the number of creatures you control") == [
        EffectSpec("pt_cda", {"affects": "self", "power_count": _CREATURES_YOU_CONTROL})
    ]


def test_toughness_only_cda_parses_for_a_whitelisted_selector():
    assert static_effect_specs("~'s toughness is equal to the number of lands you control") == [
        EffectSpec("pt_cda", {"affects": "self", "toughness_count": _LANDS_YOU_CONTROL})
    ]


def test_power_and_toughness_form_still_sets_both():
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of creatures you control"
    ) == [
        EffectSpec("pt_cda", {
            "affects": "self",
            "power_count": _CREATURES_YOU_CONTROL,
            "toughness_count": _CREATURES_YOU_CONTROL,
        })
    ]


def test_a_basic_land_subtype_now_parses_via_the_shared_grammar():
    # PAR-120: "forests you control" used to be a different, unwired
    # selector — the shared noun-phrase grammar reaches it generically now.
    assert static_effect_specs("~'s power is equal to the number of forests you control") == [
        EffectSpec("pt_cda", {
            "affects": "self",
            "power_count": {"zone": "battlefield", "of": "you", "filter": {"subtype": "forest"}},
        })
    ]


def test_unwhitelisted_quantity_fails_closed():
    # Unknown nouns remain unclaimed even with an otherwise valid chosen-player scope.
    assert static_effect_specs(
        "~'s power is equal to the number of tapped frobnicators the chosen player controls"
    ) is None


def test_real_card_modeled():
    c = Card(
        id="iw", name="Ironroot Warlord", type_line="Creature — Treefolk Warrior",
        is_creature=True, power=0, toughness=4,
        oracle_text="Ironroot Warlord's power is equal to the number of creatures you control.\n"
                    "{1}{W}, {T}: Create a 1/1 white Soldier creature token.",
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -------------------------------------------------------------------


def test_power_scales_live_toughness_stays_printed():
    eng = make_engine([creature("Bear")], hand=0)
    state = eng.state
    warlord = obj_on_battlefield(
        state, eng,
        Card(id="iw", name="Ironroot Warlord", type_line="Creature — Treefolk",
             is_creature=True, power=0, toughness=4,
             oracle_text="Ironroot Warlord's power is equal to the number of creatures you control."),
        controller="p1",
    )
    bind_from_catalogue(warlord)
    eng.recompute_continuous_effects()
    # only Ironroot Warlord itself so far → power 1, toughness the printed 4
    assert (warlord.power, warlord.toughness) == (1, 4)

    for i in range(2):
        obj_on_battlefield(state, eng, creature(f"Ally {i}"), controller="p1")
    eng.recompute_continuous_effects()
    assert (warlord.power, warlord.toughness) == (3, 4)

    # opponents' creatures don't count
    obj_on_battlefield(state, eng, creature("Their Bear"), controller="p2")
    eng.recompute_continuous_effects()
    assert warlord.power == 3
