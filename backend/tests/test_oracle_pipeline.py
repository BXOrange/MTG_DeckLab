"""Tests for the oracle-effect front-end pipeline (docs/09, Milestone 1).

Covers the four steps — normalize → segment → handler-match → coverage gate —
and the `parse_oracle` entry point, plus the end-to-end proof that a parsed
spell binds to real `GameEffect`s and resolves through the engine.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import DealDamageEffect, DrawCardEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import ALLOWED_TARGET_KINDS, spell_target_specs
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
    _TARGET_ROWS,
    count_of,
    resolve_target_kind,
)
from mtg_analyzer.parser.oracle.normalize import SELF, normalize
from mtg_analyzer.parser.oracle.segmenter import (
    _TRIGGER_EVENTS,
    is_keyword_line,
    parse_effect_body,
)
from mtg_analyzer.parser.oracle.spec import EffectSpec


# ---------------------------------------------------------------------------
# Card factories
# ---------------------------------------------------------------------------


def spell(name, text, *, instant=True, sorcery=False):
    return Card(
        id=name, name=name, type_line="Instant" if instant else "Sorcery",
        is_instant=instant, is_sorcery=sorcery, oracle_text=text,
    )


def perm(name, text, *, keywords=(), creature=True):
    return Card(
        id=name, name=name, type_line="Creature — Test", is_creature=creature,
        power=2, toughness=2, keywords=list(keywords), oracle_text=text,
    )


# ---------------------------------------------------------------------------
# NORMALIZE
# ---------------------------------------------------------------------------


def test_normalize_strips_reminder_and_folds_self_name():
    text = "Lightning Bolt deals three damage to any target. (It's electric.)"
    out = normalize(text, "Lightning Bolt")
    assert "(" not in out and "electric" not in out  # reminder gone
    assert SELF in out and "lightning bolt" not in out  # self-name folded
    assert "3 damage" in out  # "three" → 3


def test_normalize_preserves_newlines_as_ability_separators():
    out = normalize("Flying\nWhen this dies, draw a card.")
    assert out.split("\n") == ["flying", "when this dies, draw a card."]


def test_normalize_folds_only_short_number_words():
    assert normalize("draw seven cards") == "draw 7 cards"
    # "a"/"an" are NOT folded (too many non-numeric uses) — handled per-handler.
    assert normalize("draw a card") == "draw a card"


# ---------------------------------------------------------------------------
# SUB-GRAMMARS
# ---------------------------------------------------------------------------


def test_target_rows_all_resolve_to_allowed_kinds():
    # Every target row must map to a kind the engine actually understands.
    for _frag, kind in _TARGET_ROWS:
        assert kind in ALLOWED_TARGET_KINDS


def test_resolve_target_kind_specificity():
    assert resolve_target_kind("target creature or player") == "any"
    assert resolve_target_kind("target creature") == "creature"
    assert resolve_target_kind("any target") == "any"
    assert resolve_target_kind("target spell") == "spell"
    assert resolve_target_kind("target goblin wizard") is None  # unknown → fail-closed


def test_count_of():
    assert count_of("a") == 1 and count_of("an") == 1 and count_of("3") == 3


# ---------------------------------------------------------------------------
# HANDLERS via parse_effect_body
# ---------------------------------------------------------------------------


def test_handler_damage_carries_target_kind():
    effects = parse_effect_body("~ deals 3 damage to any target")
    assert [(e.type, e.params["amount"], e.params["target_kind"]) for e in effects] == [
        ("damage", 3, "any")
    ]


def test_handler_draw_and_gain_and_destroy_and_counter():
    assert parse_effect_body("draw a card")[0].params["count"] == 1
    assert parse_effect_body("draw 2 cards")[0].params["count"] == 2
    assert parse_effect_body("you gain 5 life")[0].params["amount"] == 5
    assert parse_effect_body("destroy target creature")[0].params["target_kind"] == "creature"
    assert parse_effect_body("counter target spell")[0].type == "counter"


def test_handler_chains_effects_on_and():
    effects = parse_effect_body("draw a card and you gain 3 life")
    assert [e.type for e in effects] == ["draw", "gain_life"]


def test_handler_mill_exile_tap_counters():
    assert parse_effect_body("mill 3 cards")[0].params == {"count": 3}
    tp = parse_effect_body("target player mills 4 cards")[0]
    assert tp.params == {"count": 4, "target_kind": "player"}
    assert parse_effect_body("exile target creature")[0].params == {"target_kind": "creature"}
    untap = parse_effect_body("untap target permanent")[0]
    assert untap.type == "tap" and untap.params["untap"] is True
    ctr = parse_effect_body("put 2 +1/+1 counters on target creature")[0]
    assert ctr.type == "add_counters"
    assert ctr.params == {"count": 2, "kind": "+1/+1", "target_kind": "creature"}


def test_add_counters_on_self_is_untargeted():
    # "on ~" (the folded self-name) buffs the source, not a target.
    effects = parse_effect_body("put a +1/+1 counter on ~")
    assert effects[0].type == "add_counters" and "target_kind" not in effects[0].params


def test_add_counters_targets_any_permanent_not_just_creatures():
    # +1/+1 counters can sit on any permanent (RULE 122.1a) — a land that later
    # animates uses them. The target phrase, not the counter, sets the kind.
    assert parse_effect_body("put a +1/+1 counter on target land")[0].params["target_kind"] == "permanent"
    assert parse_effect_body("put 2 +1/+1 counters on target permanent")[0].params["target_kind"] == "permanent"


def test_minus_counters_carry_the_minus_kind():
    effects = parse_effect_body("put a -1/-1 counter on target creature")
    assert effects[0].type == "add_counters"
    assert effects[0].params == {"count": 1, "kind": "-1/-1", "target_kind": "creature"}


def test_pump_handler_reads_signed_pt_and_target():
    plus = parse_effect_body("target creature gets +3/+3 until end of turn")[0]
    assert plus.type == "pump"
    assert plus.params == {"power": 3, "toughness": 3, "target_kind": "creature"}
    minus = parse_effect_body("target creature gets -2/-2 until end of turn")[0]
    assert minus.params == {"power": -2, "toughness": -2, "target_kind": "creature"}


def test_pump_handler_grants_keywords():
    both = parse_effect_body("target creature gets +1/+1 and gains trample until end of turn")[0]
    assert both.params["keywords"] == ["trample"]
    kw_only = parse_effect_body("target creature gains flying until end of turn")[0]
    assert kw_only.type == "pump" and kw_only.params["keywords"] == ["flying"]
    assert "power" not in kw_only.params


def test_pump_fails_closed_on_an_unmodeled_granted_ability():
    # "gains <non-flag-keyword> until end of turn" isn't safely modeled → unclaimed.
    assert parse_effect_body("target creature gains protection until end of turn") is None


def test_scry_handler():
    assert parse_effect_body("scry 3")[0] == EffectSpec("scry", {"count": 3})
    assert parse_effect_body("put a +1/+1 counter on target creature")[0].params["target_kind"] == "creature"


def test_surveil_handler():
    assert parse_effect_body("surveil 2")[0] == EffectSpec("surveil", {"count": 2})


def test_surveil_land_etb_trigger_is_fully_modeled():
    # The common real-card shape (Hedge Maze/Lush Portico/…, RULE 701.31):
    # a tap-land whose only other ability is "surveil 1" on enter.
    land = Card(
        id="Hedge Maze", name="Hedge Maze", type_line="Land", is_land=True,
        oracle_text="This land enters tapped.\nWhen this land enters, surveil 1.",
    )
    r = parse_oracle(land)
    assert r.coverage == MODELED
    (trig,) = [s for s in r.specs if s.ability_kind == "triggered"]
    assert trig.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert trig.effects[0] == EffectSpec("surveil", {"count": 1})


def test_handler_create_token():
    effects = parse_effect_body("create 2 1/1 white soldier creature tokens")
    (e,) = effects
    assert e.type == "create_token"
    assert e.params["count"] == 2 and e.params["power"] == 1 and e.params["toughness"] == 1
    assert e.params["colors"] == ["W"] and e.params["subtypes"] == ["Soldier"]


def test_create_token_with_flag_keyword():
    e = parse_effect_body("create a 2/2 blue drake creature token with flying")[0]
    assert e.params["keywords"] == ["flying"]


def _static_specs(text, *, tl="Enchantment", creature=False):
    card = Card(id="S", name="S", type_line=tl, is_creature=creature,
                oracle_text=text, keywords=[],
                **({"power": 2, "toughness": 2} if creature else {}))
    r = parse_oracle(card)
    return r, [s for s in r.specs if s.ability_kind == "static"]


def test_static_anthem_creatures_you_control():
    r, statics = _static_specs("Creatures you control get +1/+1.")
    assert r.coverage == MODELED and len(statics) == 1
    (e,) = statics[0].effects
    assert e.type == "anthem"
    assert e.params["power"] == 1 and e.params["affects"] == "creatures_you_control"


def test_static_tribal_lord_carries_subtype_and_other():
    _, statics = _static_specs("Other Goblins you control get +1/+1.", tl="Creature — Goblin", creature=True)
    (e,) = statics[0].effects
    assert e.params["subtype"] == "Goblin"
    assert e.params["affects"] == "other_creatures_you_control"


def test_static_irregular_plural_singularizes():
    _, statics = _static_specs("Other Elves you control get +1/+1.", tl="Creature — Elf", creature=True)
    assert statics[0].effects[0].params["subtype"] == "Elf"


def test_static_token_anthem():
    _, statics = _static_specs("Creature tokens you control get +1/+1.")
    e = statics[0].effects[0]
    assert e.params.get("tokens") is True and "subtype" not in e.params


def test_static_compound_anthem_and_keyword_grant():
    _, statics = _static_specs("Other Elves you control get +1/+1 and have haste.",
                               tl="Creature — Elf", creature=True)
    types = [e.type for e in statics[0].effects]
    assert types == ["anthem", "grant_keyword"]
    assert statics[0].effects[1].params["keywords"] == ["haste"]


def test_static_keyword_grant_only():
    _, statics = _static_specs("Creatures you control have trample.")
    e = statics[0].effects[0]
    assert e.type == "grant_keyword" and e.params["keywords"] == ["trample"]


def test_static_temporary_anthem_on_instant_is_not_static():
    # "until end of turn" is a one-shot temporary buff (not modeled), never a
    # standing static ability — and never claimed as one.
    r = parse_oracle(spell("Pump", "Creatures you control get +2/+2 until end of turn."))
    assert not any(s.ability_kind == "static" for s in r.specs)


def test_static_color_scoped_global_anthem():
    # Bad Moon: no "you control" → global; "black" → colour filter.
    _, statics = _static_specs("Black creatures get +1/+1.")
    e = statics[0].effects[0]
    assert e.params["affects"] == "all_creatures" and e.params["color"] == ["B"]


def test_static_color_scoped_you_control():
    _, statics = _static_specs("White creatures you control get +1/+1.")
    e = statics[0].effects[0]
    assert e.params["affects"] == "creatures_you_control" and e.params["color"] == ["W"]


def test_static_multicolor_scope():
    _, statics = _static_specs("White and blue creatures get +1/+1.")
    assert _static_specs("White and blue creatures get +1/+1.")[1][0].effects[0].params["color"] == ["W", "U"]


def test_static_global_keyword_grant():
    # "All creatures have haste" (Concordant Crossroads) — global, "all" marker.
    _, statics = _static_specs("All creatures have haste.")
    e = statics[0].effects[0]
    assert e.type == "grant_keyword" and e.params["affects"] == "all_creatures"


def test_static_noncreature_scope_is_unclaimed():
    # "Artifacts you control get +1/+1" isn't a creature anthem → fail-closed.
    r, statics = _static_specs("Artifacts you control get +1/+1.")
    assert statics == [] and r.coverage == UNMODELED


def test_static_granted_landwalk_is_unclaimed():
    # Landwalk is parametric (a land-type quality), not a flag keyword → the
    # whole compound clause is left unclaimed rather than dropping the ability.
    r, statics = _static_specs("Other Goblins you control get +1/+1 and have mountainwalk.",
                               tl="Creature — Goblin", creature=True)
    assert statics == [] and r.coverage == UNMODELED


def test_create_token_with_nonflag_ability_is_unclaimed():
    # A "with <activated/triggered ability>" token isn't a flag keyword → the
    # whole clause is left unclaimed rather than silently dropping the ability.
    assert parse_effect_body('create a 1/1 red devil creature token with "when this dies, deal 1 damage"') is None


def test_unhandled_clause_is_unclaimed():
    # "proliferate" / "fateseal" have no one-shot effect yet — fail-closed.
    assert parse_effect_body("proliferate") is None
    assert parse_effect_body("fateseal 2") is None
    # A half-known chain fails whole (fail-closed), not partially.
    assert parse_effect_body("draw a card and mill your opponent") is None


# ---------------------------------------------------------------------------
# SEGMENTER
# ---------------------------------------------------------------------------


def test_is_keyword_line():
    assert is_keyword_line("flying, vigilance") is True
    assert is_keyword_line("islandwalk") is True
    assert is_keyword_line("draw a card") is False


def test_trigger_events_are_valid_event_types():
    valid = {v for k, v in vars(EventType).items() if not k.startswith("_") and isinstance(v, str)}
    for _pat, event in _TRIGGER_EVENTS:
        assert event in valid


# ---------------------------------------------------------------------------
# COVERAGE GATE (parse_oracle)
# ---------------------------------------------------------------------------


def test_instant_damage_is_modeled_as_spell_effect():
    r = parse_oracle(spell("Bolt", "Bolt deals 3 damage to any target."))
    assert r.coverage == MODELED
    assert [s.ability_kind for s in r.specs] == ["spell_effect"]
    assert r.specs[0].effects[0].type == "damage"


def test_etb_trigger_is_modeled():
    r = parse_oracle(perm("Visionary", "When Visionary enters the battlefield, draw a card."))
    (trig,) = [s for s in r.specs if s.ability_kind == "triggered"]
    assert trig.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert trig.effects[0].type == "draw"
    assert r.coverage == MODELED


def test_you_may_sets_optional():
    r = parse_oracle(perm("X", "When X dies, you may draw a card."))
    trig = next(s for s in r.specs if s.ability_kind == "triggered")
    assert trig.optional is True and trig.trigger["event"] == "DIES"


def test_vanilla_creature_is_trivially_modeled():
    r = parse_oracle(perm("Bear", ""))
    assert r.coverage == MODELED and r.specs == []


def test_unknown_clause_makes_card_unmodeled():
    r = parse_oracle(spell("Weird", "Exile target creature. Its controller loses the game."))
    assert r.coverage == UNMODELED and r.unclaimed


def test_partial_card_is_unmodeled_all_or_nothing():
    # One line handled (draw), one not (fateseal) → the whole card is UNMODELED.
    r = parse_oracle(spell("Half", "Draw a card.\nFateseal 2."))
    assert r.coverage == UNMODELED


def test_permanent_bare_imperative_is_not_a_spell_effect():
    # A permanent's non-triggered imperative must NOT become a resolve-time
    # effect (it would fire wrongly) — left unclaimed instead (fail-closed).
    r = parse_oracle(perm("Odd", "Draw a card."))
    assert r.coverage == UNMODELED
    assert not any(s.ability_kind == "spell_effect" for s in r.specs)


def test_keyword_line_alone_is_modeled():
    r = parse_oracle(perm("Angel", "Flying, vigilance", keywords=["Flying", "Vigilance"]))
    assert r.coverage == MODELED
    assert {s.keyword["name"] for s in r.specs} == {"flying", "vigilance"}


# ---------------------------------------------------------------------------
# TRANSFORM + GROUP PUMP handlers (RULE 712.8)
# ---------------------------------------------------------------------------


def test_transform_handler_matches_self_forms():
    for clause in ("transform ~", "transform it", "transform this permanent", "transform this creature"):
        (e,) = parse_effect_body(clause)
        assert e.type == "transform" and e.params == {}


def test_group_pump_handler_creatures_you_control():
    e = parse_effect_body("creatures you control get +2/+1 until end of turn")[0]
    assert e.type == "pump"
    assert e.params == {"power": 2, "toughness": 1, "selector": "creatures_you_control"}
    other = parse_effect_body("other creatures you control get +1/+1 until end of turn")[0]
    assert other.params["selector"] == "other_creatures_you_control"
    kw = parse_effect_body("creatures you control gain flying until end of turn")[0]
    assert kw.params == {"keywords": ["flying"], "selector": "creatures_you_control"}


# ---------------------------------------------------------------------------
# SAGA chapter grammar (RULE 714.2d)
# ---------------------------------------------------------------------------


def saga_card(name, text):
    return Card(id=name, name=name, type_line="Enchantment — Saga", oracle_text=text)


def test_saga_chapter_lines_are_modeled_as_saga_chapter_triggers():
    r = parse_oracle(saga_card(
        "History of Benalia",
        "I, II — Create a 2/2 white Knight creature token with vigilance.\n"
        "III — Creatures you control get +2/+1 until end of turn.",
    ))
    assert r.coverage == MODELED
    triggers = [s for s in r.specs if s.ability_kind == "triggered"]
    assert len(triggers) == 2
    first, second = triggers
    assert first.trigger == {"event": "SAGA_CHAPTER", "chapter": [1, 2]}
    assert first.effects[0].type == "create_token"
    assert second.trigger == {"event": "SAGA_CHAPTER", "chapter": [3]}
    assert second.effects[0].type == "pump"
    assert second.effects[0].params["selector"] == "creatures_you_control"


def test_saga_chapter_grammar_does_not_misfire_on_a_non_saga_card():
    # A non-Saga permanent whose text happens to start with a roman-numeral-
    # dash shape must NOT be parsed as a chapter line (the `is_saga` gate).
    r = parse_oracle(perm("Weird", "I — Draw a card."))
    assert r.coverage == UNMODELED


# ---------------------------------------------------------------------------
# Leveler (RULE 711) / Class (RULE 716) block grammar
# ---------------------------------------------------------------------------


def test_leveler_blocks_are_modeled_with_level_gated_specs():
    r = parse_oracle(Card(
        id="Test Dragon", name="Test Dragon", type_line="Creature — Dragon",
        is_creature=True, power=1, toughness=1, keywords=["Level Up", "Flying", "Haste"],
        oracle_text=(
            "Level up {1}{R} (Level up only as a sorcery.)\n"
            "LEVEL 2-6\n2/2\n"
            "Whenever Test Dragon attacks, Test Dragon gets +1/+0 until end of turn.\n"
            "LEVEL 7+\n6/6\nFlying, haste"
        ),
    ))
    assert r.coverage == MODELED
    activated = [s for s in r.specs if s.ability_kind == "activated"]
    assert len(activated) == 1
    assert activated[0].effects[0].type == "add_counters"
    assert activated[0].cost == {"text": "{1}{r}", "sorcery_speed_only": True}

    statics = [s for s in r.specs if s.ability_kind == "static"]
    pt_sets = [s for s in statics if s.effects[0].type == "pt_set"]
    assert {(s.effects[0].params["min_level"], s.effects[0].params["max_level"]) for s in pt_sets} == {
        (2, 6), (7, None),
    }
    grant = next(s for s in statics if s.effects[0].type == "grant_keyword")
    assert grant.effects[0].params["min_level"] == 7 and grant.effects[0].params["max_level"] is None

    trigger = next(s for s in r.specs if s.ability_kind == "triggered")
    assert trigger.trigger["event"] == "ATTACKS"
    assert (trigger.trigger["min_level"], trigger.trigger["max_level"]) == (2, 6)


def test_class_blocks_are_modeled_with_cumulative_level_gated_specs():
    r = parse_oracle(Card(
        id="Test Class", name="Test Class", type_line="Enchantment — Class",
        oracle_text=(
            "(Gain the next level as a sorcery to add its ability.)\n"
            "{1}{G}: Level 2\nCreatures you control get +1/+1.\n"
            "{3}{G}: Level 3\nCreatures you control have trample."
        ),
    ))
    assert r.coverage == MODELED
    activated = [s for s in r.specs if s.ability_kind == "activated"]
    assert len(activated) == 2
    assert [a.cost["class_level"] for a in activated] == [2, 3]
    assert all(a.cost["sorcery_speed_only"] for a in activated)
    assert [a.effects[0].type for a in activated] == ["class_level", "class_level"]

    statics = [s for s in r.specs if s.ability_kind == "static"]
    anthem = next(s for s in statics if s.effects[0].type == "anthem")
    assert anthem.effects[0].params["min_level"] == 2
    assert anthem.effects[0].params["level_counter"] == "class_level"
    grant = next(s for s in statics if s.effects[0].type == "grant_keyword")
    assert grant.effects[0].params["min_level"] == 3
    assert grant.effects[0].params["level_counter"] == "class_level"


def test_class_level_header_is_cost_first_not_level_first():
    # Real Scryfall oracle text prints "<cost>: Level N" (cost precedes
    # "Level N" on the header line, e.g. Cleric Class's "{3}{W}: Level 2") —
    # not "Level N: <cost>". A card using the wrong (level-first) order
    # must fail closed rather than silently match, so a future regression
    # back to that assumption shows up as an unclaimed line, not a
    # mis-parsed one.
    from mtg_analyzer.parser.oracle.catalogue.levels import CLASS_LEVEL_RE

    assert CLASS_LEVEL_RE.match("{1}{g}: level 2") is not None
    assert CLASS_LEVEL_RE.match("level 2: {1}{g}") is None

    r = parse_oracle(Card(
        id="Cleric Class", name="Cleric Class", type_line="Enchantment — Class",
        oracle_text=(
            "(Gain the next level as a sorcery to add its ability.)\n"
            "level 2: {1}{g}\nCreatures you control get +1/+1."
        ),
    ))
    assert r.coverage == UNMODELED
    assert any("level 2: {1}{g}" in u for u in r.unclaimed)


# ---------------------------------------------------------------------------
# INTEGRATION: specs_for fallback + binding
# ---------------------------------------------------------------------------


def test_specs_for_uses_parser_for_unregistered_modeled_card():
    specs = ability_catalogue.specs_for(spell("Bolt", "Bolt deals 3 damage to any target."))
    assert any(s.ability_kind == "spell_effect" for s in specs)


def test_specs_for_omits_effects_from_unmodeled_card():
    specs = ability_catalogue.specs_for(spell("Weird", "Fateseal 2."))
    assert not any(s.ability_kind in ("spell_effect", "triggered") for s in specs)


def test_bind_spell_effect_produces_damage_effect():
    obj = GameObject(spell("Bolt", "Bolt deals 3 damage to any target."),
                     owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    assert len(obj.spell_effects) == 1
    assert isinstance(obj.spell_effects[0], DealDamageEffect)
    assert obj.spell_effects[0].amount == 3
    assert [t.kind for t in spell_target_specs(obj)] == ["any"]


def test_activated_ability_is_modeled_with_cost():
    r = parse_oracle(perm("Sorcerer", "{T}: Sorcerer deals 1 damage to any target."))
    (act,) = [s for s in r.specs if s.ability_kind == "activated"]
    assert r.coverage == MODELED
    assert act.cost == {"text": "{t}"}
    assert act.effects[0].type == "damage" and act.effects[0].params["amount"] == 1


def test_activated_ability_chains_effects():
    r = parse_oracle(perm("Looter", "{T}: Draw a card, then discard a card."))
    act = next(s for s in r.specs if s.ability_kind == "activated")
    assert [e.type for e in act.effects] == ["draw", "discard"]


def test_mana_ability_line_is_covered_without_a_spec():
    # The engine models mana abilities separately, so the card is MODELED but
    # the "add" line yields no effect spec.
    r = parse_oracle(Card(id="Rock", name="Rock", type_line="Artifact",
                          oracle_text="{T}: Add one mana of any color."))
    assert r.coverage == MODELED
    assert not any(s.ability_kind == "activated" for s in r.specs)


def test_loyalty_ability_is_modeled_as_an_activated_ability():
    # "[+1]: <effect>" now parses into an activated ability with a loyalty cost
    # (RULE 606.5c).
    r = parse_oracle(Card(id="PW", name="Walker", type_line="Planeswalker",
                          oracle_text="[+1]: Draw a card."))
    assert r.coverage == MODELED
    loyalty_specs = [s for s in r.specs if s.ability_kind == "activated"]
    assert len(loyalty_specs) == 1
    assert loyalty_specs[0].cost == {"loyalty": 1}


def test_bind_activated_ability_from_text():
    obj = GameObject(perm("Looter", "{T}: Draw a card, then discard a card."),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert len(obj.activated_abilities) == 1
    ability = obj.activated_abilities[0]
    assert ability.cost.taps_self is True
    assert len(ability.effects) == 2


def test_bind_etb_trigger_produces_triggered_ability():
    obj = GameObject(perm("Visionary", "When Visionary enters the battlefield, draw a card."),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert len(obj.triggered_abilities) == 1
    assert obj.triggered_abilities[0].trigger_event == EventType.ENTERS_BATTLEFIELD


def test_parsed_sorcery_draws_when_resolved_end_to_end():
    # Full loop: parse "Draw two cards" → bind → cast → resolve → cards drawn.
    divination = spell("Divination", "Draw two cards.", instant=False, sorcery=True)
    eng = GameEngine.new_game([("p1", "Alice", [land_card()] * 10)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = GameObject(divination, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    before = len(p1.hand)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    # Cast removed Divination from hand (-1) then it drew 2 (+2) → net +1.
    assert len(p1.hand) == before - 1 + 2


def test_parsed_mill_sorcery_mills_when_resolved_end_to_end():
    # "Mill three cards." → self-mill: top 3 of library go to the graveyard.
    tome = spell("Tome", "Mill three cards.", instant=False, sorcery=True)
    eng = GameEngine.new_game([("p1", "Alice", [land_card()] * 10)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj = GameObject(tome, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.add_to_zone(obj, Zone.HAND)
    lib_before = len(p1.library)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert len(p1.library) == lib_before - 3
    # 3 milled Forests, plus the resolved sorcery itself lands in the graveyard.
    assert sum(1 for o in p1.graveyard if o.name == "Forest") == 3
    assert obj in p1.graveyard


def land_card():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


# ---------------------------------------------------------------------------
# PROCESSING LIST + COVERAGE METRIC
# ---------------------------------------------------------------------------


def test_abstract_clause_folds_literals_to_templates():
    from mtg_analyzer.parser.oracle import abstract_clause

    # Numbers, mana costs, the self-name and quoted names all abstract away, so
    # differently-worded clauses of the same shape fold together.
    a = abstract_clause("~ deals 3 damage to target goblin")
    b = abstract_clause("~ deals 7 damage to target goblin")
    assert a == b == "<name> deals <n> damage to target goblin"
    assert abstract_clause("mill {2}{r} cards") == "mill <cost> cards"


def test_coverage_report_metric_and_ranking():
    from mtg_analyzer.parser.oracle import coverage_over_cards

    cards = [
        spell("Bolt", "Bolt deals 3 damage to any target."),         # MODELED
        spell("Divi", "Draw two cards.", instant=False, sorcery=True),  # MODELED
        spell("FateA", "Fateseal 2."),                                # unclaimed: fateseal
        spell("FateB", "Fateseal 2."),                                # same template
        spell("Scry", "Scry 2."),                                    # unclaimed: scry
    ]
    report = coverage_over_cards(cards)
    assert report.total == 5 and report.modeled == 2
    assert report.modeled_fraction == 0.4
    # The fateseal template blocks 2 cards, scry 1 → fateseal ranks first.
    top = report.processing_list[0]
    assert top.cards == 2 and "fateseal" in top.template
    assert report.to_dict()["modeled"] == 2


# ---------------------------------------------------------------------------
# PARSE-ON-LOAD MEMOIZATION
# ---------------------------------------------------------------------------


def test_parse_oracle_caches_identical_input(monkeypatch):
    from mtg_analyzer.parser.oracle import gate as oracle_gate

    calls = []
    real = oracle_gate._parse_oracle_uncached

    def counting(card):
        calls.append(card)
        return real(card)

    monkeypatch.setattr(oracle_gate, "_parse_oracle_uncached", counting)
    oracle_gate._PARSE_CACHE.clear()

    # Two separate Card instances with identical relevant fields — the
    # second call must be a cache hit, not a second full parse.
    oracle_gate.parse_oracle(spell("Bolt", "Bolt deals 3 damage to any target."))
    oracle_gate.parse_oracle(spell("Bolt", "Bolt deals 3 damage to any target."))
    assert len(calls) == 1


def test_parse_oracle_returns_independent_copies():
    from mtg_analyzer.parser.oracle import gate as oracle_gate

    oracle_gate._PARSE_CACHE.clear()
    card = spell("Shock", "Shock deals 2 damage to any target.")

    first = oracle_gate.parse_oracle(card)
    first.specs.append("mutated")  # type: ignore[arg-type]
    first.unclaimed.append("mutated")

    second = oracle_gate.parse_oracle(card)
    assert "mutated" not in second.specs
    assert "mutated" not in second.unclaimed


def test_parse_oracle_cache_key_distinguishes_oracle_text():
    # Same name, different text must not collide (a content-keyed cache, not
    # a name-keyed one) — this is what guards a per-test fixture card from a
    # stale hit left behind by an earlier test using the same placeholder name.
    from mtg_analyzer.parser.oracle import gate as oracle_gate

    oracle_gate._PARSE_CACHE.clear()
    r_damage = oracle_gate.parse_oracle(spell("Same Name", "Same Name deals 3 damage to any target."))
    r_draw = oracle_gate.parse_oracle(spell("Same Name", "Draw a card."))

    damage_types = {e.type for s in r_damage.specs for e in s.effects}
    draw_types = {e.type for s in r_draw.specs for e in s.effects}
    assert "damage" in damage_types
    assert "draw" in draw_types


def test_parse_oracle_cache_key_distinguishes_spell_vs_permanent():
    # Same name/text, but `is_instant` differs — a bare imperative is a
    # legal spell effect on an instant, and fail-closed unclaimed on a
    # permanent (RULE 113.2). The cache key must not conflate the two.
    from mtg_analyzer.parser.oracle import gate as oracle_gate

    oracle_gate._PARSE_CACHE.clear()
    text = "Draw a card."
    r_spell = oracle_gate.parse_oracle(spell("Card Draw", text))
    r_permanent = oracle_gate.parse_oracle(perm("Card Draw", text))

    assert r_spell.modeled
    assert not r_permanent.modeled
