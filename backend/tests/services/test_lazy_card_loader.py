"""Tests for LazyCardLoader: DB-first lookup, Scryfall fallback for misses.

Reference: docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/implementation-state/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "LazyCardLoader").
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


def make_loader(handler, scryfall_primary=False):
    database = CardDatabase()
    transport = httpx.MockTransport(handler)
    scryfall = ScryfallIntegration(client=httpx.Client(transport=transport, base_url="https://api.scryfall.com"))
    return LazyCardLoader(database, scryfall, scryfall_primary=scryfall_primary), database


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
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200, json={"data": [], "not_found": [{"name": "Not A Real Card"}]}
                )
            # The flavor-name fallback retry (see test_flavor_name_*
            # below) — a genuinely unknown card misses here too.
            return httpx.Response(404, json={"details": "not found"})

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
        from mtg_analyzer.models.cards.card import Card

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
            if request.url.path == "/cards/collection":
                identifiers = json.loads(request.read())["identifiers"]
                return httpx.Response(
                    200,
                    json={"data": [], "not_found": [{"name": i["name"]} for i in identifiers]},
                )
            return httpx.Response(404, json={"details": "not found"})

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Fakefront // Fakeback"])

        # Reported under the caller's full name, not the front-face query.
        assert result.not_found == ["Fakefront // Fakeback"]
        assert result.cards == {}


# Secret Lair's "Godzilla" series (Ikoria) prints an alternate name
# alongside the real one — Scryfall's `flavor_name`. Real data (trimmed):
# https://api.scryfall.com/cards/named?exact=Zilortha,+Strength+Incarnate
ZILORTHA = {
    "id": "9a0639a0-c898-4a07-975c-a02bdd53175b",
    "name": "Zilortha, Strength Incarnate",
    "flavor_name": "Godzilla, King of the Monsters",
    "mana_cost": "{3}{R}{G}",
    "cmc": 5.0,
    "type_line": "Legendary Creature — Dinosaur",
    "oracle_text": "Trample",
    "colors": ["G", "R"],
    "color_identity": ["G", "R"],
    "keywords": ["Trample"],
    "power": "7",
    "toughness": "3",
    "set": "iko",
    "rarity": "mythic",
    "image_uris": {"small": "", "normal": "https://img.example/zilortha.jpg", "large": "", "png": ""},
}


class TestFlavorNameFallback:
    """/cards/collection only matches a card's real (Oracle) name; a promo's
    printed *flavor name* (Secret Lair's "Godzilla" series, several
    Universes Beyond crossovers) only resolves via /cards/named — verified
    against the live Scryfall API. The loader must retry there rather than
    reporting these cards as not found."""

    def test_flavor_name_resolved_via_named_endpoint_fallback(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200,
                    json={"data": [], "not_found": [{"name": "Godzilla, King of the Monsters"}]},
                )
            assert request.url.params["exact"] == "Godzilla, King of the Monsters"
            return httpx.Response(200, json=ZILORTHA)

        loader, _ = make_loader(handler)
        result = loader.load_cards(["Godzilla, King of the Monsters"])

        assert result.not_found == []
        card = result.cards["Godzilla, King of the Monsters"]
        assert card.name == "Zilortha, Strength Incarnate"
        assert card.flavor_name == "Godzilla, King of the Monsters"

    def test_flavor_name_second_load_hits_the_db_not_scryfall(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200,
                    json={"data": [], "not_found": [{"name": "Godzilla, King of the Monsters"}]},
                )
            return httpx.Response(200, json=ZILORTHA)

        loader, database = make_loader(handler)
        loader.load_cards(["Godzilla, King of the Monsters"])
        result = loader.load_cards(["Godzilla, King of the Monsters"])

        assert len(calls) == 2  # only the first load's collection + named-fallback calls
        assert result.cards["Godzilla, King of the Monsters"].name == "Zilortha, Strength Incarnate"
        # The cache row itself is reachable by flavor name too (CardDatabase.get_card).
        assert database.get_card("Godzilla, King of the Monsters") is not None

    def test_flavor_name_resolving_to_an_already_cached_name_does_not_crash(self):
        # Regression test for a real production crash: a decklist can list
        # both a plain printing and a *different* Universes Beyond
        # crossover printing of the same Oracle card by its flavor name
        # (e.g. "The Cloudsea Djinn" for Nyxbloom Ancient, a real Final
        # Fantasy crossover printing) — two different Scryfall ids
        # resolving to one `name`, which used to raise a sqlite
        # IntegrityError out of CardDatabase.save_card (fixed there via
        # `INSERT OR REPLACE`; see test_card_database.py's matching test).
        plain_printing = {
            "id": "11111111-1111-1111-1111-111111111111",
            "name": "Nyxbloom Ancient",
            "mana_cost": "{4}{G}{G}{G}",
            "cmc": 7.0,
            "type_line": "Enchantment Creature — Elemental",
            "oracle_text": "Trample",
            "colors": ["G"],
            "color_identity": ["G"],
            "keywords": ["Trample"],
            "power": "5",
            "toughness": "5",
            "set": "thb",
            "rarity": "mythic",
            "image_uris": {"small": "", "normal": "", "large": "", "png": ""},
        }
        crossover_printing = {
            **plain_printing,
            "id": "22222222-2222-2222-2222-222222222222",
            "flavor_name": "The Cloudsea Djinn",
            "set": "fca",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/cards/collection":
                import json

                identifiers = json.loads(request.read())["identifiers"]
                data = [plain_printing] if any(i["name"] == "Nyxbloom Ancient" for i in identifiers) else []
                not_found = [{"name": i["name"]} for i in identifiers if i["name"] != "Nyxbloom Ancient"]
                return httpx.Response(200, json={"data": data, "not_found": not_found})
            assert request.url.params["exact"] == "The Cloudsea Djinn"
            return httpx.Response(200, json=crossover_printing)

        loader, database = make_loader(handler)
        result = loader.load_cards(["Nyxbloom Ancient", "The Cloudsea Djinn"])

        assert result.not_found == []
        assert result.cards["Nyxbloom Ancient"].id == "11111111-1111-1111-1111-111111111111"
        assert result.cards["The Cloudsea Djinn"].id == "22222222-2222-2222-2222-222222222222"
        # No crash saving the second (different-id, same-name) printing.
        assert database.get_card("Nyxbloom Ancient") is not None


class TestStaleCachedRows:
    """A row cached before `mana_cost_string` existed self-heals on load,
    when `scryfall_primary=True` (see TestScryfallPrimaryPolicy below for
    the cache-primary default, which serves a stale row as-is instead).

    Reference: docs/implementation-state/Done_Backend.md "Mana cost model", ToDo's former
    "Hybrid/Phyrexian nuance for stale cached rows" entry — schema
    versioning (services/schema_version.py) already wipes the *whole* card
    cache when `models/card.py` changes shape, so genuinely pre-existing
    rows can't survive a deployed schema change. But a row could still end
    up without `mana_cost_string` some other way post-deploy — e.g.
    importing an old docs/08 cache export into an already-reconciled DB —
    so `LazyCardLoader` (in scryfall_primary mode) treats a stale hit as a
    miss and refetches it.
    """

    def test_stale_row_missing_mana_cost_string_is_refetched(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        loader, database = make_loader(handler, scryfall_primary=True)
        from mtg_analyzer.models.cards.card import Card

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
            if request.url.path == "/cards/collection":
                return httpx.Response(
                    200, json={"data": [], "not_found": [{"name": "Lightning Bolt"}]}
                )
            return httpx.Response(404, json={"details": "not found"})

        loader, database = make_loader(handler, scryfall_primary=True)
        from mtg_analyzer.models.cards.card import Card

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
        from mtg_analyzer.models.cards.card import Card

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


class TestStalePartnerWithSelfHeals:
    """A row cached before the scryfall_client._partner_with reminder-text
    fix has a `partner_with` value like "Frodo, Adventurous Hobbit (When
    this creature enters, ...)" instead of the bare name — which then never
    exactly matches the other commander's real name in
    services/commander_legality.py, wrongly rejecting a legal "Partner with
    X" pairing. Card.has_clean_partner_with flags this so LazyCardLoader, in
    scryfall_primary mode, refetches it instead of serving the stale copy
    forever, the same self-heal treatment TestStaleCachedRows above gives a
    pre-mana_cost_string row (cache-primary, the default, serves it as-is —
    see TestScryfallPrimaryPolicy)."""

    def test_stale_partner_with_reminder_text_is_refetched(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "sam-id",
                            "name": "Sam, Loyal Attendant",
                            "mana_cost": "{1}{G}",
                            "cmc": 2.0,
                            "type_line": "Legendary Creature — Hobbit",
                            "oracle_text": "Partner with Frodo, Adventurous Hobbit",
                            "colors": ["G"],
                            "color_identity": ["G"],
                            "keywords": ["Partner with"],
                            "set": "ltr",
                            "rarity": "rare",
                            "image_uris": {
                                "small": "https://img.example/sam-small.jpg",
                                "normal": "https://img.example/sam-normal.jpg",
                                "large": "",
                                "png": "",
                            },
                        }
                    ],
                    "not_found": [],
                },
            )

        loader, database = make_loader(handler, scryfall_primary=True)
        from mtg_analyzer.models.cards.card import Card

        database.save_card(
            Card(
                id="sam-id",
                name="Sam, Loyal Attendant",
                type_line="Legendary Creature — Hobbit",
                mana_cost_string="{1}{G}",
                converted_mana_cost=2,
                is_creature=True,
                power=1,
                toughness=1,
                has_partner=True,
                partner_with="Frodo, Adventurous Hobbit (When this creature enters, ...)",
                image_uri_normal="https://img.example/sam-normal.jpg",
            )
        )

        result = loader.load_cards(["Sam, Loyal Attendant"])

        assert len(calls) == 1  # refetched despite being "cached"
        assert result.cards["Sam, Loyal Attendant"].partner_with == "Frodo, Adventurous Hobbit"
        # The DB row itself is healed too, not just this call's result.
        assert database.get_card("Sam, Loyal Attendant").partner_with == "Frodo, Adventurous Hobbit"

    def test_clean_partner_with_is_not_treated_as_stale(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [], "not_found": []})

        loader, database = make_loader(handler)
        from mtg_analyzer.models.cards.card import Card

        database.save_card(
            Card(
                id="sam-id",
                name="Sam, Loyal Attendant",
                type_line="Legendary Creature — Hobbit",
                mana_cost_string="{1}{G}",
                converted_mana_cost=2,
                is_creature=True,
                power=1,
                toughness=1,
                has_partner=True,
                partner_with="Frodo, Adventurous Hobbit",
                image_uri_normal="https://img.example/sam-normal.jpg",
            )
        )

        result = loader.load_cards(["Sam, Loyal Attendant"])

        assert calls == []  # already clean — no refetch needed
        assert result.cards["Sam, Loyal Attendant"].partner_with == "Frodo, Adventurous Hobbit"


class TestScryfallPrimaryPolicy:
    """LazyCardLoader's `scryfall_primary` flag (default False —
    "cache-primary", mtg_analyzer/config.py's SCRYFALL_PRIMARY /
    `setup/start.py --scryfall-primary`). A name with *no* cached row at
    all is always fetched either way (TestLoadCards/TestFlavorNameFallback
    above already cover that) — only the policy for an *already-cached* but
    `stale` row differs, exercised here directly against all three
    staleness signals (TestStaleCachedRows/TestStalePartnerWithSelfHeals
    cover the scryfall_primary=True side of the same rows)."""

    def _stale_card(self, **overrides):
        from mtg_analyzer.models.cards.card import Card

        defaults = dict(
            id="sam-id",
            name="Sam, Loyal Attendant",
            type_line="Legendary Creature — Hobbit",
            mana_cost_string="{1}{G}",
            converted_mana_cost=2,
            is_creature=True,
            power=1,
            toughness=1,
        )
        defaults.update(overrides)
        return Card(**defaults)

    def test_cache_primary_serves_missing_mana_cost_data_as_is(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        loader, database = make_loader(handler)  # scryfall_primary defaults False
        database.save_card(self._stale_card(name="Lightning Bolt", mana_cost_string=""))

        result = loader.load_cards(["Lightning Bolt"])

        assert calls == []  # never refetched — the cache is authoritative
        assert result.cards["Lightning Bolt"].mana_cost_string == ""

    def test_cache_primary_serves_missing_image_data_as_is(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [], "not_found": []})

        loader, database = make_loader(handler)
        database.save_card(self._stale_card(image_uri_normal=""))

        result = loader.load_cards(["Sam, Loyal Attendant"])

        assert calls == []
        assert result.cards["Sam, Loyal Attendant"].image_uri_normal == ""

    def test_cache_primary_serves_dirty_partner_with_as_is(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [], "not_found": []})

        loader, database = make_loader(handler)
        database.save_card(
            self._stale_card(
                image_uri_normal="https://img.example/sam-normal.jpg",
                has_partner=True,
                partner_with="Frodo, Adventurous Hobbit (When this creature enters, ...)",
            )
        )

        result = loader.load_cards(["Sam, Loyal Attendant"])

        assert calls == []
        assert result.cards["Sam, Loyal Attendant"].partner_with == (
            "Frodo, Adventurous Hobbit (When this creature enters, ...)"
        )

    def test_cache_primary_still_fetches_a_name_never_seen_before(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"data": [LIGHTNING_BOLT], "not_found": []})

        loader, _ = make_loader(handler)  # scryfall_primary defaults False
        result = loader.load_cards(["Lightning Bolt"])

        assert len(calls) == 1  # no cached row at all — always fetched
        assert result.cards["Lightning Bolt"].name == "Lightning Bolt"
