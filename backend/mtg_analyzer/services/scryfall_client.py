"""Scryfall API client: fetch card data and convert it into `Card` objects.

Reference: docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md (PART 3),
docs/IMPLEMENTATION_GUIDE.md (Week 2, Day 4-5, "ScryfallIntegration").
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import httpx2 as httpx

from mtg_analyzer.models.card import VALID_COLORS, Card

_BASE_URL = "https://api.scryfall.com"
#: Scryfall asks integrations to identify themselves and to stay under
#: ~10 requests/second; a small delay between requests is the simplest
#: way to honor that without a background rate limiter.
_USER_AGENT = "MTG-Deck-Analyzer/0.1"
_MIN_REQUEST_INTERVAL_SECONDS = 0.1
#: Batch size cap for POST /cards/collection (Scryfall's own limit).
_COLLECTION_BATCH_SIZE = 75

_MANA_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


class ScryfallNotFoundError(Exception):
    """Raised when Scryfall has no card matching the given name."""


class ScryfallIntegration:
    """Thin wrapper around the Scryfall HTTP API used for lazy card loading."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        self._client = client or httpx.Client(
            base_url=_BASE_URL,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=10.0,
        )
        self._last_request_at: Optional[float] = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ScryfallIntegration":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def fetch_card(self, name: str) -> dict[str, Any]:
        """Fetch a single card by exact name. Raises ScryfallNotFoundError if unknown."""
        response = self._request("GET", "/cards/named", params={"exact": name})
        if response.status_code == 404:
            raise ScryfallNotFoundError(f'No Scryfall card found for "{name}"')
        response.raise_for_status()
        return response.json()

    def fetch_multiple(self, names: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        """Fetch several cards by name in as few requests as possible.

        Returns (found_card_data, names_not_found). Uses Scryfall's bulk
        `/cards/collection` endpoint (up to 75 identifiers per request)
        rather than one request per card.
        """
        found: list[dict[str, Any]] = []
        not_found: list[str] = []

        for start in range(0, len(names), _COLLECTION_BATCH_SIZE):
            batch = names[start : start + _COLLECTION_BATCH_SIZE]
            identifiers = [{"name": name} for name in batch]
            response = self._request(
                "POST", "/cards/collection", json={"identifiers": identifiers}
            )
            response.raise_for_status()
            body = response.json()
            found.extend(body.get("data", []))
            not_found.extend(entry.get("name", "") for entry in body.get("not_found", []))

        return found, not_found

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._throttle()
        return self._client.request(method, path, **kwargs)

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            remaining = _MIN_REQUEST_INTERVAL_SECONDS - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def card_from_scryfall_data(data: dict[str, Any]) -> Card:
    """Convert a Scryfall card object into a `Card` domain model.

    Double-faced/split cards store most face-specific fields (oracle
    text, image URIs, power/toughness) under `card_faces` instead of at
    the top level; this uses the front face as a reasonable default
    since the analyzer doesn't yet model separate card faces.
    """
    front = data
    faces = data.get("card_faces")
    if faces and ("oracle_text" not in data or not data.get("image_uris")):
        front = {**faces[0], **{k: v for k, v in data.items() if k not in faces[0]}}

    type_line = data.get("type_line", "")
    image_uris = front.get("image_uris") or data.get("image_uris") or {}

    power = _parse_int(front.get("power"))
    toughness = _parse_int(front.get("toughness"))
    is_creature = "Creature" in type_line

    return Card(
        id=data["id"],
        name=data["name"],
        type_line=type_line,
        mana_cost=_parse_mana_cost(front.get("mana_cost", "")),
        mana_cost_string=front.get("mana_cost", "") or "",
        converted_mana_cost=int(data.get("cmc") or 0),
        color_identity=set(data.get("color_identity") or []),
        is_creature=is_creature,
        is_instant="Instant" in type_line,
        is_sorcery="Sorcery" in type_line,
        is_land="Land" in type_line,
        power=power if is_creature else None,
        toughness=toughness if is_creature else None,
        oracle_text=front.get("oracle_text", ""),
        keywords=list(data.get("keywords") or []),
        image_uri_small=image_uris.get("small", ""),
        image_uri_normal=image_uris.get("normal", ""),
        image_uri_large=image_uris.get("large", ""),
        image_uri_png=image_uris.get("png", ""),
        set_code=data.get("set", ""),
        rarity=data.get("rarity", ""),
        is_legendary="Legendary" in type_line,
        has_partner=_has_partner(front.get("oracle_text", "")),
        partner_with=_partner_with(front.get("oracle_text", "")),
    )


def _parse_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        # "*" and "X" show up as power/toughness on some cards.
        return None


def _parse_mana_cost(mana_cost: str) -> dict[str, int]:
    """Tally colored/colorless mana symbols, ignoring generic numeric pips.

    The `Card` model only tracks a per-symbol pip count (no generic
    amount field), so "{2}{R}" becomes {"R": 1} with the "2" dropped;
    `converted_mana_cost` remains the source of truth for total cost.

    Hybrid ("{W/U}") and Phyrexian ("{W/P}") symbols are also
    flattened: each is split on "/" and only the half matching a known
    color/colorless letter is kept, so "{W/U}" and "{W/P}" both count
    as a single "W" pip, indistinguishable from a plain "{W}". That
    loses real information (a hybrid symbol can be paid in either
    color; a Phyrexian one can be paid with 2 life instead) — see
    backend/ToDo_Backend.md "Mana cost model" for the backlog on representing
    these properly.
    """
    counts = {color: 0 for color in sorted(VALID_COLORS) + ["C"]}
    for symbol in _MANA_SYMBOL_RE.findall(mana_cost):
        for letter in symbol.split("/"):
            if letter in counts:
                counts[letter] += 1
    return counts


def _has_partner(oracle_text: str) -> bool:
    return bool(re.search(r"^Partner\b", oracle_text, re.MULTILINE))


def _partner_with(oracle_text: str) -> Optional[str]:
    match = re.search(r"^Partner with (.+)$", oracle_text, re.MULTILINE)
    return match.group(1).strip() if match else None
