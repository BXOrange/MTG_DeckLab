"""Tests for real Commander legality: color identity, ban list, Partner rules.

Reference: backend/ToDo_Backend.md "Validator".
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.commander_legality import check_commander_legality


def make_card(name, color_identity=(), has_partner=False, partner_with=None, is_legendary=True):
    return Card(
        id=name.lower().replace(" ", "-").replace(",", ""),
        name=name,
        type_line="Legendary Creature — Test",
        color_identity=set(color_identity),
        is_creature=True,
        power=1,
        toughness=1,
        is_legendary=is_legendary,
        has_partner=has_partner,
        partner_with=partner_with,
    )


class TestColorIdentity:
    def test_card_outside_commander_identity_is_illegal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        offender = make_card("Cultivate", color_identity={"G"}, is_legendary=False)

        errors = check_commander_legality([commander], [commander, offender])

        assert len(errors) == 1
        assert "Cultivate" in errors[0]

    def test_card_within_commander_identity_is_legal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        ally = make_card("Lightning Bolt", color_identity={"R"}, is_legendary=False)

        errors = check_commander_legality([commander], [commander, ally])

        assert errors == []

    def test_two_commanders_union_their_identities(self):
        first = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        second = make_card("Tymna the Weaver", color_identity={"W", "B"}, has_partner=True)
        ally = make_card("Sol Ring", color_identity=set(), is_legendary=False)

        errors = check_commander_legality([first, second], [first, second, ally])

        assert errors == []

    def test_no_commanders_skips_color_identity_check(self):
        offender = make_card("Cultivate", color_identity={"G"}, is_legendary=False)

        errors = check_commander_legality([], [offender])

        assert errors == []


class TestBanList:
    def test_banned_card_is_illegal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        banned = make_card("Black Lotus", color_identity=set(), is_legendary=False)

        errors = check_commander_legality([commander], [commander, banned])

        assert any("Black Lotus" in error for error in errors)

    def test_unbanned_card_is_legal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        fine = make_card("Sol Ring", color_identity=set(), is_legendary=False)

        errors = check_commander_legality([commander], [commander, fine])

        assert errors == []


class TestPartnerRules:
    def test_both_generic_partner_is_legal(self):
        first = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        second = make_card("Tymna the Weaver", color_identity={"W", "B"}, has_partner=True)

        errors = check_commander_legality([first, second], [first, second])

        assert errors == []

    def test_reciprocal_partner_with_is_legal(self):
        first = make_card(
            "Kraum, Ludevic's Opus",
            color_identity={"U", "R"},
            has_partner=True,
            partner_with="Silas Renn, Seeker Adept",
        )
        second = make_card(
            "Silas Renn, Seeker Adept",
            color_identity={"U", "B"},
            has_partner=True,
            partner_with="Kraum, Ludevic's Opus",
        )

        errors = check_commander_legality([first, second], [first, second])

        assert errors == []

    def test_generic_partner_cannot_pair_with_named_partner(self):
        generic = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        named = make_card(
            "Kraum, Ludevic's Opus",
            color_identity={"U", "R"},
            has_partner=True,
            partner_with="Silas Renn, Seeker Adept",
        )

        errors = check_commander_legality([generic, named], [generic, named])

        assert len(errors) == 1
        assert "Thrasios" in errors[0]
        assert "Kraum" in errors[0]

    def test_two_commanders_without_any_partner_is_illegal(self):
        first = make_card("Krenko, Mob Boss", color_identity={"R"})
        second = make_card("Grand Warlord Radha", color_identity={"R", "G"})

        errors = check_commander_legality([first, second], [first, second])

        assert len(errors) == 1

    def test_single_commander_never_needs_partner(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})

        errors = check_commander_legality([commander], [commander])

        assert errors == []
