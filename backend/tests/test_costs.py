"""Tests for the regex activated-ability cost parser (game/costs.py, RULE 602)."""

from mtg_analyzer.game.costs import (
    DISCARD_HAND,
    ActivationCost,
    parse_activation_cost,
)


class TestParseText:
    def test_mana_and_tap(self):
        cost = parse_activation_cost("{2}{R}, {T}: Deal 1 damage.")
        assert cost.taps_self is True
        assert cost.mana.converted_mana_cost == 3
        assert cost.mana.color_identity == {"R"}

    def test_tap_symbol_is_not_counted_as_mana(self):
        cost = parse_activation_cost("{T}: Add {G}.")
        assert cost.taps_self is True
        assert cost.mana.is_free  # {T} must not leak into the mana cost

    def test_untap_symbol(self):
        cost = parse_activation_cost("{Q}: Untap target creature.")
        assert cost.untaps_self is True
        assert cost.taps_self is False

    def test_sacrifice_self(self):
        assert parse_activation_cost("Sacrifice ~: Draw a card.").sacrifice == "self"
        assert parse_activation_cost("Sacrifice this creature: Draw.").sacrifice == "self"

    def test_sacrifice_a_type(self):
        assert parse_activation_cost("Sacrifice a creature: Add {B}.").sacrifice == "creature"
        assert parse_activation_cost("Sacrifice an artifact: Draw.").sacrifice == "artifact"

    def test_pay_life(self):
        assert parse_activation_cost("Pay 3 life: Draw a card.").pay_life == 3

    def test_discard_variants(self):
        assert parse_activation_cost("Discard a card: Draw.").discard == 1
        assert parse_activation_cost("Discard two cards: Draw.").discard == 2
        assert parse_activation_cost("{T}, Discard your hand: Win.").discard == DISCARD_HAND

    def test_remove_counters(self):
        cost = parse_activation_cost("Remove a +1/+1 counter from ~: Draw.")
        assert cost.remove_counters == ("+1/+1", 1)
        loyalty = parse_activation_cost("Remove three loyalty counters: Ultimate.")
        assert loyalty.remove_counters == ("loyalty", 3)

    def test_compound_cost(self):
        cost = parse_activation_cost("{1}{B}, {T}, Sacrifice a creature, Pay 2 life: Draw two cards.")
        assert cost.mana.converted_mana_cost == 2
        assert cost.taps_self and cost.sacrifice == "creature" and cost.pay_life == 2
        # The effect after the colon is not mistaken for part of the cost.
        assert cost.discard == 0

    def test_free_cost(self):
        assert parse_activation_cost(None).is_free
        assert parse_activation_cost("").is_free

    def test_tap_others(self):
        # Birchlore Rangers — no {T} of its own, taps two *other* Elves.
        cost = parse_activation_cost("Tap two untapped Elves you control: Add one mana of any color.")
        assert cost.tap_others == (2, "elf")
        assert cost.taps_self is False
        # Heritage Druid.
        cost3 = parse_activation_cost("Tap three untapped Elves you control: Add {G}{G}{G}.")
        assert cost3.tap_others == (3, "elf")

    def test_add_counter_cost(self):
        # Devoted Druid's untap ability.
        cost = parse_activation_cost("Put a -1/-1 counter on this creature: Untap this creature.")
        assert cost.add_counters_cost == ("-1/-1", 1)
        assert not cost.is_free

    def test_exile_self_from_hand(self):
        # Elvish Spirit Guide.
        cost = parse_activation_cost("Exile this creature from your hand: Add {G}.")
        assert cost.exile_self_from_hand is True
        assert not cost.is_free


class TestParseDict:
    def test_explicit_fields_win_over_text(self):
        cost = parse_activation_cost({"mana": "{U}", "taps_self": True})
        assert cost.taps_self is True and cost.mana.color_identity == {"U"}

    def test_text_field_is_parsed(self):
        cost = parse_activation_cost({"text": "{T}, Pay 1 life"})
        assert cost.taps_self is True and cost.pay_life == 1

    def test_passthrough_of_existing_cost(self):
        original = ActivationCost(pay_life=5)
        assert parse_activation_cost(original) is original


def test_label_round_trips_the_parts():
    cost = parse_activation_cost("{2}, {T}, Sacrifice a creature, Pay 1 life: Draw.")
    label = cost.label()
    assert "{T}" in label and "Sacrifice a creature" in label and "Pay 1 life" in label
