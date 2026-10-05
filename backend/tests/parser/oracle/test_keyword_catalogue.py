"""Tests for the RULE 702 keyword catalogue (parser front-end, docs/09).

Covers the vocabulary's integrity (every keyword classified, every parametric
one with a working extractor) and `parse_keywords` anchoring on Scryfall's
``keywords`` array + pulling the parameter out of oracle text.
"""

import re

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.keywords import (
    KEYWORDS,
    KeywordShape,
    keyword_slug,
    parse_keywords,
)


def _card(keywords, oracle_text="", **kw):
    return Card(
        id="T", name="T", type_line="Creature", is_creature=True,
        power=1, toughness=1, keywords=list(keywords), oracle_text=oracle_text, **kw
    )


# --- Catalogue integrity ----------------------------------------------------


class TestCatalogueIntegrity:
    def test_covers_the_whole_rule_702_range(self):
        # Every keyword ability 702.2 .. 702.194 has a row (Daybound/Nightbound
        # share 702.145, ∞ is 702.186); expect the full 194-keyword vocabulary.
        assert len(KEYWORDS) >= 193
        rules = {kd.rule for kd in KEYWORDS.values()}
        assert "702.9" in rules and "702.194" in rules

    def test_every_parametric_keyword_has_an_extractor(self):
        for kd in KEYWORDS.values():
            if kd.is_parametric:
                assert kd.regex is not None, f"{kd.slug} has no extractor regex"
            else:
                assert kd.regex is None, f"flag {kd.slug} should carry no regex"

    def test_slugs_are_canonical(self):
        assert keyword_slug("First Strike") == "first_strike"
        assert keyword_slug("Jump-Start") == "jump_start"
        assert keyword_slug("For Mirrodin!") == "for_mirrodin"
        assert keyword_slug("∞") == "infinity"

    def test_aliases_resolve_to_base_keyword(self):
        assert keyword_slug("Multikicker") == "kicker"
        assert keyword_slug("Megamorph") == "morph"
        assert keyword_slug("Totem armor") == "umbra_armor"


# --- Flag keywords ----------------------------------------------------------


class TestFlagKeywords:
    def test_flying_is_a_bare_keyword_spec(self):
        specs = parse_keywords(_card(["Flying"], "Flying"))
        assert len(specs) == 1
        assert specs[0].ability_kind == "keyword"
        assert specs[0].keyword == {"name": "flying"}
        assert specs[0].parser.source == "rule:702.9"

    def test_multiple_flags_preserve_order_and_dedupe(self):
        specs = parse_keywords(_card(["Trample", "Flying", "Flying"]))
        assert [s.keyword["name"] for s in specs] == ["trample", "flying"]

    def test_unknown_keyword_is_skipped(self):
        assert parse_keywords(_card(["Wobble"])) == []


# --- Parametric: NUMBER -----------------------------------------------------


class TestNumberKeywords:
    def test_annihilator_extracts_n(self):
        specs = parse_keywords(_card(["Annihilator"], "Annihilator 2"))
        assert specs[0].keyword == {"name": "annihilator", "n": 2}

    def test_toxic_extracts_n(self):
        specs = parse_keywords(_card(["Toxic"], "Toxic 1 (Players dealt combat damage...)"))
        assert specs[0].keyword == {"name": "toxic", "n": 1}

    def test_missing_number_falls_back_to_bare_name(self):
        specs = parse_keywords(_card(["Crew"], "Crew a vehicle"))
        assert specs[0].keyword == {"name": "crew"}


# --- Parametric: COST -------------------------------------------------------


class TestCostKeywords:
    def test_kicker_extracts_mana_cost(self):
        specs = parse_keywords(_card(["Kicker"], "Kicker {2}{R} (You may pay an additional {2}{R}.)"))
        assert specs[0].keyword == {"name": "kicker", "cost": "{2}{R}"}

    def test_ward_extracts_single_pip(self):
        specs = parse_keywords(_card(["Ward"], "Ward {2}"))
        assert specs[0].keyword == {"name": "ward", "cost": "{2}"}

    def test_equip_skips_a_qualifier_before_the_cost(self):
        specs = parse_keywords(_card(["Equip"], "Equip Bird {2}"))
        assert specs[0].keyword == {"name": "equip", "cost": "{2}"}

    def test_escape_reads_cost_after_the_dash(self):
        # The full clause is captured (not just the mana pips) — the
        # "Exile N other cards from your graveyard" component is genuinely
        # modeled downstream (`game/costs.parse_activation_cost`), not
        # merely carried, so dropping it here would silently lose it.
        specs = parse_keywords(
            _card(["Escape"], "Escape—{2}{B}{B}, Exile four other cards from your graveyard.")
        )
        assert specs[0].keyword == {
            "name": "escape",
            "cost": "{2}{B}{B}, Exile four other cards from your graveyard",
        }

    def test_ward_without_a_mana_cost_falls_back_to_free_text(self):
        # A non-mana ward cost isn't dropped (unlike other COST-shaped
        # keywords with no mana-cost match) — it's genuinely modeled
        # downstream via `game/costs.parse_activation_cost`.
        specs = parse_keywords(_card(["Ward"], "Ward—Pay 3 life."))
        assert specs[0].keyword == {"name": "ward", "cost": "Pay 3 life"}

    def test_ward_discard_cost_falls_back_to_free_text(self):
        specs = parse_keywords(_card(["Ward"], "Ward—Discard a card."))
        assert specs[0].keyword == {"name": "ward", "cost": "Discard a card"}

    def test_ward_sacrifice_cost_falls_back_to_free_text(self):
        specs = parse_keywords(_card(["Ward"], "Ward—Sacrifice a creature."))
        assert specs[0].keyword == {"name": "ward", "cost": "Sacrifice a creature"}


# --- Parametric: NUMBER_COST ------------------------------------------------


class TestNumberCostKeywords:
    def test_suspend_extracts_both(self):
        specs = parse_keywords(_card(["Suspend"], "Suspend 4—{1}{U} (Rather than cast this card...)"))
        assert specs[0].keyword == {"name": "suspend", "n": 4, "cost": "{1}{U}"}

    def test_reinforce_extracts_both(self):
        specs = parse_keywords(_card(["Reinforce"], "Reinforce 2—{1}{G}"))
        assert specs[0].keyword == {"name": "reinforce", "n": 2, "cost": "{1}{G}"}


# --- Parametric: QUALITY ----------------------------------------------------


class TestQualityKeywords:
    def test_protection_extracts_colour(self):
        specs = parse_keywords(_card(["Protection"], "Protection from red"))
        assert specs[0].keyword == {"name": "protection", "quality": "red"}

    def test_protection_extracts_colour_before_reminder_text(self):
        specs = parse_keywords(_card(
            ["Protection"],
            "Protection from black (This creature can't be blocked, targeted, "
            "dealt damage, enchanted, or equipped by anything black.)",
        ))
        assert specs[0].keyword == {"name": "protection", "quality": "black"}

    def test_hexproof_from_extracts_quality(self):
        # Scryfall's keywords array names this variant "Hexproof from" (PAR-5)
        # — both it and the bare "Hexproof" entry alias onto one slug and
        # de-dupe, so only one spec should come out, carrying the quality.
        specs = parse_keywords(_card(["Hexproof from", "Hexproof"], "Hexproof from black"))
        assert [s.keyword for s in specs if s.keyword["name"] == "hexproof"] == [
            {"name": "hexproof", "quality": "black"}
        ]

    def test_hexproof_from_extracts_quality_before_reminder_text(self):
        specs = parse_keywords(_card(
            ["Hexproof from", "Hexproof"],
            "Hexproof from monocolored (This creature can't be the target of "
            "monocolored spells or abilities your opponents control.)",
        ))
        assert specs[0].keyword == {"name": "hexproof", "quality": "monocolored"}

    def test_bare_hexproof_has_no_quality(self):
        specs = parse_keywords(_card(["Hexproof"], "Hexproof"))
        assert specs[0].keyword == {"name": "hexproof"}

    def test_enchant_extracts_what_it_attaches_to(self):
        specs = parse_keywords(_card(["Enchant"], "Enchant creature\nEnchanted creature gets +1/+1."))
        assert specs[0].keyword == {"name": "enchant", "quality": "creature"}

    def test_landwalk_variant_uses_slug_prefix(self):
        specs = parse_keywords(_card(["Islandwalk"], "Islandwalk"))
        assert specs[0].keyword == {"name": "landwalk", "quality": "island"}

    def test_two_landwalks_both_survive(self):
        specs = parse_keywords(_card(["Islandwalk", "Forestwalk"]))
        assert [s.keyword["quality"] for s in specs] == ["island", "forest"]


# --- Daybound/Nightbound face scoping (RULE 702.145) -------------------------


class TestDayboundNightbound:
    def test_recognised_from_the_keywords_array(self):
        specs = parse_keywords(_card(["Daybound"], "Daybound"))
        assert {s.keyword["name"] for s in specs} == {"daybound"}

    def test_recovered_from_oracle_text_when_missing_from_the_array(self):
        # Mirrors the "Enchant" cross-check above: `Card.back_face` never
        # carries a separate keywords list for the back face, so a
        # daybound/nightbound DFC's *current* face is only ever named in its
        # own oracle_text — the ground truth here, same as Enchant.
        specs = parse_keywords(_card([], "Nightbound"))
        assert {s.keyword["name"] for s in specs} == {"nightbound"}

    def test_a_face_never_claims_the_opposite_faces_keyword(self):
        # The front face's own text never mentions "Nightbound" (RULE 702.145a:
        # they live on opposite faces), so only "daybound" is recognised here.
        specs = parse_keywords(_card([], "Daybound"))
        assert {s.keyword["name"] for s in specs} == {"daybound"}


# --- Security / validation --------------------------------------------------


class TestValidation:
    def test_keyword_number_is_clamped(self):
        specs = parse_keywords(_card(["Annihilator"], "Annihilator 999999999"))
        assert specs[0].keyword["n"] == 10_000  # MAX_EFFECT_MAGNITUDE

    def test_extracted_regexes_are_anchored_not_catastrophic(self):
        # Sanity: extractor regexes match against a benign string quickly.
        for kd in KEYWORDS.values():
            if kd.regex is not None:
                kd.regex.search("x" * 500)  # should not hang
