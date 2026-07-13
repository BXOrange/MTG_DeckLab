"""Tests for Scryfall response parsing and the ScryfallIntegration client.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3).
"""

import httpx2 as httpx
import pytest

from mtg_analyzer.services.scryfall_client import (
    ScryfallIntegration,
    ScryfallNotFoundError,
    card_from_scryfall_data,
)

LIGHTNING_BOLT = {
    "id": "77c17415-56c9-4677-b6d5-e18641640e6f",
    "name": "Lightning Bolt",
    "mana_cost": "{R}",
    "cmc": 1.0,
    "type_line": "Instant",
    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
    "colors": ["R"],
    "color_identity": ["R"],
    "keywords": [],
    "set": "clu",
    "rarity": "common",
    "image_uris": {
        "small": "https://cards.scryfall.io/small/lightning_bolt.jpg",
        "normal": "https://cards.scryfall.io/normal/lightning_bolt.jpg",
        "large": "https://cards.scryfall.io/large/lightning_bolt.jpg",
        "png": "https://cards.scryfall.io/png/lightning_bolt.png",
    },
}

GRIZZLY_BEARS = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Grizzly Bears",
    "mana_cost": "{1}{G}",
    "cmc": 2.0,
    "type_line": "Creature — Bear",
    "oracle_text": "",
    "colors": ["G"],
    "color_identity": ["G"],
    "keywords": [],
    "power": "2",
    "toughness": "2",
    "set": "a25",
    "rarity": "common",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

THRASIOS = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Thrasios, Triton Hero",
    "mana_cost": "{G}{U}",
    "cmc": 2.0,
    "type_line": "Legendary Creature — Merfolk Wizard",
    "oracle_text": (
        "Partner (You can have two commanders if both have partner.)\n"
        "{1}{G/U}, {T}: Scry X, where X is the number of cards you've drawn this turn."
    ),
    "colors": ["G", "U"],
    "color_identity": ["G", "U"],
    "keywords": ["Partner"],
    "power": "1",
    "toughness": "3",
    "set": "cma",
    "rarity": "mythic",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}


#: Hybrid mana in the casting cost itself ("{W/U}{W/U}"), not just in an
#: activated ability's cost (THRASIOS below already covers that case via
#: its oracle text). Real data: https://api.scryfall.com/cards/named?exact=Azorius+Guildmage
AZORIUS_GUILDMAGE = {
    "id": "66666666-6666-6666-6666-666666666666",
    "name": "Azorius Guildmage",
    "mana_cost": "{W/U}{W/U}",
    "cmc": 2.0,
    "type_line": "Creature — Vedalken Wizard",
    "oracle_text": (
        "{1}{W}: Tap target creature.\n{1}{U}: Draw a card, then discard a card."
    ),
    "colors": ["U", "W"],
    "color_identity": ["U", "W"],
    "keywords": [],
    "power": "1",
    "toughness": "1",
    "set": "guc",
    "rarity": "uncommon",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

#: Phyrexian mana ("{B/P}") is payable with life instead of a colored
#: pip, but still counts fully toward color identity. Real data:
#: https://api.scryfall.com/cards/named?exact=Dismember
DISMEMBER = {
    "id": "77777777-7777-7777-7777-777777777777",
    "name": "Dismember",
    "mana_cost": "{1}{B/P}{B/P}",
    "cmc": 3.0,
    "type_line": "Instant",
    "oracle_text": "Target creature gets -5/-5 until end of turn.",
    "colors": ["B"],
    "color_identity": ["B"],
    "keywords": [],
    "set": "nph",
    "rarity": "uncommon",
    "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
}

#: Modal double-faced card (layout "modal_dfc"): most fields live per-face
#: in card_faces (no top-level mana_cost/oracle_text/image_uris), but
#: color_identity is a whole-card property Scryfall already unions across
#: both faces at the top level — Valki alone is {B}, Tibalt alone is
#: {B, R}, combined color_identity is {B, R}. Real data (trimmed):
#: https://api.scryfall.com/cards/named?exact=Valki,+God+of+Lies
VALKI_TIBALT = {
    "id": "88888888-8888-8888-8888-888888888888",
    "name": "Valki, God of Lies // Tibalt, Cosmic Impostor",
    "layout": "modal_dfc",
    "cmc": 2.0,
    "type_line": "Legendary Creature — God // Legendary Planeswalker — Tibalt",
    "color_identity": ["B", "R"],
    "keywords": [],
    "set": "khm",
    "rarity": "mythic",
    "card_faces": [
        {
            "object": "card_face",
            "name": "Valki, God of Lies",
            "mana_cost": "{1}{B}",
            "type_line": "Legendary Creature — God",
            "oracle_text": (
                "When Valki enters, each opponent reveals their hand. For each "
                "opponent, exile a creature card they revealed this way until "
                "Valki leaves the battlefield."
            ),
            "colors": ["B"],
            "power": "2",
            "toughness": "1",
            "image_uris": {
                "small": "https://img.example/valki-small.jpg",
                "normal": "https://img.example/valki-normal.jpg",
                "large": "",
                "png": "",
            },
        },
        {
            "object": "card_face",
            "name": "Tibalt, Cosmic Impostor",
            "mana_cost": "{5}{B}{R}",
            "type_line": "Legendary Planeswalker — Tibalt",
            "oracle_text": "As Tibalt enters, you get an emblem ...",
            "colors": ["B", "R"],
            "loyalty": "5",
            "image_uris": {
                "small": "https://img.example/tibalt-small.jpg",
                "normal": "https://img.example/tibalt-normal.jpg",
                "large": "",
                "png": "",
            },
        },
    ],
}

#: Modal DFC whose front is an instant and back is a land ("Malakir
#: Rebirth // Malakir Mire" shape). The combined top-level type line is
#: "Instant // Land"; a naive `"Land" in type_line` check would wrongly
#: flag the whole card as a land. Front-face-first flags must not.
INSTANT_LAND_MDFC = {
    "id": "99999999-9999-9999-9999-999999999999",
    "name": "Malakir Rebirth // Malakir Mire",
    "layout": "modal_dfc",
    "cmc": 2.0,
    "type_line": "Instant // Land",
    "color_identity": ["B"],
    "keywords": [],
    "set": "znr",
    "rarity": "rare",
    "card_faces": [
        {
            "name": "Malakir Rebirth",
            "mana_cost": "{1}{B}",
            "type_line": "Instant",
            "oracle_text": "Return target creature card ...",
            "image_uris": {
                "small": "https://img.example/rebirth-small.jpg",
                "normal": "https://img.example/rebirth-normal.jpg",
                "large": "",
                "png": "",
            },
        },
        {
            "name": "Malakir Mire",
            "mana_cost": "",
            "type_line": "Land",
            "oracle_text": "Malakir Mire enters the battlefield tapped ...",
            "image_uris": {
                "small": "https://img.example/mire-small.jpg",
                "normal": "https://img.example/mire-normal.jpg",
                "large": "",
                "png": "",
            },
        },
    ],
}


class TestCardFromScryfallData:
    def test_instant(self):
        card = card_from_scryfall_data(LIGHTNING_BOLT)
        assert card.name == "Lightning Bolt"
        assert card.is_instant is True
        assert card.mana_cost["R"] == 1
        assert card.converted_mana_cost == 1
        assert card.color_identity == {"R"}
        assert card.image_uri_normal == LIGHTNING_BOLT["image_uris"]["normal"]
        assert card.set_code == "clu"
        assert card.rarity == "common"

    def test_creature_power_toughness_parsed_as_int(self):
        card = card_from_scryfall_data(GRIZZLY_BEARS)
        assert card.is_creature is True
        assert card.power == 2
        assert card.toughness == 2
        # Generic mana ("{1}") isn't representable per-color; only the pip is kept.
        assert card.mana_cost["G"] == 1

    def test_non_creature_has_no_power_toughness(self):
        card = card_from_scryfall_data(LIGHTNING_BOLT)
        assert card.power is None
        assert card.toughness is None

    def test_partner_card_detected(self):
        card = card_from_scryfall_data(THRASIOS)
        assert card.has_partner is True
        assert card.partner_with is None
        assert card.is_legendary is True

    def test_partner_with_named_card(self):
        data = {
            **THRASIOS,
            "id": "33333333-3333-3333-3333-333333333333",
            "name": "Ravos, Dux of Bricktown",
            "oracle_text": "Partner with Silas Renn, Seeker Adept",
        }
        card = card_from_scryfall_data(data)
        assert card.has_partner is True
        assert card.partner_with == "Silas Renn, Seeker Adept"

    def test_variable_power_toughness_is_none(self):
        data = {**GRIZZLY_BEARS, "power": "*", "toughness": "*"}
        card = card_from_scryfall_data(data)
        assert card.power is None
        assert card.toughness is None

    def test_hybrid_mana_in_casting_cost_counts_both_colors(self):
        card = card_from_scryfall_data(AZORIUS_GUILDMAGE)
        assert card.color_identity == {"W", "U"}

    def test_hybrid_symbol_in_activated_ability_cost_counts_toward_identity(self):
        # THRASIOS's mana_cost ("{G}{U}") is plain, but its activated
        # ability costs "{1}{G/U}" — color identity still includes both
        # colors because it comes straight from Scryfall's own
        # already-correct color_identity field, not derived from
        # mana_cost alone.
        card = card_from_scryfall_data(THRASIOS)
        assert card.color_identity == {"G", "U"}

    def test_phyrexian_mana_counts_toward_identity_even_though_payable_with_life(self):
        card = card_from_scryfall_data(DISMEMBER)
        assert card.color_identity == {"B"}
        # The flattened mana_cost dict can't represent "or 2 life" either
        # way (see docs/implementation-state/Done_Backend.md "Mana cost model"),
        # but that's a separate, already-documented limitation from
        # color identity, which is unaffected by it.
        assert card.mana_cost["B"] == 2

    def test_mdfc_color_identity_unions_both_faces(self):
        card = card_from_scryfall_data(VALKI_TIBALT)
        # Front face (Valki) alone is mono-black; back face (Tibalt)
        # adds red. A bug that only looked at the front face's colors
        # would miss the red half entirely.
        assert card.color_identity == {"B", "R"}

    def test_mdfc_uses_front_face_for_face_specific_fields(self):
        # mana_cost/oracle_text/power/toughness aren't present at the
        # top level for a modal DFC (see VALKI_TIBALT) — only per-face.
        # card_from_scryfall_data uses the front face for the primary
        # fields (the back lives in the back_* fields).
        card = card_from_scryfall_data(VALKI_TIBALT)
        assert card.mana_cost["B"] == 1
        assert card.power == 2
        assert card.toughness == 1
        assert "Valki" in card.oracle_text

    def test_mdfc_front_face_image_is_captured(self):
        card = card_from_scryfall_data(VALKI_TIBALT)
        assert card.image_uri_normal == "https://img.example/valki-normal.jpg"

    def test_mdfc_back_face_is_captured(self):
        card = card_from_scryfall_data(VALKI_TIBALT)
        assert card.layout == "modal_dfc"
        assert card.has_back_face is True
        assert card.is_modal_dfc is True
        assert card.is_transforming is False
        assert card.back_name == "Tibalt, Cosmic Impostor"
        assert card.back_type_line == "Legendary Planeswalker — Tibalt"
        assert card.back_mana_cost_string == "{5}{B}{R}"
        assert card.back_image_uri_normal == "https://img.example/tibalt-normal.jpg"
        # Tibalt is a planeswalker, not a creature: no power/toughness.
        assert card.back_power is None
        assert card.back_toughness is None

    def test_mdfc_type_flags_come_from_front_face_not_combined_line(self):
        # "Malakir Rebirth // Malakir Mire" is Instant // Land. The front
        # face is an instant, so the card must be flagged instant — not
        # land, which the combined "Instant // Land" line would wrongly
        # trigger.
        card = card_from_scryfall_data(INSTANT_LAND_MDFC)
        assert card.is_instant is True
        assert card.is_land is False
        assert card.type_line == "Instant"
        assert card.back_type_line == "Land"
        assert card.back_image_uri_normal == "https://img.example/mire-normal.jpg"

    def test_single_faced_card_has_no_back_face(self):
        card = card_from_scryfall_data(LIGHTNING_BOLT)
        assert card.has_back_face is False
        assert card.back_name == ""
        assert card.back_image_uri_normal == ""

    def test_transform_card_back_is_reached_by_transforming_not_casting(self):
        delver = {
            "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "name": "Delver of Secrets // Insectile Aberration",
            "layout": "transform",
            "cmc": 1.0,
            "type_line": "Creature — Human Wizard // Creature — Insect",
            "color_identity": ["U"],
            "keywords": [],
            "set": "isd",
            "rarity": "common",
            "card_faces": [
                {
                    "name": "Delver of Secrets",
                    "mana_cost": "{U}",
                    "type_line": "Creature — Human Wizard",
                    "oracle_text": "At the beginning of your upkeep, ...",
                    "power": "1",
                    "toughness": "1",
                    "image_uris": {"small": "", "normal": "https://img.example/delver.jpg", "large": "", "png": ""},
                },
                {
                    "name": "Insectile Aberration",
                    "mana_cost": "",
                    "type_line": "Creature — Insect",
                    "oracle_text": "Flying",
                    "power": "3",
                    "toughness": "2",
                    "image_uris": {"small": "", "normal": "https://img.example/aberration.jpg", "large": "", "png": ""},
                },
            ],
        }
        card = card_from_scryfall_data(delver)
        assert card.is_transforming is True
        assert card.is_modal_dfc is False
        assert card.has_back_face is True
        # The back is a creature — its power/toughness are captured.
        assert card.back_power == 3
        assert card.back_toughness == 2
        assert card.back_image_uri_normal == "https://img.example/aberration.jpg"

    def test_split_card_shares_one_image_and_has_no_separate_back(self):
        # "Wear // Tear" (layout "split") has two faces in the data but a
        # single printed image, so no back image is captured.
        wear_tear = {
            "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "name": "Wear // Tear",
            "layout": "split",
            "cmc": 2.0,
            "type_line": "Instant // Instant",
            "color_identity": ["R", "W"],
            "keywords": [],
            "set": "dgm",
            "rarity": "uncommon",
            "oracle_text": "Destroy target artifact.\n----\nDestroy target enchantment.",
            "image_uris": {"small": "", "normal": "https://img.example/weartear.jpg", "large": "", "png": ""},
            "card_faces": [
                {"name": "Wear", "mana_cost": "{1}{R}", "type_line": "Instant", "oracle_text": "Destroy target artifact."},
                {"name": "Tear", "mana_cost": "{W}", "type_line": "Instant", "oracle_text": "Destroy target enchantment."},
            ],
        }
        card = card_from_scryfall_data(wear_tear)
        assert card.layout == "split"
        assert card.has_back_face is False
        assert card.back_image_uri_normal == ""
        # The single shared image is still served as the front.
        assert card.image_uri_normal == "https://img.example/weartear.jpg"


class TestScryfallIntegration:
    def _client(self, handler) -> ScryfallIntegration:
        transport = httpx.MockTransport(handler)
        return ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))

    def test_fetch_card_returns_data(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["exact"] == "Lightning Bolt"
            return httpx.Response(200, json=LIGHTNING_BOLT)

        with self._client(handler) as scryfall:
            data = scryfall.fetch_card("Lightning Bolt")
        assert data["name"] == "Lightning Bolt"

    def test_fetch_card_not_found_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"details": "not found"})

        with self._client(handler) as scryfall:
            with pytest.raises(ScryfallNotFoundError):
                scryfall.fetch_card("Not A Real Card")

    def test_fetch_multiple_splits_found_and_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": [LIGHTNING_BOLT],
                    "not_found": [{"name": "Not A Real Card"}],
                },
            )

        with self._client(handler) as scryfall:
            found, not_found = scryfall.fetch_multiple(["Lightning Bolt", "Not A Real Card"])
        assert [c["name"] for c in found] == ["Lightning Bolt"]
        assert not_found == ["Not A Real Card"]

    def test_fetch_multiple_batches_over_75_identifiers(self):
        request_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json={"data": [], "not_found": []})

        names = [f"Card {i}" for i in range(150)]
        with self._client(handler) as scryfall:
            scryfall.fetch_multiple(names)
        assert request_count == 2
