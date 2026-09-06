"""MEC-73's parser contract for the selected subtype hand-cheat package."""

from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import match_clause


def test_subtype_hand_cheat_clause_emits_the_restricted_primitive():
    specs = match_clause(
        "put an elemental creature card from your hand onto the battlefield. "
        "that creature gains haste until end of turn. sacrifice it at the beginning "
        "of the next end step"
    )

    assert specs is not None
    assert [(spec.type, spec.params) for spec in specs] == [
        ("cheat_creature_from_hand", {"subtypes": ["Elemental"]}),
    ]


def test_incandescent_soulstoke_is_fully_modeled():
    card = Card(
        id="soulstoke", name="Incandescent Soulstoke",
        type_line="Creature — Elemental Shaman", is_creature=True,
        oracle_text=(
            "Other Elemental creatures you control get +1/+1.\n"
            "{1}{R}, {T}: You may put an Elemental creature card from your hand onto "
            "the battlefield. That creature gains haste until end of turn. Sacrifice it "
            "at the beginning of the next end step."
        ),
    )

    result = parse_oracle(card)

    assert result.modeled is True
    activated = next(spec for spec in result.effect_specs if spec.ability_kind == "activated")
    assert activated.effects[0].type == "cheat_creature_from_hand"
