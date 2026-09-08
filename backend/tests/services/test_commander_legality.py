"""Tests for real Commander legality: color identity, ban list, Partner rules.

Reference: docs/implementation-state/Done_Backend.md "Validator".
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.commander_legality import check_commander_legality


def make_card(
    name,
    color_identity=(),
    has_partner=False,
    partner_with=None,
    is_legendary=True,
    type_line="Legendary Creature — Test",
    oracle_text="",
):
    return Card(
        id=name.lower().replace(" ", "-").replace(",", ""),
        name=name,
        type_line=type_line,
        color_identity=set(color_identity),
        is_creature="Creature" in type_line,
        power=1 if "Creature" in type_line else None,
        toughness=1 if "Creature" in type_line else None,
        is_legendary=is_legendary,
        has_partner=has_partner,
        partner_with=partner_with,
        oracle_text=oracle_text,
    )


class TestColorIdentity:
    def test_card_outside_commander_identity_is_illegal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        offender = make_card("Cultivate", color_identity={"G"}, is_legendary=False)

        result = check_commander_legality([commander], [commander, offender])

        assert len(result.errors) == 1
        assert "Cultivate" in result.errors[0]
        assert result.color_identity_violation_names == ["Cultivate"]
        assert result.banned_card_names == []

    def test_card_within_commander_identity_is_legal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        ally = make_card("Lightning Bolt", color_identity={"R"}, is_legendary=False)

        result = check_commander_legality([commander], [commander, ally])

        assert result.errors == []
        assert result.color_identity_violation_names == []

    def test_two_commanders_union_their_identities(self):
        first = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        second = make_card("Tymna the Weaver", color_identity={"W", "B"}, has_partner=True)
        ally = make_card("Sol Ring", color_identity=set(), is_legendary=False)

        result = check_commander_legality([first, second], [first, second, ally])

        assert result.errors == []

    def test_no_commanders_skips_color_identity_check(self):
        offender = make_card("Cultivate", color_identity={"G"}, is_legendary=False)

        result = check_commander_legality([], [offender])

        assert result.errors == []
        assert result.color_identity_violation_names == []


class TestBanList:
    def test_banned_card_is_illegal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        banned = make_card("Black Lotus", color_identity=set(), is_legendary=False)

        result = check_commander_legality([commander], [commander, banned])

        assert any("Black Lotus" in error for error in result.errors)
        assert result.banned_card_names == ["Black Lotus"]
        assert result.color_identity_violation_names == []

    def test_unbanned_card_is_legal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        fine = make_card("Sol Ring", color_identity=set(), is_legendary=False)

        result = check_commander_legality([commander], [commander, fine])

        assert result.errors == []
        assert result.banned_card_names == []

    def test_banned_and_color_identity_violation_can_both_apply(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})
        banned_off_color = make_card(
            "Griselbrand", color_identity={"B"}, is_legendary=True
        )

        result = check_commander_legality([commander], [commander, banned_off_color])

        assert result.banned_card_names == ["Griselbrand"]
        assert result.color_identity_violation_names == ["Griselbrand"]
        assert len(result.errors) == 2


class TestPartnerRules:
    def test_both_generic_partner_is_legal(self):
        first = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        second = make_card("Tymna the Weaver", color_identity={"W", "B"}, has_partner=True)

        result = check_commander_legality([first, second], [first, second])

        assert result.errors == []

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

        result = check_commander_legality([first, second], [first, second])

        assert result.errors == []

    def test_generic_partner_cannot_pair_with_named_partner(self):
        generic = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        named = make_card(
            "Kraum, Ludevic's Opus",
            color_identity={"U", "R"},
            has_partner=True,
            partner_with="Silas Renn, Seeker Adept",
        )

        result = check_commander_legality([generic, named], [generic, named])

        assert len(result.errors) == 1
        assert "Thrasios" in result.errors[0]
        assert "Kraum" in result.errors[0]

    def test_two_commanders_without_any_partner_is_illegal(self):
        first = make_card("Krenko, Mob Boss", color_identity={"R"})
        second = make_card("Grand Warlord Radha", color_identity={"R", "G"})

        result = check_commander_legality([first, second], [first, second])

        assert len(result.errors) == 1

    def test_single_commander_never_needs_partner(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})

        result = check_commander_legality([commander], [commander])

        assert result.errors == []


class TestFriendsForeverRules:
    def test_both_friends_forever_is_legal(self):
        first = make_card(
            "Bruse Tarl, Boorish Herder",
            color_identity={"R", "W"},
            oracle_text="Friends forever (You can have two commanders if the other one has friends forever.)",
        )
        second = make_card(
            "Ravos, Soultender",
            color_identity={"G", "W"},
            oracle_text="Friends forever (You can have two commanders if the other one has friends forever.)",
        )

        result = check_commander_legality([first, second], [first, second])

        assert result.errors == []

    def test_friends_forever_cannot_pair_with_plain_partner(self):
        friend = make_card(
            "Bruse Tarl, Boorish Herder",
            color_identity={"R", "W"},
            oracle_text="Friends forever (You can have two commanders if the other one has friends forever.)",
        )
        partner = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)

        result = check_commander_legality([friend, partner], [friend, partner])

        assert len(result.errors) == 1


class TestBackgroundRules:
    def test_choose_a_background_pairs_with_background(self):
        creature = make_card(
            "Faldorn, Dread Wolf Herder",
            color_identity={"G"},
            oracle_text="Choose a Background (You can choose a Background as one of your two commanders.)",
        )
        background = make_card(
            "Slime Against Humanity",
            color_identity={"B", "G"},
            type_line="Enchantment — Background",
            is_legendary=False,
        )

        result = check_commander_legality([creature, background], [creature, background])

        assert result.errors == []

    def test_background_cannot_pair_with_plain_partner(self):
        partner = make_card("Thrasios, Triton Hero", color_identity={"G", "U"}, has_partner=True)
        background = make_card(
            "Slime Against Humanity",
            color_identity={"B", "G"},
            type_line="Enchantment — Background",
            is_legendary=False,
        )

        result = check_commander_legality([partner, background], [partner, background])

        assert any("gemeinsam Commander" in error for error in result.errors)

    def test_lone_background_is_not_legendary(self):
        background = make_card(
            "Slime Against Humanity",
            color_identity={"B", "G"},
            type_line="Enchantment — Background",
            is_legendary=False,
        )

        result = check_commander_legality([background], [background])

        assert any("nicht legendär" in error for error in result.errors)


class TestLegendaryRule:
    def test_non_legendary_commander_is_illegal(self):
        commander = make_card(
            "Cultivate",
            color_identity={"G"},
            is_legendary=False,
            type_line="Sorcery",
        )

        result = check_commander_legality([commander], [commander])

        assert any("nicht legendär" in error for error in result.errors)

    def test_can_be_your_commander_text_makes_non_legendary_card_legal(self):
        commander = make_card(
            "Grand Master of Flowers",
            color_identity={"W"},
            is_legendary=False,
            oracle_text="Grand Master of Flowers can be your commander.",
        )

        result = check_commander_legality([commander], [commander])

        assert result.errors == []

    def test_legendary_commander_is_legal(self):
        commander = make_card("Krenko, Mob Boss", color_identity={"R"})

        result = check_commander_legality([commander], [commander])

        assert result.errors == []
