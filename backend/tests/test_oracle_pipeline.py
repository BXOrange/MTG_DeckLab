"""Tests for the oracle-effect front-end pipeline (docs/09, Milestone 1).

Covers the four steps — normalize → segment → handler-match → coverage gate —
and the `parse_oracle` entry point, plus the end-to-end proof that a parsed
spell binds to real `GameEffect`s and resolves through the engine.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import ability_catalogue, combat, continuous
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
from mtg_analyzer.parser.oracle.normalize import SELF, _fold_self_name, normalize
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


def test_normalize_folds_leading_until_end_of_turn_to_trailing_form():
    # Triumph of the Hordes-shaped: "Until end of turn, X." means the same
    # thing as the far more common trailing "X until end of turn." every
    # handler's grammar already expects.
    out = normalize("Until end of turn, creatures you control get +1/+1 and gain trample and infect.")
    assert out == "creatures you control get +1/+1 and gain trample and infect until end of turn."


def test_normalize_leaves_multi_sentence_leading_until_end_of_turn_alone():
    # A quoted granted ability can carry its own internal period (Bail
    # Out-shaped) — folding "up to the first period" would relocate the
    # duration into the middle of that quote, so the fold only applies to a
    # genuinely single-sentence line (no embedded period before the last).
    text = (
        'until end of turn, target creature you control gains "when ~ dies, '
        'return it to the battlefield tapped under its owner\'s control. '
        'It deals 1 damage to each opponent."'
    )
    out = normalize(text)
    assert out.startswith("until end of turn, ")


def test_normalize_folds_alchemy_a_prefix_self_reference():
    # PAR-4: an MTG Arena "Alchemy" rebalance is named with Scryfall's own
    # "A-" prefix, but its own oracle text keeps self-referring by the
    # un-prefixed base name (A-Thran Portal's "Thran Portal is the chosen
    # type...") — both the printed and the un-prefixed form must fold.
    text = "As A-Thran Portal enters, choose a basic land type.\nThran Portal is the chosen type."
    out = normalize(text, "A-Thran Portal")
    assert "thran portal" not in out
    assert out.count(SELF) == 2


def test_normalize_folds_comma_less_legendary_given_name():
    # "Kaalia of the Vast" self-refers as "Kaalia" — the given name (the
    # single word before " of ") folds to ~ where it's a genuine
    # self-reference.
    out = normalize(
        "Whenever Kaalia attacks an opponent, you may put a Demon creature "
        "card from your hand onto the battlefield.",
        "Kaalia of the Vast",
    )
    assert out.startswith(f"whenever {SELF} attacks an opponent")
    # a possessive / mid-sentence occurrence folds too
    out2 = normalize(
        "Whenever you gain life, put two +1/+1 counters on Karlov.",
        "Karlov of the Ghost Council",
    )
    assert out2 == f"whenever you gain life, put 2 +1/+1 counters on {SELF}."


def test_normalize_given_name_prefix_keeps_a_creature_type_reading():
    # "Cleric of Life's Bond" → "another Cleric you control" is a tribal
    # filter, not a self-reference; "Knight of the New Coalition" → "a …
    # Knight creature token" is a token subtype; "Fear of Fear Itself" →
    # "gains fear until end of turn" is the keyword. None fold.
    assert "another cleric you control" in normalize(
        "Whenever another Cleric you control enters, you gain 1 life.",
        "Cleric of Life's Bond",
    )
    assert "knight creature token" in normalize(
        "When this creature enters, create a 2/2 white and blue Knight "
        "creature token with vigilance.",
        "Knight of the New Coalition",
    )
    assert "gains fear until end of turn" in normalize(
        "{2}: Target creature gains fear until end of turn.",
        "Fear of Fear Itself",
    )


def test_normalize_given_name_prefix_only_when_single_word_and_has_of():
    # "Ghost Council of Orzhova" — the pre-" of " span is two words, so
    # nothing extra folds (and "Ghost"/"Council" alone must not).
    out = normalize(
        "Whenever Ghost Council of Orzhova attacks, target opponent loses 1 life.",
        "Ghost Council of Orzhova",
    )
    assert out == f"whenever {SELF} attacks, target opponent loses 1 life."
    # a comma name is unaffected by the new prefix path
    assert normalize("Krenko, Mob Boss taps.", "Krenko, Mob Boss") == f"{SELF} taps."


def test_fold_self_name_does_not_strip_a_prefix_when_next_char_not_a_letter():
    # Guard against a name that merely starts with "A-" followed by
    # something that isn't the Alchemy rebalance convention (a digit) —
    # no real card does this, but the stripped form should never be
    # produced from garbage input: "1" alone must stay untouched even
    # though the full name "A- 1" still folds.
    out = _fold_self_name("A- 1 is great, unlike 1.", "A- 1")
    assert out == f"{SELF} is great, unlike 1."


def test_normalize_strips_a_one_off_flavor_keyword_label():
    # Universes Beyond sets mint card-specific "Name — <effect>" labels
    # (Jumbo Cactuar's real printed text) using the exact RULE 207.2c
    # ability-word template, but for a one-off name no fixed whitelist can
    # ever enumerate — Scryfall's own per-card `keywords` array is what
    # confirms "10,000 Needles" is being used label-style here.
    text = "10,000 Needles — Whenever this creature attacks, it gets +9999/+0 until end of turn."
    out = normalize(text, keywords=["10,000 Needles"])
    assert out == "whenever ~ attacks, it gets +9999/+0 until end of turn."


def test_normalize_strips_an_ability_word_not_on_the_fixed_evergreen_list():
    # Threshold isn't in `_ABILITY_WORD_RE`'s small hand-maintained list,
    # but it's a real RULE 207.2c ability word Scryfall tags the same way —
    # the keywords-driven strip catches it too, generically.
    text = "Threshold — Enchanted creature has shroud as long as there are 7 or more cards in your graveyard."
    out = normalize(text, keywords=["Threshold"])
    assert out == "enchanted creature has shroud as long as there are 7 or more cards in your graveyard."


def test_normalize_never_strips_a_registered_real_keywords_own_line():
    # A genuine flag/parametric keyword's own bare line must never be
    # touched by this mechanism — only a string Scryfall lists that ISN'T
    # one of our registered RULE 701/702 keywords is a strip candidate.
    text = "Flying — this text should never appear, but the label must survive."
    out = normalize(text, keywords=["Flying"])
    assert out.startswith("flying —")


def test_normalize_keywords_param_is_optional_and_backward_compatible():
    text = "Flying\nVigilance"
    assert normalize(text) == normalize(text, keywords=None) == normalize(text, keywords=[])


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
    # animates uses them. The target phrase, not the counter, sets the kind:
    # "target land" is land-only (RULE 115.1c), "target permanent" is unscoped.
    assert parse_effect_body("put a +1/+1 counter on target land")[0].params["target_kind"] == "land"
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
    # "Artifacts you control get +1/+1" isn't a creature anthem → fail-closed
    # (PAR-3 deliberately keeps `_ANTHEM_RE` creature-only — a bare "+N/+N"
    # on a non-creature permanent is never printed on a real card).
    r, statics = _static_specs("Artifacts you control get +1/+1.")
    assert statics == [] and r.coverage == UNMODELED


# --- PAR-3: non-creature group scopes (keyword-grant/quoted-grant only) ----


def test_static_card_type_narrowed_creature_anthem():
    # "Other artifact creatures you control get +1/+1." (Chief of the
    # Foundry) — still a *creature* scope (RULE 205.2b), just narrowed by
    # the printed card type rather than a creature subtype: `card_type`,
    # not `subtype` ("Artifact" is never a subtype `_has_subtype` would see).
    _, statics = _static_specs(
        "Other artifact creatures you control get +1/+1.", tl="Artifact Creature", creature=True,
    )
    e = statics[0].effects[0]
    assert e.type == "anthem"
    assert e.params["affects"] == "other_creatures_you_control"
    assert e.params["card_type"] == "artifact"
    assert "subtype" not in e.params


def test_static_bare_artifact_scope_keyword_grant():
    # "Artifacts you control have hexproof." (Leonin Abunas) — a bare
    # non-creature scope; `artifacts_you_control` already filters by type on
    # its own, so no extra `card_type` param is needed.
    _, statics = _static_specs("Artifacts you control have hexproof.")
    e = statics[0].effects[0]
    assert e.type == "grant_keyword" and e.params["keywords"] == ["hexproof"]
    assert e.params["affects"] == "artifacts_you_control"
    assert "card_type" not in e.params


def test_static_bare_enchantment_scope_needs_card_type_filter():
    # "enchantments" has no dedicated selector, unlike artifacts/lands — it
    # rides the broader `permanents_you_control`, narrowed by `card_type`.
    _, statics = _static_specs("Other enchantments you control have shroud.")
    e = statics[0].effects[0]
    assert e.params["affects"] == "permanents_you_control"
    assert e.params["card_type"] == "enchantment"


def test_static_global_noncreature_scope_quoted_grant_excludes_self():
    # "Other enchantments have '…'" (Aura Flux) — global (no "you control"),
    # "other" excludes just the source, same treatment `_scope_params` gives
    # a global "Other creatures …" anthem.
    _, statics = _static_specs(
        'Other enchantments have "At the beginning of your upkeep, '
        'sacrifice this enchantment unless you pay {2}."'
    )
    e = statics[0].effects[0]
    assert e.params["affects"] == "all_permanents"
    assert e.params["card_type"] == "enchantment"
    assert e.params["exclude_self"] is True


def test_static_bare_land_scope_uses_dedicated_selector():
    _, statics = _static_specs("Lands you control have \"{T}: Add {C}.\"")
    e = statics[0].effects[0]
    assert e.params["affects"] == "lands_you_control"
    assert "card_type" not in e.params


def test_static_compound_noncreature_scope_stays_unclaimed():
    # "Artifacts and enchantments you control have shroud." (Fountain Watch)
    # — no engine selector ORs two card types yet, so this deliberately
    # stays fail-closed rather than guessing (PAR-3 is single-word only).
    r, statics = _static_specs("Artifacts and enchantments you control have shroud.")
    assert statics == [] and r.coverage == UNMODELED


def test_static_enchanted_creatures_group_scope_stays_unclaimed():
    # "Enchanted creatures you control get +2/+2." (A Tale for the Ages) —
    # a characteristic filter, not a subtype; guessing one ("Enchanted")
    # would silently match no real creature's type line, so this stays
    # fail-closed instead of half-modeled (PAR-3 spot-check finding).
    r, statics = _static_specs("Enchanted creatures you control get +2/+2.")
    assert statics == [] and r.coverage == UNMODELED


def test_noncreature_scope_grant_applies_to_real_battlefield_objects():
    # End-to-end (docs/09's "parse-only has masked runtime bugs" lesson):
    # a Leonin Abunas-shaped card actually grants hexproof to artifacts on a
    # real battlefield, and leaves non-artifacts untouched.
    from mtg_analyzer.models.game_state import GameState
    from mtg_analyzer.models.player import Player

    lord_card = Card(
        id="Leonin Abunas Shaped", name="Leonin Abunas Shaped", type_line="Creature — Cat Cleric",
        is_creature=True, power=1, toughness=2,
        oracle_text="Artifacts you control have hexproof.",
    )
    artifact_card = Card(id="Some Artifact", name="Some Artifact", type_line="Artifact")
    bear_card = Card(
        id="Some Bear", name="Some Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2,
    )

    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])

    def put(card):
        obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        bind_from_catalogue(obj)
        state.add_to_battlefield(obj)
        return obj

    put(lord_card)
    artifact = put(artifact_card)
    bear = put(bear_card)

    continuous.recompute(state)
    assert combat.has_hexproof(artifact)
    assert not combat.has_hexproof(bear)


def test_global_noncreature_scope_grant_excludes_the_source():
    # An Aura-Flux-shaped card granting to "other enchantments" (global,
    # no "you control") must not grant to itself.
    from mtg_analyzer.models.game_state import GameState
    from mtg_analyzer.models.player import Player

    aura_flux_shaped = Card(
        id="Aura Flux Shaped", name="Aura Flux Shaped", type_line="Enchantment",
        oracle_text='Other enchantments have "{T}: Add {C}."',
    )
    other_enchantment = Card(id="Other Enchantment", name="Other Enchantment", type_line="Enchantment")

    state = GameState(players=[Player(id="p1", life=20), Player(id="p2", life=20)])

    def put(card, controller="p1"):
        obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        bind_from_catalogue(obj)
        state.add_to_battlefield(obj)
        return obj

    source = put(aura_flux_shaped)
    other = put(other_enchantment, controller="p2")

    continuous.recompute(state)
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    assert mana_abilities_for(other)
    assert not mana_abilities_for(source)


def test_static_granted_landwalk_is_claimed_via_its_raw_variant_slug():
    # Card-pool Batch 7: landwalk is parametric (a land-type quality), but the
    # grant mechanism only ever needs the raw variant slug ("mountainwalk") —
    # `combat._landwalk_slugs` matches any `granted_keywords` entry ending in
    # "walk" directly — so this is claimed now, unlike every *other*
    # parametric keyword grant (e.g. "protection from X"), which still needs
    # a quality param the grant can't express and stays unclaimed.
    r, statics = _static_specs("Other Goblins you control get +1/+1 and have mountainwalk.",
                               tl="Creature — Goblin", creature=True)
    assert r.coverage != UNMODELED
    kws = [s for s in statics[0].effects if s.type == "grant_keyword"][0]
    assert kws.params["keywords"] == ["mountainwalk"]


def test_create_token_with_nonflag_ability_is_unclaimed():
    # A "with <activated/triggered ability>" token isn't a flag keyword → the
    # whole clause is left unclaimed rather than silently dropping the ability.
    assert parse_effect_body('create a 1/1 red devil creature token with "when this dies, deal 1 damage"') is None


def test_unhandled_clause_is_unclaimed():
    # "fateseal" has no one-shot effect yet — fail-closed. ("proliferate" was
    # this family's other example pre-Batch-5; it's modeled now — see
    # test_modal_and_creature_filter_family.py.)
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


def test_draw_recognizes_targeted_and_mass_forms():
    # Kenrith/Oona's Grace-shaped: "target player/opponent draws a card" is
    # a real RULE 115 target, not the source's own controller drawing —
    # mirrors `_discard`'s pre-existing ``who`` treatment.
    bare = parse_effect_body("draw a card")[0]
    assert bare.type == "draw" and bare.params == {"count": 1}
    you = parse_effect_body("you draw a card")[0]
    assert you.params == {"count": 1}
    targeted = parse_effect_body("target player draws a card")[0]
    assert targeted.params == {"count": 1, "target_kind": "player"}
    opponent = parse_effect_body("target opponent draws 2 cards")[0]
    assert opponent.params == {"count": 2, "target_kind": "player"}
    each = parse_effect_body("each opponent draws a card")[0]
    assert each.params == {"count": 1, "selector": "each_opponent"}


def test_kenrith_targeted_draw_ability_is_fully_modeled():
    card = Card(
        id="Kenrith, the Returned King", name="Kenrith, the Returned King",
        type_line="Legendary Creature — Human Noble", is_creature=True,
        power=4, toughness=4,
        oracle_text="{R}: All creatures gain trample and haste until end of turn.\n"
                     "{1}{G}: Put a +1/+1 counter on target creature.\n"
                     "{2}{W}: Target player gains 5 life.\n"
                     "{3}{U}: Target player draws a card.\n"
                     "{4}{B}: Put target creature card from a graveyard onto the "
                     "battlefield under its owner's control.",
    )
    result = parse_oracle(card)
    assert result.modeled


def test_group_pump_handler_creatures_you_control():
    e = parse_effect_body("creatures you control get +2/+1 until end of turn")[0]
    assert e.type == "pump"
    assert e.params == {"power": 2, "toughness": 1, "selector": "creatures_you_control"}
    other = parse_effect_body("other creatures you control get +1/+1 until end of turn")[0]
    assert other.params["selector"] == "other_creatures_you_control"
    kw = parse_effect_body("creatures you control gain flying until end of turn")[0]
    assert kw.params == {"keywords": ["flying"], "selector": "creatures_you_control"}


def test_pump_grant_handles_a_two_keyword_conjunction():
    # Triumph of the Hordes-shaped: "gain X and Y" (as opposed to a single
    # granted keyword) — the leading "Until end of turn," is folded to this
    # trailing form by `normalize` before the segmenter ever sees it.
    e = parse_effect_body(
        "creatures you control get +1/+1 and gain trample and infect until end of turn"
    )[0]
    assert e.type == "pump"
    assert e.params == {
        "power": 1, "toughness": 1,
        "keywords": ["trample", "infect"],
        "selector": "creatures_you_control",
    }


def test_triumph_of_the_hordes_is_fully_modeled_end_to_end():
    card = spell(
        "Triumph of the Hordes",
        "Until end of turn, creatures you control get +1/+1 and gain trample and infect. "
        "(Creatures with infect deal damage to creatures in the form of -1/-1 counters "
        "and to players in the form of poison counters.)",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert len(result.specs) == 1
    assert result.specs[0].effects[0].params["keywords"] == ["trample", "infect"]


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


def test_remove_counter_cost_line_is_modeled():
    # RULE 701.19/602.1: a "Remove a <kind> counter from ~:" cost with no
    # mana/{T} alongside it used to fail `segmenter._COST_LOOKS_REAL`'s sniff
    # (only "{...}"/sacrifice/pay life/discard/put-a-counter-on/tap-others
    # were trusted), so the whole line stayed unclaimed. Triskelion's real
    # oracle text is exactly this shape end to end.
    r = parse_oracle(perm(
        "Triskelion",
        "Triskelion enters the battlefield with three +1/+1 counters on it.\n"
        "Remove a +1/+1 counter from Triskelion: It deals 1 damage to any target.",
    ))
    assert r.coverage == MODELED
    (act,) = [s for s in r.specs if s.ability_kind == "activated"]
    assert act.cost == {"text": "remove a +1/+1 counter from ~"}
    assert act.effects[0].type == "damage" and act.effects[0].params["amount"] == 1


def test_remove_counter_cost_binds_and_pays_end_to_end():
    obj = GameObject(perm(
        "Triskelion",
        "Remove a +1/+1 counter from Triskelion: It deals 1 damage to any target.",
    ), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    (ability,) = obj.activated_abilities
    assert ability.cost.remove_counters == ("+1/+1", 1)

    eng = GameEngine.new_game([("p1", "Alice", [land_card()] * 10)], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    obj.controller_id = p1.id
    eng.state.battlefield.append(obj)
    assert not eng.can_activate(p1, obj, ability)  # no counters yet
    obj.add_counters("+1/+1", 1)
    assert eng.can_activate(p1, obj, ability)
    eng.activate_ability(p1, obj, targets=[p1])
    assert obj.counters.get("+1/+1") is None  # the one counter was removed to pay


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
