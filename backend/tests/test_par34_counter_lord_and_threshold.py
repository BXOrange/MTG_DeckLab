"""PAR-34 — two RULE 613.6 / 613.4 static shapes.

1. "Each creature you control with a +1/+1 counter on it has `<keyword>`."
   (the Abzan "outlast" cycle — Abzan Falconer / Abzan Battle Priest /
   Ainok Bond-Kin / Duskshell Crawler / Tuskguard Captain). A
   `grant_keyword` static scoped to `creatures_you_control` **filtered by
   counter presence** — `continuous.affected_objects`' `has_counter_kind`
   param (MEC-21) already narrows the group, so no engine change.
   `static_handlers._GROUP_COUNTER_GRANT_RE`.

2. The Odyssey-block **Threshold** phrasing: "Threshold — As long as seven
   or more cards are in your graveyard, ~ gets +N/+N …" — `normalize.
   _ABILITY_WORD_RE` now strips the "Threshold —" label, and
   `_STATIC_CONDITION_RES` gained the subject-verb "N or more cards are in
   your graveyard" variant of the existing "there are N or more cards …"
   `control_count` condition.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.support.game import creature, make_engine, obj_on_battlefield


# --- parse ---------------------------------------------------------------


def test_counter_lord_parses():
    assert static_effect_specs(
        "each creature you control with a +1/+1 counter on it has flying"
    ) == [
        EffectSpec("grant_keyword", {
            "keywords": ["flying"],
            "affects": "creatures_you_control",
            "has_counter_kind": "+1/+1",
        })
    ]
    # multi-keyword
    assert static_effect_specs(
        "each creature you control with a +1/+1 counter on it has trample, lifelink"
    )[0].params["keywords"] == ["trample", "lifelink"]


def test_threshold_label_and_are_in_graveyard_phrasing():
    specs = static_effect_specs(
        "as long as 7 or more cards are in your graveyard, ~ gets +2/+2"
    )
    assert specs is not None
    assert specs[0].params["active_if"] == {
        "kind": "control_count", "selector": "cards_in_your_graveyard", "min": 7,
    }


def test_threshold_compounds_reuse_static_and_quoted_ability_catalogues():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ gets +2/+2 and has "{R}: ~ gets +1/+0 until end of turn"'
    )
    assert [spec.type for spec in specs] == ["anthem", "grant_activated_ability"]
    assert all(spec.params["active_if"]["min"] == 7 for spec in specs)

    restriction = static_effect_specs(
        "as long as there are 7 or more cards in your graveyard, ~ gets +2/+2 and can't block"
    )
    assert [spec.type for spec in restriction] == ["anthem", "grant_keyword"]
    assert restriction[1].params["keywords"] == ["cant_block"]

    additional = static_effect_specs(
        "white creatures get an additional +1/+1 as long as there are 7 or more cards in your graveyard"
    )
    assert additional[0].params["power"] == 1
    assert additional[0].params["active_if"]["min"] == 7


def test_colored_self_and_quoted_ability_compose_generically():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ is white and has "{T}: Destroy target black or red creature."'
    )
    assert [spec.type for spec in specs] == ["color_change", "grant_activated_ability"]
    assert all(spec.params["active_if"]["min"] == 7 for spec in specs)


def test_self_static_composes_stats_color_keyword_and_quote_generically():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ gets +3/+3, is black, has trample, and has '
        '"At the beginning of your upkeep, sacrifice a creature."'
    )
    assert [spec.type for spec in specs] == [
        "anthem", "color_change", "grant_keyword", "grant_triggered_ability",
    ]
    assert all(spec.params["active_if"]["min"] == 7 for spec in specs)


def test_quoted_another_counter_reuses_the_generic_counter_body():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "At the beginning of your upkeep, you may put another +1/+1 '
        'counter on this creature."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["optional"] is True
    assert granted.params["grant_effects"] == [{
        "type": "add_counters", "params": {"count": 1, "kind": "+1/+1"},
    }]


def test_quoted_graveyard_exile_uses_generic_multi_pick_effect():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "At the beginning of your end step, exile two cards from your graveyard."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["grant_effects"] == [{
        "type": "exile_own_graveyard_cards", "params": {"count": 2},
    }]


def test_quoted_noncolor_group_pump_reuses_filtered_group_effect():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "When this creature enters, nonblack creatures get -2/-2 until end of turn."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["grant_effects"] == [{
        "type": "pump", "params": {
            "power": -2, "toughness": -2, "selector": "all_creatures",
            "creature_filter": {"without_color": "B"},
        },
    }]


def test_quoted_opponent_spell_trigger_regrants_a_safe_group_condition():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "Whenever an opponent casts a spell, you may put a creature card '
        'from your hand onto the battlefield."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["group_condition"] == {"subject": "group", "controller": "not_you"}
    assert granted.params["grant_effects"] == [{
        "type": "put_from_hand_onto_battlefield",
        "params": {"criteria": {"type": "creature"}, "count": 1},
    }]


def test_quoted_combat_qualified_pump_reuses_target_kind():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ gets +1/+1 and has "{T}: Target attacking or blocking creature gets +3/+3 until end of turn."'
    )
    granted = specs[1]
    assert granted.type == "grant_activated_ability"
    assert granted.params["grant_effects"] == [{
        "type": "pump", "params": {
            "power": 3, "toughness": 3, "target_kind": "attacking_or_blocking_creature",
        },
    }]


def test_quoted_fixed_color_group_protection_is_generic_and_temporary():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "When this creature enters, creatures you control gain protection from black until end of turn."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["grant_effects"] == [{
        "type": "grant_fixed_protection_group",
        "params": {"selector": "creatures_you_control", "color": "B"},
    }]


def test_quoted_pay_then_return_this_card_uses_generic_self_reference():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "When this creature dies, you may pay {W}{W}. If you do, '
        'return this card to the battlefield under your control."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["grant_effects"] == [{
        "type": "pay_cost_then", "params": {
            "cost": "pay {w}{w}", "effects": [{
                "type": "return_self_to_battlefield",
                "params": {"tapped": False, "under_your_control": True},
            }],
        },
    }]


def test_quoted_owner_graveyard_dies_trigger_keeps_its_trigger_card_reference():
    specs = static_effect_specs(
        'as long as there are 7 or more cards in your graveyard, '
        '~ has "Whenever a nontoken creature is put into your graveyard from the battlefield, '
        'you may pay {1}. If you do, return that card to your hand."'
    )
    granted = specs[0]
    assert granted.type == "grant_triggered_ability"
    assert granted.params["group_condition"] == {
        "subject": "group", "type": "creature", "nontoken": True,
        "controller": "any", "owner": "you", "other": False,
    }
    assert granted.params["grant_effects"][0]["params"]["remember_trigger_subject"] is True


def test_activation_tail_combines_threshold_condition_and_once_per_game_limit():
    card = Card(
        id="threshold-activation", name="Any Threshold Activation",
        type_line="Creature — Wizard", is_creature=True,
        oracle_text=("{1}{U}: Put a +1/+1 counter on this creature and draw a card. "
                     "Activate only if there are seven or more cards in your graveyard and only once."),
    )
    spec = parse_oracle(card).specs[0]
    assert spec.ability_kind == "activated"
    assert {effect.type for effect in spec.effects} >= {
        "activation_condition_marker", "activate_only_once_marker",
    }


def test_sedge_slivers_quoted_static_uses_live_swamp_condition():
    card = Card(
        id="sedge", name="Sedge Sliver", type_line="Creature — Sliver", is_creature=True,
        oracle_text='All Sliver creatures have "This creature gets +1/+1 as long as you control a Swamp."',
    )
    assert parse_oracle(card).coverage != UNMODELED


def test_real_cards_modeled():
    for name, text, tl in [
        ("Abzan Falconer",
         "Outlast {W}\nEach creature you control with a +1/+1 counter on it has flying.",
         "Creature — Human Soldier"),
        ("Nimble Mongoose",
         "Trample\nThreshold — As long as seven or more cards are in your graveyard, "
         "Nimble Mongoose gets +2/+2.",
         "Creature — Mongoose"),
    ]:
        c = Card(id=name[:3], name=name, type_line=tl, is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_sliver_quoted_bodies_reuse_subtype_regeneration_and_mill_a_card():
    assert parse_effect_body("regenerate target sliver") == [
        EffectSpec("regenerate", {"target_kind": "creature", "creature_filter": {"subtype": "Sliver"}})
    ]
    assert parse_effect_body("target player mills a card") == [
        EffectSpec("mill", {"count": 1, "target_kind": "player"})
    ]
    assert parse_effect_body("target sliver creature gets +2/+2 until end of turn") == [
        EffectSpec("pump", {
            "power": 2, "toughness": 2, "target_kind": "creature",
            "creature_filter": {"subtype": "Sliver"},
        })
    ]
    assert parse_effect_body(
        "target sliver creature gets +x/+0 until end of turn, where x is the number of slivers on the battlefield"
    ) == [EffectSpec("pump", {
        "target_kind": "creature", "creature_filter": {"subtype": "Sliver"},
        "amount_from_count_selector": "creatures_of_type_sliver",
        "amount_from_count_selector_axis": "power",
    })]
    for name, text in [
        ("Crypt Sliver", 'All Slivers have "{T}: Regenerate target Sliver."'),
        ("Screeching Sliver", 'All Slivers have "{T}: Target player mills a card."'),
        ("Firewake Sliver", 'All Slivers have "{1}, Sacrifice this permanent: Target Sliver creature gets +2/+2 until end of turn."'),
        ("Magma Sliver", 'All Slivers have "{T}: Target Sliver creature gets +X/+0 until end of turn, where X is the number of Slivers on the battlefield."'),
    ]:
        card = Card(id=name, name=name, type_line="Creature — Sliver", is_creature=True, oracle_text=text)
        assert parse_oracle(card).coverage != UNMODELED


def test_basal_slivers_granted_mana_ability_retains_its_sacrifice_cost():
    eng = make_engine([creature("x")], [creature("y")])
    state = eng.state
    lord = obj_on_battlefield(
        state, eng,
        Card(id="basal", name="Basal Sliver", type_line="Creature — Sliver", is_creature=True,
             oracle_text='All Slivers have "Sacrifice this permanent: Add {B}{B}."'),
    )
    host = obj_on_battlefield(state, eng, Card(
        id="host", name="Host", type_line="Creature — Sliver", is_creature=True,
    ))
    bind_from_catalogue(lord)
    eng.recompute_continuous_effects()
    granted = [ability for ability in mana_abilities_for(host) if ability.cost.sacrifice == "self"]
    assert len(granted) == 1 and granted[0].options == [{"B": 2}]


def test_quoted_graveyard_replacement_is_a_generic_group_grant():
    eng = make_engine([creature("x")], [creature("y")])
    state = eng.state
    lord = obj_on_battlefield(state, eng, Card(
        id="redirect-lord", name="Any Lord", type_line="Creature — Sliver",
        is_creature=True,
        oracle_text=(
            'All Slivers have "If this permanent would be put into a graveyard, '
            'you may put it on top of its owner’s library instead."'
        ),
    ))
    host = obj_on_battlefield(state, eng, Card(
        id="redirect-host", name="Any Host", type_line="Creature — Sliver", is_creature=True,
    ))
    bind_from_catalogue(lord)
    eng.recompute_continuous_effects()
    assert host._graveyard_to_library_replacement

    eng.rules.put_into_graveyard(host)
    assert host.zone == Zone.LIBRARY
    assert state.player_by_id(host.owner_id).library[-1] is host


def test_quoted_type_choice_composes_existing_generic_effects():
    card = Card(
        id="type-lord", name="Any Lord", type_line="Creature — Wizard", is_creature=True,
        oracle_text=(
            'All Wizards have "{1}: This permanent becomes the creature type '
            'of your choice in addition to its other types until end of turn."'
        ),
    )
    spec = parse_oracle(card).specs[0].effects[0]
    assert spec.type == "grant_activated_ability"
    assert spec.params["subtype"] == "Wizard"
    assert spec.params["grant_effects"][0]["type"] == "_request_choose_creature_type_grant"


def test_random_hand_reveal_named_comparison_is_not_tribal_specific():
    eng = make_engine([creature("x")], [creature("y")])
    state = eng.state
    opponent = state.player_by_id("p2")
    named = GameObject(creature("Named Card"), owner_id="p2", zone=Zone.HAND)
    opponent.add_to_zone(named, Zone.HAND)

    effect = EffectRegistry.create("reveal_random_hand_card_if_named", {
        "named_card": "Named Card", "target_kind": "opponent",
    })
    effect.apply(eng.rules.context, [opponent])
    assert named.zone == Zone.GRAVEYARD


# --- execute -----------------------------------------------------------


def _counter_creature(state, eng, name, counters=0, controller="p1"):
    obj = obj_on_battlefield(state, eng, creature(name), controller=controller)
    if counters:
        obj.counters["+1/+1"] = counters
        obj.plus_one_counters = counters
    return obj


def test_counter_lord_only_grants_to_counter_bearers_you_control():
    eng = make_engine([creature("x")], [creature("y")])
    state = eng.state
    lord = obj_on_battlefield(
        state, eng,
        Card(id="af", name="Abzan Falconer", type_line="Creature — Soldier",
             is_creature=True, power=1, toughness=3,
             oracle_text="Each creature you control with a +1/+1 counter on it has flying."),
        controller="p1",
    )
    bind_from_catalogue(lord)

    buffed = _counter_creature(state, eng, "Buffed Ally", counters=1)
    plain = _counter_creature(state, eng, "Plain Ally", counters=0)
    their_buffed = _counter_creature(state, eng, "Their Buffed", counters=1, controller="p2")
    eng.recompute_continuous_effects()

    assert "flying" in buffed.granted_keywords
    assert "flying" not in plain.granted_keywords
    assert "flying" not in their_buffed.granted_keywords

    # remove the counter → the grant drops on the next recompute
    buffed.counters["+1/+1"] = 0
    buffed.plus_one_counters = 0
    eng.recompute_continuous_effects()
    assert "flying" not in buffed.granted_keywords
