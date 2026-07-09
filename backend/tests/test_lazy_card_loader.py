"""Tests for LazyCardLoader: DB-first lookup, Scryfall fallback for misses.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "LazyCardLoader").
"""

import httpx2 as httpx

from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.lazy_card_loader import LazyCardLoader
from mtg_analyzer.services.scryfall_client import ScryfallIntegration

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
        "small": "https://img.example/bolt-small.jpg",
        "normal": "https://img.example/bolt-normal.jpg",
        "large": "",
        "png": "",
    },
}

# Modal double-faced card: Scryfall's /cards/collection resolves this by
# front-face name alone, but always returns it under the full combined
# name — the loader must alias results back to whatever name was
# actually requested, or a front-face-only request silently matches
# nothing (see services/lazy_card_loader.py's _front_face_name).
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
            "oracle_text": "",
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
            "oracle_text": "",
            "colors": ["B", "R"],
            "loyalty": "5",
            "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
        },
    ],
}


def make_loader(handler):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
    return LazyCardLoader(database, scryfall), database


class TestLoadCards:
    def test_fetches_from_scryfall_on_first_use(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, database = make_loader(handler)
        result = loader.load_cards(["Lightning Bolt"])

        assert result.cards["Lightning Bolt"].name == "Lightning Bolt"
        assert result.not_found == []
        assert len(calls) == 1
        # Second load must hit the DB, not Scryfall again.
        assert database.get_card("Lightning Bolt") is not None

    def test_second_load_does_not_call_scryfall_again(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        loader.load_cards(["Lightning Bolt"])
        loader.load_cards(["Lightning Bolt"])

        assert len(calls) == 1

    def test_unknown_card_reported_as_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [], "not_found": [{"name": "Not A Real Card"}]}
            )

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Not A Real Card"])

        assert result.cards == {}
        assert result.not_found == ["Not A Real Card"]

    def test_lookup_is_case_insensitive_to_requested_name(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        result = loader.load_cards(["lightning bolt"])

        assert "lightning bolt" in result.cards
        assert result.cards["lightning bolt"].name == "Lightning Bolt"

    def test_duplicate_names_deduped_before_fetch(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            body = request.read()
            import json

            identifiers = json.loads(body)["identifiers"]
            assert len(identifiers) == 1
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        loader, _ = make_loader(handler)
        loader.load_cards(["Lightning Bolt", "Lightning Bolt"])

        assert len(calls) == 1

    def test_mixed_cached_and_missing_only_fetches_missing(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            import json

            identifiers = json.loads(request.read())["identifiers"]
            assert identifiers == [{"name": "Lightning Bolt"}]
            return httpx.Response(
                200, json={"data": [LIGHTNING_BOLT], "not_found": []}
            )

        database = CardDatabase()
        transport = httpx.MockTransport(handler)
        scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
        loader = LazyCardLoader(database, scryfall)

        # Pre-seed "Counterspell" directly so only "Lightning Bolt" is missing.
        # `mana_cost_string` set (a "fully cached" row, not a stale one that
        # predates that field — see TestStaleCachedRows below) so it
        # doesn't itself trigger a refetch.
        from mtg_analyzer.models.card import Card

        database.save_card(
            Card(
                id="counterspell-id",
                name="Counterspell",
                type_line="Instant",
                mana_cost_string="{U}{U}",
                converted_mana_cost=2,
                is_instant=True,
                image_uri_normal="https://img.example/counterspell.jpg",
            )
        )

        result = loader.load_cards(["Counterspell", "Lightning Bolt"])

        assert set(result.cards) == {"Counterspell", "Lightning Bolt"}
        assert len(calls) == 1

    def test_mdfc_resolved_by_front_face_name_alone(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # Real Scryfall behavior: /cards/collection resolves a
            # front-face-only identifier, but always echoes back the
            # full combined name in the result.
            return httpx.Response(200, json={"data": [VALKI_TIBALT], "not_found": []})

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Valki, God of Lies"])

        assert result.not_found == []
        assert "Valki, God of Lies" in result.cards
        card = result.cards["Valki, God of Lies"]
        assert card.name == "Valki, God of Lies // Tibalt, Cosmic Impostor"
        assert card.color_identity == {"B", "R"}

    def test_mdfc_second_load_by_front_face_name_hits_the_db_not_scryfall(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [VALKI_TIBALT], "not_found": []})

        loader, database = make_loader(handler)
        loader.load_cards(["Valki, God of Lies"])
        result = loader.load_cards(["Valki, God of Lies"])

        assert len(calls) == 1
        assert result.cards["Valki, God of Lies"].name == "Valki, God of Lies // Tibalt, Cosmic Impostor"

    def test_mdfc_resolved_by_full_combined_name_too(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [VALKI_TIBALT], "not_found": []})

        loader, _ = make_loader(handler)
        full_name = "Valki, God of Lies // Tibalt, Cosmic Impostor"
        result = loader.load_cards([full_name])

        assert full_name in result.cards

    def test_full_combined_name_is_queried_by_front_face(self):
        # Faithful Scryfall behavior: it resolves the FRONT-FACE identifier
        # and reports the full "Front // Back" name as not_found. The loader
        # must therefore query by front face even when asked for the full
        # name, or these cards (Wear // Tear, pathways, MDFCs) vanish.
        import json

        sent_identifiers = []

        def handler(request: httpx.Request) -> httpx.Response:
            identifiers = json.loads(request.read())["identifiers"]
            sent_identifiers.extend(i["name"] for i in identifiers)
            data = []
            not_found = []
            for identifier in identifiers:
                if identifier["name"].lower() == "valki, god of lies":
                    data.append(VALKI_TIBALT)
                else:
                    not_found.append({"name": identifier["name"]})
            return httpx.Response(200, json={"data": data, "not_found": not_found})

        loader, _ = make_loader(handler)
        full_name = "Valki, God of Lies // Tibalt, Cosmic Impostor"
        result = loader.load_cards([full_name])

        # Queried by front face, not the (not-found) combined name.
        assert sent_identifiers == ["Valki, God of Lies"]
        assert result.not_found == []
        assert result.cards[full_name].name == full_name

    def test_single_slash_separator_is_queried_by_front_face(self):
        # Real decklists write DFCs with a single slash too, e.g.
        # "Halvar, God of Battle / Sword of the Realms". Scryfall still
        # only matches by face name, so the loader must extract the front
        # face regardless of slash/spacing.
        import json

        sent_identifiers = []

        def handler(request: httpx.Request) -> httpx.Response:
            identifiers = json.loads(request.read())["identifiers"]
            sent_identifiers.extend(i["name"] for i in identifiers)
            data = [VALKI_TIBALT] if any(
                i["name"].lower() == "valki, god of lies" for i in identifiers
            ) else []
            return httpx.Response(200, json={"data": data, "not_found": []})

        loader, _ = make_loader(handler)
        requested = "Valki, God of Lies / Tibalt, Cosmic Impostor"  # single slash
        result = loader.load_cards([requested])

        assert sent_identifiers == ["Valki, God of Lies"]
        assert requested in result.cards

    def test_genuinely_unknown_dfc_reported_under_requested_name(self):
        import json

        def handler(request: httpx.Request) -> httpx.Response:
            identifiers = json.loads(request.read())["identifiers"]
            return httpx.Response(
                200,
                json={"data": [], "not_found": [{"name": i["name"]} for i in identifiers]},
            )

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Fakefront // Fakeback"])

        # Reported under the caller's full name, not the front-face query.
        assert result.not_found == ["Fakefront // Fakeback"]
        assert result.cards == {}


class TestStaleCachedRows:
    """A row cached before `mana_cost_string` existed self-heals on load.

    Reference: backend/Done_Backend.md "Mana cost model", ToDo's former
    "Hybrid/Phyrexian nuance for stale cached rows" entry — schema
    versioning (services/schema_version.py) already wipes the *whole* card
    cache when `models/card.py` changes shape, so genuinely pre-existing
    rows can't survive a deployed schema change. But a row could still end
    up without `mana_cost_string` some other way post-deploy — e.g.
    importing an old docs/08 cache export into an already-reconciled DB —
    so `LazyCardLoader` treats a stale hit as a miss and refetches it.
    """

    def test_stale_row_missing_mana_cost_string_is_refetched(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        loader, database = make_loader(handler)
        from mtg_analyzer.models.card import Card

        # Simulates a row cached before `mana_cost_string` existed: a
        # non-land with no raw cost string, but a real mana value (the
        # "Sol Ring" bug shape) — same id Scryfall reports for the fixture.
        database.save_card(
            Card(
                id=LIGHTNING_BOLT["id"],
                name="Lightning Bolt",
                type_line="Instant",
                converted_mana_cost=1,
                is_instant=True,
            )
        )

        result = loader.load_cards(["Lightning Bolt"])

        assert len(calls) == 1  # refetched despite being "cached"
        assert result.cards["Lightning Bolt"].mana_cost_string == "{R}"
        # The DB row itself is healed too, not just this call's result.
        assert database.get_card("Lightning Bolt").mana_cost_string == "{R}"

    def test_stale_row_falls_back_to_cache_if_refetch_finds_nothing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": [], "not_found": [{"name": "Lightning Bolt"}]}
            )

        loader, database = make_loader(handler)
        from mtg_analyzer.models.card import Card

        stale = Card(
            id="stale-id", name="Lightning Bolt", type_line="Instant", converted_mana_cost=1,
            is_instant=True,
        )
        database.save_card(stale)

        result = loader.load_cards(["Lightning Bolt"])

        # A previously-working card must not start reporting as not-found
        # just because its self-heal refetch didn't come back.
        assert result.not_found == []
        assert result.cards["Lightning Bolt"] == stale

    def test_land_with_blank_mana_cost_string_is_not_treated_as_stale(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [], "not_found": []})

        loader, database = make_loader(handler)
        from mtg_analyzer.models.card import Card

        database.save_card(
            Card(
                id="forest-id",
                name="Forest",
                type_line="Basic Land — Forest",
                is_land=True,
                image_uri_normal="https://img.example/forest.jpg",
            )
        )

        result = loader.load_cards(["Forest"])

        assert calls == []  # a land's blank mana_cost_string is legitimate
        assert result.cards["Forest"].name == "Forest"
