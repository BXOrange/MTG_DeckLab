"""PAR-96 — total-mana cast-trigger rider decomposition."""

from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


_PARSER = ParserProvenance(version="test", source="test")


def test_high_mana_rider_is_additive_or_exclusive_as_printed():
    additive = segment_line(
        "whenever you cast an instant or sorcery spell, ~ gets +1/+1 until end of turn. "
        "if 5 or more mana was spent to cast that spell, create a token that's a copy of ~.",
        allow_spell_effect=False, provenance=_PARSER,
    )
    assert additive.claimed and additive.spec.trigger.get("spell_mana_spent_at_least") is None
    assert additive.extra_specs[0].trigger["spell_mana_spent_at_least"] == 5

    replacement = segment_line(
        "whenever you cast an instant or sorcery spell, ~ deals 1 damage to each opponent. "
        "if 5 or more mana was spent to cast that spell, ~ deals 3 damage to each opponent instead.",
        allow_spell_effect=False, provenance=_PARSER,
    )
    assert replacement.claimed
    assert replacement.spec.trigger["spell_mana_spent_less_than"] == 5
    assert replacement.extra_specs[0].trigger["spell_mana_spent_at_least"] == 5


def test_two_additive_mana_riders_keep_their_independent_thresholds():
    segment = segment_line(
        "whenever you cast a noncreature spell, create a 1/1 colorless hero creature token. "
        "if 4 or more mana was spent to cast that spell, draw 2 cards. "
        "if 8 or more mana was spent to cast that spell, sacrifice ~ and it deals that much damage "
        "to each opponent.",
        allow_spell_effect=False, provenance=_PARSER,
    )

    assert segment.claimed
    assert [spec.trigger["spell_mana_spent_at_least"] for spec in segment.extra_specs] == [4, 8]
    assert segment.extra_specs[1].effects[1].params == {
        "amount": 0,
        "selector": "each_opponent",
        "amount_from_trigger_event": "mana_spent",
    }
