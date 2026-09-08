"""PAR-43 — single-characteristic CDA: "~'s power is equal to the number of
`<X>`." (RULE 604.3 — Ironroot Warlord / Kolaghan Forerunners / Suki,
Kyoshi Warrior — a printed toughness with a live-count power).

`static_handlers._PT_CDA_SINGLE_RE` emits a `pt_cda` spec with only
`power_count` (or `toughness_count`) set — `continuous.recompute`'s 7a
`pt_cda` pass already applies the two independently, so no engine change.
Same `_PT_CDA_SELECTORS` whitelist as the "power **and** toughness" form.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


# --- parse -----------------------------------------------------------------


def test_power_only_cda_parses():
    assert static_effect_specs("~'s power is equal to the number of creatures you control") == [
        EffectSpec("pt_cda", {"affects": "self", "power_count": "creatures_you_control"})
    ]


def test_toughness_only_cda_parses_for_a_whitelisted_selector():
    assert static_effect_specs("~'s toughness is equal to the number of lands you control") == [
        EffectSpec("pt_cda", {"affects": "self", "toughness_count": "lands_you_control"})
    ]


def test_power_and_toughness_form_still_sets_both():
    assert static_effect_specs(
        "~'s power and toughness are each equal to the number of creatures you control"
    ) == [
        EffectSpec("pt_cda", {
            "affects": "self",
            "power_count": "creatures_you_control",
            "toughness_count": "creatures_you_control",
        })
    ]


def test_unwhitelisted_quantity_fails_closed():
    assert static_effect_specs(
        "~'s power is equal to the number of forests you control"
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
