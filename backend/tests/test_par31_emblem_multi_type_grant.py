"""PAR-31 — "you get an emblem with '<ability>'" inner-body coverage.

First slice: the multi-permanent-type keyword grant that Elspeth,
Knight-Errant's −8 emblem carries — "Artifacts, creatures, enchantments,
and lands you control have indestructible." — plus its standing-static
cousins (Fountain Watch, Spiritual Asylum). A `grant_keyword` scoped to
`permanents_you_control` narrowed by the `card_type` *list*
`continuous.affected_objects` already ORs (Grand Abolisher-shaped).
`static_handlers._MULTI_PERMANENT_TYPE_GRANT_RE`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


# --- parse -------------------------------------------------------------


def test_multi_type_grant_parses_as_card_type_list():
    assert static_effect_specs(
        "artifacts, creatures, enchantments, and lands you control have indestructible"
    ) == [
        EffectSpec("grant_keyword", {
            "keywords": ["indestructible"],
            "affects": "permanents_you_control",
            "card_type": ["artifact", "creature", "enchantment", "land"],
        })
    ]
    # two-word list, "X and Y" with no comma
    assert static_effect_specs(
        "artifacts and enchantments you control have shroud"
    )[0].params["card_type"] == ["artifact", "enchantment"]


def test_single_type_grant_untouched():
    # A one-word scope still routes through the PAR-3 permanent-type path
    # (a bare `card_type` string / dedicated selector), never this handler.
    specs = static_effect_specs("artifacts you control have hexproof")
    assert specs[0].params["affects"] == "artifacts_you_control"
    assert "card_type" not in specs[0].params or isinstance(
        specs[0].params.get("card_type"), str
    )
    # A creature scope stays a creature scope.
    assert static_effect_specs("creatures you control have flying")[0].params[
        "affects"
    ] == "creatures_you_control"


def test_unrecognised_word_in_list_fails_closed():
    assert static_effect_specs(
        "artifacts and goblins you control have haste"
    ) in (None, [])


# --- execute ---------------------------------------------------------


def test_grant_only_hits_your_permanents_of_listed_types():
    eng = make_engine([creature("mine")], [creature("theirs")])
    state = eng.state
    lord = obj_on_battlefield(
        state, eng,
        Card(id="fw", name="Fountain Watch", type_line="Enchantment",
             oracle_text="Artifacts and enchantments you control have shroud."),
        controller="p1",
    )
    bind_from_catalogue(lord)

    my_artifact = obj_on_battlefield(
        state, eng,
        Card(id="a1", name="My Rock", type_line="Artifact"),
        controller="p1",
    )
    my_creature = obj_on_battlefield(state, eng, creature("My Bear"), controller="p1")
    their_artifact = obj_on_battlefield(
        state, eng,
        Card(id="a2", name="Their Rock", type_line="Artifact"),
        controller="p2",
    )
    eng.recompute_continuous_effects()

    assert "shroud" in my_artifact.granted_keywords
    assert "shroud" in lord.granted_keywords  # the enchantment grants to itself
    assert "shroud" not in my_creature.granted_keywords  # creature not in the list
    assert "shroud" not in their_artifact.granted_keywords  # not yours


# --- end to end -----------------------------------------------------


def test_real_cards_modeled():
    cases = [
        ("Elspeth, Knight-Errant", "Legendary Planeswalker — Elspeth",
         "+1: Create a 1/1 white Soldier creature token.\n"
         "+1: Target creature gets +3/+3 and gains flying until end of turn.\n"
         "−8: You get an emblem with \"Artifacts, creatures, enchantments, and "
         "lands you control have indestructible.\""),
        ("Fountain Watch", "Enchantment",
         "Artifacts and enchantments you control have shroud."),
        ("Spiritual Asylum", "Enchantment",
         "Creatures and lands you control have shroud.\n"
         "When a creature you control attacks, sacrifice Spiritual Asylum."),
    ]
    for name, tl, text in cases:
        c = Card(id=name[:3], name=name, type_line=tl, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)
