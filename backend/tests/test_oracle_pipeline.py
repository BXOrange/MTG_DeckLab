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
    pump = parse_effect_body("put 2 +1/+1 counters on target creature")[0]
    assert pump.type == "add_counters" and pump.params == {"count": 2, "target_kind": "creature"}


def test_add_counters_on_self_is_untargeted():
    # "on ~" (the folded self-name) buffs the source, not a target.
    effects = parse_effect_body("put a +1/+1 counter on ~")
    assert effects[0].type == "add_counters" and "target_kind" not in effects[0].params


def test_add_counters_targets_any_permanent_not_just_creatures():
    # +1/+1 counters can sit on any permanent (RULE 122.1a) — a land that later
    # animates uses them. The target phrase, not the counter, sets the kind.
    assert parse_effect_body("put a +1/+1 counter on target land")[0].params["target_kind"] == "permanent"
    assert parse_effect_body("put 2 +1/+1 counters on target permanent")[0].params["target_kind"] == "permanent"
    assert parse_effect_body("put a +1/+1 counter on target creature")[0].params["target_kind"] == "creature"


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
    assert parse_effect_body("scry 2") is None
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
    # One line handled (draw), one not (regenerate) → the whole card is UNMODELED.
    r = parse_oracle(spell("Half", "Draw a card.\nRegenerate target creature."))
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
# INTEGRATION: specs_for fallback + binding
# ---------------------------------------------------------------------------


def test_specs_for_uses_parser_for_unregistered_modeled_card():
    specs = ability_catalogue.specs_for(spell("Bolt", "Bolt deals 3 damage to any target."))
    assert any(s.ability_kind == "spell_effect" for s in specs)


def test_specs_for_omits_effects_from_unmodeled_card():
    specs = ability_catalogue.specs_for(spell("Weird", "Regenerate target creature."))
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


def test_loyalty_ability_is_unmodeled_for_now():
    # "[+1]: ..." isn't a real mana/tap cost — deferred to M4 (RULE 606).
    r = parse_oracle(Card(id="PW", name="Walker", type_line="Planeswalker",
                          oracle_text="[+1]: Draw a card."))
    assert r.coverage == UNMODELED


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
        spell("RegenA", "Regenerate target creature."),              # unclaimed: regen
        spell("RegenB", "Regenerate target creature."),              # same template
        spell("Scry", "Scry 2."),                                    # unclaimed: scry
    ]
    report = coverage_over_cards(cards)
    assert report.total == 5 and report.modeled == 2
    assert report.modeled_fraction == 0.4
    # The regenerate template blocks 2 cards, scry 1 → regenerate ranks first.
    top = report.processing_list[0]
    assert top.cards == 2 and "regenerate" in top.template
    assert report.to_dict()["modeled"] == 2
